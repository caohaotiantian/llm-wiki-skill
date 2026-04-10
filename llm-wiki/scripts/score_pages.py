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

import re


PRIORITY_TAGS = {"pinned", "priority/high", "priority/medium", "priority/low"}


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
