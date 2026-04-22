# LLM Wiki Skill

[English](README.md) | [中文](README-cn.md)

An agent skill that builds and maintains an autonomous, self-compounding knowledge base inside an [Obsidian](https://obsidian.md) vault.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the idea that an LLM can maintain a persistent wiki where knowledge is pre-synthesized and cross-referenced, not re-queried from raw documents each time.

## What It Does

You feed it source documents — markdown, PDFs, Word docs, PowerPoint, spreadsheets, HTML, images, and more. The agent synthesizes them into interlinked wiki pages with `[[wikilinks]]`, tracks provenance, and maintains consistency through periodic linting.

**Three core operations:**

| Operation | What it does |
|-----------|-------------|
| **Ingest** | Process source documents into synthesized, cross-referenced wiki pages |
| **Query** | Search the wiki and synthesize answers with citations |
| **Lint** | Health check — find dead links, alias mismatches, orphans, stale content, contradictions |

**What makes the wiki compound:**

- Each source can generate multiple interlinked pages, not just one summary
- Queries can be filed back as wiki pages, becoming first-class knowledge
- New sources cross-reference with existing pages automatically
- The manifest tracks what's been processed, so nothing is re-done

## Vault Structure

```
my-wiki/
├── .obsidian/           # Obsidian recognizes this as a vault
├── raw/                 # Immutable source documents (the ground truth)
│   ├── extracted/       # MineRU-extracted markdown versions of binary sources
│   └── .manifest.json   # Tracks ingested sources with SHA-256 hashes
├── wiki/                # Synthesized knowledge pages (taxonomy emerges from content)
├── index.md             # Auto-maintained page catalog
├── log.md               # Append-only operation history
└── schema.md            # Wiki conventions and templates
```

## Example Use Cases

- **Enterprise design docs** — Ingest architecture documents, track decisions across services, automatically update linked references when a source changes
- **Research knowledge base** — Compile papers, notes, and transcripts into an interlinked wiki with provenance tracking
- **Project onboarding** — Build a wiki from existing docs so new team members can query synthesized knowledge instead of reading everything
- **Personal learning** — Ingest books, articles, and courses into a growing knowledge graph

## Features

- **Incremental diff-based re-ingestion** — When a source changes, diffs the old snapshot against the new version to identify exactly what changed, then updates only the affected wiki pages. Saves significant tokens at scale.
- **Cascading updates** — Changes propagate through the link graph: updated facts ripple to pages that cite them
- **Change detection** — Detects new/modified sources on conversation start and suggests re-ingestion
- **Delete and archive** — Full workflow for removing sources and handling derived pages
- **Provenance markers** — Claims are marked as extracted, inferred, or ambiguous using inline footnotes
- **Mass update safeguard** — Pauses for confirmation when modifying >10 existing pages
- **Obsidian-native** — Uses wikilinks, callouts, embeds, frontmatter, tags, and Graph View
- **Scaling guidance** — Strategies for 100+ sources / 500+ pages (index splitting, targeted lint, log rotation)
- **Session scoping** — Prevents infinite reprocessing loops across conversations
- **Optional MineRU integration** — Extract text from PDFs, DOCX, images, and more. Auto-detects OCR; `--ocr` / `--no-ocr` overrides, `--fast` CPU pipeline backend, `--start`/`--end` for page ranges
- **Periodic scanning** — Detect new, failed, or low-quality extractions; retry automatically
- **Link validation** — Detects alias mismatches (`[[alias]]` that should be `[[filename|alias]]`) and missing link targets. Auto-fix rewrites aliases to correct pipe syntax, preserving display text and heading anchors. Runs as post-ingest validation and during lint.
- **Compiled-truth + timeline page model** — Each page separates rewritable synthesis (compiled truth) from an append-only evidence trail (timeline), preventing knowledge drift over time
- **Typed links** — Frontmatter `links:` with semantic types (`references`, `contradicts`, `depends_on`, `supersedes`, `authored_by`, `works_at`, `mentions`) for graph queries
- **Hybrid retrieval** — Optional PGlite/Postgres index with vector + keyword search fused via reciprocal rank fusion (RRF). Configurable embedding providers (local, OpenAI-compatible, or any remote API)
- **Graph analysis** — NetworkX-powered graph operations: neighbors, shortest path, PageRank centrality, community detection, orphan finding
- **Attribute filtering** — Query pages by frontmatter attributes: `--where "type=concept tag=strategy confidence>=0.7"`
- **Multi-query expansion** — Generates query paraphrases via Anthropic or OpenAI-compatible chat APIs for better retrieval recall. Integrated into search with `--expand` (fast, averaged embedding) and `--expand-thorough` (multi-query RRF) flags
- **Pluggable storage backend** — `StorageBackend` protocol with file-first (default) and database-first implementations
- **Provider-agnostic API** — Embeddings and expansion work with any OpenAI-compatible or Anthropic-compatible endpoint via environment variables (`EMBEDDING_BASE_URL`, `EXPANSION_BASE_URL`, etc.)

## Installation

See [INSTALL.md](INSTALL.md) for detailed instructions for each agent platform (Claude Code, Codex CLI, Gemini CLI, Cursor, Windsurf, etc.).

**Quick start (Claude Code):**

```bash
# Clone into your global skills directory
git clone https://github.com/caohaotiantian/llm-wiki-skill.git
cp -r llm-wiki-skill/llm-wiki ~/.claude/skills/llm-wiki

# Or for project-scoped use
cp -r llm-wiki-skill/llm-wiki .claude/skills/llm-wiki
```

Then ask Claude: *"Set up a knowledge base wiki in ./my-wiki and ingest these docs"*

## Dependencies

**Required:**
- An AI coding agent that supports skills (Claude Code, Codex, Gemini CLI, etc.)
- Python 3.10+ with `pyyaml` — needed for all scripts (`pip install pyyaml`)
- Node.js 18+ with `@electric-sql/pglite` — for PGlite embedded Postgres (search index and DatabaseBackend)

**Recommended:**
- [`mineru`](https://github.com/opendatalab/mineru) — for high-quality document extraction (PDF, DOCX, images, and more). Install with `pip install "mineru[all]"`. Without it, the agent can still read files directly using its built-in capabilities.
- Obsidian — for graph view, search, and Dataview queries. The skill works without it (it's just markdown files), but Obsidian makes the wiki much more useful.

**Optional:**
- `sentence-transformers` — for local CPU-based embeddings (no API key needed)
- `networkx` — for graph analysis (centrality, communities, paths)
- Any OpenAI-compatible or Anthropic-compatible API — for remote embeddings and multi-query expansion. Configure via `EMBEDDING_BASE_URL` / `EXPANSION_BASE_URL` environment variables.

## Project Structure

```
llm-wiki-skill/
├── llm-wiki/                # The skill bundle (this is what you install)
│   ├── SKILL.md             # Main skill definition
│   ├── references/
│   │   ├── schema.md        # Page templates and frontmatter conventions
│   │   └── obsidian.md      # Obsidian operating reference (URI, CLI, markdown)
│   └── scripts/
│       ├── frontmatter.py   # Shared YAML frontmatter parser (PyYAML)
│       ├── db_ops.py        # Shared database operations for storage/index
│       ├── extract.py       # Document extraction (optional MineRU integration)
│       ├── scan.py          # Scan raw/ for new, failed, or low-quality extractions
│       ├── diff_sources.py  # Structured diff for incremental re-ingestion
│       ├── lint_links.py    # Wikilink validator + stale/unbalanced checks + referenced-by
│       ├── score_pages.py   # Composite page scoring
│       ├── chunking.py      # Recursive text chunking for index
│       ├── embeddings.py    # Provider-agnostic embedding interface
│       ├── index.py         # Hybrid search index (PGlite/Postgres)
│       ├── graph.py         # Graph analysis (NetworkX)
│       ├── query_filter.py  # Attribute-based page filtering
│       ├── expansion.py     # Multi-query expansion (Anthropic/OpenAI)
│       ├── storage.py       # Pluggable storage backend protocol
│       └── sidecar/         # PGlite Node.js HTTP sidecar
├── INSTALL.md               # Installation instructions for all agent platforms
├── LICENSE                  # MIT
└── README.md                # This file
```

## How This Differs from Karpathy's Gist

Karpathy's [original gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) describes the pattern at a high level — it's intentionally abstract and leaves implementation details to the user and their LLM. This project is a concrete, production-oriented implementation that adds several capabilities not covered in the gist or other community implementations (e.g. [Astro-Han/karpathy-llm-wiki](https://github.com/Astro-Han/karpathy-llm-wiki)):

| Capability | Karpathy's Gist | This Project |
|---|---|---|
| Document extraction (PDF, DOCX, images, ...) | User handles manually (e.g. Obsidian Web Clipper) | Built-in via [MineRU](https://github.com/opendatalab/mineru) |
| Change detection | Not covered | Periodic scanning + SHA-256 hash tracking in `.manifest.json` |
| Incremental re-ingestion | Not covered | Section-level structured diffs — only changed parts are reprocessed |
| Source-to-page dependency tracking | Not covered | `.manifest.json` maps each source to the wiki pages it produced |
| Mass update safeguard | Not covered | Pauses for confirmation when >10 existing pages would be modified |
| Session scoping | Not covered | Prevents infinite reprocessing loops across conversations |
| Page type taxonomy | Loosely mentioned | Five starter templates (concepts, entities, topics, sources, queries); taxonomy emerges from content |
| Provenance markers | Not covered | Inline footnotes: `^[extracted]`, `^[inferred]`, `^[ambiguous]` |
| Obsidian integration | Tips only | Full reference: URI scheme, CLI commands, vault config, plugins |
| Link validation | Not covered | Detects alias mismatches and missing pages; auto-fix with `--fix` |
| Hybrid retrieval | Not covered | Vector + keyword search with RRF fusion via PGlite/Postgres |
| Graph analysis | Not covered | PageRank, communities, shortest path, orphan detection |
| Knowledge model | Flat pages | Compiled-truth + timeline separation with staleness detection |
| Typed links | Not covered | Semantic link types in frontmatter for graph queries |

The gist also suggests features this project does not yet cover: varied output formats (Marp slide decks, matplotlib charts).

## What's New

**Extraction modes** — `extract.py` auto-detects whether OCR is needed (default); explicit overrides: `--no-ocr` (text-only, fastest), `--ocr` (force OCR on scanned docs), `--fast` (CPU pipeline backend), `--start`/`--end` (extract a page range).

**Document extraction** — Replaced Docling with [MineRU](https://github.com/opendatalab/mineru) for higher-quality extraction of PDFs, DOCX, and images. MineRU is invoked via CLI for minimal coupling. Install with `pip install "mineru[all]"`.

**Compiled-truth + timeline page model** — Each wiki page now separates rewritable synthesis (above the `---` separator) from an append-only evidence trail (below it), preventing knowledge drift over time.

**Typed links** — Frontmatter `links:` field supports semantic types (`references`, `contradicts`, `depends_on`, `supersedes`, `authored_by`, `works_at`, `mentions`) for structured graph queries.

**Hybrid retrieval** — New PGlite/Postgres-backed search index combining vector similarity and keyword search via reciprocal rank fusion (RRF). Supports `rebuild`, `sync`, `query`, and `verify` commands.

**Provider-agnostic embeddings** — Embedding and query expansion providers are fully configurable via environment variables. Works with local models (`sentence-transformers`), OpenAI-compatible APIs, or Anthropic APIs.

**Multi-query expansion** — Generates query paraphrases for better retrieval recall. Two modes: `--expand` (fast, averaged embedding) and `--expand-thorough` (multi-query RRF).

**Graph analysis** — NetworkX-powered graph layer with neighborhood traversal, shortest path, PageRank/betweenness centrality, Louvain community detection, orphan finding, and Cytoscape.js HTML export.

**Attribute filtering** — Query pages by frontmatter attributes: `--where "type=concept tag=strategy confidence>=0.7 updated_since=30d"`.

**Pluggable storage backend** — `StorageBackend` protocol with two implementations: `FileVaultBackend` (markdown files authoritative) and `DatabaseBackend` (database authoritative, markdown exported).

**Composite page scoring** — Five-indicator weighted formula (query hits, ingest freshness, edit recency, manual weight, cross-ref density) with scores stored in `.stats.json`.

**Shared frontmatter parser** — All scripts now use a unified `frontmatter.py` module backed by PyYAML, replacing 6 independent regex-based parsers.

**Link validation improvements** — `lint_links.py` now detects stale/unbalanced pages and injects `referenced-by` backlink blocks. Auto-fix rewrites alias mismatches to correct pipe syntax.

**Batch RPC** — PGlite sidecar supports transactional multi-statement execution via `/batch` endpoint.

## Credits

- [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — The LLM Wiki concept

## License

MIT
