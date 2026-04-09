---
name: llm-wiki
description: >
  Build and maintain an autonomous, self-compounding knowledge base (wiki) inside an Obsidian vault.
  Use this skill whenever the user wants to: create a knowledge base or wiki, ingest documents into a
  structured knowledge system, query a compiled knowledge base, maintain or lint a wiki for consistency,
  set up automated knowledge synchronization, or manage cross-referenced documentation. Also trigger
  when the user mentions "wiki", "knowledge base", "knowledge graph", "ingest documents", "compile notes",
  "cross-reference", "wiki lint", or wants to turn a collection of files into organized, interlinked knowledge.
  This skill handles the full lifecycle: setup, ingestion, querying, linting, and continuous maintenance.
---

# LLM Wiki

An autonomous, self-compounding knowledge base that lives in an Obsidian vault. You ingest raw sources (articles, PDFs, code, docs), the LLM synthesizes them into interlinked wiki pages, and periodic linting keeps everything consistent. The wiki is a **persistent, compounding artifact** — knowledge is pre-synthesized and cross-referenced, not re-queried from raw documents each time.

The human is in charge of sourcing, exploration, and asking the right questions. You do the grunt work — summarizing, cross-referencing, filing, and bookkeeping.

## Core Concepts

### Three Layers

```
Raw Sources → Wiki Pages → Index/Schema
(immutable)   (synthesized)  (coordination)
```

- **Raw sources** are never modified after ingestion. They are the ground truth. The `.manifest.json` tracks SHA-256 hashes to detect unauthorized changes. For extra protection on Unix systems, you can lock them with `chmod -R a-w raw/` — but this is optional and doesn't work on Windows.
- **Wiki pages** are the synthesized knowledge layer — entities, concepts, topics — with cross-references via `[[wikilinks]]`.
- **Index and log** are coordination files that track what exists and what happened.

### Three Operations

| Operation | What it does | When to use |
|-----------|-------------|-------------|
| **Ingest** | Process sources → create/update wiki pages | New source material arrives |
| **Query** | Search wiki → synthesize answer with citations | User asks a question |
| **Lint** | Health check → fix inconsistencies | Periodically, or after large ingests |

---

## Vault Structure

```
<vault-root>/
├── .obsidian/              # Obsidian configuration
├── raw/                    # Immutable source documents (flat or organized — your choice)
│   ├── extracted/          # Docling-extracted markdown versions of binary sources
│   └── .manifest.json      # Tracks ingested sources (hash, timestamp, resulting pages)
├── wiki/                   # Synthesized knowledge pages (subdirectories emerge from content)
├── index.md                # Content catalog — organized by category
├── log.md                  # Append-only operation history
└── schema.md               # Wiki conventions and page templates
```

The subdirectories under both `raw/` and `wiki/` are **not prescribed** — they should emerge from the content. The agent discovers files by scanning recursively, not by expecting a fixed directory structure. Common starting patterns include `concepts/`, `entities/`, `topics/`, `sources/`, `queries/` — but a domain might naturally call for `protocols/`, `people/`, `systems/`, or something else entirely. Let the content dictate the taxonomy. The templates in `schema.md` provide five page types as starting points; adapt or ignore them as needed.

---

## Setup

When the user asks to set up a new wiki or knowledge base:

1. **Check dependencies** — before anything else, verify the current Python environment has the optional packages:
   ```python
   python3 -c "import docling; import pip_system_certs; print('Dependencies OK')"
   ```
   - **If both imports succeed**: skip step 2 — use the current environment as-is.
   - **If any import fails**: inform the user. These are optional — the skill works without them (the agent can read files directly and watch for changes manually). Ask whether they'd like to install into a virtual environment. Do not install without confirmation.
2. **Set up a Python virtual environment** (only if step 1 failed and user agreed):
   ```bash
   python3 -m venv <vault-path>/.venv
   <vault-path>/.venv/bin/pip install docling pip-system-certs
   ```
   On Windows, use `<vault-path>\.venv\Scripts\pip` instead. This keeps the skill's dependencies isolated from the system Python.
