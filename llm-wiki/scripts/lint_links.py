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
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from frontmatter import parse as _parse_fm, parse_aliases as _parse_aliases_fm, parse_typed_links as _parse_typed_links_fm, atomic_write


def normalize_for_matching(name: str) -> str:
    """Normalize a name for fuzzy matching.

    Case-insensitive, treats spaces/hyphens/underscores as equivalent.
    Note: Obsidian's exact normalization behavior is not fully documented
    and may vary. This is a lenient approximation — it may resolve links
    that Obsidian itself would not. Prefer exact filenames in wikilinks.
    """
    return re.sub(r"[\s\-_]+", " ", name).strip().lower()


def parse_frontmatter_aliases(content: str) -> list[str]:
    """Extract aliases from YAML frontmatter."""
    fm, _ = _parse_fm(content)
    return _parse_aliases_fm(fm)


KNOWN_LINK_TYPES = {
    "references", "contradicts", "depends_on", "supersedes",
    "authored_by", "works_at", "mentions",
}


def parse_typed_links(content: str) -> list[dict]:
    """Extract typed links from YAML frontmatter."""
    fm, _ = _parse_fm(content)
    return _parse_typed_links_fm(fm)


def _parse_updated_date(content: str) -> str | None:
    """Extract the 'updated' date from frontmatter."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content, re.DOTALL)
    if not match:
        return None
    m = re.search(r"^updated:\s*(\d{4}-\d{2}-\d{2})", match.group(1), re.MULTILINE)
    return m.group(1) if m else None


def _parse_timeline_dates(content: str) -> list[str]:
    """Extract all dates from timeline entries (below the --- separator in body)."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    fm_match = re.match(r"^---\s*\n.*?\n(?:---|\.\.\.)(?:\s*\n)", content, re.DOTALL)
    if not fm_match:
        return []
    body = content[fm_match.end():]
    parts = re.split(r"\n---\s*\n", body, maxsplit=1)
    if len(parts) < 2:
        return []
    timeline = parts[1]
    return re.findall(r"^-\s+(\d{4}-\d{2}-\d{2})", timeline, re.MULTILINE)


def check_stale_pages(vault_path) -> list[dict]:
    """Find pages whose compiled truth is older than latest timeline entry."""
    vault_path = Path(vault_path)
    results = []
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return results
    for root, dirs, files in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md") or fname.endswith(".snapshot.md"):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, vault_path)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            updated = _parse_updated_date(content)
            if not updated:
                continue
            timeline_dates = _parse_timeline_dates(content)
            if not timeline_dates:
                continue
            latest = max(timeline_dates)
            if latest > updated:
                results.append({"page": rel, "updated": updated, "latest_timeline": latest})
    return results


def check_unbalanced_pages(vault_path, threshold: int = 5) -> list[dict]:
    """Find pages with many timeline entries since last compiled-truth update."""
    vault_path = Path(vault_path)
    results = []
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return results
    for root, dirs, files in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md") or fname.endswith(".snapshot.md"):
                continue
            full = os.path.join(root, fname)
            rel = os.path.relpath(full, vault_path)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            updated = _parse_updated_date(content)
            if not updated:
                continue
            timeline_dates = _parse_timeline_dates(content)
            newer = [d for d in timeline_dates if d > updated]
            if len(newer) >= threshold:
                results.append({"page": rel, "updated": updated, "new_entries": len(newer)})
    return results


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

                # Register filename (warn on duplicates)
                norm_stem = normalize_for_matching(stem)
                if norm_stem in by_filename and by_filename[norm_stem] != rel_path:
                    print(f"Warning: duplicate filename '{stem}' — "
                          f"{by_filename[norm_stem]} and {rel_path}. "
                          f"Bare [[{stem}]] links are ambiguous.",
                          file=sys.stderr)
                by_filename[norm_stem] = rel_path

                # Also register with directory prefix for path-based links
                # e.g., "wiki/concepts/microservices" for [[wiki/concepts/microservices]]
                rel_no_ext = os.path.splitext(rel_path)[0]
                norm_rel = normalize_for_matching(rel_no_ext)
                if norm_rel != norm_stem:
                    by_filename[norm_rel] = rel_path

                # Parse aliases from frontmatter
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except OSError:
                    continue

                for alias in parse_frontmatter_aliases(content):
                    norm_alias = normalize_for_matching(alias)
                    if norm_alias:
                        if norm_alias not in by_alias:
                            by_alias[norm_alias] = rel_path
                        elif by_alias[norm_alias] != rel_path:
                            print(f"Warning: duplicate alias '{alias}' — "
                                  f"{by_alias[norm_alias]} and {rel_path}. "
                                  f"First registration wins.",
                                  file=sys.stderr)

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
    target = target.strip()
    # Strip .md extension — Obsidian ignores it during resolution
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def scan_file_for_links(file_path: str) -> list[dict]:
    """Extract all wikilinks from a file with line numbers.

    Returns list of {"line": int, "raw": str, "target": str}
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"Warning: cannot read {file_path}: {e}", file=sys.stderr)
        return []

    results = []
    in_frontmatter = False
    code_fence_marker = ""  # tracks the opening fence (e.g., "```" or "````")

    for i, line in enumerate(lines, start=1):
        # Skip frontmatter — links in YAML values aren't rendered as wikilinks
        if i == 1 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() in ("---", "..."):
                in_frontmatter = False
            continue

        # Skip fenced code blocks — track opening fence to handle nested fences
        stripped = line.strip()
        if not code_fence_marker:
            # Not in a code block — check for opening fence
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence_match:
                code_fence_marker = fence_match.group(1)
                continue
        else:
            # In a code block — only close on a fence of same char and >= length
            fence_char = code_fence_marker[0]
            fence_len = len(code_fence_marker)
            close_match = re.match(
                r"^" + re.escape(fence_char) + r"{" + str(fence_len) + r",}\s*$",
                stripped,
            )
            if close_match:
                code_fence_marker = ""
            continue

        # Strip inline code spans — links inside `backticks` are not rendered
        scannable = re.sub(r"`[^`]+`", "", line)

        for match in WIKILINK_RE.finditer(scannable):
            raw = match.group(1)
            target = extract_link_target(raw)
            # Skip same-note heading links like [[#Heading]] (target is empty)
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
            "alias_mismatches": [{"file": str, "line": int, "link": str, "target_file": str, "suggested": str}],
            "missing": [{"link": str, "referenced_from": ["path:line", ...]}],
            "summary": {"total_links": int, "resolved": int, "alias_mismatches": int,
                         "missing": int, "missing_unique_targets": int},
            "clean": bool,
        }
    Note: total_links == resolved + alias_mismatches + missing (all count occurrences).
    missing_unique_targets counts distinct targets (len of the missing list).
    """
    by_filename = index["by_filename"]
    by_alias = index["by_alias"]

    alias_mismatches = []
    missing_links: dict[str, dict] = {}  # keyed by normalized target
    missing_occurrences = 0
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
                # Preserve heading/block ref and display text from raw link
                raw = link["raw"]
                raw_base = raw.split("|")[0]  # target part (may include #heading)
                heading = ""
                if "#" in raw_base:
                    _, h = raw_base.split("#", 1)
                    heading = "#" + h
                display = raw.split("|", 1)[1] if "|" in raw else link["target"]
                alias_mismatches.append({
                    "file": rel_path,
                    "line": link["line"],
                    "link": link["target"],
                    "raw": raw,
                    "target_file": target_file,
                    "suggested": f"[[{target_stem}{heading}|{display}]]",
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
                missing_occurrences += 1

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
            "missing": missing_occurrences,
            "missing_unique_targets": len(missing_list),
        },
        "clean": len(alias_mismatches) == 0 and len(missing_list) == 0,
    }


