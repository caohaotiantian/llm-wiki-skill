#!/usr/bin/env python3
"""Wiki index management: rebuild, sync, query, verify.

Connects to either PGlite sidecar (HTTP) or native Postgres (psycopg).
Manages page chunking, embedding, and hybrid search.

Usage:
    python index.py rebuild <vault-path>
    python index.py sync <vault-path>
    python index.py query <vault-path> "search terms"
    python index.py verify <vault-path>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chunking import chunk_page
from embeddings import get_provider, EmbeddingProvider
from expansion import expand_query
from frontmatter import parse as parse_frontmatter, parse_typed_links as _parse_typed_links_fm


# ---------------------------------------------------------------------------
# Database client abstraction
# ---------------------------------------------------------------------------

class DbClient:
    """Database client supporting PGlite sidecar (HTTP) or native Postgres."""

    def __init__(self, database_url: str | None = None, sidecar_url: str | None = None):
        self._pg_conn = None
        self._sidecar_url = None

        if database_url:
            import psycopg
            self._pg_conn = psycopg.connect(database_url, autocommit=False)
        else:
            self._sidecar_url = sidecar_url or "http://localhost:5488"

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        """Execute a query and return rows as list of dicts."""
        if self._pg_conn is not None:
            return self._query_pg(sql, params)
        return self._query_sidecar(sql, params)

    def execute(self, sql: str, params: list | None = None) -> int:
        """Execute a statement and return affected row count."""
        if self._pg_conn is not None:
            return self._execute_pg(sql, params)
        return self._execute_sidecar(sql, params)

    def ping(self) -> bool:
        """Check if the database is reachable."""
        if self._pg_conn is not None:
            try:
                self._query_pg("SELECT 1", [])
                return True
            except Exception:
                return False
        return self._ping_sidecar()

    def begin(self):
        """Begin a transaction (Postgres only; sidecar is auto-commit)."""
        if self._pg_conn is not None:
            self._pg_conn.execute("BEGIN")

    def commit(self):
        """Commit the current transaction."""
        if self._pg_conn is not None:
            self._pg_conn.commit()

    def rollback(self):
        """Roll back the current transaction."""
        if self._pg_conn is not None:
            self._pg_conn.rollback()

    def batch(self, statements: list[tuple[str, list]]) -> list[dict]:
        """Execute multiple statements in a single transaction.

        Each entry is ``(sql, params_list)``.  Returns a list of result
        dicts with ``rows`` and ``affected`` keys.

        Sidecar path: single HTTP POST with ``method='batch'``.
        Native Postgres path: BEGIN → execute each → COMMIT (ROLLBACK on error).
        """
        if self._pg_conn is not None:
            # Native Postgres: explicit transaction
            results: list[dict] = []
            try:
                self._pg_conn.execute("BEGIN")
                for sql, params in statements:
                    cur = self._pg_conn.execute(sql, params)
                    rows = [dict(r) for r in cur.fetchall()] if cur.description else []
                    affected = cur.rowcount if cur.rowcount >= 0 else 0
                    results.append({"rows": rows, "affected": affected})
                self._pg_conn.commit()
            except Exception:
                self._pg_conn.rollback()
                raise
            return results
        else:
            # Sidecar: single batch RPC call
            payload: dict[str, Any] = {
                "method": "batch",
                "params": {
                    "statements": [
                        {"sql": sql, "args": args or []}
                        for sql, args in statements
                    ]
                },
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self._sidecar_url}/rpc",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            except urllib.error.URLError as e:
                raise ConnectionError(
                    f"Cannot reach PGlite sidecar at {self._sidecar_url}: {e}"
                ) from e
            return result.get("results", [])

    def close(self):
        """Close the database connection."""
        if self._pg_conn is not None:
            self._pg_conn.close()

    # -- Native Postgres via psycopg --

    def _query_pg(self, sql: str, params: list | None) -> list[dict]:
        cur = self._pg_conn.cursor()
        cur.execute(sql, params or [])
        if cur.description is None:
            return []
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]

    def _execute_pg(self, sql: str, params: list | None) -> int:
        cur = self._pg_conn.cursor()
        cur.execute(sql, params or [])
        return cur.rowcount

    # -- PGlite sidecar via HTTP --

    def _rpc(self, method: str, sql: str | None = None, args: list | None = None) -> dict:
        payload: dict[str, Any] = {"method": method, "params": {}}
        if sql is not None:
            payload["params"]["sql"] = sql
        if args is not None:
            payload["params"]["args"] = args
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._sidecar_url}/rpc",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(f"Cannot reach PGlite sidecar at {self._sidecar_url}: {e}") from e

    def _query_sidecar(self, sql: str, params: list | None) -> list[dict]:
        result = self._rpc("query", sql, params or [])
        return result.get("rows", [])

    def _execute_sidecar(self, sql: str, params: list | None) -> int:
        result = self._rpc("execute", sql, params or [])
        return result.get("affected", 0)

    def _ping_sidecar(self) -> bool:
        try:
            result = self._rpc("ping")
            return result.get("ok", False)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Page parsing helpers
# ---------------------------------------------------------------------------

@dataclass
class LinkRef:
    """A link to another page with an optional type."""
    target: str
    link_type: str = "references"


@dataclass
class WikiPage:
    """Parsed wiki page."""
    slug: str
    path: Path
    title: str
    page_type: str
    compiled_truth: str
    timeline: str
    frontmatter: dict
    content_hash: str
    raw_content: str
    links: list[LinkRef] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of page content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()




def extract_typed_links(fm_text: str) -> list[LinkRef]:
    """Extract typed links from frontmatter text (backward-compat wrapper).

    Wraps the shared frontmatter parser for callers that pass raw YAML text.
    """
    content = f"---\n{fm_text}\n---\n"
    fm, _ = parse_frontmatter(content)
    return [LinkRef(target=tl["target"], link_type=tl["type"]) for tl in _parse_typed_links_fm(fm)]


def extract_links(content: str) -> list[LinkRef]:
    """Extract wiki-style [[links]] from content."""
    return [LinkRef(target=m) for m in re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", content)]




def parse_wiki_page(file_path: Path, wiki_root: Path) -> WikiPage:
    """Parse a wiki markdown file into a WikiPage."""
    content = file_path.read_text(encoding="utf-8")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")

    slug = file_path.stem
    fm, body = parse_frontmatter(normalized)

    # Extract title from first heading or filename
    title_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else slug.replace("-", " ").title()

    # Determine page type from frontmatter or directory
    page_type = "unknown"
    if "type" in fm:
        page_type = fm["type"]
    elif "tags" in fm and isinstance(fm["tags"], list):
        # Use first tag as type hint
        page_type = fm["tags"][0] if fm["tags"] else "unknown"

    # Split compiled truth from timeline
    parts = re.split(r"\n---\s*\n", body, maxsplit=1)
    compiled_truth = parts[0].strip()
    timeline = parts[1].strip() if len(parts) > 1 else ""

    prose_links = extract_links(content)
    typed_links_raw = _parse_typed_links_fm(fm)
    typed_links = [LinkRef(target=tl["target"], link_type=tl["type"]) for tl in typed_links_raw]
    # Merge: typed links first, then prose wikilinks
    links: list[LinkRef] = typed_links + prose_links
    tags = fm.get("tags", []) if isinstance(fm.get("tags"), list) else []

    return WikiPage(
        slug=slug,
        path=file_path,
        title=title,
        page_type=page_type,
        compiled_truth=compiled_truth,
        timeline=timeline,
        frontmatter=fm,
        content_hash=compute_content_hash(content),
        raw_content=content,
        links=links,
        tags=tags,
    )


def scan_wiki_pages(vault_path: Path) -> list[WikiPage]:
    """Scan vault wiki/ directory for markdown pages."""
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        print(f"Warning: wiki/ directory not found at {wiki_dir}", file=sys.stderr)
        return []

    pages = []
    for md_file in sorted(wiki_dir.rglob("*.md")):
        if md_file.name.endswith(".snapshot.md"):
            continue
        try:
            page = parse_wiki_page(md_file, wiki_dir)
            pages.append(page)
        except Exception as e:
            print(f"Warning: Failed to parse {md_file}: {e}", file=sys.stderr)
    return pages


# ---------------------------------------------------------------------------
# Embedding dimension helpers
# ---------------------------------------------------------------------------

def _get_db_embedding_dim(db: DbClient) -> int | None:
    """Get the current embedding dimension from existing data."""
    try:
        rows = db.query(
            "SELECT embedding FROM content_chunks WHERE embedding IS NOT NULL LIMIT 1"
        )
        if rows and rows[0].get("embedding"):
            emb = rows[0]["embedding"]
            if isinstance(emb, (list, tuple)):
                return len(emb)
            if isinstance(emb, str) and emb.startswith("["):
                return emb.count(",") + 1
        return None
    except Exception:
        return None


def _migrate_embedding_dim(db: DbClient, new_dim: int) -> None:
    """Alter content_chunks embedding column to new dimension and clear existing embeddings."""
    print(f"Migrating embedding dimension to {new_dim}...", file=sys.stderr)
    db.execute("DELETE FROM content_chunks")
    db.execute(f"ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector({new_dim})")
    # Recreate HNSW index
    db.execute("DROP INDEX IF EXISTS content_chunks_hnsw")
    db.execute(
        "CREATE INDEX content_chunks_hnsw ON content_chunks USING hnsw (embedding vector_cosine_ops)"
    )
    print(f"Embedding dimension migrated to {new_dim}.", file=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_rebuild(db: DbClient, vault_path: Path, provider: EmbeddingProvider) -> None:
    """Full rebuild: scan all pages, chunk, embed, upsert into DB."""
    pages = scan_wiki_pages(vault_path)
    if not pages:
        print("No wiki pages found.")
        return

    print(f"Rebuilding index for {len(pages)} pages...")
    use_vectors = provider.dimension() > 0

    if use_vectors:
        db_dim = _get_db_embedding_dim(db)
        provider_dim = provider.dimension()
        if db_dim is not None and db_dim != provider_dim:
            print(f"Embedding dimension changed ({db_dim} → {provider_dim}). Migrating schema...", file=sys.stderr)
            _migrate_embedding_dim(db, provider_dim)

    for page in pages:
        try:
            _upsert_page(db, page, provider, use_vectors)
        except Exception as e:
            print(f"Error indexing page: {e}", file=sys.stderr)
            raise
        print(f"  indexed: {page.slug}")

    print(f"Rebuild complete. {len(pages)} pages indexed.")


def cmd_sync(db: DbClient, vault_path: Path, provider: EmbeddingProvider) -> None:
    """Incremental sync: only update pages whose content hash changed."""
    pages = scan_wiki_pages(vault_path)

    # Get existing hashes from DB
    existing = {}
    try:
        rows = db.query("SELECT slug, content_hash FROM pages")
        existing = {r["slug"]: r["content_hash"] for r in rows}
    except Exception:
        pass  # Table may not exist on first sync; rebuild will create it

    use_vectors = provider.dimension() > 0

    if use_vectors:
        db_dim = _get_db_embedding_dim(db)
        provider_dim = provider.dimension()
        if db_dim is not None and db_dim != provider_dim:
            print(
                f"Error: Embedding dimension mismatch (DB has {db_dim}, provider has {provider_dim}). "
                f"Run 'rebuild' to migrate, or change your embedding provider back.",
                file=sys.stderr,
            )
            return

    updated = 0
    skipped = 0

    for page in pages:
        if existing.get(page.slug) == page.content_hash:
            skipped += 1
            continue
        _upsert_page(db, page, provider, use_vectors)
        updated += 1
        print(f"  updated: {page.slug}")

    # Remove pages no longer on disk
    disk_slugs = {p.slug for p in pages}
    removed = 0
    db.begin()
    try:
        for slug in existing:
            if slug not in disk_slugs:
                db.execute("DELETE FROM pages WHERE slug = $1", [slug])
                removed += 1
                print(f"  removed: {slug}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    print(f"Sync complete. updated={updated}, skipped={skipped}, removed={removed}")


def _average_embeddings(embeddings: list[list[float]]) -> list[float]:
    """Element-wise mean of embedding vectors."""
    if not embeddings:
        return []
    dim = len(embeddings[0])
    avg = [0.0] * dim
    for emb in embeddings:
        for i in range(dim):
            avg[i] += emb[i]
    n = len(embeddings)
    return [v / n for v in avg]


def _merge_query_results(all_results: list[list[dict]]) -> list[dict]:
    """Merge results from multiple queries using score summation."""
    merged: dict[str, dict] = {}
    score_acc: dict[str, float] = {}
    best_score: dict[str, float] = {}
    for results in all_results:
        for row in results:
            slug = row.get("page_slug", "")
            row_score = row.get("score", 0)
            score_acc[slug] = score_acc.get(slug, 0) + row_score
            # Keep the dict from the highest-scored individual hit
            if slug not in merged or row_score > best_score.get(slug, 0):
                merged[slug] = dict(row)
                best_score[slug] = row_score
    for slug, entry in merged.items():
        entry["score"] = score_acc[slug]
    combined = sorted(merged.values(), key=lambda r: r.get("score", 0), reverse=True)
    return combined[:20]


def cmd_query(
    db: DbClient,
    vault_path: Path,
    provider: EmbeddingProvider,
    query_text: str,
    *,
    as_json: bool = False,
    expand: bool = False,
    expand_thorough: bool = False,
) -> list[dict]:
    """Hybrid search: vector + keyword with RRF fusion.

    Returns a list of result dicts (also printed unless *as_json* is set).

    When *expand* is True (fast mode), query paraphrases are embedded and
    averaged into a single vector for the vector search.  When
    *expand_thorough* is True, each paraphrase is searched independently
    and results are merged by score summation.  *expand_thorough* takes
    precedence over *expand*.
    """
    # -- Thorough expansion: run separate searches and merge --
    if expand_thorough:
        paraphrases = expand_query(query_text)
        print(
            f"Expanded query into {len(paraphrases) - 1} paraphrases "
            f"(thorough mode, {len(paraphrases)} queries)",
            file=sys.stderr,
        )
        all_results: list[list[dict]] = []
        for pq in paraphrases:
            sub = cmd_query(db, vault_path, provider, pq, as_json=False)
            all_results.append(sub)
        rows = _merge_query_results(all_results)

        # Staleness already annotated per sub-query; re-annotate merged set
        _annotate_staleness(db, rows)

        if as_json:
            print(json.dumps(rows, indent=2, default=str))
            return rows

        if not rows:
            print("No results found.")
            return rows

        print(f"Found {len(rows)} results for: {query_text}\n")
        for i, row in enumerate(rows[:20]):
            slug = row.get("page_slug", "?")
            source = row.get("chunk_source", "?")
            score = row.get("score", 0)
            stale_flag = " [STALE]" if row.get("stale") else ""
            excerpt = (row.get("chunk_text", "") or "")[:200].replace("\n", " ")
            print(f"  [{i+1}] {slug} ({source}) score={score:.4f}{stale_flag}")
            print(f"      {excerpt}...")
            print()
        return rows

    # -- Fast expansion: average embeddings --
    if expand:
        paraphrases = expand_query(query_text)
        print(
            f"Expanded query into {len(paraphrases) - 1} paraphrases (fast mode)",
            file=sys.stderr,
        )

    use_vectors = provider.dimension() > 0

    if use_vectors:
        # Embed query (fast expand: average all paraphrase embeddings)
        if expand:
            all_embeddings = provider.embed_batch(paraphrases)
            query_embedding = _average_embeddings(all_embeddings)
        else:
            query_embedding = provider.embed_batch([query_text])[0]
        emb_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # RRF hybrid search: vector rank + keyword rank fused via UNION ALL
        sql = """
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
                   row_number() OVER (ORDER BY ts_rank(search_vector, websearch_to_tsquery('english', $2)) DESC) AS rnk
            FROM pages p, websearch_to_tsquery('english', $2) query
            WHERE search_vector @@ query
            ORDER BY ts_rank(search_vector, websearch_to_tsquery('english', $2)) DESC
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
        """
        rows = db.query(sql, [emb_literal, query_text])

        # Sort by score descending, then limit
        rows.sort(key=lambda r: r.get("score", 0), reverse=True)
        rows = rows[:20]
    else:
        # Keyword-only fallback
        sql = """
        SELECT p.slug AS page_slug, NULL AS chunk_index,
               'compiled_truth' AS chunk_source,
               LEFT(p.compiled_truth, 300) AS chunk_text,
               ts_rank(p.search_vector, websearch_to_tsquery('english', $1)) AS score
        FROM pages p
        WHERE p.search_vector @@ websearch_to_tsquery('english', $1)
        ORDER BY score DESC
        LIMIT 20
        """
        rows = db.query(sql, [query_text])

    # Staleness check: compare page updated_at vs latest timeline entry
    _annotate_staleness(db, rows)

    if as_json:
        print(json.dumps(rows, indent=2, default=str))
        return rows

    # Display results
    if not rows:
        print("No results found.")
        return rows

    print(f"Found {len(rows)} results for: {query_text}\n")
    for i, row in enumerate(rows[:20]):
        slug = row.get("page_slug", "?")
        source = row.get("chunk_source", "?")
        score = float(row.get("score", 0) or 0)
        stale_flag = " [STALE]" if row.get("stale") else ""
        excerpt = (row.get("chunk_text", "") or "")[:200].replace("\n", " ")
        print(f"  [{i+1}] {slug} ({source}) score={score:.4f}{stale_flag}")
        print(f"      {excerpt}...")
        print()

    return rows


def cmd_verify(db: DbClient, vault_path: Path) -> dict:
    """Health check: embedding coverage, stale pages, orphans, dangling links."""
    pages = scan_wiki_pages(vault_path)
    disk_slugs = {p.slug for p in pages}
    disk_hashes = {p.slug: p.content_hash for p in pages}

    report: dict[str, Any] = {
        "disk_pages": len(pages),
        "db_pages": 0,
        "pages_with_embeddings": 0,
        "pages_without_embeddings": 0,
        "stale_pages": [],
        "orphan_pages": [],
        "dangling_links": [],
    }

    try:
        db_pages = db.query("SELECT slug, content_hash FROM pages")
        report["db_pages"] = len(db_pages)

        db_slugs = set()
        for row in db_pages:
            slug = row["slug"]
            db_slugs.add(slug)
            if slug not in disk_slugs:
                report["orphan_pages"].append(slug)
            elif row["content_hash"] != disk_hashes.get(slug):
                report["stale_pages"].append(slug)

        # Embedding coverage
        emb_rows = db.query(
            "SELECT DISTINCT page_slug FROM content_chunks WHERE embedding IS NOT NULL"
        )
        embedded_slugs = {r["page_slug"] for r in emb_rows}
        report["pages_with_embeddings"] = len(embedded_slugs)
        report["pages_without_embeddings"] = report["db_pages"] - len(embedded_slugs)

        # Dangling links
        link_rows = db.query("SELECT DISTINCT to_slug FROM links")
        for row in link_rows:
            target = row["to_slug"]
            if target not in db_slugs and target not in disk_slugs:
                report["dangling_links"].append(target)

    except Exception as e:
        print(f"Warning: DB query failed (is the database running?): {e}", file=sys.stderr)

    # Print report
    print("=== Wiki Index Health Check ===")
    print(f"  Pages on disk:            {report['disk_pages']}")
    print(f"  Pages in DB:              {report['db_pages']}")
    print(f"  With embeddings:          {report['pages_with_embeddings']}")
    print(f"  Without embeddings:       {report['pages_without_embeddings']}")
    print(f"  Stale (hash mismatch):    {len(report['stale_pages'])}")
    if report["stale_pages"]:
        for s in report["stale_pages"]:
            print(f"    - {s}")
    print(f"  Orphan (in DB not disk):  {len(report['orphan_pages'])}")
    if report["orphan_pages"]:
        for s in report["orphan_pages"]:
            print(f"    - {s}")
    print(f"  Dangling links:           {len(report['dangling_links'])}")
    if report["dangling_links"]:
        for s in report["dangling_links"]:
            print(f"    - {s}")

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_page(db: DbClient, page: WikiPage, provider: EmbeddingProvider, use_vectors: bool) -> None:
    """Insert or update a single page and its chunks/links/tags.

    All statements are collected and executed via ``db.batch()`` so they
    run inside a single transaction.
    """
    from frontmatter import json_default
    fm_json = json.dumps(page.frontmatter, default=json_default)

    statements: list[tuple[str, list]] = []

    # Upsert page
    statements.append((
        """INSERT INTO pages (slug, type, title, compiled_truth, timeline, frontmatter, content_hash, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, now())
           ON CONFLICT (slug) DO UPDATE SET
               type = EXCLUDED.type,
               title = EXCLUDED.title,
               compiled_truth = EXCLUDED.compiled_truth,
               timeline = EXCLUDED.timeline,
               frontmatter = EXCLUDED.frontmatter,
               content_hash = EXCLUDED.content_hash,
               updated_at = now()""",
        [page.slug, page.page_type, page.title, page.compiled_truth, page.timeline, fm_json, page.content_hash],
    ))

    # Delete old chunks
    statements.append(("DELETE FROM content_chunks WHERE page_slug = $1", [page.slug]))

    # Insert new chunks
    chunked = chunk_page(page.raw_content)
    chunk_index = 0
    for source in ("compiled_truth", "timeline"):
        texts = chunked.get(source, [])
        if use_vectors and texts:
            embeddings = provider.embed_batch(texts)
        else:
            embeddings = [None] * len(texts)
        for text, emb in zip(texts, embeddings):
            if emb is not None:
                emb_literal = "[" + ",".join(str(x) for x in emb) + "]"
                statements.append((
                    """INSERT INTO content_chunks (page_slug, chunk_index, chunk_source, chunk_text, embedding)
                       VALUES ($1, $2, $3, $4, $5::vector)""",
                    [page.slug, chunk_index, source, text, emb_literal],
                ))
            else:
                statements.append((
                    """INSERT INTO content_chunks (page_slug, chunk_index, chunk_source, chunk_text)
                       VALUES ($1, $2, $3, $4)""",
                    [page.slug, chunk_index, source, text],
                ))
            chunk_index += 1

    # Delete old links
    statements.append(("DELETE FROM links WHERE from_slug = $1", [page.slug]))

    # Insert new links
    seen_links: set[tuple[str, str]] = set()
    for link in page.links:
        key = (link.target, link.link_type)
        if key in seen_links:
            continue
        seen_links.add(key)
        statements.append((
            "INSERT INTO links (from_slug, to_slug, link_type) VALUES ($1, $2, $3)",
            [page.slug, link.target, link.link_type],
        ))

    # Delete old tags
    statements.append(("DELETE FROM tags WHERE page_slug = $1", [page.slug]))

    # Insert new tags
    for tag in set(page.tags):
        statements.append((
            "INSERT INTO tags (page_slug, tag) VALUES ($1, $2)",
            [page.slug, tag],
        ))

    db.batch(statements)


def _parse_timeline_dates(timeline_text: str) -> list[str]:
    """Extract YYYY-MM-DD dates from timeline entry lines."""
    return re.findall(r"^-\s+(\d{4}-\d{2}-\d{2})", timeline_text, re.MULTILINE)


def _annotate_staleness(db: DbClient, rows: list[dict]) -> None:
    """Add a ``stale`` boolean to each result row.

    A page is stale when its frontmatter ``updated`` date is older than
    the most recent timeline entry date.  Both are extracted from the
    pages table (frontmatter JSONB and timeline text column).
    """
    if not rows:
        return
    slugs = [r.get("page_slug") for r in rows if r.get("page_slug")]
    if not slugs:
        return

    try:
        placeholders = ", ".join(f"${i+1}" for i in range(len(slugs)))
        page_rows = db.query(
            f"SELECT slug, frontmatter, timeline FROM pages WHERE slug IN ({placeholders})",
            slugs,
        )

        stale_map: dict[str, bool] = {}
        for pr in page_rows:
            slug = pr["slug"]
            fm = pr.get("frontmatter") or {}
            if isinstance(fm, str):
                try:
                    import json as _json
                    fm = _json.loads(fm)
                except (ValueError, TypeError):
                    fm = {}
            updated_str = fm.get("updated", "")
            timeline_text = pr.get("timeline") or ""
            timeline_dates = _parse_timeline_dates(timeline_text)

            if updated_str and timeline_dates:
                latest_timeline = max(timeline_dates)
                stale_map[slug] = latest_timeline > str(updated_str)
            else:
                stale_map[slug] = False

        for row in rows:
            slug = row.get("page_slug")
            row["stale"] = stale_map.get(slug, False)
    except Exception as e:
        print(f"Warning: staleness check failed, defaulting to not-stale: {e}", file=sys.stderr)
        for row in rows:
            row["stale"] = False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def get_db_client() -> DbClient:
    """Create a DB client from environment configuration."""
    database_url = os.environ.get("DATABASE_URL")
    sidecar_url = os.environ.get("PGLITE_URL", "http://localhost:5488")
    return DbClient(database_url=database_url, sidecar_url=sidecar_url)


def main():
    parser = argparse.ArgumentParser(description="Wiki index management.")
    sub = parser.add_subparsers(dest="command", help="Subcommand")

    p_rebuild = sub.add_parser("rebuild", help="Full index rebuild")
    p_rebuild.add_argument("vault_path", type=Path, help="Path to vault directory")
    p_rebuild.add_argument("--provider", default=None, help="Embedding provider: null, local, openai/remote (default: auto-detect)")

    p_sync = sub.add_parser("sync", help="Incremental sync")
    p_sync.add_argument("vault_path", type=Path, help="Path to vault directory")
    p_sync.add_argument("--provider", default=None, help="Embedding provider: null, local, openai/remote (default: auto-detect)")

    p_query = sub.add_parser("query", help="Hybrid search")
    p_query.add_argument("vault_path", type=Path, help="Path to vault directory")
    p_query.add_argument("query_text", help="Search query")
    p_query.add_argument("--provider", default=None, help="Embedding provider: null, local, openai/remote (default: auto-detect)")
    p_query.add_argument("--json", action="store_true", dest="json_output", default=False, help="Output results as JSON")
    p_query.add_argument("--expand", action="store_true", help="Fast expansion: average embeddings")
    p_query.add_argument("--expand-thorough", action="store_true", help="Thorough expansion: multi-query RRF")

    p_verify = sub.add_parser("verify", help="Health check")
    p_verify.add_argument("vault_path", type=Path, help="Path to vault directory")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db = get_db_client()

    try:
        if args.command == "rebuild":
            provider = get_provider(args.provider)
            cmd_rebuild(db, args.vault_path, provider)
        elif args.command == "sync":
            provider = get_provider(args.provider)
            cmd_sync(db, args.vault_path, provider)
        elif args.command == "query":
            provider = get_provider(args.provider)
            cmd_query(db, args.vault_path, provider, args.query_text, as_json=args.json_output, expand=args.expand, expand_thorough=args.expand_thorough)
        elif args.command == "verify":
            cmd_verify(db, args.vault_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
