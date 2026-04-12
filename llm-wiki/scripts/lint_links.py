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
    """Normalize a name for fuzzy matching.

    Case-insensitive, treats spaces/hyphens/underscores as equivalent.
    Note: Obsidian's exact normalization behavior is not fully documented
    and may vary. This is a lenient approximation — it may resolve links
    that Obsidian itself would not. Prefer exact filenames in wikilinks.
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
    # Normalize CRLF → LF for Windows compatibility
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Extract frontmatter block (--- or ... as closing delimiter)
    match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content, re.DOTALL)
    if not match:
        return []

    fm = match.group(1)

    # Try inline format: aliases: [a, b, c] or aliases: ["Smith, John", b]
    inline = re.search(r"^aliases:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline:
        raw = inline.group(1)
        # Parse respecting quoted values (commas inside quotes are not delimiters)
        aliases = []
        for m in re.finditer(r'"([^"]*?)"|\'([^\']*?)\'|([^,\s][^,]*)', raw):
            val = (m.group(1) or m.group(2) or m.group(3) or "").strip()
            if val:
                aliases.append(val)
        return aliases

    # Try list format: aliases:\n  - a\n  - b
    list_match = re.search(r"^aliases:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.MULTILINE)
    if list_match:
        items = re.findall(r"^\s+-\s+(.+)", list_match.group(1), re.MULTILINE)
        return [item.strip().strip("\"'") for item in items if item.strip()]

    return []


KNOWN_LINK_TYPES = {
    "references", "contradicts", "depends_on", "supersedes",
    "authored_by", "works_at", "mentions",
}


def parse_typed_links(content: str) -> list[dict]:
    """Extract typed links from YAML frontmatter.

    Handles format:
        links:
          - {target: "slug", type: "references"}
          - {target: "other", type: "contradicts"}
    Also handles unquoted values.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content, re.DOTALL)
    if not match:
        return []
    fm = match.group(1)
    links = []
    for m in re.finditer(
        r'-\s*\{[^}]*target:\s*"?([^",}\s]+)"?\s*,\s*type:\s*"?([^",}\s]+)"?[^}]*\}',
        fm,
    ):
        links.append({"target": m.group(1), "type": m.group(2)})
    # Also handle reversed order: {type: ..., target: ...}
    for m in re.finditer(
        r'-\s*\{[^}]*type:\s*"?([^",}\s]+)"?\s*,\s*target:\s*"?([^",}\s]+)"?[^}]*\}',
        fm,
    ):
        links.append({"target": m.group(2), "type": m.group(1)})
    return links


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
            with open(abs_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
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

        # Wikilinks from prose
        content_norm = content.replace("\r\n", "\n").replace("\r", "\n")
        fm_match = re.match(
            r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content_norm, re.DOTALL
        )
        body = content_norm[fm_match.end():] if fm_match else content_norm
        for target in WIKILINK_RE.findall(body):
            if target == slug:
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
            fp.write_text(new_content, encoding="utf-8")
            modified += 1

    return modified


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

    # Auto-fix if requested
    if args.fix and report["alias_mismatches"]:
        fixes = fix_alias_mismatches(vault_path, report["alias_mismatches"])
        if not args.json_output:
            print(f"Fixed {fixes} alias mismatch(es).\n")
        # Re-scan after fixing to get updated report
        index = build_resolution_index(vault_path)
        report = resolve_links(vault_path, index, files_to_scan)
        report["summary"]["fixes_applied"] = fixes

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
