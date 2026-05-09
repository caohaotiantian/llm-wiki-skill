---
name: llm-wiki
description: >
  Build, maintain, and query an autonomous wiki knowledge base inside an Obsidian vault.
  Trigger when the user wants to: set up a new wiki vault, ingest source documents into
  wiki pages, query compiled wiki knowledge with citations, lint wiki pages for broken
  links or stale content, manage wiki page scores, or rebuild the wiki search index.
  Trigger phrases: "set up wiki vault", "ingest into wiki", "query the wiki",
  "lint wiki links", "wiki knowledge base", "score wiki pages", "rebuild wiki index".
  Do NOT trigger for: general Wikipedia references, markdown syntax questions,
  or knowledge management discussions that don't involve an Obsidian vault.
---

# LLM Wiki

An autonomous, self-compounding knowledge base in an Obsidian vault. You ingest raw sources (articles, PDFs, code, docs), synthesize them into interlinked wiki pages with `[[wikilinks]]`, and periodic linting keeps everything consistent. Knowledge is pre-synthesized and cross-referenced — not re-queried from raw documents each time.

The human sources material and asks questions. You handle summarizing, cross-referencing, filing, and bookkeeping.

## Core Concepts

Three layers: Raw Sources (immutable inputs) → Wiki Pages (synthesized knowledge) → Index/Schema (coordination files).

Three operations: Ingest (source → pages), Query (search → answer), Lint (health checks).

---

## Setup

When the user asks to set up a new wiki:

1. **Ask language preference** — store in `.manifest.json` as `"language": "<code>"` (e.g. `"zh-CN"`, `"en"`). All wiki content uses this language; technical terms and proper nouns stay in their original language. Default to the user's current language if unspecified.

2. **Check dependencies** — verify required and optional packages:
   ```python
   python3 -c "import yaml; print('Python OK')"
   ```
   ```bash
   node -e "console.log('Node.js OK')"
   ```
   `pyyaml` and Node.js 18+ are required. `mineru` is optional (document extraction). Ask before installing into a venv:
   ```bash
   python3 -m venv <vault-path>/.venv
   <vault-path>/.venv/bin/pip install pyyaml "mineru[all]"
   ```

3. **Create vault structure:**
   ```
   <vault-root>/
   ├── .obsidian/app.json       # Minimal Obsidian config
   ├── raw/                     # Immutable source documents
   │   └── .manifest.json       # Source tracking (hash, pages, language)
   ├── wiki/                    # Synthesized knowledge pages
   ├── index.md                 # Page catalog by category
   ├── log.md                   # Append-only operation history
   ├── schema.md                # Copy from references/schema.md
   └── .stats.json              # Page scoring counters
   ```

4. **Initialize files** — create `index.md`, `log.md`, `schema.md` (from `references/schema.md`), `.manifest.json`, `.stats.json` with their initial content (see Coordination Files section for schemas).

5. **Start PGlite sidecar** — required for search index and DatabaseBackend:
   ```bash
   node <skill-dir>/scripts/sidecar/server.js --data-dir <vault-path>/index
   ```
   This auto-initializes the schema on first run. Listens on port 5488 by default.

6. **Build the search index:**
   ```bash
   python <skill-dir>/scripts/index.py rebuild <vault-path>
   ```

7. **Register with Obsidian** (if installed): `open "obsidian://open?path=<vault-path>"`

8. **Gitignore** the vault directory if inside a tracked repo.

The subdirectories under both `raw/` and `wiki/` are **not prescribed** — they emerge from the content. The agent discovers files by scanning recursively. Common patterns include `concepts/`, `entities/`, `topics/`, `sources/`, `queries/` — but let the content dictate the taxonomy.

---

## Page Model

### Compiled Truth + Timeline

Every wiki page has two zones separated by `---`:

- **Above:** Compiled truth — current best understanding. Rewrite when new evidence changes the picture.
- **Below:** Timeline — append-only evidence trail (newest first). Never edit, only extend.

See `references/schema.md` for full templates and examples.

### Footnote Citations (v2 page format)

