#!/usr/bin/env python3
"""Pluggable storage backend for wiki operations.

Two implementations:
- FileVaultBackend: markdown files are authoritative, index is a derived cache (default)
- DatabaseBackend: database is authoritative, markdown is produced on export

Users choose at init time: init --backend file (default) or init --backend database.

Usage:
    python storage.py --backend file <vault-path> list-pages
    python storage.py --backend file <vault-path> get-page <slug>
    python storage.py --backend file <vault-path> search "query text"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Protocol, runtime_checkable

from frontmatter import parse as _parse_fm, parse_typed_links as _parse_typed_links_fm, atomic_write


@dataclass
class Page:
    """A wiki page."""
    slug: str
    type: str = "concept"
    title: str = ""
    compiled_truth: str = ""
    timeline: str = ""
    frontmatter: dict = field(default_factory=dict)
    content_hash: str = ""

    def to_markdown(self) -> str:
        """Serialize page to markdown with YAML frontmatter."""
        fm_lines = ["---"]
        # Write key frontmatter fields
        if self.title:
            fm_lines.append(f"title: {self.title}")
        if self.type:
            fm_lines.append(f"type: {self.type}")
        # Write remaining frontmatter
        skip = {"title", "type"}
        for k, v in self.frontmatter.items():
            if k in skip:
                continue
            if isinstance(v, list):
                fm_lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
            else:
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")

        parts = ["\n".join(fm_lines), ""]
        if self.title:
            parts.append(f"# {self.title}")
            parts.append("")
        if self.compiled_truth:
            parts.append(self.compiled_truth)
        if self.timeline:
            parts.append("")
            parts.append("---")
            parts.append("")
            parts.append(self.timeline)
        return "\n".join(parts) + "\n"


@dataclass
class Link:
    """A typed link between pages."""
    from_slug: str
    to_slug: str
    link_type: str = "references"


@dataclass
class SearchHit:
    """A search result."""
    page_slug: str
    chunk_text: str = ""
    score: float = 0.0
    source: str = ""  # "compiled_truth" or "timeline"
    stale: bool = False


@dataclass
class SyncReport:
    """Result of a sync operation."""
    added: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0


@runtime_checkable
class StorageBackend(Protocol):
    """Storage backend interface."""
    def init(self, vault_path: Path) -> None: ...
    def get_page(self, slug: str) -> Page | None: ...
    def put_page(self, page: Page) -> None: ...
    def delete_page(self, slug: str) -> None: ...
    def list_pages(self, where: dict | None = None) -> list[Page]: ...
    def add_link(self, from_slug: str, to_slug: str, link_type: str) -> None: ...
    def get_backlinks(self, slug: str) -> list[Link]: ...
    def search_keyword(self, query: str, limit: int = 10) -> list[SearchHit]: ...
    def search_hybrid(self, query: str, embedding: list[float] | None = None, limit: int = 10) -> list[SearchHit]: ...
    def export_markdown(self, destination: Path) -> int: ...
    def sync(self) -> SyncReport: ...


def _compute_content_hash(content: str) -> str:
    """SHA-256 hash of page content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from markdown content (backward-compat wrapper)."""
    fm, _ = _parse_fm(content)
    return fm


def _parse_typed_links(content: str) -> list[dict]:
    """Parse typed links from markdown content (backward-compat wrapper)."""
    fm, _ = _parse_fm(content)
    return _parse_typed_links_fm(fm)






def _parse_page_from_markdown(slug: str, content: str) -> Page:
    """Parse a markdown file into a Page object."""
    frontmatter, _body = _parse_fm(content)

    # Extract title from first heading
    title = frontmatter.get("title", "")
    if not title:
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

    page_type = frontmatter.get("type", "")
    if not page_type:
        tags = frontmatter.get("tags", [])
        if isinstance(tags, list) and tags:
            page_type = tags[0]
        elif isinstance(tags, str):
            page_type = tags

    # Split compiled truth from timeline
    body = _body
    parts = re.split(r"\n---\s*\n", body, maxsplit=1)
    compiled_truth = parts[0].strip()
    timeline = parts[1].strip() if len(parts) > 1 else ""

    # Strip leading heading if it matches the title (avoid duplicate on round-trip)
    if title and compiled_truth.startswith(f"# {title}"):
        compiled_truth = compiled_truth[len(f"# {title}"):].strip()

    # Parse typed links from frontmatter
    typed_links = _parse_typed_links_fm(frontmatter)
    if typed_links:
        frontmatter["links"] = typed_links

    return Page(
        slug=slug,
        type=page_type or "concept",
        title=title,
        compiled_truth=compiled_truth,
        timeline=timeline,
        frontmatter=frontmatter,
        content_hash=_compute_content_hash(content),
    )


class FileVaultBackend:
    """File-first backend: markdown files are authoritative.

    The index (if present) is a derived cache. On conflict, files win.
    """

    def __init__(self):
        self._vault_path: Path | None = None
        self._pages: dict[str, Page] = {}  # slug -> Page cache

    def init(self, vault_path: Path) -> None:
        self._vault_path = Path(vault_path)
        self._scan_wiki()

    def _scan_wiki(self) -> None:
        """Scan wiki/ directory and load all pages into cache."""
        self._pages.clear()
        wiki_dir = self._vault_path / "wiki"
        if not wiki_dir.is_dir():
            return
        for root, dirs, files in os.walk(str(wiki_dir)):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".md") or fname.endswith(".snapshot.md"):
                    continue
                full = os.path.join(root, fname)
                slug = os.path.splitext(fname)[0]
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    self._pages[slug] = _parse_page_from_markdown(slug, content)
                except OSError:
                    continue

    def get_page(self, slug: str) -> Page | None:
        return self._pages.get(slug)

    def put_page(self, page: Page) -> None:
        if self._vault_path is None:
            raise RuntimeError("Backend not initialized")
        # Write markdown file
        wiki_dir = self._vault_path / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        file_path = wiki_dir / f"{page.slug}.md"
        md = page.to_markdown()
        atomic_write(file_path, md)
        page.content_hash = _compute_content_hash(md)
        self._pages[page.slug] = page

    def delete_page(self, slug: str) -> None:
        if self._vault_path is None:
            raise RuntimeError("Backend not initialized")
        wiki_dir = self._vault_path / "wiki"
        file_path = wiki_dir / f"{slug}.md"
        if file_path.exists():
            file_path.unlink()
        self._pages.pop(slug, None)

    def list_pages(self, where: dict | None = None) -> list[Page]:
        pages = list(self._pages.values())
        if where:
            filtered = []
            for page in pages:
                match = True
                for key, val in where.items():
                    if key == "type":
                        if page.type != val:
                            match = False
                    elif key == "tag":
                        tags = page.frontmatter.get("tags", [])
                        if isinstance(tags, str):
                            tags = [tags]
                        if val not in tags:
                            match = False
                    else:
                        if page.frontmatter.get(key) != val:
                            match = False
                if match:
                    filtered.append(page)
            return filtered
        return pages

    def add_link(self, from_slug: str, to_slug: str, link_type: str) -> None:
        page = self._pages.get(from_slug)
        if not page:
            return
        links = page.frontmatter.get("links", [])
        if not isinstance(links, list):
            links = []
        # Don't add duplicate
        for link in links:
            if isinstance(link, dict) and link.get("target") == to_slug and link.get("type") == link_type:
                return
        links.append({"target": to_slug, "type": link_type})
        page.frontmatter["links"] = links

    def get_backlinks(self, slug: str) -> list[Link]:
        backlinks = []
        for page in self._pages.values():
            links = page.frontmatter.get("links", [])
            if not isinstance(links, list):
                continue
            for link in links:
                if isinstance(link, dict) and link.get("target") == slug:
                    backlinks.append(Link(
                        from_slug=page.slug,
                        to_slug=slug,
                        link_type=link.get("type", "references"),
                    ))
        return backlinks

    def search_keyword(self, query: str, limit: int = 10) -> list[SearchHit]:
        """Simple keyword search over page content."""
        query_lower = query.lower()
        terms = query_lower.split()
        hits = []
        for page in self._pages.values():
            full_text = f"{page.title} {page.compiled_truth} {page.timeline}".lower()
            score = sum(1 for term in terms if term in full_text)
            if score > 0:
                # Find best matching excerpt
                excerpt = ""
                for line in (page.compiled_truth + "\n" + page.timeline).split("\n"):
                    if any(term in line.lower() for term in terms):
                        excerpt = line.strip()[:200]
                        break
                hits.append(SearchHit(
                    page_slug=page.slug,
                    chunk_text=excerpt,
                    score=score / len(terms),
                    source="compiled_truth",
                ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def search_hybrid(self, query: str, embedding: list[float] | None = None, limit: int = 10) -> list[SearchHit]:
        """Hybrid search. Without DB, falls back to keyword search."""
        return self.search_keyword(query, limit)

    def export_markdown(self, destination: Path) -> int:
        """Export all pages to markdown files."""
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        count = 0
        for page in self._pages.values():
            file_path = destination / f"{page.slug}.md"
            atomic_write(file_path, page.to_markdown())
            count += 1
        return count

    def sync(self) -> SyncReport:
        """Re-scan wiki/ and detect changes."""
        old_hashes = {slug: page.content_hash for slug, page in self._pages.items()}
        self._scan_wiki()
        new_hashes = {slug: page.content_hash for slug, page in self._pages.items()}

        added = len(set(new_hashes) - set(old_hashes))
        deleted = len(set(old_hashes) - set(new_hashes))
        updated = sum(
            1 for slug in set(old_hashes) & set(new_hashes)
            if old_hashes[slug] != new_hashes[slug]
        )
        unchanged = len(set(old_hashes) & set(new_hashes)) - updated

        return SyncReport(added=added, updated=updated, deleted=deleted, unchanged=unchanged)


class DatabaseBackend:
    """Database-first backend: PGlite/Postgres is authoritative.

    Markdown is produced on demand via export_markdown().
    Requires a running database (PGlite sidecar or native Postgres).

    Constructor accepts either:
      - A ``db`` object with ``.query()`` and ``.execute()`` methods
        (for direct use / testing).
      - A ``db_url`` string (Postgres connection or sidecar URL) which
        will be connected lazily on ``init()``.
    """

    def __init__(self, db=None, db_url: str | None = None):
        self._db = db
        self._db_url = db_url
        self._vault_path: Path | None = None

    # -- helpers -----------------------------------------------------------

    def _ensure_db(self):
        if self._db is None:
            raise RuntimeError(
                "DatabaseBackend not initialised — call init() first or "
                "pass a db object to the constructor."
            )

    @staticmethod
    def _row_to_page(row: dict) -> Page:
        """Convert a DB row dict to a Page dataclass."""
        fm = row.get("frontmatter") or {}
        if isinstance(fm, str):
            try:
                fm = json.loads(fm)
            except (ValueError, TypeError):
                fm = {}
        return Page(
            slug=row["slug"],
            type=row.get("type", "concept"),
            title=row.get("title", ""),
            compiled_truth=row.get("compiled_truth", ""),
            timeline=row.get("timeline", ""),
            frontmatter=fm,
            content_hash=row.get("content_hash", ""),
        )

    # -- StorageBackend interface ------------------------------------------

    def init(self, vault_path: Path) -> None:
        self._vault_path = Path(vault_path)
        if self._db is None and self._db_url:
            from index import DbClient
            self._db = DbClient(database_url=self._db_url)
        if self._db is None:
            # Try environment-based auto-detection (same as index.py)
            try:
                from index import get_db_client
                self._db = get_db_client()
            except Exception:
                pass  # Will fail on first use via _ensure_db

    def get_page(self, slug: str) -> Page | None:
        self._ensure_db()
        from db_ops import get_page_row
        row = get_page_row(self._db, slug)
        if not row:
            return None
        return self._row_to_page(row)

    def put_page(self, page: Page) -> None:
        self._ensure_db()
        from db_ops import upsert_page_row, delete_links_from, add_link_row, replace_tags
        content_hash = page.content_hash or _compute_content_hash(page.to_markdown())
        upsert_page_row(
            self._db,
            slug=page.slug,
            page_type=page.type,
            title=page.title,
            compiled_truth=page.compiled_truth,
            timeline=page.timeline,
            frontmatter=page.frontmatter,
            content_hash=content_hash,
        )
        # Sync typed links from frontmatter
        links = page.frontmatter.get("links", [])
        if isinstance(links, list):
            delete_links_from(self._db, page.slug)
            for link in links:
                if isinstance(link, dict):
                    add_link_row(
                        self._db,
                        page.slug,
                        link.get("target", ""),
                        link.get("type", "references"),
                    )
        # Sync tags
        tags = page.frontmatter.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if isinstance(tags, list):
            replace_tags(self._db, page.slug, tags)

    def delete_page(self, slug: str) -> None:
        self._ensure_db()
        from db_ops import delete_page_row
        delete_page_row(self._db, slug)

    def list_pages(self, where: dict | None = None) -> list[Page]:
        self._ensure_db()
        from db_ops import list_page_rows
        rows = list_page_rows(self._db, where)
        return [self._row_to_page(r) for r in rows]

    def add_link(self, from_slug: str, to_slug: str, link_type: str) -> None:
        self._ensure_db()
        from db_ops import add_link_row
        add_link_row(self._db, from_slug, to_slug, link_type)

    def get_backlinks(self, slug: str) -> list[Link]:
        self._ensure_db()
        from db_ops import get_backlink_rows
        rows = get_backlink_rows(self._db, slug)
        return [
            Link(
                from_slug=r["from_slug"],
                to_slug=r["to_slug"],
                link_type=r.get("link_type", "references"),
            )
            for r in rows
        ]

    def search_keyword(self, query: str, limit: int = 10) -> list[SearchHit]:
        self._ensure_db()
        from db_ops import search_keyword_rows
        rows = search_keyword_rows(self._db, query, limit)
        return [
            SearchHit(
                page_slug=r.get("page_slug", ""),
                chunk_text=r.get("chunk_text", ""),
                score=float(r.get("score", 0)),
                source=r.get("chunk_source", ""),
            )
            for r in rows
        ]

    def search_hybrid(self, query: str, embedding: list[float] | None = None, limit: int = 10) -> list[SearchHit]:
        self._ensure_db()
        if embedding is None:
            return self.search_keyword(query, limit)
        from db_ops import search_hybrid_rows
        rows = search_hybrid_rows(self._db, query, embedding, limit)
        return [
            SearchHit(
                page_slug=r.get("page_slug", ""),
                chunk_text=r.get("chunk_text", ""),
                score=float(r.get("score", 0)),
                source=r.get("chunk_source", ""),
            )
            for r in rows
        ]

    def export_markdown(self, destination: Path) -> int:
        self._ensure_db()
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        pages = self.list_pages()
        count = 0
        for page in pages:
            file_path = destination / f"{page.slug}.md"
            atomic_write(file_path, page.to_markdown())
            count += 1
        return count

    def sync(self) -> SyncReport:
        """Sync filesystem wiki/ pages into the database.

        Scans wiki/ for markdown files, upserts changed pages, and
        removes DB rows for pages no longer on disk.
        """
        self._ensure_db()
        from db_ops import get_page_row, upsert_page_row, delete_page_row, delete_links_from, add_link_row, replace_tags

        if self._vault_path is None:
            raise RuntimeError("Backend not initialized")

        wiki_dir = self._vault_path / "wiki"
        if not wiki_dir.is_dir():
            return SyncReport()

        # Gather current DB hashes
        existing_rows = self._db.query("SELECT slug, content_hash FROM pages")
        existing = {r["slug"]: r["content_hash"] for r in existing_rows}

        added = 0
        updated = 0
        unchanged = 0

        # Walk filesystem
        disk_slugs: set[str] = set()
        for root, dirs, files in os.walk(str(wiki_dir)):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".md") or fname.endswith(".snapshot.md"):
                    continue
                full = os.path.join(root, fname)
                slug = os.path.splitext(fname)[0]
                disk_slugs.add(slug)
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except OSError:
                    continue
                page = _parse_page_from_markdown(slug, content)
                new_hash = _compute_content_hash(content)
                if existing.get(slug) == new_hash:
                    unchanged += 1
                    continue
                upsert_page_row(
                    self._db,
                    slug=page.slug,
                    page_type=page.type,
                    title=page.title,
                    compiled_truth=page.compiled_truth,
                    timeline=page.timeline,
                    frontmatter=page.frontmatter,
                    content_hash=new_hash,
                )
                # Sync links
                links = page.frontmatter.get("links", [])
                if isinstance(links, list):
                    delete_links_from(self._db, slug)
                    for link in links:
                        if isinstance(link, dict):
                            add_link_row(
                                self._db, slug,
                                link.get("target", ""),
                                link.get("type", "references"),
                            )
                # Sync tags
                tags = page.frontmatter.get("tags", [])
                if isinstance(tags, str):
                    tags = [tags]
                if isinstance(tags, list):
                    replace_tags(self._db, slug, tags)

                if slug in existing:
                    updated += 1
                else:
                    added += 1

        # Delete DB rows not on disk
        deleted = 0
        for slug in existing:
            if slug not in disk_slugs:
                delete_page_row(self._db, slug)
                deleted += 1

        return SyncReport(added=added, updated=updated, deleted=deleted, unchanged=unchanged)


def get_backend(backend_name: str = "file", **kwargs) -> StorageBackend:
    """Get a storage backend by name.

    Args:
        backend_name: "file" (default) or "database"
        **kwargs: Passed to the backend constructor.
            For DatabaseBackend: ``db`` (object) or ``db_url`` (str).
    """
    if backend_name == "file":
        return FileVaultBackend()
    elif backend_name == "database":
        return DatabaseBackend(**kwargs)
    else:
        raise ValueError(f"Unknown backend: {backend_name}")


def main():
    parser = argparse.ArgumentParser(description="Storage backend CLI.")
    parser.add_argument("vault_path", help="Path to the wiki vault")
    parser.add_argument("--backend", default="file", choices=["file", "database"],
                        help="Storage backend (default: file)")
    parser.add_argument("--json", dest="json_output", action="store_true")

    sub = parser.add_subparsers(dest="command")

    list_cmd = sub.add_parser("list-pages", help="List all pages")
    list_cmd.add_argument("--type", default=None, help="Filter by type")

    get_cmd = sub.add_parser("get-page", help="Get a page by slug")
    get_cmd.add_argument("slug", help="Page slug")

    search_cmd = sub.add_parser("search", help="Search pages")
    search_cmd.add_argument("query", help="Search query")
    search_cmd.add_argument("--limit", type=int, default=10)

    sub.add_parser("sync", help="Sync with filesystem")

    export_cmd = sub.add_parser("export", help="Export to markdown")
    export_cmd.add_argument("destination", help="Export destination directory")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    backend = get_backend(args.backend)
    backend.init(Path(args.vault_path))

    if args.command == "list-pages":
        where = {"type": args.type} if args.type else None
        pages = backend.list_pages(where)
        if args.json_output:
            from frontmatter import json_default
            print(json.dumps([asdict(p) for p in pages], indent=2, default=json_default))
        else:
            for p in pages:
                print(f"  {p.slug}  [{p.type}]  {p.title}")

    elif args.command == "get-page":
        page = backend.get_page(args.slug)
        if page:
            if args.json_output:
                from frontmatter import json_default
                print(json.dumps(asdict(page), indent=2, default=json_default))
            else:
                print(page.to_markdown())
        else:
            print(f"Page not found: {args.slug}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "search":
        hits = backend.search_keyword(args.query, args.limit)
        if args.json_output:
            print(json.dumps([asdict(h) for h in hits], indent=2))
        else:
            for h in hits:
                print(f"  {h.score:.2f}  {h.page_slug}  {h.chunk_text[:80]}...")

    elif args.command == "sync":
        report = backend.sync()
        if args.json_output:
            print(json.dumps(asdict(report), indent=2))
        else:
            print(f"Sync: +{report.added} ~{report.updated} -{report.deleted} ={report.unchanged}")

    elif args.command == "export":
        count = backend.export_markdown(Path(args.destination))
        print(f"Exported {count} pages to {args.destination}")


if __name__ == "__main__":
    main()
