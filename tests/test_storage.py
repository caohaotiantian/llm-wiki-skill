#!/usr/bin/env python3
"""Tests for storage.py."""

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from storage import (
    Page, Link, SearchHit, SyncReport,
    FileVaultBackend, DatabaseBackend, get_backend,
    StorageBackend, _parse_frontmatter, _parse_page_from_markdown,
    _parse_typed_links,
)


def _make_wiki_page(wiki_dir, slug, content):
    """Helper to create a wiki page file."""
    path = wiki_dir / f"{slug}.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_page_to_markdown():
    page = Page(slug="test", type="concept", title="Test Page",
                compiled_truth="Content here.", timeline="- 2026-01-01: Created")
    md = page.to_markdown()
    assert "title: Test Page" in md
    assert "Content here." in md
    assert "---" in md  # separator
    assert "2026-01-01" in md


def test_parse_frontmatter():
    content = '---\ntitle: Hello\ntags: [concept, test]\nstatus: active\n---\n# Hello\n'
    fm = _parse_frontmatter(content)
    assert fm["title"] == "Hello"
    assert "concept" in fm["tags"]
    assert fm["status"] == "active"


def test_parse_page_from_markdown():
    content = """---
tags: [concept]
title: My Page
updated: 2026-01-01
---

# My Page

This is compiled truth.

---

## Timeline

- 2026-01-01: Created
"""
    page = _parse_page_from_markdown("my-page", content)
    assert page.slug == "my-page"
    assert page.title == "My Page"
    assert "compiled truth" in page.compiled_truth.lower()
    assert "2026-01-01" in page.timeline