def fix_alias_mismatches(vault_path: Path, mismatches: list[dict]) -> int:
    """Rewrite [[alias]] → [[filename|alias]] in-place for each mismatch.

    Skips frontmatter and fenced code blocks to avoid corrupting examples.
    Uses regex with boundary anchors to avoid corrupting pipe-syntax links.

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
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue

        # Build replacement list from raw wikilink content.
        # Uses raw content (including #heading) so heading links are matched.
        # (?<!!) prevents matching embeds.
        compiled: list[tuple] = []
        seen_raws: set[str] = set()
        for m in file_mismatches:
            raw = m.get("raw", m["link"])
            # Deduplicate by raw content (same raw = same pattern)
            raw_base = raw.split("|")[0]  # target part (may include #heading)
            if raw_base in seen_raws:
                continue
            seen_raws.add(raw_base)

            target_stem = os.path.splitext(os.path.basename(m["target_file"]))[0]
            # Extract heading/block suffix to preserve in replacement
            heading = ""
            if "#" in raw_base:
                alias_part, heading = raw_base.split("#", 1)
                heading = "#" + heading
            else:
                alias_part = raw_base

            pattern = re.compile(
                r"(?<!!)\[\["
                + re.escape(raw_base)          # e.g. "AI" or "AI#Introduction"
                + r"(\|[^\]]+)?"               # optional display text
                + r"\]\]"
            )
            compiled.append((pattern, target_stem, heading, alias_part))

        new_lines = []
        in_frontmatter = False
        code_fence_marker = ""

        for i, line in enumerate(lines):
            # Skip frontmatter
            if i == 0 and line.strip() == "---":
                in_frontmatter = True
                new_lines.append(line)
                continue
            if in_frontmatter:
                if line.strip() in ("---", "..."):
                    in_frontmatter = False
                new_lines.append(line)
                continue

            # Skip fenced code blocks (track fence marker for nested fences)
            stripped = line.strip()
            if not code_fence_marker:
                fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
                if fence_match:
                    code_fence_marker = fence_match.group(1)
                    new_lines.append(line)
                    continue
            else:
                fence_char = code_fence_marker[0]
                fence_len = len(code_fence_marker)
                close_match = re.match(
                    r"^" + re.escape(fence_char) + r"{" + str(fence_len) + r",}\s*$",
                    stripped,
                )
                if close_match:
                    code_fence_marker = ""
                new_lines.append(line)
                continue

            # Apply replacements only outside inline code spans
            # Split line into code/non-code segments, fix only non-code parts
            parts = re.split(r"(`[^`]+`)", line)
            modified_parts = []
            for part in parts:
                if part.startswith("`") and part.endswith("`"):
                    # Inline code span — leave untouched
                    modified_parts.append(part)
                else:
                    for pattern, target_stem, heading, alias_part in compiled:
                        def _replacer(m, _stem=target_stem, _heading=heading,
                                      _alias=alias_part):
                            display = m.group(1)  # "|display text" or None
                            if display:
                                return f"[[{_stem}{_heading}{display}]]"
                            return f"[[{_stem}{_heading}|{_alias}]]"
                        new_part, count = pattern.subn(_replacer, part)
                        if count > 0:
                            part = new_part
                            fixes_applied += count
                            break  # one pattern per match — avoid chained corruption
                    modified_parts.append(part)
            modified = "".join(modified_parts)

            new_lines.append(modified)

        try:
            atomic_write(abs_path, "".join(new_lines))
        except OSError as e:
            print(f"Warning: could not write {rel_path}: {e}", file=sys.stderr)

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
            raw = m.get('raw', m['link'])
            print(f"  {m['file']}:{m['line']}  [[{raw}]]  →  {m['suggested']}")
        print()

    if report["missing"]:
        unique = len(report['missing'])
        occur = summary['missing']
        label = f"{unique} target{'s' if unique != 1 else ''}, {occur} occurrence{'s' if occur != 1 else ''}"
        print(f"MISSING PAGES ({label}):")
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


def inject_referenced_by(vault_path) -> int:
    """Inject or update '## Referenced by' blocks in wiki pages.

    Scans all wiki pages for typed links (frontmatter) and wikilinks (prose),
    builds a reverse map {target_slug: [(source_slug, link_type), ...]},
    then injects/updates a marked block at the end of each target page.

    Returns the number of pages modified.
    """
    vault_path = Path(vault_path)
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return 0

    # Collect all pages
    pages: dict[str, Path] = {}  # slug -> file path
    for root, dirs, files in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.endswith(".md") and not fname.endswith(".snapshot.md"):
                fp = Path(root) / fname
                pages[fp.stem] = fp

    # Build reverse map: target_slug -> [(source_slug, link_type), ...]
    reverse_map: dict[str, list[tuple[str, str]]] = {}

    for slug, fp in pages.items():
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Typed links from frontmatter
        typed = parse_typed_links(content)
        for link in typed:
            target = link["target"]
            if target == slug:
                continue
            reverse_map.setdefault(target, []).append((slug, link["type"]))

        # Wikilinks from prose (excluding referenced-by blocks to avoid circular refs)
        content_norm = content.replace("\r\n", "\n").replace("\r", "\n")
        fm_match = re.match(
            r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content_norm, re.DOTALL
        )
        body = content_norm[fm_match.end():] if fm_match else content_norm
        # Strip referenced-by blocks before scanning
        body = re.sub(
            r"<!-- referenced-by:start -->.*?<!-- referenced-by:end -->",
            "", body, flags=re.DOTALL,
        )
        for raw_target in WIKILINK_RE.findall(body):
            target = extract_link_target(raw_target)
            if not target or target == slug:
                continue
            # Don't duplicate if already covered by a typed link
            existing = reverse_map.get(target, [])
            if not any(src == slug for src, _ in existing):
                reverse_map.setdefault(target, []).append((slug, "references"))

    # Inject/update blocks
    modified = 0
    start_marker = "<!-- referenced-by:start -->"
    end_marker = "<!-- referenced-by:end -->"

    for target_slug, backlinks in reverse_map.items():
        if target_slug not in pages:
            continue
        fp = pages[target_slug]

        # Sort backlinks for deterministic output
        backlinks_sorted = sorted(set(backlinks))

        lines = []
        lines.append(start_marker)
        lines.append("## Referenced by")
        lines.append("")
        for src_slug, link_type in backlinks_sorted:
            lines.append(f"- [[{src_slug}]] ({link_type})")
        lines.append(end_marker)
        block = "\n".join(lines)

        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if start_marker in content and end_marker in content:
            # Replace existing block
            new_content = re.sub(
                re.escape(start_marker) + r".*?" + re.escape(end_marker),
                block,
                content,
                flags=re.DOTALL,
            )
        else:
            # Append at end
            new_content = content.rstrip("\n") + "\n\n" + block + "\n"

        if new_content != content:
            atomic_write(fp, new_content)
            modified += 1

    return modified


# ---------------------------------------------------------------------------
# v2 footnote lint rules (L-1..L-4) and format_version dispatch.
#
# Per design wiki-footnote-citations.md §4.7, a page is treated as v2 iff
# `format_version` parses to the integer literal 2. Any other value (string
# "2", float 2.1, future int 3, missing key) is treated as legacy and the
# new rules do not apply.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FootnoteRef:
    """An inline `[^id]` reference occurrence in the body."""
    id: str
    line: int
    col: int


@dataclass(frozen=True)
class FootnoteDef:
    """A `[^id]: text` definition occurrence in the body."""
    id: str
    line: int
    col: int
    text: str


# Reference: `[^id]` inline. Strict charset matches the migrator's ID scheme
# (lowercase alphanumerics + hyphen). Definitions with mixed case or other
# characters are simply not parsed by these rules.
_FOOTNOTE_REF_RE = re.compile(r"\[\^([a-z0-9-]+)\]")
# Definition: a line beginning `[^id]: <text>`. Multiline mode lets us scan
# the whole body in one pass.
_FOOTNOTE_DEF_RE = re.compile(
    r"^\[\^([a-z0-9-]+)\]:\s*(.*)$", re.MULTILINE
)


def is_v2_page(frontmatter: dict) -> bool:
    """Return True iff `frontmatter['format_version']` is the integer literal 2.

    Strict integer comparison (per design §4.7): rejects bool (which subclasses
    int in Python), strings, floats, and future versions.
    """
    value = frontmatter.get("format_version")
    if isinstance(value, bool):
        return False
    return isinstance(value, int) and value == 2


def _scannable_body(body: str) -> str:
    """Return body with fenced code blocks and inline code spans blanked out.

    Replaces those regions with same-length space runs so absolute character
    offsets — and therefore line/col coordinates of surviving matches — stay
    aligned with the original body. Mirrors the exclusion logic at
    `fix_alias_mismatches` (lint_links.py:485-505) which skips fenced blocks
    and inline `code` spans, so footnote markers inside code never trigger
    lint rules. (We keep newlines so `re.MULTILINE` anchors keep working.)
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    out_lines: list[str] = []
    code_fence_marker = ""

    for line in lines:
        stripped = line.strip()
        if not code_fence_marker:
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence_match:
                code_fence_marker = fence_match.group(1)
                # Blank the fence line itself so a `[^id]` accidentally on the
                # opening fence is not parsed.
                out_lines.append(" " * len(line))
                continue
            # Strip inline `code` spans — replace each with same-length spaces
            # so column offsets are preserved.
            scrubbed = re.sub(
                r"`[^`\n]+`", lambda m: " " * len(m.group(0)), line
            )
            out_lines.append(scrubbed)
        else:
            fence_char = code_fence_marker[0]
            fence_len = len(code_fence_marker)
            close_match = re.match(
                r"^" + re.escape(fence_char) + r"{" + str(fence_len) + r",}\s*$",
                stripped,
            )
            if close_match:
                code_fence_marker = ""
            out_lines.append(" " * len(line))

    return "\n".join(out_lines)


