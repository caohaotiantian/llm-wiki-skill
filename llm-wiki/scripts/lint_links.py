#!/usr/bin/env python3
"""
Scan wiki pages for wikilink issues: alias mismatches and missing targets.

Builds a resolution index from all filenames and frontmatter aliases,
then checks every [[wikilink]] in the scanned files against it.

Usage:
    python lint_links.py <vault-path>                              # vault-wide scan
    python lint_links.py <vault-path> --json                       # JSON output
    python lint_links.py <vault-path> --files wiki/a.md wiki/b.md  # targeted scan
    python lint_links.py <vault-path> --fix                        # auto-fix alias mismatches
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


def normalize_for_matching(name: str) -> str:
    """Normalize a name for Obsidian-style matching.

    Obsidian treats spaces, hyphens, and underscores as equivalent
    and matches case-insensitively.
    """
    return re.sub(r"[\s\-_]+", " ", name).strip().lower()


def parse_frontmatter_aliases(content: str) -> list[str]:
    """Extract aliases from YAML frontmatter without PyYAML.

    Handles both formats:
        aliases: [a, b, c]
        aliases:
          - a
          - b
    """
    # Extract frontmatter block
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return []

    fm = match.group(1)

    # Try inline format: aliases: [a, b, c]
    inline = re.search(r"^aliases:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline:
        raw = inline.group(1)
        return [a.strip().strip("\"'") for a in raw.split(",") if a.strip()]

    # Try list format: aliases:\n  - a\n  - b
    list_match = re.search(r"^aliases:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.MULTILINE)
    if list_match:
        items = re.findall(r"^\s+-\s+(.+)", list_match.group(1), re.MULTILINE)
        return [item.strip().strip("\"'") for item in items if item.strip()]

    return []


def build_resolution_index(vault_path: Path) -> dict:
    """Build an index mapping normalized names to file paths.

    Returns:
        {
            "by_filename": {normalized_name: relative_path, ...},
            "by_alias": {normalized_alias: relative_path, ...},
        }

    Scans wiki/ and raw/ directories for .md files.
    """
    by_filename: dict[str, str] = {}
    by_alias: dict[str, str] = {}

    scan_dirs = []
    wiki_dir = vault_path / "wiki"
    raw_dir = vault_path / "raw"
    if wiki_dir.is_dir():
        scan_dirs.append(wiki_dir)
    if raw_dir.is_dir():
        scan_dirs.append(raw_dir)

    for scan_dir in scan_dirs:
        for root, dirs, files in os.walk(str(scan_dir)):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                # Skip snapshot files
                if fname.endswith(".snapshot.md"):
                    continue

                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, vault_path)
                stem = os.path.splitext(fname)[0]

                # Register filename
                norm_stem = normalize_for_matching(stem)
                by_filename[norm_stem] = rel_path

                # Also register with directory prefix for path-based links
                # e.g., "wiki/concepts/microservices" for [[wiki/concepts/microservices]]
                rel_no_ext = os.path.splitext(rel_path)[0]
                norm_rel = normalize_for_matching(rel_no_ext)
                if norm_rel != norm_stem:
                    by_filename[norm_rel] = rel_path

                # Parse aliases from frontmatter
                try:
                    content = open(full_path, "r", encoding="utf-8", errors="replace").read()
                except OSError:
                    continue

                for alias in parse_frontmatter_aliases(content):
                    norm_alias = normalize_for_matching(alias)
                    if norm_alias and norm_alias not in by_filename:
                        by_alias[norm_alias] = rel_path

    return {"by_filename": by_filename, "by_alias": by_alias}


# Matches [[target]], [[target|display]], [[target#heading]], [[target#^block]]
# Does NOT match embeds (![[...]]) — those are handled separately
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]]+?)\]\]")


def extract_link_target(wikilink_content: str) -> str:
    """Extract the resolution target from wikilink inner content.

    [[target]] → target
    [[target|display]] → target
    [[target#heading]] → target
    [[target#^block-id]] → target
    [[target#heading|display]] → target
    """
    # Remove display text (after |)
    target = wikilink_content.split("|")[0]
    # Remove heading/block reference (after #)
    target = target.split("#")[0]
    return target.strip()


def scan_file_for_links(file_path: str) -> list[dict]:
    """Extract all wikilinks from a file with line numbers.

    Returns list of {"line": int, "raw": str, "target": str}
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    results = []
    in_frontmatter = False
    frontmatter_closed = False

    for i, line in enumerate(lines, start=1):
        # Skip frontmatter — links in YAML values aren't rendered as wikilinks
        if i == 1 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() == "---":
                in_frontmatter = False
                frontmatter_closed = True
            continue

        for match in WIKILINK_RE.finditer(line):
            raw = match.group(1)
            target = extract_link_target(raw)
            if target:
                results.append({"line": i, "raw": raw, "target": target})

    return results


def resolve_links(
    vault_path: Path,
    index: dict,
    files_to_scan: list[str],
) -> dict:
    """Resolve all wikilinks in the given files against the index.

    Returns:
        {
            "alias_mismatches": [{"file", "line", "link", "target_file", "suggested"}],
            "missing": [{"file", "line", "link", "referenced_from"}],
            "summary": {"total_links", "resolved", "alias_mismatches", "missing"},
            "clean": bool,
        }
    """
    by_filename = index["by_filename"]
    by_alias = index["by_alias"]

    alias_mismatches = []
    missing_links: dict[str, dict] = {}  # keyed by normalized target
    resolved_count = 0
    total_count = 0

    for file_path in files_to_scan:
        abs_path = os.path.join(str(vault_path), file_path) if not os.path.isabs(file_path) else file_path
        rel_path = os.path.relpath(abs_path, vault_path)
        links = scan_file_for_links(abs_path)

        for link in links:
            total_count += 1
            norm_target = normalize_for_matching(link["target"])

            # Phase 1: Does it match a filename?
            if norm_target in by_filename:
                resolved_count += 1
                continue

            # Phase 2: Does it match an alias?
            if norm_target in by_alias:
                target_file = by_alias[norm_target]
                target_stem = os.path.splitext(os.path.basename(target_file))[0]
                alias_mismatches.append({
                    "file": rel_path,
                    "line": link["line"],
                    "link": link["target"],
                    "target_file": target_file,
                    "suggested": f"[[{target_stem}|{link['target']}]]",
                })
                continue

            # Phase 3: Unresolved
            if norm_target not in missing_links:
                missing_links[norm_target] = {
                    "link": link["target"],
                    "referenced_from": [],
                }
            ref_entry = f"{rel_path}:{link['line']}"
            if ref_entry not in missing_links[norm_target]["referenced_from"]:
                missing_links[norm_target]["referenced_from"].append(ref_entry)

    missing_list = [
        {
            "link": v["link"],
            "referenced_from": v["referenced_from"],
        }
        for v in missing_links.values()
    ]

    return {
        "alias_mismatches": alias_mismatches,
        "missing": missing_list,
        "summary": {
            "total_links": total_count,
            "resolved": resolved_count,
            "alias_mismatches": len(alias_mismatches),
            "missing": len(missing_list),
        },
        "clean": len(alias_mismatches) == 0 and len(missing_list) == 0,
    }


def fix_alias_mismatches(vault_path: Path, mismatches: list[dict]) -> int:
    """Rewrite [[alias]] → [[filename|alias]] in-place for each mismatch.

    Returns the number of fixes applied.
    """
    # Group mismatches by file for efficient processing
    by_file: dict[str, list[dict]] = {}
    for m in mismatches:
        by_file.setdefault(m["file"], []).append(m)

    fixes_applied = 0

    for rel_path, file_mismatches in by_file.items():
        abs_path = os.path.join(str(vault_path), rel_path)
        try:
            content = open(abs_path, "r", encoding="utf-8").read()
        except OSError:
            continue

        for m in file_mismatches:
            target_stem = os.path.splitext(os.path.basename(m["target_file"]))[0]
            old_link = f"[[{m['link']}]]"
            new_link = f"[[{target_stem}|{m['link']}]]"
            if old_link in content:
                content = content.replace(old_link, new_link, 1)
                fixes_applied += 1

        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass

    return fixes_applied


def print_report(report: dict, json_output: bool = False) -> None:
    """Print the resolution report in human-readable or JSON format."""
    if json_output:
        print(json.dumps(report, indent=2))
        return

    summary = report["summary"]

    if report["clean"]:
        print(f"All {summary['total_links']} links OK. No issues found.")
        return

    print(f"Scanned {summary['total_links']} links: "
          f"{summary['resolved']} resolved, "
          f"{summary['alias_mismatches']} alias mismatches, "
          f"{summary['missing']} missing.\n")

    if report["alias_mismatches"]:
        print(f"ALIAS MISMATCHES ({len(report['alias_mismatches'])}):")
        for m in report["alias_mismatches"]:
            print(f"  {m['file']}:{m['line']}  [[{m['link']}]]  →  {m['suggested']}")
        print()

    if report["missing"]:
        print(f"MISSING PAGES ({len(report['missing'])}):")
        for m in report["missing"]:
            refs = ", ".join(m["referenced_from"][:3])
            suffix = f" (+{len(m['referenced_from']) - 3} more)" if len(m["referenced_from"]) > 3 else ""
            print(f"  [[{m['link']}]]  referenced from: {refs}{suffix}")
        print()


def collect_wiki_files(vault_path: Path) -> list[str]:
    """Collect all .md files under wiki/ (relative paths)."""
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return []

    results = []
    for root, dirs, files in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.endswith(".md") and not fname.endswith(".snapshot.md"):
                full_path = os.path.join(root, fname)
                results.append(os.path.relpath(full_path, vault_path))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Scan wiki pages for wikilink issues: alias mismatches and missing targets.",
    )
    parser.add_argument("vault_path", help="Path to the wiki vault")
    parser.add_argument(
        "--files", nargs="+", default=None, metavar="FILE",
        help="Scan only these files (vault-relative paths). Default: all files in wiki/",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output report as JSON",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Auto-fix alias mismatches by rewriting [[alias]] → [[filename|alias]]",
    )

    args = parser.parse_args()
    vault_path = Path(args.vault_path).resolve()

    if not vault_path.is_dir():
        print(f"Error: {vault_path} is not a directory.", file=sys.stderr)
        sys.exit(1)

    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        print(f"Error: {wiki_dir} does not exist. Is this a valid wiki vault?",
              file=sys.stderr)
        sys.exit(1)

    # Build resolution index from all files
    index = build_resolution_index(vault_path)

    # Determine which files to scan
    if args.files:
        files_to_scan = args.files
    else:
        files_to_scan = collect_wiki_files(vault_path)

    if not files_to_scan:
        print("No files to scan.")
        sys.exit(0)

    # Resolve links
    report = resolve_links(vault_path, index, files_to_scan)

    # Auto-fix if requested
    if args.fix and report["alias_mismatches"]:
        fixes = fix_alias_mismatches(vault_path, report["alias_mismatches"])
        if not args.json_output:
            print(f"Fixed {fixes} alias mismatch(es).\n")
        # Re-scan after fixing to get updated report
        index = build_resolution_index(vault_path)
        report = resolve_links(vault_path, index, files_to_scan)

    print_report(report, json_output=args.json_output)
    sys.exit(0 if report["clean"] else 1)


if __name__ == "__main__":
    main()