def test_file_vault_backend_init(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "page-a", "---\ntags: [concept]\n---\n# Page A\nContent A\n")
    _make_wiki_page(wiki_dir, "page-b", "---\ntags: [entity]\n---\n# Page B\nContent B\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)
    pages = backend.list_pages()
    assert len(pages) == 2


def test_file_vault_backend_get_page(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "test", "---\ntags: [concept]\ntitle: Test\n---\n# Test\nBody\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)
    page = backend.get_page("test")
    assert page is not None
    assert page.title == "Test"


def test_file_vault_backend_put_page(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()

    backend = FileVaultBackend()
    backend.init(tmp_path)
    page = Page(slug="new-page", type="concept", title="New", compiled_truth="Content")
    backend.put_page(page)

    assert (wiki_dir / "new-page.md").exists()
    retrieved = backend.get_page("new-page")
    assert retrieved is not None
    assert retrieved.title == "New"


def test_file_vault_backend_delete_page(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "doomed", "---\ntags: [concept]\n---\n# Doomed\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)
    backend.delete_page("doomed")
    assert backend.get_page("doomed") is None
    assert not (wiki_dir / "doomed.md").exists()


def test_file_vault_backend_list_pages_with_filter(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "c1", "---\ntags: [concept]\n---\n# C1\n")
    _make_wiki_page(wiki_dir, "e1", "---\ntags: [entity]\n---\n# E1\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)
    concepts = backend.list_pages(where={"type": "concept"})
    assert len(concepts) == 1
    assert concepts[0].slug == "c1"


def test_file_vault_backend_search(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "alpha", "---\ntags: [concept]\n---\n# Alpha\nThe alpha concept is important.\n")
    _make_wiki_page(wiki_dir, "beta", "---\ntags: [concept]\n---\n# Beta\nBeta is different.\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)
    hits = backend.search_keyword("alpha")
    assert len(hits) >= 1
    assert hits[0].page_slug == "alpha"


def test_file_vault_backend_backlinks(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "a", '---\ntags: [concept]\nlinks:\n  - {target: "b", type: "references"}\n---\n# A\n')
    _make_wiki_page(wiki_dir, "b", "---\ntags: [concept]\n---\n# B\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)
    backlinks = backend.get_backlinks("b")
    assert len(backlinks) == 1
    assert backlinks[0].from_slug == "a"
    assert backlinks[0].link_type == "references"


def test_file_vault_backend_sync(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "page", "---\ntags: [concept]\n---\n# Page\nV1\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)

    # Modify page
    _make_wiki_page(wiki_dir, "page", "---\ntags: [concept]\n---\n# Page\nV2 updated\n")
    # Add new page
    _make_wiki_page(wiki_dir, "new", "---\ntags: [concept]\n---\n# New\n")

    report = backend.sync()
    assert report.added == 1
    assert report.updated == 1


def test_file_vault_backend_export(tmp_path):
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    _make_wiki_page(wiki_dir, "export-test", "---\ntags: [concept]\n---\n# Export\nContent\n")

    backend = FileVaultBackend()
    backend.init(tmp_path)

    dest = tmp_path / "export"
    count = backend.export_markdown(dest)
    assert count == 1
    assert (dest / "export-test.md").exists()


def test_get_backend_file():
    b = get_backend("file")
    assert isinstance(b, FileVaultBackend)


def test_get_backend_database():
    b = get_backend("database")
    assert isinstance(b, DatabaseBackend)


def test_get_backend_unknown():
    try:
        get_backend("unknown")
        assert False
    except ValueError:
        pass


def test_database_backend_no_db_raises():
    """DatabaseBackend without a db object raises RuntimeError, not NotImplementedError."""
    b = DatabaseBackend()
    # Don't call init — no db available
    try:
        b.get_page("test")
        assert False, "Expected RuntimeError"
    except RuntimeError:
        pass


def test_file_vault_implements_protocol():
    b = FileVaultBackend()
    assert isinstance(b, StorageBackend)


def test_database_backend_implements_protocol():
    b = DatabaseBackend(db=_MockDb())
    assert isinstance(b, StorageBackend)


# ---------------------------------------------------------------------------
# Mock DB for DatabaseBackend tests
# ---------------------------------------------------------------------------

class _MockDb:
    """Minimal mock matching the db duck-type contract."""

    def __init__(self):
        self._pages: dict[str, dict] = {}
        self._links: list[dict] = []
        self._tags: list[dict] = []

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        params = params or []
        if "FROM pages WHERE slug = $1" in sql:
            slug = params[0]
            if slug in self._pages:
                return [self._pages[slug]]
            return []
        if "FROM pages" in sql and "WHERE" not in sql:
            return list(self._pages.values())
        if "FROM pages" in sql and "type = $1" in sql:
            t = params[0]
            return [p for p in self._pages.values() if p["type"] == t]
        if "FROM links WHERE to_slug" in sql:
            target = params[0]
            return [l for l in self._links if l["to_slug"] == target]
        if "SELECT slug, content_hash FROM pages" in sql:
            return [{"slug": p["slug"], "content_hash": p["content_hash"]}
                    for p in self._pages.values()]
        if "search_vector" in sql or "content_chunks" in sql:
            return []
        return []

    def execute(self, sql: str, params: list | None = None) -> int:
        params = params or []
        if sql.strip().startswith("INSERT INTO pages") or "ON CONFLICT (slug)" in sql:
            row = {
                "slug": params[0], "type": params[1], "title": params[2],
                "compiled_truth": params[3], "timeline": params[4],
                "frontmatter": params[5], "content_hash": params[6],
            }
            self._pages[params[0]] = row
            return 1
        if sql.strip().startswith("DELETE FROM pages"):
            slug = params[0]
            if slug in self._pages:
                del self._pages[slug]
                self._links = [l for l in self._links
                               if l["from_slug"] != slug and l["to_slug"] != slug]
                self._tags = [t for t in self._tags if t["page_slug"] != slug]
                return 1
            return 0
        if sql.strip().startswith("INSERT INTO links"):
            self._links.append({
                "from_slug": params[0], "to_slug": params[1],
                "link_type": params[2],
            })
            return 1
        if sql.strip().startswith("DELETE FROM links WHERE from_slug"):
            before = len(self._links)
            self._links = [l for l in self._links if l["from_slug"] != params[0]]
            return before - len(self._links)
        if sql.strip().startswith("DELETE FROM tags"):
            before = len(self._tags)
            self._tags = [t for t in self._tags if t["page_slug"] != params[0]]
            return before - len(self._tags)
        if sql.strip().startswith("INSERT INTO tags"):
            self._tags.append({"page_slug": params[0], "tag": params[1]})
            return 1
        return 0


# ---------------------------------------------------------------------------
# DatabaseBackend tests
# ---------------------------------------------------------------------------

def test_db_backend_get_page():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    page = Page(slug="test", type="concept", title="Test", compiled_truth="Body")
    b.put_page(page)

    got = b.get_page("test")
    assert got is not None
    assert got.slug == "test"
    assert got.title == "Test"
    assert got.compiled_truth == "Body"


def test_db_backend_get_page_not_found():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))
    assert b.get_page("nope") is None


def test_db_backend_put_page():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    page = Page(slug="s", type="entity", title="S", compiled_truth="c",
                frontmatter={"tags": ["alpha"], "links": [{"target": "other", "type": "references"}]})
    b.put_page(page)

    assert "s" in db._pages
    assert len(db._links) == 1
    assert db._links[0]["to_slug"] == "other"
    assert len(db._tags) == 1
    assert db._tags[0]["tag"] == "alpha"


def test_db_backend_delete_page():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    b.put_page(Page(slug="bye", type="concept", title="Bye"))
    b.delete_page("bye")
    assert b.get_page("bye") is None


def test_db_backend_list_pages():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    b.put_page(Page(slug="a", type="concept", title="A"))
    b.put_page(Page(slug="b", type="entity", title="B"))

    all_pages = b.list_pages()
    assert len(all_pages) == 2

    concepts = b.list_pages(where={"type": "concept"})
    assert len(concepts) == 1
    assert concepts[0].slug == "a"


def test_db_backend_add_link_and_backlinks():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    b.put_page(Page(slug="a", type="concept", title="A"))
    b.put_page(Page(slug="b", type="concept", title="B"))
    b.add_link("a", "b", "references")

    backlinks = b.get_backlinks("b")
    assert len(backlinks) >= 1
    assert any(bl.from_slug == "a" for bl in backlinks)


def test_db_backend_search_keyword_empty():
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    hits = b.search_keyword("anything")
    assert hits == []


def test_db_backend_search_hybrid_no_embedding():
    """Without embedding, hybrid falls back to keyword search."""
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(Path("/tmp"))

    hits = b.search_hybrid("query", embedding=None)
    assert hits == []


def test_db_backend_export_markdown(tmp_path):
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(tmp_path)

    b.put_page(Page(slug="exported", type="concept", title="Exported", compiled_truth="Body"))
    dest = tmp_path / "export"
    count = b.export_markdown(dest)
    assert count == 1
    assert (dest / "exported.md").exists()
    content = (dest / "exported.md").read_text()
    assert "Exported" in content


def test_db_backend_sync(tmp_path):
    db = _MockDb()
    b = DatabaseBackend(db=db)
    b.init(tmp_path)

    # Create wiki dir with a page
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "synced.md").write_text(
        "---\ntags: [concept]\ntitle: Synced\n---\n# Synced\nContent\n"
    )

    report = b.sync()
    assert report.added == 1
    assert report.updated == 0
    assert report.deleted == 0

    # Syncing again without changes
    report2 = b.sync()
    assert report2.unchanged == 1
    assert report2.added == 0

    # Modify the page
    (wiki_dir / "synced.md").write_text(
        "---\ntags: [concept]\ntitle: Synced\n---\n# Synced\nUpdated content\n"
    )
    report3 = b.sync()
    assert report3.updated == 1

    # Delete the file, add a new one
    (wiki_dir / "synced.md").unlink()
    (wiki_dir / "new-page.md").write_text(
        "---\ntags: [entity]\ntitle: New\n---\n# New\nBody\n"
    )
    report4 = b.sync()
    assert report4.added == 1
    assert report4.deleted == 1
