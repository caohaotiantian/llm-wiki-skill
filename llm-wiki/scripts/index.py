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
        self._pg_conn.commit()
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
    links: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of page content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from content."""
    fm_match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n)", content, re.DOTALL)
    if not fm_match:
        return {}, content

    fm_text = fm_match.group(1)
    body = content[fm_match.end():]

    # Simple YAML-like parser for basic key: value pairs
    fm: dict[str, Any] = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Handle YAML lists like [tag1, tag2]
            if value.startswith("[") and value.endswith("]"):
                items = [item.strip().strip("'\"") for item in value[1:-1].split(",")]
                fm[key] = [i for i in items if i]
            elif value.lower() in ("true", "false"):
                fm[key] = value.lower() == "true"
            else:
                fm[key] = value.strip("'\"")
    return fm, body


def extract_links(content: str) -> list[str]:
    """Extract wiki-style [[links]] from content."""
    return re.findall(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]", content)


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

    links = extract_links(content)
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
        try:
            page = parse_wiki_page(md_file, wiki_dir)
            pages.append(page)
        except Exception as e:
            print(f"Warning: Failed to parse {md_file}: {e}", file=sys.stderr)
    return pages


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

    for page in pages:
        _upsert_page(db, page, provider, use_vectors)
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
        pass  # Table might not exist yet; rebuild will handle it

    use_vectors = provider.dimension() > 0
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
    for slug in existing:
        if slug not in disk_slugs:
            db.execute("DELETE FROM pages WHERE slug = $1", [slug])
            removed += 1
            print(f"  removed: {slug}")

    print(f"Sync complete. updated={updated}, skipped={skipped}, removed={removed}")


def cmd_query(db: DbClient, vault_path: Path, provider: EmbeddingProvider, query_text: str) -> None:
    """Hybrid search: vector + keyword with RRF fusion."""
    use_vectors = provider.dimension() > 0

    if use_vectors:
        # Embed query
        query_embedding = provider.embed_batch([query_text])[0]
        emb_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"

        # RRF hybrid search: vector rank + keyword rank fused
        sql = """
        WITH vector_ranked AS (
            SELECT cc.page_slug, cc.chunk_index, cc.chunk_source, cc.chunk_text,
                   1 - (cc.embedding <=> $1::vector) AS cosine_sim,
                   ROW_NUMBER() OVER (ORDER BY cc.embedding <=> $1::vector) AS vrank
            FROM content_chunks cc
            WHERE cc.embedding IS NOT NULL
            ORDER BY cc.embedding <=> $1::vector
            LIMIT 50
        ),
        keyword_ranked AS (
            SELECT p.slug AS page_slug, NULL::int AS chunk_index,
                   'compiled_truth' AS chunk_source,
                   LEFT(p.compiled_truth, 300) AS chunk_text,
                   ts_rank(p.search_vector, websearch_to_tsquery('english', $2)) AS kw_rank,
                   ROW_NUMBER() OVER (
                       ORDER BY ts_rank(p.search_vector, websearch_to_tsquery('english', $2)) DESC
                   ) AS krank
            FROM pages p
            WHERE p.search_vector @@ websearch_to_tsquery('english', $2)
            LIMIT 50
        ),
        rrf AS (
            SELECT page_slug, chunk_index, chunk_source, chunk_text,
                   COALESCE(cosine_sim, 0) AS cosine_sim,
                   (1.0 / (60 + COALESCE(vrank, 999))) + (1.0 / (60 + COALESCE(krank, 999))) AS rrf_score
            FROM vector_ranked
            FULL OUTER JOIN keyword_ranked USING (page_slug)
        )
        SELECT DISTINCT ON (page_slug)
            page_slug, chunk_index, chunk_source, chunk_text, cosine_sim, rrf_score
        FROM rrf
        ORDER BY page_slug, rrf_score DESC
        """
        rows = db.query(sql, [emb_literal, query_text])

        # Sort by RRF score descending
        rows.sort(key=lambda r: r.get("rrf_score", 0), reverse=True)
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

    # Dedup: cosine > 0.85 collapse (for vector results)
    if use_vectors:
        rows = _dedup_results(rows, threshold=0.85)

    # Display results
    if not rows:
        print("No results found.")
        return

    print(f"Found {len(rows)} results for: {query_text}\n")
    for i, row in enumerate(rows[:20]):
        slug = row.get("page_slug", "?")
        source = row.get("chunk_source", "?")
        score = row.get("rrf_score", row.get("score", 0))
        excerpt = (row.get("chunk_text", "") or "")[:200].replace("\n", " ")
        print(f"  [{i+1}] {slug} ({source}) score={score:.4f}")
        print(f"      {excerpt}...")
        print()


def cmd_verify(db: DbClient, vault_path: Path) -> None:
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
    """Insert or update a single page and its chunks/links/tags."""
    fm_json = json.dumps(page.frontmatter)

    # Upsert page
    db.execute(
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
    )

    # Replace chunks
    db.execute("DELETE FROM content_chunks WHERE page_slug = $1", [page.slug])
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
                db.execute(
                    """INSERT INTO content_chunks (page_slug, chunk_index, chunk_source, chunk_text, embedding)
                       VALUES ($1, $2, $3, $4, $5::vector)""",
                    [page.slug, chunk_index, source, text, emb_literal],
                )
            else:
                db.execute(
                    """INSERT INTO content_chunks (page_slug, chunk_index, chunk_source, chunk_text)
                       VALUES ($1, $2, $3, $4)""",
                    [page.slug, chunk_index, source, text],
                )
            chunk_index += 1

    # Replace links
    db.execute("DELETE FROM links WHERE from_slug = $1", [page.slug])
    for target in set(page.links):
        db.execute(
            "INSERT INTO links (from_slug, to_slug, link_type) VALUES ($1, $2, 'references')",
            [page.slug, target],
        )

    # Replace tags
    db.execute("DELETE FROM tags WHERE page_slug = $1", [page.slug])
    for tag in set(page.tags):
        db.execute(
            "INSERT INTO tags (page_slug, tag) VALUES ($1, $2)",
            [page.slug, tag],
        )


def _dedup_results(rows: list[dict], threshold: float = 0.85) -> list[dict]:
    """Remove near-duplicate results based on cosine similarity threshold.

    Layer 1: Best chunk per page (already done in SQL DISTINCT ON).
    Layer 2: Collapse pages with cosine_sim > threshold to the first seen.
    """
    if not rows:
        return rows

    seen_sims: list[float] = []
    deduped: list[dict] = []

    for row in rows:
        sim = row.get("cosine_sim", 0)
        if sim and any(abs(sim - s) < (1 - threshold) for s in seen_sims):
            continue
        seen_sims.append(sim or 0)
        deduped.append(row)

    return deduped


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
    p_rebuild.add_argument("--provider", default=None, help="Embedding provider: null, local, openai")

    p_sync = sub.add_parser("sync", help="Incremental sync")
    p_sync.add_argument("vault_path", type=Path, help="Path to vault directory")
    p_sync.add_argument("--provider", default=None, help="Embedding provider: null, local, openai")

    p_query = sub.add_parser("query", help="Hybrid search")
    p_query.add_argument("vault_path", type=Path, help="Path to vault directory")
    p_query.add_argument("query_text", help="Search query")
    p_query.add_argument("--provider", default=None, help="Embedding provider: null, local, openai")

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
            cmd_query(db, args.vault_path, provider, args.query_text)
        elif args.command == "verify":
            cmd_verify(db, args.vault_path)
    finally:
        db.close()


if __name__ == "__main__":
    main()
