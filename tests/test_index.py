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
    _get_db_embedding_dim,
    _migrate_embedding_dim,
    _average_embeddings,
    _merge_query_results,
    _upsert_page,
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

    # Should have called batch for upsert, chunks, links, tags
    assert db.batch.call_count > 0
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


# ---------------------------------------------------------------------------
# Embedding dimension detection tests
# ---------------------------------------------------------------------------

def test_get_db_embedding_dim_from_string_data():
    """Detect dimension from string-encoded embedding data."""
    db = _mock_db()
    db.query.return_value = [{"embedding": "[0.1,0.2,0.3]"}]
    assert _get_db_embedding_dim(db) == 3


def test_get_db_embedding_dim_from_list_data():
    """Detect dimension from list embedding data."""
    db = _mock_db()
    db.query.return_value = [{"embedding": [0.1, 0.2, 0.3, 0.4]}]
    assert _get_db_embedding_dim(db) == 4


def test_get_db_embedding_dim_no_data():
    """Return None when no embeddings exist."""
    db = _mock_db()
    db.query.return_value = []
    assert _get_db_embedding_dim(db) is None


def test_get_db_embedding_dim_db_error():
    """Return None on DB error."""
    db = _mock_db()
    db.query.side_effect = Exception("table not found")
    assert _get_db_embedding_dim(db) is None


def test_get_db_embedding_dim_null_embedding():
    """Return None when embedding value is None."""
    db = _mock_db()
    db.query.return_value = [{"embedding": None}]
    assert _get_db_embedding_dim(db) is None


def test_migrate_embedding_dim(capsys):
    """Migration deletes chunks, alters column, and recreates index."""
    db = _mock_db()
    _migrate_embedding_dim(db, 1536)

    execute_calls = [str(c) for c in db.execute.call_args_list]
    assert any("DELETE FROM content_chunks" in c for c in execute_calls)
    assert any("ALTER TABLE" in c and "1536" in c for c in execute_calls)
    assert any("DROP INDEX" in c for c in execute_calls)
    assert any("CREATE INDEX" in c for c in execute_calls)

    err = capsys.readouterr().err
    assert "1536" in err
    assert "Migrating" in err


def test_rebuild_migrates_dimension(capsys):
    """Rebuild auto-migrates when embedding dimension changes."""
    db = _mock_db()
    dim_query_done = [False]

    def query_side_effect(sql, *args, **kwargs):
        if "content_chunks" in sql and "embedding" in sql and not dim_query_done[0]:
            dim_query_done[0] = True
            return [{"embedding": "[" + ",".join(["0.1"] * 384) + "]"}]
        return []

    db.query.side_effect = query_side_effect

    provider = MagicMock()
    provider.dimension.return_value = 1536
    provider.embed_batch.return_value = [[0.1] * 1536]

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {"page.md": "---\ntags: [concept]\n---\n\n# Page\n\nContent."})
        cmd_rebuild(db, vault, provider)

    alter_calls = [c for c in db.execute.call_args_list if "ALTER TABLE" in str(c)]
    assert len(alter_calls) > 0

    err = capsys.readouterr().err
    assert "migrat" in err.lower()


def test_rebuild_no_migration_when_dim_matches(capsys):
    """Rebuild does not migrate when dimensions already match."""
    db = _mock_db()
    dim_query_done = [False]

    def query_side_effect(sql, *args, **kwargs):
        if "content_chunks" in sql and "embedding" in sql and not dim_query_done[0]:
            dim_query_done[0] = True
            return [{"embedding": "[" + ",".join(["0.1"] * 384) + "]"}]
        return []

    db.query.side_effect = query_side_effect

    provider = MagicMock()
    provider.dimension.return_value = 384
    provider.embed_batch.return_value = [[0.1] * 384]

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {"page.md": "---\ntags: [concept]\n---\n\n# Page\n\nContent."})
        cmd_rebuild(db, vault, provider)

    alter_calls = [c for c in db.execute.call_args_list if "ALTER TABLE" in str(c)]
    assert len(alter_calls) == 0

    err = capsys.readouterr().err
    assert "migrat" not in err.lower()


