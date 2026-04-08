# LLM Wiki Skill

An agent skill that builds and maintains an autonomous, self-compounding knowledge base inside an [Obsidian](https://obsidian.md) vault.

Inspired by [Andrej Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the idea that an LLM can maintain a persistent wiki where knowledge is pre-synthesized and cross-referenced, not re-queried from raw documents each time.

## What It Does

You feed it source documents (markdown, PDFs, code, docx, etc.). The agent synthesizes them into interlinked wiki pages with `[[wikilinks]]`, tracks provenance, and maintains consistency through periodic linting.

**Three core operations:**

| Operation | What it does |
|-----------|-------------|
| **Ingest** | Process source documents into synthesized, cross-referenced wiki pages |
| **Query** | Search the wiki and synthesize answers with citations |
| **Lint** | Health check — find dead links, orphans, stale content, contradictions |

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
│   ├── .manifest.json   # Tracks ingested sources with SHA-256 hashes
│   └── *.snapshot.md    # Snapshots for diff-based re-ingestion
├── wiki/                # Synthesized knowledge pages
│   ├── concepts/        # Ideas, patterns, methodologies
│   ├── entities/        # People, orgs, systems, products
│   ├── topics/          # Broad subjects tying concepts together
│   ├── sources/         # Source summary pages
│   └── queries/         # Filed query answers (cross-cutting analyses)
├── outputs/reports/     # Lint reports and generated artifacts
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
- **Optional Unstructured integration** — Extract text from PDFs, DOCX, PPTX, images
- **File watcher** — Cross-platform monitoring of raw sources for changes (requires `watchdog`)

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

Run the dependency checker to see what's available:

```bash
python3 scripts/check-deps.py
```

**Required:**
- An AI coding agent that supports skills (Claude Code, Codex, Gemini CLI, etc.)
- Python 3.8+
- [`unstructured`](https://github.com/Unstructured-IO/unstructured) — for document extraction (PDF, DOCX, PPTX, images). Install with `pip install "unstructured[all-docs]"`.
- [`watchdog`](https://github.com/gorakhargosh/watchdog) — for the file watcher. Install with `pip install watchdog`.

**Recommended:**
- Obsidian — for graph view, search, and Dataview queries. The skill works without it (it's just markdown files), but Obsidian makes the wiki much more useful.

## Project Structure

```
llm-wiki-skill/
├── llm-wiki/                # The skill bundle (this is what you install)
│   ├── SKILL.md             # Main skill definition
│   ├── references/
│   │   ├── schema.md        # Page templates and frontmatter conventions
│   │   └── obsidian.md      # Obsidian operating reference (URI, CLI, markdown)
│   └── scripts/
│       ├── extract.py       # Document extraction (optional Unstructured integration)
│       ├── diff_sources.py  # Structured diff for incremental re-ingestion
│       └── watch.py         # Cross-platform file watcher (requires watchdog)
├── scripts/
│   └── check-deps.py        # Dependency checker
├── INSTALL.md               # Installation instructions for all agent platforms
├── LICENSE                  # MIT
└── README.md                # This file
```

## Credits

- [Andrej Karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — The LLM Wiki concept
- [ekadetov/llm-wiki](https://github.com/ekadetov/llm-wiki) — Claude Code plugin implementation
- [Ar9av/obsidian-wiki](https://github.com/Ar9av/obsidian-wiki) — Obsidian wiki framework with multi-agent support
- [kepano/obsidian-skills](https://github.com/kepano/obsidian-skills) — Obsidian agent skills and CLI reference
- [safishamsi/graphify](https://github.com/safishamsi/graphify) — Knowledge graph extraction patterns

## License

MIT