3. **Create the vault directory** at the user's specified path (or current directory)
4. **Initialize the structure** — create `raw/`, `wiki/`, `index.md`, `log.md`, `schema.md`, and `raw/.manifest.json`
5. **Initialize `.obsidian/`** with minimal config so Obsidian recognizes it as a vault
6. **Register with Obsidian** (if installed) — open the vault using `open "obsidian://open?path=<vault-path>"`. Skip this step if Obsidian is not available; the wiki works as plain markdown files.
7. **Write `schema.md`** — copy the contents of `references/schema.md` into the vault as `schema.md`
8. **Add the vault directory to `.gitignore`** if the vault is inside a git repo that shouldn't track it

### Minimal `.obsidian/` config

Create `.obsidian/app.json` (see `references/obsidian.md` for details on each setting):
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

### Initial `index.md`

```markdown
# Wiki Index

> Auto-maintained catalog of all wiki pages. Updated on every ingest.

## Concepts

## Entities

## Topics

## Sources

## Queries
```

### Initial `log.md`

The log uses a strict format so it can be reliably parsed by grep. Never deviate from this heading structure — consistency matters more than aesthetics here.

```markdown
# Operation Log

> Append-only record of wiki operations. Each entry follows the exact format:
> `## [YYYY-MM-DD HH:MM] action | subject`
> where action is one of: setup, ingest, re-ingest, query, lint, update

## [YYYY-MM-DD HH:MM] setup | Wiki initialized
- Vault created at `<path>`
```

### Initial `.manifest.json`

```json
{
  "sources": [],
  "version": 1
}
```

A populated manifest entry looks like this — follow this schema exactly so cross-session consistency is maintained:

```json
{
  "sources": [
    {
      "path": "raw/articles/microservices-design.pdf",
      "extracted": "raw/extracted/articles/microservices-design.pdf.md",
      "extraction_method": "docling +ocr",
      "sha256": "a1b2c3d4e5f6...",
      "ingested_at": "2026-04-07T14:30:00Z",
      "size_bytes": 4523,
      "pages_created": ["wiki/concepts/microservices.md", "wiki/entities/order-service.md"],
      "pages_updated": ["wiki/entities/team-beta.md"]
    }
  ],
  "version": 1
}
```

Fields: `path` (relative to vault root), `extracted` (path to the extracted markdown in `raw/extracted/`, omit for text/markdown sources that don't need extraction), `extraction_method` (`docling +ocr`, `docling`, `fallback`, or `agent`; omit for text/markdown sources), `sha256` (file hash for change detection), `ingested_at` (ISO timestamp), `size_bytes` (file size), `pages_created` (new pages from this source), `pages_updated` (existing pages modified during this ingest).

Snapshot files follow a deterministic naming convention (`<source-or-extracted-path>.snapshot.md`) and do not need to be tracked in the manifest.

Compute SHA-256 with: `python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`

---

## Ingest

Ingestion is the core operation. When the user provides source material (files, URLs, pasted text):

### Step 1: Accept and store the source

- **Local files**: The user can place files anywhere inside `raw/` — flat or in subdirectories. If the agent is copying files on the user's behalf, just put them directly in `raw/` (or a subdirectory if the user prefers organization). No specific directory structure is required.
- **URLs**: Fetch the content and save as `raw/<domain>-<slug>.md`. Store the original URL in the file's YAML frontmatter as `source_url`.
- **Pasted text**: Save to `raw/YYYY-MM-DD-<brief-slug>.md`
- For non-markdown files (PDF, DOCX, etc.), extract text content first (see **Document Extraction** below). Extracted markdown goes to `raw/extracted/<filename>.md`.
- **Save a snapshot** for diff-based re-ingestion later — instead of re-reading the entire source, the agent can diff the snapshot against the new version to see exactly what changed. For text/markdown sources, the snapshot goes alongside the source (e.g., `raw/article.md.snapshot.md`). For extracted binary files, the snapshot goes alongside the extracted file (e.g., `raw/extracted/report.pdf.md.snapshot.md`).

### Step 2: Read and understand

- Read the source material thoroughly
- Identify: key concepts, entities (people, organizations, systems), relationships, claims, and open questions
- Note which existing wiki pages are relevant (check `index.md`)

### Step 3: Compile into wiki pages

For each significant concept, entity, or topic found in the source:

- **If a wiki page already exists**: Update it with new information, marking the source. Merge, don't duplicate.
- **If it's genuinely new**: Create a new page using the templates in `schema.md`

Each wiki page should have:

```markdown
---
aliases: []
tags: []
sources:
  - "[[raw/articles/source-name]]"
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active
---

# Page Title

