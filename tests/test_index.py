#!/usr/bin/env python3
"""Tests for index.py with mocked DB client."""

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from index import (
    DbClient,
    WikiPage,
    compute_content_hash,
    parse_frontmatter,
    extract_links,
    parse_wiki_page,
    scan_wiki_pages,
    cmd_rebuild,
    cmd_sync,
    cmd_verify,
    _dedup_results,
)
from embeddings import NullProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_vault(tmp_path: Path, pages: dict[str, str]) -> Path:
    """Create a temporary vault with wiki pages."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    for name, content in pages.items():
        (wiki_dir / name).write_text(content, encoding="utf-8")
    return tmp_path


def _mock_db() -> MagicMock:
    """Create a mock DbClient."""
    db = MagicMock(spec=DbClient)
    db.query.return_value = []
    db.execute.return_value = 0
    db.ping.return_value = True
    return db


# ---------------------------------------------------------------------------
# Content hash tests
# ---------------------------------------------------------------------------

def test_content_hash_deterministic():
    h1 = compute_content_hash("hello world")
    h2 = compute_content_hash("hello world")
    assert h1 == h2


def test_content_hash_differs():
    h1 = compute_content_hash("hello")
    h2 = compute_content_hash("world")
    assert h1 != h2


# ---------------------------------------------------------------------------
# Frontmatter parsing tests
# ---------------------------------------------------------------------------

def test_parse_frontmatter_basic():
    content = "---\ntitle: Test\ntags: [a, b]\n---\n\n# Body"
    fm, body = parse_frontmatter(content)
    assert fm["title"] == "Test"
    assert fm["tags"] == ["a", "b"]
    assert "# Body" in body


def test_parse_frontmatter_no_frontmatter():
    content = "# Just a heading\n\nSome text."
    fm, body = parse_frontmatter(content)
    assert fm == {}
    assert body == content


def test_parse_frontmatter_boolean():
    content = "---\ndraft: true\npublished: false\n---\n\nBody"
    fm, body = parse_frontmatter(content)
    assert fm["draft"] is True
    assert fm["published"] is False


# ---------------------------------------------------------------------------
# Link extraction tests
# ---------------------------------------------------------------------------

def test_extract_links():
    content = "See [[page-one]] and [[page-two|display text]]."
    links = extract_links(content)
    assert "page-one" in links
    assert "page-two" in links
    assert len(links) == 2


def test_extract_links_none():
    content = "No links here."
    links = extract_links(content)
    assert links == []


# ---------------------------------------------------------------------------
# Page parsing tests
# ---------------------------------------------------------------------------

def test_parse_wiki_page():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        wiki_dir = vault / "wiki"
        wiki_dir.mkdir()
        page_file = wiki_dir / "test-page.md"
        page_file.write_text(
            "---\ntags: [concept]\n---\n\n# Test Page\n\nContent here.\n\n"
            "See [[other-page]].\n\n---\n\n## Timeline\n\n- 2026-01-01: Created",
            encoding="utf-8",
        )
        page = parse_wiki_page(page_file, wiki_dir)

    assert page.slug == "test-page"
    assert page.title == "Test Page"
    assert "Content here." in page.compiled_truth
    assert "2026-01-01" in page.timeline
    assert "other-page" in page.links
    assert "concept" in page.tags
    assert page.content_hash  # not empty


def test_parse_wiki_page_no_frontmatter():
    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        wiki_dir = vault / "wiki"
        wiki_dir.mkdir()
        page_file = wiki_dir / "simple.md"
        page_file.write_text("# Simple\n\nJust text.", encoding="utf-8")
        page = parse_wiki_page(page_file, wiki_dir)

    assert page.slug == "simple"
    assert page.title == "Simple"
    assert page.timeline == ""


# ---------------------------------------------------------------------------
# Scan tests
# ---------------------------------------------------------------------------

def test_scan_wiki_pages():
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(
            Path(tmp),
            {
                "page-a.md": "---\ntags: [concept]\n---\n\n# Page A\n\nContent A.",
                "page-b.md": "# Page B\n\nContent B.",
            },
        )
        pages = scan_wiki_pages(vault)

    assert len(pages) == 2
    slugs = {p.slug for p in pages}
    assert "page-a" in slugs
    assert "page-b" in slugs


def test_scan_wiki_pages_no_wiki_dir():
    with tempfile.TemporaryDirectory() as tmp:
        pages = scan_wiki_pages(Path(tmp))
    assert pages == []


# ---------------------------------------------------------------------------
# Rebuild tests (mocked DB)
# ---------------------------------------------------------------------------

def test_cmd_rebuild_calls_upsert(capsys):
    db = _mock_db()
    provider = NullProvider()

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(
            Path(tmp),
            {"my-page.md": "---\ntags: [concept]\n---\n\n# My Page\n\nHello world."},
        )
        cmd_rebuild(db, vault, provider)

    # Should have called execute for upsert, chunks, links, tags
    assert db.execute.call_count > 0
    output = capsys.readouterr().out
    assert "my-page" in output
    assert "Rebuild complete" in output


def test_cmd_rebuild_empty_vault(capsys):
    db = _mock_db()
    provider = NullProvider()

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {})
        cmd_rebuild(db, vault, provider)

    output = capsys.readouterr().out
    assert "No wiki pages found" in output


# ---------------------------------------------------------------------------
# Sync tests (mocked DB)
# ---------------------------------------------------------------------------

def test_cmd_sync_skips_unchanged(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        content = "---\ntags: [concept]\n---\n\n# Stable\n\nUnchanged content."
        vault = _make_vault(Path(tmp), {"stable.md": content})
        pages = scan_wiki_pages(vault)
        page_hash = pages[0].content_hash

        db = _mock_db()
        # DB already has this page with same hash
        db.query.return_value = [{"slug": "stable", "content_hash": page_hash}]
        provider = NullProvider()

        cmd_sync(db, vault, provider)

    output = capsys.readouterr().out
    assert "skipped=1" in output


def test_cmd_sync_updates_changed(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(
            Path(tmp),
            {"changed.md": "# Changed\n\nNew content."},
        )
        db = _mock_db()
        db.query.return_value = [{"slug": "changed", "content_hash": "oldhash"}]
        provider = NullProvider()

        cmd_sync(db, vault, provider)

    output = capsys.readouterr().out
    assert "updated=1" in output
    assert "updated: changed" in output


def test_cmd_sync_removes_deleted(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {})
        db = _mock_db()
        db.query.return_value = [{"slug": "deleted-page", "content_hash": "somehash"}]
        provider = NullProvider()

        cmd_sync(db, vault, provider)

    output = capsys.readouterr().out
    assert "removed=1" in output


# ---------------------------------------------------------------------------
# Verify tests (mocked DB)
# ---------------------------------------------------------------------------

def test_cmd_verify_healthy(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        content = "---\ntags: [concept]\n---\n\n# Good\n\nHealthy."
        vault = _make_vault(Path(tmp), {"good.md": content})
        pages = scan_wiki_pages(vault)

        db = _mock_db()
        db.query.side_effect = [
            # pages table
            [{"slug": "good", "content_hash": pages[0].content_hash}],
            # content_chunks with embeddings
            [{"page_slug": "good"}],
            # links
            [],
        ]

        result = cmd_verify(db, vault)

    assert result["disk_pages"] == 1
    assert result["db_pages"] == 1
    assert result["pages_with_embeddings"] == 1
    assert result["stale_pages"] == []
    assert result["orphan_pages"] == []


def test_cmd_verify_stale_page(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {"stale.md": "# Stale\n\nContent."})

        db = _mock_db()
        db.query.side_effect = [
            [{"slug": "stale", "content_hash": "wrong_hash"}],
            [],
            [],
        ]

        result = cmd_verify(db, vault)

    assert "stale" in result["stale_pages"]


def test_cmd_verify_orphan_page(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {})

        db = _mock_db()
        db.query.side_effect = [
            [{"slug": "ghost", "content_hash": "abc"}],
            [],
            [],
        ]

        result = cmd_verify(db, vault)

    assert "ghost" in result["orphan_pages"]


def test_cmd_verify_dangling_links(capsys):
    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {"exists.md": "# Exists\n\nContent."})

        db = _mock_db()
        pages = scan_wiki_pages(vault)
        db.query.side_effect = [
            [{"slug": "exists", "content_hash": pages[0].content_hash}],
            [],
            [{"to_slug": "nonexistent-target"}],
        ]

        result = cmd_verify(db, vault)

    assert "nonexistent-target" in result["dangling_links"]


# ---------------------------------------------------------------------------
# Dedup tests
# ---------------------------------------------------------------------------

def test_dedup_empty():
    assert _dedup_results([]) == []


def test_dedup_preserves_diverse():
    rows = [
        {"page_slug": "a", "cosine_sim": 0.9},
        {"page_slug": "b", "cosine_sim": 0.5},
        {"page_slug": "c", "cosine_sim": 0.2},
    ]
    result = _dedup_results(rows, threshold=0.85)
    assert len(result) == 3


def test_dedup_collapses_similar():
    rows = [
        {"page_slug": "a", "cosine_sim": 0.95},
        {"page_slug": "b", "cosine_sim": 0.94},  # very close to a
        {"page_slug": "c", "cosine_sim": 0.5},
    ]
    result = _dedup_results(rows, threshold=0.85)
    # b should be collapsed with a (diff = 0.01 < 1-0.85 = 0.15)
    assert len(result) < 3
