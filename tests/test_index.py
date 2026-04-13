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
    LinkRef,
    WikiPage,
    compute_content_hash,
    parse_frontmatter,
    extract_links,
    extract_typed_links,
    parse_wiki_page,
    scan_wiki_pages,
    cmd_rebuild,
    cmd_sync,
    cmd_query,
    cmd_verify,
    _annotate_staleness,
    _parse_timeline_dates,
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
    targets = [l.target for l in links]
    assert "page-one" in targets
    assert "page-two" in targets
    assert len(links) == 2
    assert all(l.link_type == "references" for l in links)


def test_extract_links_none():
    content = "No links here."
    links = extract_links(content)
    assert links == []


def test_extract_typed_links():
    fm = 'links:\n  - {target: "foo", type: "extends"}\n  - {target: "bar", type: "references"}\n'
    links = extract_typed_links(fm)
    assert len(links) == 2
    assert links[0].target == "foo"
    assert links[0].link_type == "extends"
    assert links[1].target == "bar"
    assert links[1].link_type == "references"


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
    assert any(l.target == "other-page" for l in page.links)
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
# Query tests (mocked DB)
# ---------------------------------------------------------------------------

def test_cmd_query_keyword_only(capsys):
    """Keyword-only query (NullProvider) returns formatted results."""
    db = _mock_db()
    provider = NullProvider()

    # Simulate keyword search results
    db.query.return_value = [
        {"page_slug": "alpha", "chunk_index": None, "chunk_source": "compiled_truth",
         "chunk_text": "Alpha page content here", "score": 0.75},
        {"page_slug": "beta", "chunk_index": None, "chunk_source": "compiled_truth",
         "chunk_text": "Beta page content here", "score": 0.50},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        results = cmd_query(db, vault, provider, "test search")

    assert len(results) == 2
    assert results[0]["page_slug"] == "alpha"
    assert results[1]["page_slug"] == "beta"
    # Staleness annotation present
    assert "stale" in results[0]

    output = capsys.readouterr().out
    assert "alpha" in output
    assert "beta" in output
    assert "Found 2 results" in output


def test_cmd_query_no_results(capsys):
    """Empty result set handled gracefully."""
    db = _mock_db()
    provider = NullProvider()

    db.query.return_value = []

    with tempfile.TemporaryDirectory() as tmp:
        vault = Path(tmp)
        results = cmd_query(db, vault, provider, "nonexistent query")

    assert results == []
    output = capsys.readouterr().out
    assert "No results found" in output


# ---------------------------------------------------------------------------
# Staleness detection tests
# ---------------------------------------------------------------------------

def test_parse_timeline_dates():
    """Extract YYYY-MM-DD dates from timeline entries."""
    timeline = "- 2026-04-10: Created from source\n- 2026-04-12: Updated with new info\n"
    dates = _parse_timeline_dates(timeline)
    assert dates == ["2026-04-10", "2026-04-12"]


def test_parse_timeline_dates_empty():
    """No dates in timeline returns empty list."""
    assert _parse_timeline_dates("") == []
    assert _parse_timeline_dates("No dated entries here") == []


def test_annotate_staleness_stale_page():
    """Page is stale when timeline has newer dates than frontmatter updated."""
    db = _mock_db()
    db.query.return_value = [
        {
            "slug": "my-page",
            "frontmatter": {"updated": "2026-04-01"},
            "timeline": "- 2026-04-10: New evidence added\n",
        }
    ]
    rows = [{"page_slug": "my-page", "chunk_text": "some text"}]
    _annotate_staleness(db, rows)
    assert rows[0]["stale"] is True


def test_annotate_staleness_fresh_page():
    """Page is fresh when updated date is newer than all timeline entries."""
    db = _mock_db()
    db.query.return_value = [
        {
            "slug": "my-page",
            "frontmatter": {"updated": "2026-04-15"},
            "timeline": "- 2026-04-10: Old entry\n",
        }
    ]
    rows = [{"page_slug": "my-page", "chunk_text": "some text"}]
    _annotate_staleness(db, rows)
    assert rows[0]["stale"] is False


def test_annotate_staleness_no_timeline():
    """Page without timeline is not stale."""
    db = _mock_db()
    db.query.return_value = [
        {
            "slug": "my-page",
            "frontmatter": {"updated": "2026-04-01"},
            "timeline": "",
        }
    ]
    rows = [{"page_slug": "my-page", "chunk_text": "some text"}]
    _annotate_staleness(db, rows)
    assert rows[0]["stale"] is False


def test_annotate_staleness_no_updated_date():
    """Page without updated date is not stale."""
    db = _mock_db()
    db.query.return_value = [
        {
            "slug": "my-page",
            "frontmatter": {},
            "timeline": "- 2026-04-10: Some entry\n",
        }
    ]
    rows = [{"page_slug": "my-page", "chunk_text": "some text"}]
    _annotate_staleness(db, rows)
    assert rows[0]["stale"] is False


def test_annotate_staleness_empty_rows():
    """Empty rows list is handled gracefully."""
    db = _mock_db()
    _annotate_staleness(db, [])
    db.query.assert_not_called()


def test_annotate_staleness_db_failure():
    """DB failure defaults to not-stale."""
    db = _mock_db()
    db.query.side_effect = Exception("connection lost")
    rows = [{"page_slug": "my-page", "chunk_text": "some text"}]
    _annotate_staleness(db, rows)
    assert rows[0]["stale"] is False