One-to-two sentence summary for quick scanning.

## Overview
<!-- Core description -->

## Details
<!-- Deeper content, organized by the topic's natural structure -->

## Relationships
<!-- Links to related wiki pages with brief context -->
- Related to [[Other Concept]] — because X
- Part of [[Broader Topic]]

## Open Questions
<!-- Use callouts to highlight question context -->
> [!question] Question text
> Why this matters and what we'd need to answer it.

## Sources
- [[raw/articles/source-name]] — extracted on YYYY-MM-DD
```

### Step 4: Cross-link

- Use `[[wikilinks]]` for all references to other wiki pages
- Scan existing pages for mentions of newly created concepts — add links there too
- Every page should be reachable from at least one other page (no orphans)

### Step 5: Update coordination files

- **`index.md`**: Add/update entries for all new/modified pages with one-line summaries
- **`log.md`**: Append an entry like `## [2026-04-07 14:30] ingest | Source Title` with a bullet list of pages created/updated
- **`.manifest.json`**: Record the source file path, SHA-256 hash, timestamp, and list of resulting wiki pages

### Batch ingestion

When ingesting multiple sources at once, process them in a single pass to maximize cross-referencing. Read all sources first, then compile pages that synthesize across sources rather than creating isolated summaries.

### Mass update safeguard

If an ingest or update operation would modify more than 10 existing wiki pages, pause and list the affected pages for the user before proceeding. Large-scale updates are more likely to introduce drift or unintended changes, so the human should confirm the scope. This doesn't apply to creating new pages — only to modifying existing ones.

---

## Document Extraction

The wiki handles plain markdown, text, and code files natively. For all other formats (PDF, DOCX, PPTX, XLSX, images, HTML, and more), there are two extraction approaches. Extracted markdown files are stored in `raw/extracted/` — the originals in `raw/` are never modified.

> **Note:** `<skill-dir>` in the commands below refers to the directory containing this SKILL.md file.

### Approach 1: Docling extraction (recommended for large or complex documents)