def test_sync_aborts_on_dimension_mismatch(capsys):
    """Sync warns and aborts when embedding dimension changes."""
    db = _mock_db()
    call_count = [0]

    def query_side_effect(sql, *args, **kwargs):
        call_count[0] += 1
        if "content_chunks" in sql and "embedding" in sql:
            return [{"embedding": "[" + ",".join(["0.1"] * 384) + "]"}]
        if "slug" in sql and "content_hash" in sql:
            return []
        return []

    db.query.side_effect = query_side_effect

    provider = MagicMock()
    provider.dimension.return_value = 1536

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {"page.md": "---\ntags: [concept]\n---\n\n# Page\n\nContent."})
        cmd_sync(db, vault, provider)

    err = capsys.readouterr().err
    assert "mismatch" in err.lower()
    # Should NOT have called INSERT (no upserts)
    insert_calls = [c for c in db.execute.call_args_list if "INSERT" in str(c)]
    assert len(insert_calls) == 0


def test_sync_no_abort_when_dim_matches(capsys):
    """Sync proceeds normally when dimensions match."""
    db = _mock_db()

    def query_side_effect(sql, *args, **kwargs):
        if "content_chunks" in sql and "embedding" in sql:
            return [{"embedding": "[" + ",".join(["0.1"] * 384) + "]"}]
        if "slug" in sql and "content_hash" in sql:
            return [{"slug": "page", "content_hash": "oldhash"}]
        return []

    db.query.side_effect = query_side_effect

    provider = MagicMock()
    provider.dimension.return_value = 384
    provider.embed_batch.return_value = [[0.1] * 384]

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(Path(tmp), {"page.md": "---\ntags: [concept]\n---\n\n# Page\n\nContent."})
        cmd_sync(db, vault, provider)

    err = capsys.readouterr().err
    assert "mismatch" not in err.lower()
    # Should have proceeded with sync (batch was called for upserts)
    assert db.batch.call_count > 0


# ---------------------------------------------------------------------------
# Query expansion helper tests
# ---------------------------------------------------------------------------

