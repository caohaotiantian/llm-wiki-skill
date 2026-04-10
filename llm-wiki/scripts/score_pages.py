#!/usr/bin/env python3
"""
Compute composite page scores for wiki pages.

Reads counters from .stats.json, scans wikilinks for cross-reference density,
reads frontmatter for manual weight and priority tags, then writes computed_score
to each page's YAML frontmatter.

Usage:
    python score_pages.py <vault-path>                              # full recalc
    python score_pages.py <vault-path> --pages wiki/a.md wiki/b.md  # incremental
    python score_pages.py <vault-path> --json                       # JSON output
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path


PRIORITY_TAGS = {"pinned", "priority/high", "priority/medium", "priority/low"}


DEFAULT_STATS = {
    "version": 1,
    "weights": {
        "query_frequency": 0.4,
        "access_count": 0.3,
        "cross_ref_density": 0.3,
    },
    "tag_bonuses": {
        "pinned": 10,
        "priority/high": 6,
        "priority/medium": 3,
        "priority/low": 1,
    },
    "pages": {},
}


def load_stats(vault_path: Path) -> dict:
    """Load .stats.json from vault root.

    If the file doesn't exist, creates it with defaults and returns defaults.
    """
    stats_path = Path(vault_path) / ".stats.json"
    if not stats_path.exists():
        stats = copy.deepcopy(DEFAULT_STATS)
        save_stats(vault_path, stats)
        return stats

    with open(stats_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_stats(vault_path: Path, stats: dict) -> None:
    """Write .stats.json to vault root."""
    stats_path = Path(vault_path) / ".stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
        f.write("\n")


def calculate_tag_bonus(priority_tags: list[str], tag_bonuses: dict[str, int | float]) -> float:
    """Sum tag bonuses for the given priority tags."""
    return sum(tag_bonuses.get(tag, 0) for tag in priority_tags)


def parse_weight_and_tags(content: str) -> tuple[int | float, list[str]]:
    """Extract manual weight and priority tags from page frontmatter.

    Returns (weight, priority_tags) where priority_tags is a list of
    matching tag strings from PRIORITY_TAGS.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content, re.DOTALL)
    if not match:
        return 0, []

    fm = match.group(1)

    # Parse weight
    weight: int | float = 0
    weight_match = re.search(r"^weight:\s*(.+)$", fm, re.MULTILINE)
    if weight_match:
        try:
            val = weight_match.group(1).strip()
            weight = float(val) if "." in val else int(val)
        except ValueError:
            pass

    # Parse tags — inline format: tags: [a, b, c]
    priority_tags: list[str] = []
    inline = re.search(r"^tags:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline:
        raw_tags = [t.strip().strip("\"'") for t in inline.group(1).split(",")]
        priority_tags = [t for t in raw_tags if t in PRIORITY_TAGS]
    else:
        # List format: tags:\n  - a\n  - b
        list_match = re.search(r"^tags:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.MULTILINE)
        if list_match:
            items = re.findall(r"^\s+-\s+(.+)", list_match.group(1), re.MULTILINE)
            priority_tags = [
                t.strip().strip("\"'") for t in items if t.strip().strip("\"'") in PRIORITY_TAGS
            ]

    return weight, priority_tags


def write_computed_score(content: str, score: float) -> str:
    """Write or update computed_score in page frontmatter.

    If frontmatter exists and has computed_score, update it.
    If frontmatter exists without computed_score, insert before closing ---.
    If no frontmatter, return content unchanged.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^(---\s*\n)(.*?)(\n---)", content, re.DOTALL)
    if not match:
        return content

    prefix = match.group(1)
    fm = match.group(2)
    suffix = match.group(3)
    rest = content[match.end():]

    # Update existing or insert new
    if re.search(r"^computed_score:\s*", fm, re.MULTILINE):
        fm = re.sub(r"^computed_score:\s*.*$", f"computed_score: {score}", fm, flags=re.MULTILINE)
    else:
        fm = fm + f"\ncomputed_score: {score}"

    return prefix + fm + suffix + rest


def normalize_values(raw: dict[str, int | float]) -> dict[str, float]:
    """Normalize values to 0-10 scale relative to max.

    The page with the highest value gets 10. Zero stays zero.
    If all values are zero, all normalized values are zero.
    """
    if not raw:
        return {}
    max_val = max(raw.values())
    if max_val == 0:
        return {k: 0.0 for k in raw}
    return {k: round(v / max_val * 10, 2) for k, v in raw.items()}


def compute_score(
    norm_query_freq: float,
    norm_access_count: float,
    norm_cross_ref: float,
    manual_weight: int | float,
    tag_bonus: int | float,
    weights: dict[str, float],
) -> float:
    """Compute composite score from normalized indicators + manual adjustments.

    Formula:
        score = (w1 * norm_query_freq)
              + (w2 * norm_access_count)
              + (w3 * norm_cross_ref)
              + manual_weight
              + tag_bonus

    Returns score rounded to 1 decimal place.
    """
    score = (
        weights["query_frequency"] * norm_query_freq
        + weights["access_count"] * norm_access_count
        + weights["cross_ref_density"] * norm_cross_ref
        + manual_weight
        + tag_bonus
    )
    return round(score, 1)


# Matches [[target]], [[target|display]], [[target#heading]]
# Does NOT match embeds (![[...]])
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]]+?)\]\]")


def _extract_target(wikilink_content: str) -> str:
    """Extract resolution target: [[target|display]] -> target, [[target#h]] -> target."""
    target = wikilink_content.split("|")[0].split("#")[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def _collect_wiki_files(vault_path: Path) -> dict[str, str]:
    """Collect all .md files under wiki/.

    Returns {normalized_stem: relative_path} for resolving link targets.
    """
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return {}

    files: dict[str, str] = {}
    for root, dirs, filenames in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in filenames:
            if fname.endswith(".md") and not fname.endswith(".snapshot.md"):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, vault_path)
                stem = os.path.splitext(fname)[0].lower()
                files[stem] = rel
    return files


def _scan_links_in_file(file_path: str) -> list[str]:
    """Extract all wikilink targets from a file, skipping frontmatter and code blocks."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    targets = []
    in_frontmatter = False
    code_fence_marker = ""

    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() in ("---", "..."):
                in_frontmatter = False
            continue

        stripped = line.strip()
        if not code_fence_marker:
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence_match:
                code_fence_marker = fence_match.group(1)
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
            continue

        # Strip inline code spans
        scannable = re.sub(r"`[^`]+`", "", line)
        for match in WIKILINK_RE.finditer(scannable):
            target = _extract_target(match.group(1))
            if target:
                targets.append(target)

    return targets


def count_incoming_links(vault_path: Path) -> dict[str, int]:
    """Count incoming wikilinks for each wiki page.

    Returns {relative_path: count} for all pages that have at least one incoming link.
    """
    vault_path = Path(vault_path)
    file_index = _collect_wiki_files(vault_path)
    if not file_index:
        return {}

    counts: dict[str, int] = {}

    for stem, rel_path in file_index.items():
        abs_path = os.path.join(str(vault_path), rel_path)
        targets = _scan_links_in_file(abs_path)
        for target in targets:
            norm = target.lower()
            if norm in file_index:
                target_path = file_index[norm]
                counts[target_path] = counts.get(target_path, 0) + 1

    return counts