Use the extraction script bundled with the skill. It uses [Docling](https://github.com/docling-project/docling) with optimized settings: accurate table structure recognition, OCR for scanned pages, and 2x image resolution.

```bash
pip install docling pip-system-certs
```

```bash
# Output goes to raw/extracted/<filename>.md by default
python <skill-dir>/scripts/extract.py <input-file>

# Or specify an explicit output path
python <skill-dir>/scripts/extract.py <input-file> <output-markdown>
```

For native-text PDFs where OCR is unnecessary, disable it for faster processing:

```bash
python <skill-dir>/scripts/extract.py --no-ocr <input-file>
```

The script auto-detects file type and routes to Docling for conversion. For plain text, markdown, and code files, it reads them directly without Docling. There is no hard file size limit — large files produce a warning but extraction proceeds.

After extraction, record in the manifest:
- `extracted`: path to the extracted file (e.g. `raw/extracted/report.pdf.md`)
- `extraction_method`: `docling +ocr`, `docling`, or `fallback`

### Approach 2: Agent direct reading (fallback)

If Docling is not installed, produces unsatisfactory results, or the user prefers it, **the agent can read the source file directly** using its built-in file reading capability. Many AI agents can natively read PDFs and images. In this mode:

1. Copy the source file into `raw/` as-is (no conversion step)
2. Read the file directly using the agent's file reading tool
3. Synthesize wiki pages from what you read
4. Record `extraction_method: agent` in the manifest entry (no `extracted` field)

This is the simplest approach and requires no Python dependencies. It works well for short documents, clean PDFs, and when the agent's native file reading is sufficient. It is less reliable for scanned documents, complex table layouts, or very large files where Docling's dedicated parsing pipeline produces better results.

### Which approach to use

- **Docling** when: the document has complex tables, multi-column layouts, scanned/image-based pages, or is very large. Also when you need consistent, reproducible extraction across sessions.
- **Agent direct reading** when: Docling is not installed, the document is short and clean, or the user asks you to read the file directly.
- If Docling extraction produces poor results for a specific file, fall back to agent direct reading for that file and note it in the log.

If neither approach is available (no Docling, agent cannot read the format), tell the user what to install:

> I need the Docling library to extract text from this .docx file. Install it with:
> `pip install docling pip-system-certs`

### Scanning for extraction work

Use the scan script to find files that need extraction, retry failed extractions, or re-extract low-quality results:

```bash
# One-shot scan — reports what needs attention
python <skill-dir>/scripts/scan.py <vault-path>

# JSON output for agent consumption
python <skill-dir>/scripts/scan.py <vault-path> --json

# Periodic scanning (every 5 minutes)
python <skill-dir>/scripts/scan.py <vault-path> --watch 300

# Scan and automatically extract all findings
python <skill-dir>/scripts/scan.py <vault-path> --auto-extract
```

The scan detects:
- **New files**: in `raw/` but not in `.manifest.json` and not yet extracted
- **Failed extractions**: in manifest but extracted file is missing
- **Low quality**: extracted file is suspiciously small relative to source (<1% size ratio or nearly empty)
- **Modified sources**: file hash differs from what's recorded in manifest

---

## Query

When the user asks a question about the wiki's knowledge:

1. **Search**: Read `index.md` to identify relevant pages. For larger wikis, use grep/glob to find pages mentioning key terms.
2. **Retrieve**: Read the relevant wiki pages.
3. **Synthesize**: Answer the question using the wiki's compiled knowledge. Cite sources with `[[wikilinks]]`.
4. **File the answer**: Save the answer as a wiki page under `wiki/queries/` if it synthesizes across 3+ wiki pages or reveals a non-obvious connection. Don't file simple single-page lookups. This is how the wiki compounds — queries produce new artifacts that future queries can build on. Ask the user if borderline.

### Query output format

```markdown
## Answer

[Synthesized answer here, citing [[Wiki Page]] sources]

### Sources consulted
- [[wiki/concepts/concept-a]] — relevant because X
- [[wiki/entities/entity-b]] — mentioned Y
- [[raw/articles/original-source]] — primary source for Z
```

---

## Lint

Linting ensures wiki health. Run it periodically or when the user asks.

### Checks to perform

| Check | What to look for | Auto-fixable? |
|-------|-----------------|---------------|
| **Dead links** | `[[wikilinks]]` pointing to non-existent pages | Create stub pages |
| **Orphaned pages** | Pages with no incoming links | Add links from related pages or index |
| **Stale content** | Pages whose sources have been updated since last compile | Flag for re-ingestion |
| **Missing cross-refs** | Pages that mention concepts without linking them | Add `[[wikilinks]]` |
| **Index drift** | Pages that exist but aren't in `index.md` | Add to index |
| **Duplicate concepts** | Multiple pages covering the same topic | Suggest merge |
| **Empty sections** | Pages with placeholder sections that were never filled | Flag or remove |
| **Frontmatter issues** | Missing required fields, outdated timestamps | Fix automatically |
| **Schema drift** | Pages using outdated frontmatter schema (missing new fields, deprecated tags) | Migrate to current schema |

### Lint output

Save a report to `wiki/lint-YYYY-MM-DD.md`:

```markdown
# Lint Report — YYYY-MM-DD

## Summary
- X issues found, Y auto-fixed, Z need attention

## Auto-fixed
- Added [[missing-page]] stub (dead link from [[source-page]])
- Updated index.md with 3 missing entries

## Needs Attention
- [[concept-a]] and [[concept-b]] appear to cover the same topic — consider merging
- [[entity-x]] has no incoming links and unclear relevance
```

Also append to `log.md`.

---

## Change Detection and Auto-Update

The wiki automatically detects and ingests changes — the user just drops files into `raw/` and the agent handles the rest.

### Auto-ingest (on conversation start)

At the start of each conversation where the wiki is in scope, scan for changes and **ingest them automatically**:

1. **Run a scan** — use `python <skill-dir>/scripts/scan.py <vault-path> --json` to get a structured report of new, failed, and low-quality extractions.
2. **New files in `raw/`** not yet in `.manifest.json` → extract (if binary format) and ingest them. Extracted markdown goes to `raw/extracted/`.
3. **Modified sources** (compare file hashes to `.manifest.json`) → re-extract and re-ingest them using diff-based processing
4. **Failed or low-quality extractions** — if a file in the manifest has no extracted file or an unusually small one, retry extraction. You can run `python <skill-dir>/scripts/scan.py <vault-path> --json` to get a structured report of all extraction issues.

Briefly report what was processed:

> Auto-ingested 2 new files and re-ingested 1 modified source. Created 5 wiki pages, updated 2.

No user confirmation is needed for auto-ingest — **except** when the mass update safeguard applies (modifying >10 existing pages). In that case, pause and list the affected pages before proceeding.

### Explicit triggers

The user can also run operations manually by asking you to ingest, query, or lint. Additionally, if the user asks for a lint after auto-ingest completes, run it.

### Continuous monitoring (optional setup)

For teams that want periodic detection between conversations, run `scripts/scan.py <vault-path> --watch 300` to re-scan the `raw/` directory every 5 minutes. Use `--auto-extract` to automatically extract new files. The user can run this in a terminal tab or cron job.

The watcher logs detected changes so the next conversation's auto-ingest picks them up immediately.

---

## Cascading Updates

When a source is re-ingested (because it was modified), use diff-based re-ingestion to minimize work and token usage:

### Step 1: Diff the source

Compare the old snapshot against the new version to understand exactly what changed. Use the bundled diff script:

```bash
python <skill-dir>/scripts/diff_sources.py <source>.snapshot.md <new-source> --json
```

This produces a structured diff showing added/removed/changed sections and unchanged sections. If no snapshot exists (legacy source ingested before snapshots were introduced), fall back to reading the entire source.

### Step 2: Scope the update

Based on the diff:
- **Added sections**: May introduce new concepts/entities → check if new wiki pages are needed
- **Removed sections**: May obsolete claims in existing wiki pages → check and remove
- **Changed sections**: Update the specific claims/facts in affected wiki pages
- **Unchanged sections**: Skip entirely — don't re-read or re-process these

### Step 3: Update affected pages

1. **Identify affected pages**: Check `.manifest.json` for which wiki pages were generated from this source
2. **Update wiki pages**: Modify only the parts that correspond to changed sections. Don't regenerate from scratch — preserve manually added content and links from other sources
3. **Follow the link graph**: Check pages that link to the updated pages. If the changes affect their content (e.g., a renamed concept, a corrected fact), update those too

### Step 4: Finalize

1. **Save new snapshot**: Overwrite `<source>.snapshot.md` with the new content
2. **Update `.manifest.json`**: New hash, timestamp, and updated page lists
3. **Update `index.md`**: Refresh summaries for modified pages
4. **Append to `log.md`**: Record what changed using the diff summary (e.g., "3 sections changed, 1 added")

The depth of cascading depends on the nature of the change:
- **Factual correction**: Update the page + any pages that cite the corrected fact
- **New information added**: Update the page + pages that would benefit from the new info
- **Structural change** (renamed concept, merged topics): Follow all incoming links and update references

---

## Deleting and Archiving

When the user wants to remove a source or wiki page:

### Removing a source
1. Delete (or move to an `_archive/` directory) the source file from `raw/`
2. Remove its entry from `.manifest.json`
3. Check `pages_created` from the manifest entry — for each page that was solely derived from this source (no other sources listed in its frontmatter), either delete it or set `status: archived`
4. For pages that had multiple sources, remove references to the deleted source but keep the page
5. Run an orphan check — follow links from deleted/archived pages and fix any dangling references
6. Update `index.md` and append to `log.md`

### Archiving wiki pages
Set `status: archived` in frontmatter rather than deleting. This preserves link history and allows recovery. Archived pages can be excluded from queries by checking the status field.

---

## Best Practices

### Writing wiki pages
- Lead with a one-sentence summary — readers (and future LLM queries) scan this first
- Use `[[wikilinks]]` liberally — connections are the wiki's primary value
- Include provenance: which source said what, and when
- Mark uncertain claims: "According to [[source]], X (unverified)" or use `status: needs-review` in frontmatter
- Keep pages focused on one concept/entity — split if a page covers too much

### Managing the wiki
- The human decides what to ingest and what questions to ask. The LLM handles the bookkeeping.
- Don't over-organize upfront — let the taxonomy emerge from the content
- Use `log.md` to understand the wiki's history without reading every page
- The manifest is the source of truth for what's been processed

### Session scoping
Each conversation session should have a clear scope — don't try to re-process the entire wiki every time. Check `log.md` to understand what's already been done, and focus on what's new or changed since the last operation. This prevents infinite reprocessing loops where the agent keeps finding "improvements" to make. If the user asks for a comprehensive update, that's fine — but don't initiate one unprompted.

### Concurrent access
This skill assumes single-writer access to the vault. If multiple agents or users edit the wiki simultaneously, `.manifest.json` and `index.md` can have write conflicts. For teams, coordinate so only one session modifies the wiki at a time, or use git branching to merge changes.

### Provenance: claims vs pages
Use **inline footnotes** (`^[inferred]`, `^[ambiguous]`) for claim-level confidence — marking individual statements within a page. Use **frontmatter `status`** for page-level review state (`active`, `needs-review`, `stub`, `archived`). These are complementary: a page can be `status: active` while containing some `^[ambiguous]` claims.

### Log rotation
When `log.md` exceeds ~100 entries, move older entries to `log-archive.md` and keep only the most recent 20 in `log.md`. This keeps conversation-start log checks cheap.

### Version control for the vault
Consider initializing git inside the vault itself (`git init` in the vault root) for version history and backup. The Obsidian Git plugin can automate commits. This is separate from any project repo the vault might live alongside.

### Scaling (100+ sources, 500+ pages)

As the wiki grows, some operations need to adapt:

- **Index**: When `index.md` exceeds ~200 entries, it becomes expensive to read in full. Split into `index-concepts.md`, `index-entities.md`, etc., or switch to grep-based discovery instead of reading the whole index.
- **Cross-linking**: The "scan existing pages for mentions" step becomes O(n). Use grep to search for the concept name across `wiki/` rather than reading every page. Target pages listed in `index.md` under related categories first.
- **Lint**: Full lint checks are expensive at scale. Run targeted checks (e.g., just orphan detection, or just the pages affected by a recent ingest) by default. Reserve full-vault lint for explicit user requests.
- **Manifest**: The `.manifest.json` file stays manageable — it only grows with the number of sources, not pages.
- **Graph View**: Obsidian's graph view handles thousands of nodes well, but dense cross-linking makes it more useful at any scale.

### Obsidian integration

The wiki is a folder of markdown files — it works with or without Obsidian open. But Obsidian adds significant value through its linking, graph, and query features. See `references/obsidian.md` for the complete reference (URI scheme, CLI, markdown syntax, plugins).

Key points:

- **Wikilinks**: Use `[[page-name]]` for all internal links (not `[text](path)`). Obsidian tracks renames automatically. Link to headings with `[[page#Heading]]` and blocks with `[[page#^block-id]]`.
- **Embeds**: Use `![[page-name]]` to embed one note inside another — useful for embedding source summaries into concept pages.
- **Callouts**: Use `> [!type]` blocks for structured annotations — `> [!warning]` for risks, `> [!question]` for open questions, `> [!tip]` for insights. These render as styled blocks in Obsidian.
- **Provenance markers**: Use inline footnotes to mark claim confidence: no marker = extracted from source, `^[inferred]` = LLM-synthesized, `^[ambiguous]` = sources disagree.
- **Properties**: YAML frontmatter is queryable via Dataview. Keep `tags`, `status`, `sources`, `created`, `updated` consistent across all pages.
- **Tags**: Use `#tags` inline or in frontmatter. Prefer lowercase-hyphenated, max 5 per page. Nested tags like `#architecture/microservices` create hierarchy.
- **Graph View**: Obsidian automatically visualizes the wiki's link structure. Denser cross-linking = more useful graph.
- **CLI** (v1.12.0+): If Obsidian is running, use `obsidian read`, `obsidian search`, `obsidian backlinks`, `obsidian rename` for operations that benefit from Obsidian's awareness of links. Use `obsidian rename` instead of filesystem renames to update all backlinks.
- **URI scheme**: Use `open "obsidian://open?path=<vault-path>"` to register and open vaults. Use `obsidian://open?vault=<name>&file=<path>` to navigate to specific pages.
- **Dataview**: If the plugin is installed, users can query pages dynamically — e.g., list all `status: needs-review` pages, or build tables from frontmatter fields.

---

## Bundled Resources

- `references/schema.md` — Default page templates and frontmatter conventions
- `references/obsidian.md` — Obsidian operating reference: URI scheme, CLI commands, flavored markdown syntax, vault config, recommended plugins, and retrieval patterns
- `scripts/extract.py` — Document extraction using Docling (optional dependency). Output goes to `raw/extracted/` by default.
- `scripts/scan.py` — Scans `raw/` for new, failed, or low-quality extractions. Supports periodic scanning and auto-extraction.
- `scripts/diff_sources.py` — Structured diff between source versions for incremental re-ingestion
