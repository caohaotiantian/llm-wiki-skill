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


def test_database_backend_not_implemented():
    b = DatabaseBackend()
    b.init(Path("/tmp"))
    try:
        b.get_page("test")
        assert False
    except NotImplementedError:
        pass


def test_file_vault_implements_protocol():
    b = FileVaultBackend()
    assert isinstance(b, StorageBackend)