def test_average_embeddings_basic():
    """Average of two orthogonal vectors."""
    result = _average_embeddings([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    assert len(result) == 3
    assert abs(result[0] - 0.5) < 1e-9
    assert abs(result[1] - 0.5) < 1e-9
    assert abs(result[2] - 0.0) < 1e-9


def test_average_embeddings_single():
    """Average of a single vector is itself."""
    result = _average_embeddings([[0.3, 0.6, 0.9]])
    assert len(result) == 3
    assert abs(result[0] - 0.3) < 1e-9


def test_average_embeddings_empty():
    """Empty input returns empty list."""
    assert _average_embeddings([]) == []


def test_merge_query_results_dedup():
    """Merge keeps highest-scored chunk and sums scores."""
    r1 = [{"page_slug": "a", "score": 0.5, "chunk_text": "low"}]
    r2 = [{"page_slug": "a", "score": 0.8, "chunk_text": "high"}]
    merged = _merge_query_results([r1, r2])
    assert len(merged) == 1
    assert merged[0]["page_slug"] == "a"
    assert merged[0]["chunk_text"] == "high"
    assert abs(merged[0]["score"] - 1.3) < 1e-9


def test_merge_query_results_limit():
    """Merge limits to 20 results."""
    results = [[{"page_slug": f"p-{i}", "score": 0.1, "chunk_text": f"t{i}"}] for i in range(30)]
    merged = _merge_query_results(results)
    assert len(merged) == 20


# ---------------------------------------------------------------------------
# Query expansion integration tests
# ---------------------------------------------------------------------------

def test_cmd_query_expand_fast(capsys):
    """Fast expansion averages embeddings."""
    db = _mock_db()

    # Mock expansion to return original + 1 paraphrase
    with patch("index.expand_query", return_value=["test query", "alternative phrasing"]):
        provider = MagicMock()
        provider.dimension.return_value = 3
        provider.embed_batch.return_value = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

        db.query.return_value = [
            {"page_slug": "result", "chunk_index": 0, "chunk_source": "compiled_truth",
             "chunk_text": "Result content", "score": 0.8},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            results = cmd_query(db, vault, provider, "test query", expand=True)

    assert len(results) >= 1
    # embed_batch should have been called with both queries
    provider.embed_batch.assert_called_once()
    call_args = provider.embed_batch.call_args[0][0]
    assert len(call_args) == 2

    err = capsys.readouterr().err
    assert "fast" in err.lower() or "paraphrase" in err.lower()


def test_cmd_query_expand_thorough(capsys):
    """Thorough expansion runs multiple queries and merges."""
    db = _mock_db()
    call_count = [0]

    def query_side_effect(sql, *args, **kwargs):
        # Return different results for different calls
        if "websearch_to_tsquery" in sql:
            call_count[0] += 1
            return [
                {"page_slug": f"page-{call_count[0]}", "chunk_index": 0,
                 "chunk_source": "compiled_truth", "chunk_text": f"Content {call_count[0]}",
                 "score": 0.5},
            ]
        # For staleness queries
        return []

    db.query.side_effect = query_side_effect

    with patch("index.expand_query", return_value=["query1", "query2"]):
        provider = NullProvider()

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            results = cmd_query(db, vault, provider, "test query", expand_thorough=True)

    # Should have results from multiple queries
    assert len(results) >= 1

    err = capsys.readouterr().err
    assert "thorough" in err.lower() or "paraphrase" in err.lower()


def test_cmd_query_no_expand(capsys):
    """Without expand flags, no expansion happens."""
    db = _mock_db()
    db.query.return_value = [
        {"page_slug": "alpha", "chunk_index": None, "chunk_source": "compiled_truth",
         "chunk_text": "Alpha content", "score": 0.75},
    ]

    with patch("index.expand_query") as mock_expand:
        provider = NullProvider()
        with tempfile.TemporaryDirectory() as tmp:
            results = cmd_query(db, Path(tmp), provider, "test")

    mock_expand.assert_not_called()


def test_cmd_query_thorough_takes_precedence(capsys):
    """expand_thorough takes precedence over expand."""
    db = _mock_db()

    def query_side_effect(sql, *args, **kwargs):
        if "websearch_to_tsquery" in sql:
            return [{"page_slug": "p1", "chunk_index": 0,
                      "chunk_source": "compiled_truth", "chunk_text": "text",
                      "score": 0.5}]
        return []

    db.query.side_effect = query_side_effect

    with patch("index.expand_query", return_value=["q1", "q2"]) as mock_expand:
        provider = NullProvider()
        with tempfile.TemporaryDirectory() as tmp:
            results = cmd_query(db, Path(tmp), provider, "test",
                                expand=True, expand_thorough=True)

    err = capsys.readouterr().err
    assert "thorough" in err.lower()


# ---------------------------------------------------------------------------
# Batch transaction tests
# ---------------------------------------------------------------------------

def test_dbclient_batch_method_exists():
    """Batch method exists on DbClient with correct signature."""
    assert hasattr(DbClient, 'batch')
    import inspect
    sig = inspect.signature(DbClient.batch)
    params = list(sig.parameters.keys())
    assert "self" in params
    assert "statements" in params


def test_upsert_page_uses_batch():
    """_upsert_page should call db.batch() instead of individual executes."""
    db = _mock_db()
    db.batch = MagicMock(return_value=[])
    provider = NullProvider()

    page = WikiPage(
        slug="test-page",
        path=Path("/tmp/test-page.md"),
        title="Test Page",
        page_type="concept",
        compiled_truth="Some content about testing.",
        timeline="",
        frontmatter={"tags": ["concept"]},
        content_hash="abc123",
        raw_content="---\ntags: [concept]\n---\n\n# Test Page\n\nSome content about testing.",
        links=[LinkRef(target="other-page", link_type="references")],
        tags=["concept"],
    )
    _upsert_page(db, page, provider, use_vectors=False)

    # Should have called batch once with multiple statements
    db.batch.assert_called_once()
    statements = db.batch.call_args[0][0]
    # At minimum: upsert page, delete chunks, insert chunk(s), delete links, insert link, delete tags, insert tag
    assert len(statements) >= 3
    # First statement should be the page upsert
    assert "INSERT INTO pages" in statements[0][0]
    # Should not have called execute directly for page data
    db.execute.assert_not_called()


def test_cmd_rebuild_no_begin_commit():
    """cmd_rebuild should not call begin/commit — batch handles transactions."""
    db = _mock_db()
    db.batch = MagicMock(return_value=[])
    provider = NullProvider()

    with tempfile.TemporaryDirectory() as tmp:
        vault = _make_vault(
            Path(tmp),
            {"page.md": "---\ntags: [concept]\n---\n\n# Page\n\nContent."},
        )
        cmd_rebuild(db, vault, provider)

    db.begin.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()
