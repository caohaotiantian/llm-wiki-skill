#!/usr/bin/env python3
"""Tests for db_ops.py using a mock database client."""

import sys
import os
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from db_ops import (
    get_page_row,
    upsert_page_row,
    delete_page_row,
    list_page_rows,
    add_link_row,
    delete_links_from,
    get_backlink_rows,
    replace_tags,
    search_keyword_rows,
    search_hybrid_rows,
)


# ---------------------------------------------------------------------------
# Mock database
# ---------------------------------------------------------------------------

class MockDb:
    """In-memory mock that records SQL calls and returns canned rows.

    Good enough to test that db_ops functions pass the right SQL/params
    and transform results correctly.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, list]] = []  # (method, sql, params)
        self._query_results: list[list[dict]] = []  # FIFO of results for .query()
        self._execute_results: list[int] = []  # FIFO of results for .execute()

    def push_query_result(self, rows: list[dict]):
        self._query_results.append(rows)

    def push_execute_result(self, affected: int):
        self._execute_results.append(affected)

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        self.calls.append(("query", sql, params or []))
        if self._query_results:
            return self._query_results.pop(0)
        return []

    def execute(self, sql: str, params: list | None = None) -> int:
        self.calls.append(("execute", sql, params or []))
        if self._execute_results:
            return self._execute_results.pop(0)
        return 0


# ---------------------------------------------------------------------------
# Tests — Page CRUD
# ---------------------------------------------------------------------------

def test_get_page_row_found():
    db = MockDb()
    row = {"slug": "foo", "type": "concept", "title": "Foo",
           "compiled_truth": "body", "timeline": "", "frontmatter": "{}",
           "content_hash": "abc123"}
    db.push_query_result([row])

    result = get_page_row(db, "foo")
    assert result == row
    assert len(db.calls) == 1
    assert db.calls[0][2] == ["foo"]


def test_get_page_row_not_found():
    db = MockDb()
    db.push_query_result([])
    assert get_page_row(db, "missing") is None


def test_upsert_page_row():
    db = MockDb()
    upsert_page_row(db, "s", "concept", "Title", "body", "tl", {"a": 1}, "hash")
    assert len(db.calls) == 1
    method, sql, params = db.calls[0]
    assert method == "execute"
    assert "INSERT INTO pages" in sql
    assert params[0] == "s"
    assert params[1] == "concept"
    # frontmatter should be serialized JSON
    assert '"a": 1' in params[5] or '"a":1' in params[5]


def test_upsert_page_row_string_frontmatter():
    """If frontmatter is already a JSON string, pass it through."""
    db = MockDb()
    upsert_page_row(db, "s", "concept", "T", "", "", '{"x":1}', "h")
    params = db.calls[0][2]
    assert params[5] == '{"x":1}'


def test_delete_page_row_found():
    db = MockDb()
    db.push_execute_result(1)
    assert delete_page_row(db, "foo") is True


def test_delete_page_row_not_found():
    db = MockDb()
    db.push_execute_result(0)
    assert delete_page_row(db, "nope") is False


def test_list_page_rows_no_filter():
    db = MockDb()
    rows = [{"slug": "a"}, {"slug": "b"}]
    db.push_query_result(rows)
    result = list_page_rows(db)
    assert result == rows
    assert "ORDER BY slug" in db.calls[0][1]


def test_list_page_rows_type_filter():
    db = MockDb()
    db.push_query_result([{"slug": "a"}])
    result = list_page_rows(db, where={"type": "entity"})
    assert len(result) == 1
    sql = db.calls[0][1]
    assert "type = $1" in sql
    assert db.calls[0][2] == ["entity"]


def test_list_page_rows_tag_filter():
    db = MockDb()
    db.push_query_result([])
    list_page_rows(db, where={"tag": "strategy"})
    sql = db.calls[0][1]
    assert "tags.tag = $1" in sql
    assert db.calls[0][2] == ["strategy"]


def test_list_page_rows_frontmatter_filter():
    db = MockDb()
    db.push_query_result([])
    list_page_rows(db, where={"status": "active"})
    sql = db.calls[0][1]
    assert "frontmatter->>'status'" in sql
    assert db.calls[0][2] == ["active"]


# ---------------------------------------------------------------------------
# Tests — Links
# ---------------------------------------------------------------------------

def test_add_link_row():
    db = MockDb()
    add_link_row(db, "a", "b", "references")
    assert len(db.calls) == 1
    assert "INSERT INTO links" in db.calls[0][1]
    assert db.calls[0][2] == ["a", "b", "references"]


def test_delete_links_from():
    db = MockDb()
    db.push_execute_result(3)
    result = delete_links_from(db, "a")
    assert result == 3
    assert "DELETE FROM links" in db.calls[0][1]


def test_get_backlink_rows():
    db = MockDb()
    db.push_query_result([
        {"from_slug": "x", "to_slug": "target", "link_type": "references"},
    ])
    rows = get_backlink_rows(db, "target")
    assert len(rows) == 1
    assert rows[0]["from_slug"] == "x"


# ---------------------------------------------------------------------------
# Tests — Tags
# ---------------------------------------------------------------------------

def test_replace_tags():
    db = MockDb()
    replace_tags(db, "page", ["alpha", "beta", "alpha"])  # duplicate
    # First call: DELETE, then two INSERTs (alpha deduplicated)
    assert db.calls[0][1].startswith("DELETE FROM tags")
    insert_calls = [c for c in db.calls if "INSERT INTO tags" in c[1]]
    assert len(insert_calls) == 2  # alpha, beta (set dedup)


# ---------------------------------------------------------------------------
# Tests — Search
# ---------------------------------------------------------------------------

def test_search_keyword_rows():
    db = MockDb()
    db.push_query_result([
        {"page_slug": "p1", "chunk_source": "compiled_truth",
         "chunk_text": "some text", "score": 0.5},
    ])
    rows = search_keyword_rows(db, "test query", limit=5)
    assert len(rows) == 1
    assert rows[0]["page_slug"] == "p1"
    assert db.calls[0][2] == ["test query", 5]


def test_search_hybrid_rows():
    db = MockDb()
    db.push_query_result([
        {"page_slug": "p1", "chunk_text": "txt", "chunk_source": "compiled_truth", "score": 0.8},
        {"page_slug": "p2", "chunk_text": "txt2", "chunk_source": "timeline", "score": 0.3},
    ])
    embedding = [0.1, 0.2, 0.3]
    rows = search_hybrid_rows(db, "q", embedding, limit=5)
    # Should be sorted descending by score
    assert rows[0]["page_slug"] == "p1"
    assert len(rows) == 2
    # Check embedding literal was built
    assert "[0.1,0.2,0.3]" in db.calls[0][2][0]


def test_search_hybrid_rows_limit():
    db = MockDb()
    many = [{"page_slug": f"p{i}", "chunk_text": "", "chunk_source": "compiled_truth", "score": i}
            for i in range(20)]
    db.push_query_result(many)
    rows = search_hybrid_rows(db, "q", [0.0], limit=3)
    assert len(rows) == 3
