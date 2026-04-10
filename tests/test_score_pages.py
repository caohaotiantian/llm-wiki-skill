#!/usr/bin/env python3
"""Tests for score_pages.py scoring logic."""

import sys
import os

# Add scripts dir to path so we can import score_pages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from score_pages import normalize_values, compute_score, parse_weight_and_tags, write_computed_score


def test_normalize_values_basic():
    """Normalize maps max to 10, zero stays zero."""
    raw = {"a": 10, "b": 5, "c": 0}
    result = normalize_values(raw)
    assert result == {"a": 10.0, "b": 5.0, "c": 0.0}


def test_normalize_values_all_zero():
    """When all values are zero, all normalized values are zero."""
    raw = {"a": 0, "b": 0}
    result = normalize_values(raw)
    assert result == {"a": 0.0, "b": 0.0}


def test_normalize_values_single_page():
    """Single page with nonzero value normalizes to 10."""
    raw = {"a": 7}
    result = normalize_values(raw)
    assert result == {"a": 10.0}


def test_normalize_values_empty():
    """Empty input returns empty output."""
    assert normalize_values({}) == {}


def test_compute_score_basic():
    """Compute score with all indicators."""
    score = compute_score(
        norm_query_freq=10.0,
        norm_access_count=10.0,
        norm_cross_ref=10.0,
        manual_weight=0,
        tag_bonus=0,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    assert score == 10.0


def test_compute_score_with_manual_weight():
    """Manual weight is additive."""
    score = compute_score(
        norm_query_freq=5.0,
        norm_access_count=5.0,
        norm_cross_ref=5.0,
        manual_weight=3,
        tag_bonus=0,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    assert score == 8.0


def test_compute_score_with_tag_bonus():
    """Tag bonus is additive."""
    score = compute_score(
        norm_query_freq=0.0,
        norm_access_count=0.0,
        norm_cross_ref=0.0,
        manual_weight=0,
        tag_bonus=10,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    assert score == 10.0


def test_compute_score_rounds_to_one_decimal():
    """Score is rounded to 1 decimal place."""
    score = compute_score(
        norm_query_freq=3.33,
        norm_access_count=3.33,
        norm_cross_ref=3.33,
        manual_weight=0,
        tag_bonus=0,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    # 0.4*3.33 + 0.3*3.33 + 0.3*3.33 = 1.332 + 0.999 + 0.999 = 3.33
    assert score == 3.3


def test_parse_weight_and_tags_defaults():
    """No weight or priority tags returns defaults."""
    content = "---\naliases: []\ntags: [concept]\nstatus: active\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 0
    assert tags == []


def test_parse_weight_and_tags_with_weight():
    """Reads numeric weight from frontmatter."""
    content = "---\nweight: 5\ntags: [concept]\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 5
    assert tags == []


def test_parse_weight_and_tags_with_priority_tags():
    """Extracts priority tags from tag list."""
    content = "---\ntags: [concept, pinned, priority/high]\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 0
    assert set(tags) == {"pinned", "priority/high"}


def test_parse_weight_and_tags_list_format():
    """Handles YAML list format for tags."""
    content = "---\ntags:\n  - entity\n  - priority/medium\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert tags == ["priority/medium"]


def test_parse_weight_and_tags_float_weight():
    """Handles float weight values."""
    content = "---\nweight: 2.5\ntags: [concept]\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 2.5


def test_write_computed_score_new_field():
    """Adds computed_score to frontmatter that doesn't have it."""
    content = "---\naliases: []\ntags: [concept]\nstatus: active\n---\n# Page\n\nBody text.\n"
    result = write_computed_score(content, 7.3)
    assert "computed_score: 7.3" in result
    assert "# Page" in result
    assert "Body text." in result


def test_write_computed_score_update_existing():
    """Updates existing computed_score value."""
    content = "---\naliases: []\ncomputed_score: 3.1\ntags: [concept]\n---\n# Page\n"
    result = write_computed_score(content, 8.5)
    assert "computed_score: 8.5" in result
    assert "computed_score: 3.1" not in result


def test_write_computed_score_no_frontmatter():
    """Returns content unchanged if no frontmatter."""
    content = "# Page\n\nNo frontmatter here.\n"
    result = write_computed_score(content, 5.0)
    assert result == content