def _offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert an absolute character offset into 1-based (line, col)."""
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    last_nl = prefix.rfind("\n")
    col = offset - (last_nl + 1) + 1 if last_nl >= 0 else offset + 1
    return line, col


def parse_footnotes(body: str) -> tuple[list[FootnoteRef], list[FootnoteDef]]:
    """Parse all `[^id]` refs and `[^id]: text` defs from the body.

    Excludes matches inside fenced code blocks (``` and ~~~) and inline
    backtick spans. A definition line is also recorded as one ref by the
    underlying regex; we filter those out so refs only carry inline-prose
    occurrences.
    """
    scannable = _scannable_body(body)

    defs: list[FootnoteDef] = []
    def_offsets: set[int] = set()
    for m in _FOOTNOTE_DEF_RE.finditer(scannable):
        line, col = _offset_to_line_col(scannable, m.start())
        defs.append(FootnoteDef(id=m.group(1), line=line, col=col, text=m.group(2).strip()))
        # Mark the definition's `[^id]` opening offset so we can skip it when
        # collecting refs (otherwise every def would also count as a ref).
        def_offsets.add(m.start())

    refs: list[FootnoteRef] = []
    for m in _FOOTNOTE_REF_RE.finditer(scannable):
        if m.start() in def_offsets:
            continue
        line, col = _offset_to_line_col(scannable, m.start())
        refs.append(FootnoteRef(id=m.group(1), line=line, col=col))

    return refs, defs


def _violation(rule: str, page: str, line: int, col: int, message: str,
               *, fid: str | None = None, severity: str = "error") -> dict:
    """Build a violation record (dict) with consistent keys."""
    v = {
        "rule": rule,
        "page": page,
        "line": line,
        "col": col,
        "severity": severity,
        "message": message,
    }
    if fid is not None:
        v["id"] = fid
    return v


def check_footnote_refs_have_defs(page: str, body: str, frontmatter: dict) -> list[dict]:
    """L-1: every `[^id]` ref has a matching `[^id]:` definition.

    Returns [] on legacy pages.
    """
    if not is_v2_page(frontmatter):
        return []
    refs, defs = parse_footnotes(body)
    def_ids = {d.id for d in defs}
    violations: list[dict] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.id in def_ids:
            continue
        if ref.id in seen:
            continue
        seen.add(ref.id)
        violations.append(_violation(
            "L-1", page, ref.line, ref.col,
            f"footnote reference [^{ref.id}] has no matching definition",
            fid=ref.id,
        ))
    return violations


def check_footnote_defs_referenced(page: str, body: str, frontmatter: dict) -> list[dict]:
    """L-2: every `[^id]:` def is referenced at least once. Severity=warning.

    Returns [] on legacy pages.
    """
    if not is_v2_page(frontmatter):
        return []
    refs, defs = parse_footnotes(body)
    ref_ids = {r.id for r in refs}
    violations: list[dict] = []
    seen: set[str] = set()
    for d in defs:
        if d.id in ref_ids:
            continue
        if d.id in seen:
            continue
        seen.add(d.id)
        violations.append(_violation(
            "L-2", page, d.line, d.col,
            f"footnote definition [^{d.id}] is never referenced",
            fid=d.id, severity="warning",
        ))
    return violations


def check_footnote_id_uniqueness(page: str, body: str, frontmatter: dict) -> list[dict]:
    """L-3: footnote IDs are unique within the page.

    Reports each duplicate definition (after the first) once. Returns [] on
    legacy pages.
    """
    if not is_v2_page(frontmatter):
        return []
    _, defs = parse_footnotes(body)
    violations: list[dict] = []
    first_seen: dict[str, FootnoteDef] = {}
    for d in defs:
        if d.id in first_seen:
            violations.append(_violation(
                "L-3", page, d.line, d.col,
                f"footnote id [^{d.id}] defined more than once "
                f"(first at line {first_seen[d.id].line})",
                fid=d.id,
            ))
        else:
            first_seen[d.id] = d
    return violations


def _separator_line(scannable_body: str) -> int | None:
    """Return the 1-based line number of the body's `---` separator, or None.

    Walks the scannable body line-by-line and returns the first line whose
    stripped content is exactly `---` (the compiled-truth / timeline divider).
    Line-walking avoids regex split arithmetic where `\\s*` may consume an
    unknown number of newlines.
    """
    for idx, line in enumerate(scannable_body.split("\n"), start=1):
        if line.strip() == "---":
            return idx
    return None


def _last_timeline_line(scannable_body: str, sep_line: int) -> int | None:
    """Return the 1-based line number of the last timeline bullet, or None.

    A timeline bullet matches `^-\\s+\\d{4}-\\d{2}-\\d{2}` and lives strictly
    below `sep_line` (the `---` separator). Returns None if there are no
    bullets after the separator.
    """
    last_line: int | None = None
    bullet_re = re.compile(r"^-\s+\d{4}-\d{2}-\d{2}")
    for idx, line in enumerate(scannable_body.split("\n"), start=1):
        if idx <= sep_line:
            continue
        if bullet_re.match(line):
            last_line = idx
    return last_line


def check_footnote_placement(page: str, body: str, frontmatter: dict) -> list[dict]:
    """L-4: footnote definitions all sit after the last timeline line.

    Reports any def whose line number is at or before the last timeline
    bullet (or before the body's `---` separator if a timeline exists).
    Returns [] on legacy pages, and [] if no `---` separator exists (the
    page has no timeline to anchor against).
    """
    if not is_v2_page(frontmatter):
        return []
    scannable = _scannable_body(body)
    # Anchor: the line of the body's `---` separator. Defs must come AFTER
    # it; preferably also after the last timeline bullet.
    sep_line = _separator_line(scannable)
    if sep_line is None:
        return []
    last_tl_line = _last_timeline_line(scannable, sep_line)
    threshold = last_tl_line if last_tl_line is not None else sep_line

    _, defs = parse_footnotes(body)
    violations: list[dict] = []
    for d in defs:
        if d.line <= threshold:
            violations.append(_violation(
                "L-4", page, d.line, d.col,
                f"footnote definition [^{d.id}] must appear after the timeline "
                f"(at or below line {threshold + 1})",
                fid=d.id,
            ))
    return violations


def run_all_checks(page: str, body: str, frontmatter: dict) -> list[dict]:
    """Run all v2 footnote checks against a single page.

    On legacy pages every check is a no-op, so the returned list is empty.
    Existing entry points (check_stale_pages, check_unbalanced_pages,
    fix_alias_mismatches, inject_referenced_by) remain untouched and are
    invoked separately by `main()`.
    """
    violations: list[dict] = []
    violations.extend(check_footnote_refs_have_defs(page, body, frontmatter))
    violations.extend(check_footnote_defs_referenced(page, body, frontmatter))
    violations.extend(check_footnote_id_uniqueness(page, body, frontmatter))
    violations.extend(check_footnote_placement(page, body, frontmatter))
    return violations


# ---------------------------------------------------------------------------
# Migration ops M-1..M-5 — see design wiki-footnote-citations.md §2 D6 +
# §4.4 (claims_inferred / claims_ambiguous) + §4.6 (footnote ID scheme,
# collision determinism, src- prefix).
#
# `migrate_legacy_page(page_path, content) -> (new_content, MigrationReport)`
# is the only public entry point. Existing fix paths (`fix_alias_mismatches`,
# `inject_referenced_by`) are not refactored.
# ---------------------------------------------------------------------------


@dataclass
class MigrationReport:
    """Result of running `migrate_legacy_page` on a single page.

    `success` and `skipped` are mutually exclusive in normal use:
      - success=True: the migrator wrote a new body.
      - skipped=True: the page is already v2 (`reason="already_v2"`) or the
        migration's internal round-trip parse failed
        (`reason="round_trip_failed"`).
    `format_version_before` / `_after` are diagnostic; the version is read
    from frontmatter both pre- and post-migration.
    """
    success: bool = False
    skipped: bool = False
    reason: str = ""
    format_version_before: int | None = None
    format_version_after: int | None = None
    notes: list[str] = field(default_factory=list)


# ID derived from a wikilink target: lowercase letters, digits, hyphens only.
# All other characters (spaces, slashes, dots, underscores) become `-`, then
# repeats are collapsed and edge hyphens stripped — same lenience as
# `normalize_for_matching` but emitting a slug not a normalized form.
_ID_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _slugify_basename(target: str) -> str:
    """Derive a footnote ID from a wikilink target's basename.

    Per design §4.6: ID is `basename(target).removesuffix('.md')`. We also
    lowercase + replace non-alnum with `-` so IDs match the v2 lint regex
    (`[a-z0-9-]+`). Empty result falls back to `'src'`.
    """
    target = target.split("|", 1)[0]
    target = target.split("#", 1)[0]
    target = target.strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    base = os.path.basename(target).lower()
    slug = _ID_NON_ALNUM_RE.sub("-", base).strip("-")
    return slug or "src"


def _scrub_for_scan(body: str) -> str:
    """Return body with code regions blanked but offsets preserved.

    Same shape as `_scannable_body` but additionally blanks indented code
    blocks (≥4 spaces or a tab at the start of a line). Used by the migrator
    so wikilink offsets in code don't survive the M-1 sweep.
    """
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = body.split("\n")
    out: list[str] = []
    code_fence_marker = ""
    for line in lines:
        stripped = line.strip()
        if not code_fence_marker:
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence_match:
                code_fence_marker = fence_match.group(1)
                out.append(" " * len(line))
                continue
            # Indented code block: ≥4 leading spaces or a tab. We keep blank
            # lines as-is (they don't contain wikilinks).
            if line and (line.startswith("    ") or line.startswith("\t")):
                out.append(" " * len(line))
                continue
            scrubbed = re.sub(
                r"`[^`\n]+`", lambda m: " " * len(m.group(0)), line
            )
            out.append(scrubbed)
        else:
            fence_char = code_fence_marker[0]
            fence_len = len(code_fence_marker)
            close_match = re.match(
                r"^" + re.escape(fence_char) + r"{" + str(fence_len) + r",}\s*$",
                stripped,
            )
            if close_match:
                code_fence_marker = ""
            out.append(" " * len(line))
    return "\n".join(out)


_RELATIONSHIPS_HEADING_RE = re.compile(
    r"^(#{1,6})\s+(?:relationships|related|see also)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_FOOTNOTE_DEF_LINE_RE = re.compile(r"^\[\^[a-z0-9-]+\]:\s")
_INLINE_FOOTNOTE_RE = re.compile(r"\^\[(inferred|ambiguous)\]")


def _relationships_spans(scannable: str) -> list[tuple[int, int]]:
    """Return [(start, end), ...] character spans inside Relationships sections.

    A Relationships section spans from a heading at any level whose text is
    `relationships`, `related`, or `see also` (case-insensitive) up to (but
    not including) the next heading at any level — design §2 D6 M-1.
    """
    spans: list[tuple[int, int]] = []
    headings = list(_ANY_HEADING_RE.finditer(scannable))
    rel_starts = {m.start() for m in _RELATIONSHIPS_HEADING_RE.finditer(scannable)}
    for i, m in enumerate(headings):
        if m.start() not in rel_starts:
            continue
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(scannable)
        spans.append((start, end))
    return spans


def _in_any_span(offset: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= offset < e for s, e in spans)


def _line_starts_with_footnote_def(scannable: str, offset: int) -> bool:
    """True if `scannable[offset]` lies on a `[^id]: …` definition line."""
    line_start = scannable.rfind("\n", 0, offset) + 1
    line_end = scannable.find("\n", offset)
    if line_end == -1:
        line_end = len(scannable)
    return bool(_FOOTNOTE_DEF_LINE_RE.match(scannable[line_start:line_end]))


def _has_user_footnotes(body: str) -> bool:
    """True iff the body contains any `[^id]` ref or def outside code regions.

    Used to decide whether migrator-derived IDs get the `src-` prefix
    (design §4.6 / D6 M-5).
    """
    scannable = _scrub_for_scan(body)
    return bool(_FOOTNOTE_REF_RE.search(scannable))


def _split_compiled_below(body: str) -> tuple[str, str | None]:
    """Split body on the first `\\n---\\s*\\n` separator.

    Returns (compiled_truth, below_rule). If no separator exists,
    returns (body, None).
    """
    parts = re.split(r"\n---[ \t]*\n", body, maxsplit=1)
    if len(parts) == 1:
        return body, None
    return parts[0], parts[1]


def _migrate_m1(
    compiled: str, has_user_footnotes: bool
) -> tuple[str, list[tuple[str, str]]]:
    """M-1: rewrite inline `[[target]]` wikilinks to `[^id]` refs.

    Returns the new compiled-truth text and a list of `(id, target)` pairs
    in document order, deduplicated. Excludes wikilinks inside Relationships
    sections, fenced code, inline code, indented code, and footnote-def lines.
    """
    scannable = _scrub_for_scan(compiled)
    rel_spans = _relationships_spans(scannable)

    # Walk wikilinks in the scannable view (offsets aligned with `compiled`).
    # Decisions:
    #   - skip if inside Relationships span
    #   - skip if line is a footnote-def line
    # Each kept match contributes a footnote ID assignment.
    matches: list[tuple[int, int, str]] = []  # (start, end, target)
    for m in WIKILINK_RE.finditer(scannable):
        if _in_any_span(m.start(), rel_spans):
            continue
        if _line_starts_with_footnote_def(scannable, m.start()):
            continue
        target = extract_link_target(m.group(1))
        if not target:
            continue
        matches.append((m.start(), m.end(), target))

    # Assign IDs in document order. Same target → same ID. Different targets
    # whose basename collides → numeric suffix `-2`, `-3`, …
    target_to_id: dict[str, str] = {}
    base_to_count: dict[str, int] = {}
    pairs: list[tuple[str, str]] = []  # (id, original_target_string)
    for _start, _end, target in matches:
        if target in target_to_id:
            continue
        base = _slugify_basename(target)
        if has_user_footnotes:
            base = "src-" + base
        n = base_to_count.get(base, 0) + 1
        base_to_count[base] = n
        fid = base if n == 1 else f"{base}-{n}"
        target_to_id[target] = fid
        pairs.append((fid, target))

    # Rewrite compiled-truth right-to-left so earlier offsets stay valid.
    out = compiled
    for start, end, target in reversed(matches):
        fid = target_to_id[target]
        out = out[:start] + f"[^{fid}]" + out[end:]
    return out, pairs


def _walk_back_for_claim(body: str, marker_offset: int) -> str:
    """Capture the claim text preceding a `^[inferred]` / `^[ambiguous]` marker.

    Walks back from `marker_offset` per design §2 D6 M-2 priority order:
      - previous `. ! ?`
      - bullet's first non-whitespace char (if marker is on/inside a bullet line)
      - end of previous heading line
      - start of file

    If no boundary is found within 500 chars, returns the literal string `?`.
    Otherwise returns the captured text truncated to 200 chars and stripped.
    """
    if marker_offset <= 0:
        return "?"

    # Determine if the marker's line is a bullet line.
    line_start = body.rfind("\n", 0, marker_offset) + 1
    line_text = body[line_start:marker_offset]
    bullet_match = re.match(r"^[ \t]*([-*+])[ \t]+", line_text)
    bullet_first_char_offset: int | None = None
    if bullet_match:
        # First non-whitespace char is the bullet glyph itself; per design,
        # capture from the bullet's TEXT start (the char after the bullet
        # marker and its whitespace), not from the hyphen. Verified by the
        # bullet edge-case test (no leading "- " in the entry).
        bullet_first_char_offset = line_start + bullet_match.end()

    # The captured text is the sentence PRECEDING the marker — its terminating
    # punctuation (if any) belongs to the captured text, not to the boundary.
    # So when searching for "previous sentence-end" we skip whitespace + a
    # single trailing `.`/`!`/`?` adjacent to the marker.
    search_end = marker_offset
    while search_end > 0 and body[search_end - 1] in " \t":
        search_end -= 1
    if search_end > 0 and body[search_end - 1] in ".!?":
        search_end -= 1

    # Search backwards within 500 chars for the closest of the boundaries.
    limit = max(0, marker_offset - 500)
    best: int | None = None  # offset of first char of captured text

    # Sentence-end search: find the most recent `. ` / `! ` / `? ` (or `.\n`
    # variants) PRIOR to the current sentence's terminator.
    last_period = max(
        body.rfind(". ", limit, search_end),
        body.rfind("? ", limit, search_end),
        body.rfind("! ", limit, search_end),
        body.rfind(".\n", limit, search_end),
        body.rfind("?\n", limit, search_end),
        body.rfind("!\n", limit, search_end),
    )
    if last_period != -1:
        # Capture starts after the punctuation + the following space/newline.
        candidate = last_period + 2
        if candidate <= marker_offset:
            best = candidate

    # Bullet first non-whitespace char.
    if bullet_first_char_offset is not None and bullet_first_char_offset >= limit:
        if best is None or bullet_first_char_offset > best:
            best = bullet_first_char_offset

    # End of previous heading line: find the most recent `\n` that follows
    # a heading line (i.e., the line after a heading).
    heading_iter = list(re.finditer(r"^#{1,6}\s+.*$", body[:marker_offset], re.MULTILINE))
    if heading_iter:
        last_heading = heading_iter[-1]
        # Capture starts after the heading's newline.
        nl = body.find("\n", last_heading.end())
        candidate = (nl + 1) if nl != -1 else last_heading.end()
        if candidate >= limit and (best is None or candidate > best):
            best = candidate

    # Start-of-file fallback (only if within 500-char window).
    if best is None and marker_offset <= 500:
        best = 0

    if best is None:
        return "?"

    captured = body[best:marker_offset].strip()
    if not captured:
        return "?"
    if len(captured) > 200:
        captured = captured[:200]
    return captured


def _migrate_m2(
    body: str, frontmatter: dict
) -> tuple[str, dict]:
    """M-2: extract `^[inferred]` / `^[ambiguous]` markers into frontmatter.

    Mutates a copy of `frontmatter` (returned) by appending claim text to
    `claims_inferred` / `claims_ambiguous` lists. The body returned has the
    markers stripped (token + a single trailing whitespace if present).
    """
    fm = dict(frontmatter)
    inferred = list(fm.get("claims_inferred") or [])
    ambiguous = list(fm.get("claims_ambiguous") or [])

    # Walk the markers left-to-right; collect captured text using offsets in
    # the *original* body (so walk-back sees the un-mutated text). Then strip
    # markers right-to-left so earlier offsets stay valid.
    marker_hits: list[tuple[int, int, str, str]] = []  # (start, end, kind, captured)
    for m in _INLINE_FOOTNOTE_RE.finditer(body):
        kind = m.group(1)
        captured = _walk_back_for_claim(body, m.start())
        marker_hits.append((m.start(), m.end(), kind, captured))
        if kind == "inferred":
            inferred.append(captured)
        else:
            ambiguous.append(captured)

    new_body = body
    for start, end, _kind, _captured in reversed(marker_hits):
        # Also consume a single trailing whitespace if it directly follows
        # the marker (per design §2 D6 M-2 final bullet).
        consume_end = end
        if consume_end < len(new_body) and new_body[consume_end] in " \t":
            consume_end += 1
        # If removing the marker leaves a leading space at the start of a line,
        # also drop that leading space so we don't end up with trailing-space
        # artifacts on the previous sentence.
        consume_start = start
        if consume_start > 0 and new_body[consume_start - 1] in " \t":
            consume_start -= 1
        new_body = new_body[:consume_start] + new_body[consume_end:]

    if inferred:
        fm["claims_inferred"] = inferred
    if ambiguous:
        fm["claims_ambiguous"] = ambiguous
    return new_body, fm


def _serialize_frontmatter(fm: dict) -> str:
    """Serialize a frontmatter dict back to YAML for splicing into a page.

    Produces canonical YAML with PyYAML's default flow=False so lists become
    block-style. Trailing newline is dropped — caller controls separators.
    """
    return yaml.safe_dump(
        fm, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip("\n")


def migrate_legacy_page(
    page_path: str | Path, content: str
) -> tuple[str, MigrationReport]:
    """Migrate a legacy wiki page to v2 format.

    Returns the rewritten content and a `MigrationReport`. Idempotent on
    pages already at `format_version: 2` (returns content byte-equal).
    Performs ops M-1..M-5 from design §2 D6:

      - M-1: inline compiled-truth wikilinks → `[^id]` refs (+ defs at bottom).
      - M-2: `^[inferred]` / `^[ambiguous]` markers → frontmatter claim lists.
      - M-3: write `format_version: 2` into frontmatter.
      - M-4: idempotency (skipped on v2 input).
      - M-5: when the page already contains user `[^…]` footnotes, every
        migrator-derived ID is prefixed `src-` (uniformly).

    On internal round-trip failure, returns the original content with
    `MigrationReport(skipped=True, reason="round_trip_failed")` — the caller
    must treat the file as untouched.
    """
    fm, body = _parse_fm(content)
    fv_before = fm.get("format_version") if isinstance(fm.get("format_version"), int) else None

    if is_v2_page(fm):
        return content, MigrationReport(
            skipped=True,
            reason="already_v2",
            format_version_before=fv_before,
            format_version_after=fv_before,
        )

    # Detect pre-existing user footnotes in the *original* body. This decides
    # whether migrator-derived IDs get the `src-` prefix (M-5).
    has_user_fn = _has_user_footnotes(body)

    # M-2 first: scan whole body for `^[…]` markers, capture claims, strip
    # markers. Done before M-1 so the wikilink rewriter sees the cleaned body
    # (and so claim capture sees original prose with intact wikilinks).
    body_after_m2, fm_after_m2 = _migrate_m2(body, fm)

    # Split body for M-1.
    compiled, below = _split_compiled_below(body_after_m2)

    # M-1: rewrite compiled-truth wikilinks.
    new_compiled, fn_pairs = _migrate_m1(compiled, has_user_fn)

    # Build the footnote-definition block to append at file bottom.
    def_lines = [f"[^{fid}]: [[{target}]]" for fid, target in fn_pairs]
    def_block = "\n".join(def_lines)

    # Reassemble body. If the page had no separator, we still emit one so the
    # bottom block lives below the rule per the design.
    if below is None:
        new_body = new_compiled.rstrip("\n")
        if def_block:
            new_body = new_body + "\n\n---\n\n" + def_block + "\n"
        else:
            new_body = new_compiled  # no defs, no synthetic separator
    else:
        below_stripped = below.rstrip("\n")
        new_body = new_compiled + "\n---\n" + below_stripped
        if def_block:
            new_body = new_body + "\n\n" + def_block + "\n"
        else:
            # Preserve original trailing newline if any, otherwise leave as is.
            if below.endswith("\n"):
                new_body = new_body + "\n"

    # M-3: set format_version: 2.
    fm_after_m2["format_version"] = 2

    # Reassemble the full content.
    new_fm_yaml = _serialize_frontmatter(fm_after_m2)
    new_content = "---\n" + new_fm_yaml + "\n---\n\n" + new_body.lstrip("\n")

    # Internal round-trip parse:
    #   (a) frontmatter parses without raising.
    #   (b) body still splits cleanly on the `---` separator (when defs exist).
    #   (c) frontmatter contains format_version: 2.
    try:
        rt_fm, rt_body = _parse_fm(new_content)
        if rt_fm.get("format_version") != 2:
            raise ValueError("format_version not set to 2")
        if def_block and "\n---\n" not in rt_body and "\n---" not in rt_body:
            raise ValueError("body separator missing after migration")
    except Exception as exc:  # pragma: no cover — defensive
        return content, MigrationReport(
            skipped=True,
            reason="round_trip_failed",
            format_version_before=fv_before,
            format_version_after=None,
            notes=[str(exc)],
        )

    return new_content, MigrationReport(
        success=True,
        format_version_before=fv_before,
        format_version_after=2,
    )


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
    parser.add_argument(
        "--stale", action="store_true",
        help="Check for stale pages (compiled truth older than latest timeline)",
    )
    parser.add_argument(
        "--unbalanced", action="store_true",
        help="Check for unbalanced pages (many timeline entries without rewrite)",
    )
    parser.add_argument(
        "--referenced-by", action="store_true",
        help="Inject/update '## Referenced by' blocks in wiki pages",
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

    # Auto-fix if requested. Migration runs FIRST (per design §4.3 — `--fix`
    # is the opportunistic migration vehicle). After the per-page migration
    # writes complete, the alias-mismatch fixer runs on the (possibly
    # migrated) bodies just as before.
    if args.fix:
        migrated = 0
        skipped_v2 = 0
        for rel_path in files_to_scan:
            abs_path = (
                rel_path
                if os.path.isabs(rel_path)
                else os.path.join(str(vault_path), rel_path)
            )
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    page_content = f.read()
            except OSError:
                continue
            new_content, mig_report = migrate_legacy_page(abs_path, page_content)
            if mig_report.success and new_content != page_content:
                try:
                    atomic_write(abs_path, new_content)
                    migrated += 1
                except OSError as e:
                    print(
                        f"Warning: could not write {rel_path}: {e}",
                        file=sys.stderr,
                    )
            elif mig_report.skipped and mig_report.reason == "already_v2":
                skipped_v2 += 1
        if not args.json_output and migrated:
            print(f"Migrated {migrated} legacy page(s) to v2 format.\n")

        # Re-scan after migration so the alias-mismatch list reflects the
        # new bodies (footnote refs may have moved wikilinks around).
        index = build_resolution_index(vault_path)
        report = resolve_links(vault_path, index, files_to_scan)

        fixes = 0
        if report["alias_mismatches"]:
            fixes = fix_alias_mismatches(vault_path, report["alias_mismatches"])
            if not args.json_output:
                print(f"Fixed {fixes} alias mismatch(es).\n")
            # Re-scan after fixing to get updated report
            index = build_resolution_index(vault_path)
            report = resolve_links(vault_path, index, files_to_scan)
        report["summary"]["fixes_applied"] = fixes
        report["summary"]["migrations_applied"] = migrated
        report["summary"]["migrations_skipped_v2"] = skipped_v2

    print_report(report, json_output=args.json_output)

    if args.stale:
        stale = check_stale_pages(vault_path)
        if stale:
            if args.json_output:
                print(json.dumps({"stale": stale}, indent=2))
            else:
                print(f"STALE ({len(stale)} pages need compiled-truth update):")
                for s in stale:
                    print(f"  {s['page']}  updated={s['updated']}  latest_timeline={s['latest_timeline']}")
                print()

    if args.unbalanced:
        unbalanced = check_unbalanced_pages(vault_path)
        if unbalanced:
            if args.json_output:
                print(json.dumps({"unbalanced": unbalanced}, indent=2))
            else:
                print(f"UNBALANCED ({len(unbalanced)} pages need rewrite):")
                for u in unbalanced:
                    print(f"  {u['page']}  updated={u['updated']}  new_entries={u['new_entries']}")
                print()

    if args.referenced_by:
        count = inject_referenced_by(vault_path)
        if not args.json_output:
            print(f"Injected/updated referenced-by blocks in {count} page(s).")

    sys.exit(0 if report["clean"] else 1)


if __name__ == "__main__":
    main()
