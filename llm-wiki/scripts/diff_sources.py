#!/usr/bin/env python3
"""
Diff two versions of a source document and produce a structured summary.

Used during re-ingestion to identify what changed, so the agent can
focus wiki updates on affected sections instead of re-reading everything.

Usage:
    python diff_sources.py <old-file> <new-file>
    python diff_sources.py <old-file> <new-file> --json

Output (default): Human-readable diff summary with added/removed/changed sections.
Output (--json):  Machine-readable JSON for programmatic use by agents.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys


def extract_sections(text: str) -> dict[str, str]:
    """Split a markdown document into sections by headings."""
    sections: dict[str, str] = {}
    current_heading = "_preamble"
    current_lines: list[str] = []

    for line in text.splitlines():
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            # Save previous section
            content = "\n".join(current_lines).strip()
            if content:
                sections[current_heading] = content
            current_heading = heading_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    # Save last section
    content = "\n".join(current_lines).strip()
    if content:
        sections[current_heading] = content

    return sections


def compute_diff(old_text: str, new_text: str) -> dict:
    """Compute a structured diff between two document versions."""
    old_sections = extract_sections(old_text)
    new_sections = extract_sections(new_text)

    all_headings = list(dict.fromkeys(
        list(old_sections.keys()) + list(new_sections.keys())
    ))

    added_sections = []
    removed_sections = []
    changed_sections = []
    unchanged_sections = []

    for heading in all_headings:
        old_content = old_sections.get(heading)
        new_content = new_sections.get(heading)

        if old_content is None and new_content is not None:
            added_sections.append({
                "heading": heading,
                "content": new_content,
                "char_count": len(new_content),
            })
        elif old_content is not None and new_content is None:
            removed_sections.append({
                "heading": heading,
                "content": old_content,
                "char_count": len(old_content),
            })
        elif old_content != new_content:
            # Compute line-level diff for the changed section
            old_lines = (old_content or "").splitlines()
            new_lines = (new_content or "").splitlines()
            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile="old", tofile="new",
                lineterm=""
            ))
            additions = [l[1:] for l in diff_lines if l.startswith('+') and not l.startswith('+++')]
            deletions = [l[1:] for l in diff_lines if l.startswith('-') and not l.startswith('---')]

            changed_sections.append({
                "heading": heading,
                "additions": additions,
                "deletions": deletions,
                "diff_lines": len(diff_lines),
            })
        else:
            unchanged_sections.append(heading)

    # Overall statistics
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    total_diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    lines_added = sum(1 for l in total_diff if l.startswith('+') and not l.startswith('+++'))
    lines_removed = sum(1 for l in total_diff if l.startswith('-') and not l.startswith('---'))

    return {
        "summary": {
            "sections_added": len(added_sections),
            "sections_removed": len(removed_sections),
            "sections_changed": len(changed_sections),
            "sections_unchanged": len(unchanged_sections),
            "lines_added": lines_added,
            "lines_removed": lines_removed,
            "old_size_chars": len(old_text),
            "new_size_chars": len(new_text),
        },
        "added": added_sections,
        "removed": removed_sections,
        "changed": changed_sections,
        "unchanged": unchanged_sections,
    }


def format_human_readable(diff: dict) -> str:
    """Format diff as a human-readable summary."""
    lines = []
    s = diff["summary"]

    lines.append(f"Source diff: {s['lines_added']} lines added, {s['lines_removed']} lines removed")
    lines.append(f"Sections: {s['sections_added']} added, {s['sections_removed']} removed, "
                 f"{s['sections_changed']} changed, {s['sections_unchanged']} unchanged")
    lines.append("")

    if diff["added"]:
        lines.append("ADDED SECTIONS:")
        for sec in diff["added"]:
            lines.append(f"  + [{sec['heading']}] ({sec['char_count']} chars)")
        lines.append("")

    if diff["removed"]:
        lines.append("REMOVED SECTIONS:")
        for sec in diff["removed"]:
            lines.append(f"  - [{sec['heading']}] ({sec['char_count']} chars)")
        lines.append("")

    if diff["changed"]:
        lines.append("CHANGED SECTIONS:")
        for sec in diff["changed"]:
            lines.append(f"  ~ [{sec['heading']}]")
            for add in sec["additions"][:5]:
                lines.append(f"    + {add}")
            if len(sec["additions"]) > 5:
                lines.append(f"    ... and {len(sec['additions']) - 5} more additions")
            for rem in sec["deletions"][:5]:
                lines.append(f"    - {rem}")
            if len(sec["deletions"]) > 5:
                lines.append(f"    ... and {len(sec['deletions']) - 5} more removals")
        lines.append("")

    if diff["unchanged"]:
        lines.append(f"UNCHANGED SECTIONS ({len(diff['unchanged'])}):")
        for heading in diff["unchanged"]:
            lines.append(f"  = [{heading}]")

    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Diff two versions of a source document and produce a structured summary.",
    )
    parser.add_argument("old_file", help="Path to the old version")
    parser.add_argument("new_file", help="Path to the new version")
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output as machine-readable JSON instead of human-readable summary",
    )

    args = parser.parse_args()

    for path in [args.old_file, args.new_file]:
        if not os.path.exists(path):
            print(f"Error: {path} not found")
            sys.exit(1)

    with open(args.old_file, "r", encoding="utf-8", errors="replace") as f:
        old_text = f.read()
    with open(args.new_file, "r", encoding="utf-8", errors="replace") as f:
        new_text = f.read()

    diff = compute_diff(old_text, new_text)

    if args.json_output:
        print(json.dumps(diff, indent=2))
    else:
        print(format_human_readable(diff))


if __name__ == "__main__":
    main()
