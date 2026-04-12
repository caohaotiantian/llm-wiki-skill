#!/usr/bin/env python3
"""Tests for query_filter.py."""

import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from query_filter import (
    Condition,
    _parse_frontmatter,
    conditions_to_sql,
    filter_pages,
    matches_conditions,
    parse_filter_string,
)


# ---------------------------------------------------------------------------
# Filter parsing
# ---------------------------------------------------------------------------

class TestParseFilterString:
    def test_simple_equal(self):
        conds = parse_filter_string("type=concept")
        assert len(conds) == 1
        assert conds[0].field == "type"
        assert conds[0].op == "="
        assert conds[0].value == "concept"

    def test_multiple_conditions(self):
        conds = parse_filter_string("type=concept tag=strategy")
        assert len(conds) == 2

    def test_numeric_operators(self):
        for op in [">=", "<=", ">", "<"]:
            conds = parse_filter_string(f"confidence{op}0.7")
            assert len(conds) == 1
            assert conds[0].op == op
            assert conds[0].value == "0.7"

    def test_not_equal(self):
        conds = parse_filter_string("status!=draft")
        assert conds[0].op == "!="
        assert conds[0].value == "draft"

    def test_has_field(self):
        conds = parse_filter_string("has=confidence")
        assert conds[0].field == "has"
        assert conds[0].value == "confidence"

    def test_updated_since(self):
        conds = parse_filter_string("updated_since=30d")
        assert conds[0].field == "updated_since"
        assert conds[0].value == "30d"

    def test_empty_string(self):
        assert parse_filter_string("") == []
        assert parse_filter_string("   ") == []


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

class TestMatchesConditions:
    def test_exact_match(self):
        fm = {"status": "active", "tags": ["concept"]}
        assert matches_conditions(fm, [Condition("status", "=", "active")])
        assert not matches_conditions(fm, [Condition("status", "=", "draft")])

    def test_not_equal(self):
        fm = {"status": "active"}
        assert matches_conditions(fm, [Condition("status", "!=", "draft")])
        assert not matches_conditions(fm, [Condition("status", "!=", "active")])

    def test_numeric_gte(self):
        fm = {"confidence": "0.8"}
        assert matches_conditions(fm, [Condition("confidence", ">=", "0.7")])
        assert not matches_conditions(fm, [Condition("confidence", ">=", "0.9")])

    def test_numeric_lt(self):
        fm = {"confidence": "0.5"}
        assert matches_conditions(fm, [Condition("confidence", "<", "0.7")])

    def test_tag_membership(self):
        fm = {"tags": ["concept", "strategy"]}
        assert matches_conditions(fm, [Condition("tag", "=", "strategy")])
        assert not matches_conditions(fm, [Condition("tag", "=", "entity")])

    def test_tag_not_equal(self):
        fm = {"tags": ["concept"]}
        assert matches_conditions(fm, [Condition("tag", "!=", "entity")])
        assert not matches_conditions(fm, [Condition("tag", "!=", "concept")])

    def test_type_from_tags(self):
        fm = {"tags": ["concept", "strategy"]}
        assert matches_conditions(fm, [Condition("type", "=", "concept")])
        assert not matches_conditions(fm, [Condition("type", "=", "entity")])

    def test_has_field(self):
        fm = {"confidence": "0.8"}
        assert matches_conditions(fm, [Condition("has", "=", "confidence")])
        assert not matches_conditions(fm, [Condition("has", "=", "missing")])

    def test_missing_field_not_equal(self):
        fm = {}
        assert matches_conditions(fm, [Condition("status", "!=", "anything")])

    def test_empty_conditions_match_all(self):
        assert matches_conditions({"any": "val"}, [])
        assert matches_conditions({}, [])


# ---------------------------------------------------------------------------
# updated_since
# ---------------------------------------------------------------------------

