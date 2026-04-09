#!/usr/bin/env python3
"""
Scan raw/ directory for extraction work: new files, failed extractions,
and low-quality extractions that should be retried.

Usage:
    python scan.py <vault-path>                # one-shot scan
    python scan.py <vault-path> --watch 300    # re-scan every 5 minutes
    python scan.py <vault-path> --json         # JSON output for agent consumption
    python scan.py <vault-path> --auto-extract # automatically run extract.py on findings
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


# Extensions that don't need docling extraction
NATIVE_EXTENSIONS = {
    ".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh",
}

# Minimum extracted-to-source size ratio to consider extraction acceptable.
# Below this threshold the extraction is flagged as low quality.
MIN_QUALITY_RATIO = 0.01  # 1%

# Minimum extracted file size in bytes to consider non-empty
MIN_EXTRACTED_BYTES = 50


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(vault_path: Path) -> dict:
    manifest_path = vault_path / "raw" / ".manifest.json"
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"sources": [], "version": 1}


def scan_raw(vault_path: Path, quality_ratio: float = MIN_QUALITY_RATIO) -> dict:
    """Scan raw/ and return a report of work needed.

    Returns dict with keys:
        new: list of files in raw/ not in manifest and not yet extracted
        failed: list of manifest entries where extracted file is missing
        low_quality: list of extracted files that look suspiciously small/empty
        modified: list of files whose hash differs from manifest
        ok: list of files that are fine
        stats: summary counts
    """
    raw_dir = vault_path / "raw"
    extracted_dir = raw_dir / "extracted"
    manifest = load_manifest(vault_path)

    # Build lookup from manifest
    manifest_by_path: dict[str, dict] = {}
    for entry in manifest.get("sources", []):
        manifest_by_path[entry["path"]] = entry

    new_files = []
    failed = []
    low_quality = []
    modified = []
    ok = []

    # Walk raw/ for all non-hidden files
    for root, dirs, files in os.walk(str(raw_dir)):
        # Skip hidden dirs and the extracted/ dir itself
        dirs[:] = [
            d for d in dirs
            if not d.startswith(".") and d != "extracted"
        ]
        for fname in files:
            if fname.startswith("."):
                continue
            # Skip snapshot files
            if fname.endswith(".snapshot.md"):
                continue

            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, vault_path)
            ext = os.path.splitext(fname)[1].lower()

            # Skip native text/code files — they don't need extraction
            if ext in NATIVE_EXTENSIONS:
                continue

            # Determine expected extracted path (preserving subdirectory structure)
            rel_to_raw = os.path.relpath(full_path, str(raw_dir))
            extracted_path = os.path.join(str(extracted_dir), rel_to_raw + ".md")
            in_manifest = rel_path in manifest_by_path

            if not in_manifest:
                # New file not yet processed
                if os.path.exists(extracted_path):
                    # Extracted file exists but not in manifest — treat as new
                    # (manifest wasn't updated after extraction)
                    pass
                new_files.append({
                    "path": rel_path,
                    "size_bytes": os.path.getsize(full_path),
                    "extracted_exists": os.path.exists(extracted_path),
                })
                continue

            entry = manifest_by_path[rel_path]

            # Check if source was modified since last ingestion
            current_hash = file_sha256(full_path)
            if entry.get("sha256") and current_hash != entry["sha256"]:
                modified.append({
                    "path": rel_path,
                    "old_hash": entry["sha256"][:12] + "...",
                    "new_hash": current_hash[:12] + "...",
                })
                continue

            # Check if extracted file exists
            extracted_field = entry.get("extracted")
            check_path = (
                os.path.join(str(vault_path), extracted_field)
                if extracted_field
                else extracted_path
            )

            if not os.path.exists(check_path):
                failed.append({
                    "path": rel_path,
                    "expected_extracted": os.path.relpath(check_path, vault_path),
                    "reason": "extracted file missing",
                })
                continue

            # Check extraction quality
            source_size = os.path.getsize(full_path)
            extracted_size = os.path.getsize(check_path)

            if extracted_size < MIN_EXTRACTED_BYTES:
                low_quality.append({
                    "path": rel_path,
                    "extracted": os.path.relpath(check_path, vault_path),
                    "source_bytes": source_size,
                    "extracted_bytes": extracted_size,
                    "reason": "extracted file nearly empty",
                })
            elif source_size > 0 and (extracted_size / source_size) < quality_ratio:
                low_quality.append({
                    "path": rel_path,
                    "extracted": os.path.relpath(check_path, vault_path),
                    "source_bytes": source_size,
                    "extracted_bytes": extracted_size,
                    "ratio": f"{extracted_size / source_size:.4f}",
                    "reason": f"size ratio {extracted_size / source_size:.2%} below {quality_ratio:.0%} threshold",
                })
            else:
                ok.append(rel_path)

    report = {
        "new": new_files,
        "failed": failed,
        "low_quality": low_quality,
        "modified": modified,
        "ok": ok,
        "stats": {
            "new": len(new_files),
            "failed": len(failed),
            "low_quality": len(low_quality),
            "modified": len(modified),
            "ok": len(ok),
            "total_actionable": len(new_files) + len(failed) + len(low_quality) + len(modified),
        },
    }
    return report


def print_report(report: dict, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(report, indent=2))
        return

    stats = report["stats"]
    total = stats["total_actionable"]

    if total == 0:
        print("All files OK. Nothing to do.")
        return

    print(f"Scan found {total} item(s) needing attention:\n")

    if report["new"]:
        print(f"NEW ({len(report['new'])} files not yet extracted):")
        for f in report["new"]:
            size = f["size_bytes"]
            size_str = f"{size / 1024 / 1024:.1f}MB" if size > 1024 * 1024 else f"{size / 1024:.0f}KB"
            print(f"  + {f['path']}  ({size_str})")
        print()

    if report["failed"]:
        print(f"FAILED ({len(report['failed'])} extractions missing):")
        for f in report["failed"]:
            print(f"  ! {f['path']}  ({f['reason']})")
        print()

    if report["low_quality"]:
        print(f"LOW QUALITY ({len(report['low_quality'])} extractions to retry):")
        for f in report["low_quality"]:
            print(f"  ~ {f['path']}  ({f['reason']})")
        print()

    if report["modified"]:
        print(f"MODIFIED ({len(report['modified'])} sources changed since extraction):")
        for f in report["modified"]:
            print(f"  * {f['path']}")
        print()


def auto_extract(vault_path: Path, report: dict) -> None:
    """Run extract.py on all actionable files."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    extract_script = os.path.join(script_dir, "extract.py")

    actionable = []
    for f in report["new"]:
        actionable.append(os.path.join(str(vault_path), f["path"]))
    for f in report["failed"]:
        actionable.append(os.path.join(str(vault_path), f["path"]))
    for f in report["low_quality"]:
        actionable.append(os.path.join(str(vault_path), f["path"]))
    for f in report["modified"]:
        actionable.append(os.path.join(str(vault_path), f["path"]))

    if not actionable:
        return

    print(f"\nRunning extraction on {len(actionable)} file(s)...\n")

    for path in actionable:
        print(f"--- Extracting: {os.path.relpath(path, vault_path)}")
        try:
            result = subprocess.run(
                [sys.executable, extract_script, path],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 0:
                print(f"    OK: {result.stdout.strip()}")
            else:
                print(f"    FAILED: {result.stderr.strip() or result.stdout.strip()}")
        except subprocess.TimeoutExpired:
            print(f"    TIMEOUT: extraction took longer than 10 minutes")
        except Exception as e:
            print(f"    ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Scan raw/ for extraction work: new, failed, or low-quality extractions.",
    )
    parser.add_argument("vault_path", help="Path to the wiki vault")
    parser.add_argument(
        "--watch", type=int, default=None, metavar="SECONDS",
        help="Re-scan every N seconds (e.g. --watch 300 for every 5 minutes)",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output report as JSON",
    )
    parser.add_argument(
        "--auto-extract", action="store_true",
        help="Automatically run extract.py on files that need extraction",
    )
    parser.add_argument(
        "--quality-ratio", type=float, default=MIN_QUALITY_RATIO,
        help=f"Minimum extracted/source size ratio (default: {MIN_QUALITY_RATIO})",
    )

    args = parser.parse_args()
    vault_path = Path(args.vault_path).resolve()

    if not (vault_path / "raw").is_dir():
        print(f"Error: {vault_path / 'raw'} does not exist. Is this a valid wiki vault?",
              file=sys.stderr)
        sys.exit(1)

    quality_ratio = args.quality_ratio

    if args.watch is not None:
        # Periodic scanning mode
        interval = max(args.watch, 10)  # minimum 10 seconds
        print(f"Scanning {vault_path / 'raw'} every {interval}s. Press Ctrl+C to stop.\n")
        try:
            while True:
                report = scan_raw(vault_path, quality_ratio=quality_ratio)
                print_report(report, json_output=args.json_output)
                if args.auto_extract and report["stats"]["total_actionable"] > 0:
                    auto_extract(vault_path, report)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        # One-shot scan
        report = scan_raw(vault_path, quality_ratio=quality_ratio)
        print_report(report, json_output=args.json_output)
        if args.auto_extract and report["stats"]["total_actionable"] > 0:
            auto_extract(vault_path, report)

        sys.exit(0 if report["stats"]["total_actionable"] == 0 else 1)


if __name__ == "__main__":
    main()
