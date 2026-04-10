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