def test_updated_since(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    f = wiki / "recent.md"
    f.write_text("---\ntags: [concept]\n---\n# Recent\n")
    # File was just created, so it should match updated_since=1d
    results = filter_pages(tmp_path, "updated_since=1d")
    assert len(results) == 1
    assert results[0]["slug"] == "recent"


def test_updated_since_old(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    f = wiki / "old.md"
    f.write_text("---\ntags: [concept]\n---\n# Old\n")
    # Set mtime to 60 days ago
    old_time = time.time() - 60 * 86400
    os.utime(str(f), (old_time, old_time))
    results = filter_pages(tmp_path, "updated_since=30d")
    assert len(results) == 0


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

class TestParseFrontmatter:
    def test_basic(self):
        fm = _parse_frontmatter("---\ntitle: Hello\nstatus: active\n---\n")
        assert fm["title"] == "Hello"
        assert fm["status"] == "active"

    def test_inline_list(self):
        fm = _parse_frontmatter("---\ntags: [a, b, c]\n---\n")
        assert fm["tags"] == ["a", "b", "c"]

    def test_block_list(self):
        fm = _parse_frontmatter("---\ntags:\n  - x\n  - y\n---\n")
        assert fm["tags"] == ["x", "y"]

    def test_no_frontmatter(self):
        assert _parse_frontmatter("# Just a heading\n") == {}


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

class TestSqlGeneration:
    def test_basic(self):
        conds = parse_filter_string("status=active confidence>=0.7")
        sql, params = conditions_to_sql(conds)
        assert "status = ?" in sql
        assert "confidence >= ?" in sql
        assert "active" in params

    def test_tag_like(self):
        conds = parse_filter_string("tag=strategy")
        sql, params = conditions_to_sql(conds)
        assert "LIKE" in sql
        assert "%strategy%" in params

    def test_skip_special(self):
        conds = parse_filter_string("has=field updated_since=7d")
        sql, _params = conditions_to_sql(conds)
        assert sql == "1=1"


# ---------------------------------------------------------------------------
# Integration: filter_pages
# ---------------------------------------------------------------------------

def _make_wiki(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "concept-a.md").write_text(
        '---\ntags: [concept, strategy]\ntitle: Concept A\nconfidence: 0.9\nstatus: active\n---\n# A\n'
    )
    (wiki / "entity-b.md").write_text(
        '---\ntags: [entity]\ntitle: Entity B\nstatus: draft\n---\n# B\n'
    )
    (wiki / "concept-c.md").write_text(
        '---\ntags: [concept]\ntitle: Concept C\nstatus: active\n---\n# C\n'
    )
    return tmp_path


def test_filter_by_type(tmp_path):
    vault = _make_wiki(tmp_path)
    results = filter_pages(vault, "type=concept")
    slugs = [r["slug"] for r in results]
    assert "concept-a" in slugs
    assert "concept-c" in slugs
    assert "entity-b" not in slugs


def test_filter_by_tag(tmp_path):
    vault = _make_wiki(tmp_path)
    results = filter_pages(vault, "tag=strategy")
    assert len(results) == 1
    assert results[0]["slug"] == "concept-a"


def test_filter_numeric(tmp_path):
    vault = _make_wiki(tmp_path)
    results = filter_pages(vault, "confidence>=0.7")
    assert len(results) == 1
    assert results[0]["slug"] == "concept-a"


def test_filter_combined(tmp_path):
    vault = _make_wiki(tmp_path)
    results = filter_pages(vault, "type=concept status=active")
    slugs = [r["slug"] for r in results]
    assert "concept-a" in slugs
    assert "concept-c" in slugs
    assert len(slugs) == 2


def test_filter_empty_matches_all(tmp_path):
    vault = _make_wiki(tmp_path)
    results = filter_pages(vault, "")
    assert len(results) == 3


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

def test_cli_json(tmp_path):
    vault = _make_wiki(tmp_path)
    script = os.path.join(
        os.path.dirname(__file__), "..", "llm-wiki", "scripts", "query_filter.py"
    )
    result = subprocess.run(
        [sys.executable, script, str(vault), "--where", "type=concept", "--json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert len(data) == 2


def test_cli_text(tmp_path):
    vault = _make_wiki(tmp_path)
    script = os.path.join(
        os.path.dirname(__file__), "..", "llm-wiki", "scripts", "query_filter.py"
    )
    result = subprocess.run(
        [sys.executable, script, str(vault), "--where", "status!=draft"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "concept-a" in result.stdout
