#!/usr/bin/env python3
"""Shared database operations for wiki index and storage backends.

Provides common SQL operations used by both index.py and the
DatabaseBackend in storage.py.  All functions accept a ``db`` parameter
that is duck-typed — any object with ``.query(sql, params)`` and
``.execute(sql, params)`` methods works (e.g. ``DbClient`` from
index.py or a test double).
"""
from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Page CRUD
# ---------------------------------------------------------------------------

def get_page_row(db: Any, slug: str) -> dict | None:
    """Fetch a single page row by slug, or None."""
    rows = db.query(
        "SELECT slug, type, title, compiled_truth, timeline, "
        "frontmatter, content_hash FROM pages WHERE slug = $1",
        [slug],
    )
    return rows[0] if rows else None


def upsert_page_row(
    db: Any,
    slug: str,
    page_type: str,
    title: str,
    compiled_truth: str,
    timeline: str,
    frontmatter: dict,
    content_hash: str,
) -> None:
    """Insert or update a page row (without chunks, links, or tags)."""
    fm_json = json.dumps(frontmatter) if isinstance(frontmatter, dict) else frontmatter
    db.execute(
        """INSERT INTO pages (slug, type, title, compiled_truth, timeline,
               frontmatter, content_hash, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, now())
           ON CONFLICT (slug) DO UPDATE SET
               type = EXCLUDED.type,
               title = EXCLUDED.title,
               compiled_truth = EXCLUDED.compiled_truth,
               timeline = EXCLUDED.timeline,
               frontmatter = EXCLUDED.frontmatter,
               content_hash = EXCLUDED.content_hash,
               updated_at = now()""",
        [slug, page_type, title, compiled_truth, timeline, fm_json, content_hash],
    )


def delete_page_row(db: Any, slug: str) -> bool:
    """Delete a page and cascade to chunks/links/tags.  Returns True if deleted."""
    affected = db.execute("DELETE FROM pages WHERE slug = $1", [slug])
    return affected > 0


def list_page_rows(db: Any, where: dict | None = None) -> list[dict]:
    """List pages with optional type/tag/frontmatter filters."""
    base_cols = (
        "SELECT slug, type, title, compiled_truth, timeline, "
        "frontmatter, content_hash FROM pages"
    )
    if not where:
        return db.query(f"{base_cols} ORDER BY slug")

    conditions: list[str] = []
    params: list[Any] = []
    i = 1
    if "type" in where:
        conditions.append(f"type = ${i}")
        params.append(where["type"])
        i += 1
    if "tag" in where:
        conditions.append(
            f"EXISTS (SELECT 1 FROM tags WHERE tags.page_slug = pages.slug AND tags.tag = ${i})"
        )
        params.append(where["tag"])
        i += 1
    for key, val in where.items():
        if key not in ("type", "tag"):
            conditions.append(f"frontmatter->>'{key}' = ${i}")
            params.append(str(val))
            i += 1

    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    return db.query(f"{base_cols} WHERE {where_clause} ORDER BY slug", params)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def add_link_row(db: Any, from_slug: str, to_slug: str, link_type: str) -> None:
    """Insert a link (idempotent — ignores duplicates)."""
    db.execute(
        "INSERT INTO links (from_slug, to_slug, link_type) VALUES ($1, $2, $3) "
        "ON CONFLICT DO NOTHING",
        [from_slug, to_slug, link_type],
    )


def delete_links_from(db: Any, slug: str) -> int:
    """Remove all outbound links from a page."""
    return db.execute("DELETE FROM links WHERE from_slug = $1", [slug])


def get_backlink_rows(db: Any, slug: str) -> list[dict]:
    """Get all links pointing TO this slug."""
    return db.query(
        "SELECT from_slug, to_slug, link_type FROM links WHERE to_slug = $1",
        [slug],
    )


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def replace_tags(db: Any, slug: str, tags: list[str]) -> None:
    """Replace all tags for a page."""
    db.execute("DELETE FROM tags WHERE page_slug = $1", [slug])
    for tag in set(tags):
        db.execute(
            "INSERT INTO tags (page_slug, tag) VALUES ($1, $2)",
            [slug, tag],
        )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_keyword_rows(db: Any, query: str, limit: int = 10) -> list[dict]:
    """Full-text keyword search using tsvector."""
    return db.query(
        "SELECT p.slug AS page_slug, 'compiled_truth' AS chunk_source, "
        "LEFT(p.compiled_truth, 300) AS chunk_text, "
        "ts_rank(p.search_vector, websearch_to_tsquery('english', $1)) AS score "
        "FROM pages p WHERE p.search_vector @@ websearch_to_tsquery('english', $1) "
        "ORDER BY score DESC LIMIT $2",
        [query, limit],
    )


def search_hybrid_rows(
    db: Any, query: str, embedding: list[float], limit: int = 10
) -> list[dict]:
    """Hybrid search: vector + keyword with RRF fusion."""
    emb_literal = "[" + ",".join(str(x) for x in embedding) + "]"
    rows = db.query(
        """
        WITH
        vector_hits AS (
            SELECT page_slug, chunk_index, chunk_source, chunk_text,
                   row_number() OVER (ORDER BY embedding <=> $1::vector) AS rnk
            FROM content_chunks
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT 50
        ),
        keyword_hits AS (
            SELECT p.slug AS page_slug, 0 AS chunk_index,
                   'compiled_truth' AS chunk_source, p.title AS chunk_text,
                   row_number() OVER (ORDER BY ts_rank(search_vector,
                       websearch_to_tsquery('english', $2)) DESC) AS rnk
            FROM pages p, websearch_to_tsquery('english', $2) query
            WHERE search_vector @@ query
            ORDER BY ts_rank(search_vector,
                websearch_to_tsquery('english', $2)) DESC
            LIMIT 50
        ),
        fused AS (
            SELECT page_slug, chunk_text, chunk_source,
                   SUM(1.0 / (60 + rnk)) AS score
            FROM (
                SELECT page_slug, chunk_text, chunk_source, rnk FROM vector_hits
                UNION ALL
                SELECT page_slug, chunk_text, chunk_source, rnk FROM keyword_hits
            ) u
            GROUP BY page_slug, chunk_text, chunk_source
        )
        SELECT DISTINCT ON (page_slug) page_slug, chunk_text, chunk_source, score
        FROM fused
        ORDER BY page_slug, score DESC
        """,
        [emb_literal, query],
    )
    rows.sort(key=lambda r: r.get("score", 0), reverse=True)
    return rows[:limit]