The compiled-truth zone uses Obsidian reference footnotes `[^id]` for per-sentence citations: each factual sentence ends with one or more `[^id]` refs that bind the claim to its source. Per-sentence footnote citations make compiled truth verifiable without re-reading the timeline.

Footnote definitions take the form `[^id]: …` and live at the bottom of the file, after the timeline (i.e., end of the page). Keeping every footnote definition at the bottom of the file gives Obsidian a single, predictable definition pool per page.

Footnote IDs are page-local and derived from the citation target (e.g., a citation pointing at `[[raw/articles/fowler-microservices]]` uses `[^fowler-microservices]`). IDs colliding across different targets with the same basename are disambiguated with `-2`, `-3` suffixes in document order.

Inline `^[inferred]` / `^[ambiguous]` confidence markers (Obsidian's *inline* footnote form, syntactically distinct from `[^id]`) are replaced by two frontmatter list fields, `claims_inferred:` and `claims_ambiguous:`, on v2 pages. See `references/schema.md` for the full template.

### Format Versioning

A page is treated as v2 if and only if its frontmatter contains `format_version: 2` parsed as the integer literal `2`. Absence of the key, a string `"2"`, a float `2.1`, or any other value is treated as legacy. Legacy pages keep their current format (free-form prose with inline `[[wikilinks]]` and inline `^[inferred]` markers) until migrated by `lint_links.py --fix`, which is opportunistic: a legacy page receiving `--fix` for any reason gets its compiled-truth wikilinks rewritten as footnote refs `[^id]`, its inline confidence markers moved into frontmatter, and `format_version: 2` added. Migration is idempotent — running `--fix` on a v2 page is a no-op.

The four lint rules that apply only on v2 pages: every `[^id]` ref has a matching `[^id]:` definition (L-1); every `[^id]:` definition is referenced at least once, with warning severity (L-2); footnote IDs are unique within the page (L-3); all footnote definitions sit after the last timeline line (L-4).

### Frontmatter

```yaml
---
aliases: []
tags: []
sources:
  - "[[raw/articles/source-name]]"
links:
  - {target: "page-slug", type: "references"}
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active       # active | stub | needs-review | archived
weight: 0            # additive score boost (optional)
format_version: 2    # signals v2 footnote-citation format; absent or non-int-2 = legacy
claims_inferred: []  # v2: claim snippets previously marked ^[inferred] in body
claims_ambiguous: [] # v2: claim snippets previously marked ^[ambiguous] in body
---
```

### Typed Links

Declare relationships in frontmatter `links:` — this is the authoritative edge set for graph queries. Wikilinks in prose are for readability.

Types: `references`, `contradicts`, `depends_on`, `supersedes`, `authored_by`, `works_at`, `mentions`. Extensible.

### Linking Rules

- Link target MUST be the exact filename without `.md`: `[[artificial-intelligence]]`
- Display text uses pipe syntax: `[[artificial-intelligence|AI]]`
- Never write bare `[[alias]]` — Obsidian does not resolve aliases in link targets
- See `references/obsidian.md` → "Wikilink Resolution Rules"

### Provenance Markers

- No marker = extracted from source
- `^[inferred]` = LLM-synthesized
- `^[ambiguous]` = sources disagree
- Frontmatter `status` is page-level; inline footnotes are claim-level. Both are complementary.

---

## Ingest

When the user provides source material (files, URLs, pasted text):

### Step 1: Accept and store the source

- **Local files**: Place anywhere inside `raw/` (flat or subdirectories)
- **URLs**: Fetch and save as `raw/<domain>-<slug>.md` with `source_url` in frontmatter
- **Pasted text**: Save to `raw/YYYY-MM-DD-<brief-slug>.md`
- **Binary files** (PDF, DOCX, PPTX, XLSX, images, HTML): Extract first, then ingest the extracted markdown. Two approaches:

  **MineRU extraction** (recommended for complex documents):
  ```bash
  python <skill-dir>/scripts/extract.py <input-file>                    # auto-detect OCR need
  python <skill-dir>/scripts/extract.py --no-ocr <input-file>           # text-only, skip OCR (fastest)
  python <skill-dir>/scripts/extract.py --ocr <input-file>              # force OCR (scanned docs)
  python <skill-dir>/scripts/extract.py --fast <input-file>             # pipeline backend (CPU, faster)
  python <skill-dir>/scripts/extract.py --start 0 --end 10 <input-file> # page range only
  python <skill-dir>/scripts/extract.py <input-dir>                     # batch every file in dir (one mineru call)
  ```
  Record `extraction_method` in manifest: `mineru +ocr`, `mineru +txt`, `mineru`, or `fallback`.

  **Agent direct reading** (fallback):
  Read the file directly using your built-in file reading. Record `extraction_method: agent` in manifest (no `extracted` field). Works well for short, clean documents. Less reliable for scanned pages, complex tables, or large files.

- **Save a snapshot** for diff-based re-ingestion: `<source-path>.snapshot.md` (or `<extracted-path>.snapshot.md` for binaries)

### Step 2: Read and understand

- Read the source thoroughly
- Identify key concepts, entities, relationships, claims, open questions
- Check `index.md` for relevant existing pages

### Step 3: Compile into wiki pages

- **Existing page**: Update with new information. Merge, don't duplicate.
- **New topic**: Create using templates from `schema.md`
- Follow the page model (compiled truth + timeline, typed links, provenance markers)
- Every page gets a one-sentence summary lead

### Step 4: Cross-link and verify

- Use `[[wikilinks]]` for all references. Targets must be exact filenames.
- Scan existing pages for mentions of new concepts — add links there too
- Every page must be reachable from at least one other page
- For each unresolvable link target, create a stub:

```markdown
---
aliases: []
tags: [concept]
sources: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: stub
---
# Page Title
> [!todo] Stub
> Auto-created — expand when source material is available.
## Referenced from
- [[page-that-linked-here]]
```

Set the `tags` value to whichever type fits the context (`concept`, `entity`, `topic`, etc.).

### Step 5: Update coordination files

- **`index.md`**: Add/update entries for new/modified pages
- **`.manifest.json`**: Record source path, SHA-256, timestamp, pages created/updated
- **`log.md`**: Defer until after validation (Step 6)

### Step 6: Validate links

```bash
python <skill-dir>/scripts/lint_links.py <vault-path> --files <pages...> --json
```

- **`alias_mismatches`**: Run again with `--fix` to rewrite `[[alias]]` → `[[filename|alias]]`
- **`missing`**: Create stubs (Step 4 template), re-run to confirm resolution
- Append to `log.md` only after validation passes (`clean: true` in JSON output)

Note: `--fix` with `--files` only repairs links in the specified files. For a complete vault-wide fix, run without `--files`.

### Step 7: Update page scores

```bash
python <skill-dir>/scripts/score_pages.py <vault-path> --pages <pages...> --json
```

Also increment `access_count` in `.stats.json` for every existing page read during cross-linking in Steps 3–4. Use a single read-modify-write cycle to avoid partial updates.

### Batch ingestion

Process multiple sources in a single pass to maximize cross-referencing. Read all sources first, then compile pages that synthesize across them.

### Mass update safeguard

If an ingest would modify more than 10 existing pages, pause and list affected pages for user confirmation. Does not apply to creating new pages.

---

## Query

When the user asks a question about the wiki's knowledge:

### Step 1: Search (with optional expansion)

**If the index is available** (PGlite or Postgres running):

```bash
python <skill-dir>/scripts/index.py query <vault-path> "query text" --json
python <skill-dir>/scripts/index.py query <vault-path> "query text" --expand --json
python <skill-dir>/scripts/index.py query <vault-path> "query text" --expand-thorough --json
```

This combines vector similarity + keyword search via reciprocal rank fusion (RRF). Results include chunk excerpts and scores. `--expand` generates paraphrases and averages their embeddings for a single fast search. `--expand-thorough` runs separate searches per paraphrase and fuses results (slower, better recall). Both require an expansion API (see Query Expansion in Supporting Tools).

**Narrow with attribute filters:**

```bash
python <skill-dir>/scripts/query_filter.py <vault-path> --where "type=concept tag=strategy" --json
```

Filter syntax: `type=concept`, `tag=X`, `confidence>=0.7`, `updated_since=30d`, `has=field`, and comparison operators `=`, `!=`, `>`, `<`, `>=`, `<=`.

**If no index is available:** Fall back to reading `index.md` and using grep/glob.

### Step 2: Rank and retrieve

Sort candidates by `computed_score` descending (from frontmatter). Read the highest-scored pages first.

### Step 3: Synthesize

Answer using the wiki's compiled knowledge. When multiple pages cover the same topic, weight higher-scored pages more. Format the response using footnote citations: each factual sentence in the answer ends with one or more `[^id]` refs that cite the source page or raw document, and a block of `[^id]: …` footnote definitions is listed at the end of the response. This mirrors the v2 page model — the response is itself a small footnote-cited document. Higher-scored sources should still be listed first inside the definition block.

Example of the expected response shape:

```markdown
## Answer
The transformer architecture replaces RNNs with self-attention[^attention-paper].
Training cost was approximately $4.6M, though estimates vary[^cost-survey].

[^attention-paper]: [[raw/articles/vaswani-attention]]
[^cost-survey]: [[raw/reports/training-cost-2024]]
```

### Step 4: Update counters

- Increment `access_count` in `.stats.json` for every page **read**
- Increment `query_count` in `.stats.json` for every page **cited in the answer**

### Step 5: File the answer (conditional)

Save as a page under `wiki/queries/` if the answer synthesizes across 3+ pages or reveals a non-obvious connection. Don't file simple lookups. Ask the user if borderline.

### Query output format

The full response wraps the footnoted answer (Step 3) with an optional "Sources consulted" appendix that explains *why* each cited page was relevant — useful when the response synthesizes across many pages.

```markdown
## Answer
[Synthesized answer; each factual sentence ends with one or more [^id] refs.]

[^id-1]: [[wiki/concepts/concept-a]]
[^id-2]: [[wiki/entities/entity-b]]

### Sources consulted
- [[wiki/concepts/concept-a]] — relevant because X
- [[wiki/entities/entity-b]] — mentioned Y
```

---

## Lint

Run periodically or when the user asks. Linting ensures wiki health.

### Automated checks

These are script-backed and produce structured output:

| Check | Command | Auto-fixable? |
|-------|---------|---------------|
| **Dead links** (alias mismatches + missing targets) | `lint_links.py <vault> --json` | Yes (`--fix` for aliases, stubs for missing) |
| **Stale pages** (timeline newer than compiled truth) | `lint_links.py <vault> --stale` | No — flag for rewrite |
| **Unbalanced pages** (5+ timeline entries since last rewrite) | `lint_links.py <vault> --unbalanced` | No — flag for review |
| **Orphaned pages** | `graph.py <vault> orphans` | No — add links or archive |
| **Score staleness** | `score_pages.py <vault> --json` | Yes — full recalc |

### Agent judgment checks

These require reading pages — no script automation:

| Check | What to look for |
|-------|-----------------|
| **Missing cross-refs** | Pages that mention concepts without linking them |
| **Index drift** | Pages that exist but aren't in `index.md` |
| **Duplicate concepts** | Multiple pages covering the same topic |
| **Empty sections** | Placeholder sections never filled |
| **Frontmatter issues** | Missing required fields, outdated timestamps |
| **Schema drift** | Pages using outdated frontmatter (missing fields, deprecated tags) |

### Dead link resolution (two-phase)

**Phase 1 — Alias mismatches:** Run `lint_links.py <vault> --fix` to auto-rewrite `[[alias]]` → `[[filename|alias]]`.

**Phase 2 — Stub creation:** Create stub pages for remaining missing targets (use the stub template from Ingest Step 4).

Always run Phase 1 before Phase 2 — some "missing pages" are actually alias mismatches.

### Score recalculation

Run a full scoring recalc as part of every lint:

```bash
python <skill-dir>/scripts/score_pages.py <vault-path> --json
```

Include in the lint report: top 10 pages by score, pages with zero activity.

### Lint report

Save to `wiki/lint-YYYY-MM-DD.md`:

```markdown
# Lint Report — YYYY-MM-DD

## Summary
- X issues found, Y auto-fixed, Z need attention

## Auto-fixed
- Rewrote N alias mismatches
- Added stubs for M missing targets
- Recalculated all page scores

## Needs Attention
- [[concept-a]] stale — 3 new timeline entries since last rewrite
- [[entity-x]] orphaned — no incoming links
- [[concept-b]] and [[concept-c]] may be duplicates — consider merging
```

Append summary to `log.md`.

---

## Change Detection

### Auto-ingest (on conversation start)

When the wiki is in scope, scan for changes and ingest automatically:

1. **Scan:**
   ```bash
   python <skill-dir>/scripts/scan.py <vault-path> --json
   ```
   Detects: new files not in manifest, modified sources (hash mismatch), failed extractions (extracted file missing), low-quality extractions (<1% size ratio or <50 bytes).

2. **New files** → extract (if binary) and ingest via the full Ingest workflow
3. **Modified sources** → re-ingest using diff-based cascading update (below)
4. **Failed/low-quality extractions** → retry extraction

Report briefly: "Auto-ingested 2 new files, re-ingested 1 modified source. Created 5 pages, updated 2."

No user confirmation needed — **except** when the mass update safeguard applies (modifying >10 existing pages).

### Continuous monitoring (optional)

```bash
python <skill-dir>/scripts/scan.py <vault-path> --watch 300               # scan every 5 min
python <skill-dir>/scripts/scan.py <vault-path> --watch 300 --auto-extract # scan + extract
```

Run in a terminal tab or cron job. Logs changes for the next conversation's auto-ingest.

### Cascading updates (diff-based re-ingestion)

When a source is modified:

**1. Diff the source:**
```bash
python <skill-dir>/scripts/diff_sources.py <source>.snapshot.md <new-source> --json
```
Produces added/removed/changed sections. If no snapshot exists, read the entire source.

**2. Scope the update:**
- Added sections → check if new pages needed
- Removed sections → check and remove obsolete claims
- Changed sections → update specific facts in affected pages
- Unchanged sections → skip entirely

**3. Update affected pages:**
- Check `.manifest.json` for which pages came from this source
- Modify only parts corresponding to changed sections — don't regenerate from scratch
- Follow the link graph: if changes affect linked pages (renamed concept, corrected fact), update those too

**4. Validate and finalize:**
- Validate links: `lint_links.py <vault-path> --files <modified-pages...> --fix`
- Save new snapshot (overwrite old)
- Update `.manifest.json` (new hash, timestamp, page lists)
- Update `index.md`, append to `log.md` (only after validation passes)

### Cascade depth

- **Factual correction**: Update page + pages citing the corrected fact
- **New information**: Update page + pages that benefit from new info
- **Structural change** (rename, merge): Follow all incoming links and update references

---

## Deleting and Archiving

### Removing a source

1. Delete the source file from `raw/` (or move to `_archive/`)
2. Remove its entry from `.manifest.json`
3. For pages solely derived from this source (no other sources in frontmatter): delete or set `status: archived`
4. For multi-source pages: remove references to the deleted source, keep the page
5. Run orphan check — fix dangling references from deleted/archived pages
6. Update `index.md`, append to `log.md`

### Archiving pages

Set `status: archived` in frontmatter rather than deleting. Preserves link history and allows recovery. Archived pages are excluded from query results by checking the status field.

---

## Supporting Tools

> `<skill-dir>` refers to the directory containing this SKILL.md file.

### Page Scoring

Five indicators feed a composite `computed_score` written to each page's frontmatter:

| Indicator | Source | Effect |
|-----------|--------|--------|
| Query frequency | `.stats.json` `query_count` | Pages cited in answers score higher |
| Access count | `.stats.json` `access_count` | Pages read more often score higher |
| Cross-ref density | Incoming `[[wikilinks]]` (scanned live) | Well-connected pages score higher |
| Manual weight | `weight` frontmatter field (default: 0) | User-set additive boost |
| Priority tags | `#pinned` +10, `#priority/high` +6, `medium` +3, `low` +1 | Fixed bonus |

Formula: `computed_score = (0.4 * norm(qf) + 0.3 * norm(ac) + 0.3 * norm(crd)) + weight + tag_bonus`

`norm()` scales 0–10 relative to max across all pages. Weights configurable in `.stats.json`.

```bash
python <skill-dir>/scripts/score_pages.py <vault-path>                    # full recalc
python <skill-dir>/scripts/score_pages.py <vault-path> --pages <pages..>  # incremental
python <skill-dir>/scripts/score_pages.py <vault-path> --json             # structured output
```

### Search Index

Hybrid retrieval (vector + keyword) backed by PGlite (default) or native Postgres. PGlite is a required dependency — started during setup (step 5). The index is a **derived cache** — deleting it is always safe and it can be rebuilt.

**Database** (one of):
- **PGlite sidecar**: Requires Node.js 18+. Auto-initializes schema on first run. Listens on port 5488.
  ```bash
  node <skill-dir>/scripts/sidecar/server.js --data-dir <vault-path>/index
  ```
  Override URL: set `PGLITE_URL` env var.
- **Native Postgres**: Set `DATABASE_URL` env var. No Node.js needed.

**Embeddings** (one of):
- **Local**: `pip install sentence-transformers` — 384-dim, CPU, no API key
- **Remote** (any OpenAI-compatible API): Set `EMBEDDING_API_KEY` and optionally `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`
- **None**: Keyword-only search (no embedding dependency)

**Commands:**
```bash
python <skill-dir>/scripts/index.py rebuild <vault-path>              # full reindex
python <skill-dir>/scripts/index.py sync <vault-path>                 # incremental
python <skill-dir>/scripts/index.py query <vault-path> "text" --json  # hybrid search
python <skill-dir>/scripts/index.py verify <vault-path>               # health check
```

Run `sync` after every successful ingest and on conversation start. Run `verify` as part of lint.

**Embedding dimension changes:** `rebuild` auto-detects dimension mismatches and migrates the schema. `sync` warns and aborts if dimensions don't match — run `rebuild` to migrate.

### Graph Analysis

Analyze the wiki's link structure. Requires `pip install networkx` (degrades gracefully without it). Works from typed links in frontmatter (authoritative) with wikilinks in prose as fallback edges.

```bash
python <skill-dir>/scripts/graph.py <vault-path> neighbors <slug> --depth 2
python <skill-dir>/scripts/graph.py <vault-path> path <from> <to>
python <skill-dir>/scripts/graph.py <vault-path> centrality --metric pagerank --limit 20
python <skill-dir>/scripts/graph.py <vault-path> communities
python <skill-dir>/scripts/graph.py <vault-path> orphans
python <skill-dir>/scripts/graph.py <vault-path> stats
```

All commands support `--format json` for structured output.

### Query Expansion

Generate query paraphrases for better search recall. Requires an LLM API.

```bash
python <skill-dir>/scripts/expansion.py "search query"
```

Configure via env vars: `EXPANSION_PROVIDER` (`anthropic` or `openai`), `EXPANSION_API_KEY`, `EXPANSION_BASE_URL`, `EXPANSION_MODEL`. Falls back to `ANTHROPIC_API_KEY` then `OPENAI_API_KEY`. Default models: `claude-haiku-4-5-20251001` (Anthropic), `gpt-4o-mini` (OpenAI). Returns only the original query if no API is configured.

### Storage Backend

`scripts/storage.py` provides a `StorageBackend` protocol abstracting page CRUD, link management, and search.

**DatabaseBackend** (default): Database-first backend using PGlite or Postgres. DB is authoritative; markdown exported on demand. Supports full hybrid search (vector + keyword RRF), transactional batch operations, and all StorageBackend protocol methods. Shared SQL operations live in `scripts/db_ops.py`.

**FileVaultBackend** (offline fallback): Markdown files are authoritative. Keyword search only (no vector search). No database dependency. Use when PGlite/Postgres is unavailable.

```bash
python <skill-dir>/scripts/storage.py <vault-path> list-pages
python <skill-dir>/scripts/storage.py <vault-path> get-page <slug>
python <skill-dir>/scripts/storage.py <vault-path> search "query"
```

### Document Extraction

See Ingest Step 1 for extraction commands. Additional scanning tool:

```bash
python <skill-dir>/scripts/scan.py <vault-path> --json          # find work
python <skill-dir>/scripts/scan.py <vault-path> --auto-extract   # scan + extract
```

### Text Chunking

`scripts/chunking.py` splits pages into ~300-word chunks with 50-word overlap for embedding. Page-aware mode separates compiled truth from timeline. Used internally by `index.py` — agents rarely call this directly.

---

## Coordination Files

Reference schemas for files created during setup and maintained during operations.

### .manifest.json

```json
{
  "language": "en",
  "sources": [],
  "version": 1
}
```

Populated entry:
```json
{
  "path": "raw/articles/microservices-design.pdf",
  "extracted": "raw/extracted/articles/microservices-design.pdf.md",
  "extraction_method": "mineru +ocr",
  "sha256": "a1b2c3d4e5f6...",
  "ingested_at": "2026-04-07T14:30:00Z",
  "size_bytes": 4523,
  "pages_created": ["wiki/concepts/microservices.md"],
  "pages_updated": ["wiki/entities/team-beta.md"]
}
```

Fields: `path` (relative to vault root), `extracted` (omit for text/markdown), `extraction_method` (`mineru +ocr`, `mineru +txt`, `mineru`, `fallback`, `agent`; omit for text/markdown), `sha256`, `ingested_at` (ISO), `size_bytes`, `pages_created`, `pages_updated`. Snapshots use deterministic naming (`<source-or-extracted-path>.snapshot.md`) and are not tracked in the manifest.

Compute SHA-256: `python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`

### .stats.json

```json
{
  "version": 1,
  "weights": {
    "query_frequency": 0.4,
    "access_count": 0.3,
    "cross_ref_density": 0.3
  },
  "tag_bonuses": {
    "pinned": 10,
    "priority/high": 6,
    "priority/medium": 3,
    "priority/low": 1
  },
  "pages": {}
}
```

`weights` and `tag_bonuses` are user-tunable. See Page Scoring in Supporting Tools.

### .obsidian/app.json

```json
{
  "alwaysUpdateLinks": true,
  "newLinkFormat": "relative",
  "useMarkdownLinks": false,
  "strictLineBreaks": false,
  "showFrontmatter": false,
  "defaultViewMode": "preview",
  "livePreview": true
}
```

### index.md

```markdown
# Wiki Index

> Auto-maintained catalog of all wiki pages. Updated on every ingest.

## Concepts

## Entities

## Topics

## Sources

## Queries
```

Entries sorted by `computed_score` descending within each category: `- [[page-name]] (score: 9.2) — one-line summary`

### log.md

```markdown
# Operation Log

> Append-only record. Format: `## [YYYY-MM-DD HH:MM] action | subject`
> Actions: setup, ingest, re-ingest, query, lint, update

## [YYYY-MM-DD HH:MM] setup | Wiki initialized
- Vault created at `<path>`
```

Never deviate from this heading format — consistency enables grep-based parsing.

---

## Best Practices

### Session scoping
Each conversation should have a clear scope — don't re-process the entire wiki every time. Check `log.md` to understand what's been done, and focus on what's new or changed. This prevents infinite reprocessing loops. A comprehensive update is fine if the user asks — but don't initiate one unprompted.

### Concurrent access
This skill assumes single-writer access. If multiple agents or users edit simultaneously, `.manifest.json` and `index.md` can have write conflicts. Coordinate so only one session modifies the wiki at a time, or use git branching.

### Log rotation
When `log.md` exceeds ~100 entries, move older entries to `log-archive.md` and keep only the most recent 20.

### Scaling (100+ sources, 500+ pages)
- **Index**: When `index.md` exceeds ~200 entries, split into `index-concepts.md`, `index-entities.md`, etc., or switch to grep-based discovery
- **Cross-linking**: Use grep to search `wiki/` for concept names rather than reading every page. Target pages in related `index.md` categories first.
- **Lint**: Run targeted checks by default (affected pages only). Reserve full-vault lint for explicit user requests.

### Version control
Consider `git init` inside the vault for history and backup. The Obsidian Git plugin can automate commits.

### Obsidian integration
The wiki works as plain markdown with or without Obsidian. But Obsidian adds value through graph view, backlinks, and Dataview queries. See `references/obsidian.md` for the full reference (URI scheme, CLI, syntax, plugins).

