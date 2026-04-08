# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An **Agent Skills package** (agentskills.io spec) that provides an autonomous knowledge base skill for Obsidian vaults. Not a traditional Node/Python package — it's a skill bundle installed into agent skill directories. The skill has three core operations: **ingest** (process sources into wiki pages), **query** (search and synthesize answers), and **lint** (health checks).

## Useful Commands

```bash
# Check all dependencies (Python 3.8+, unstructured, optional tools)
python3 scripts/check-deps.py

# Extract text from PDF/DOCX/PPTX to markdown
python3 llm-wiki/scripts/extract.py <input-file> <output-markdown>

# Compute structured diff for incremental re-ingestion
python3 llm-wiki/scripts/diff_sources.py <old-file> <new-file> [--json]

# Watch for raw source changes
python3 llm-wiki/scripts/watch.py <vault-path>
python3 llm-wiki/scripts/watch.py <vault-path> --filter "*.md" --debounce 3.0
```

There is no formal build system, test suite, or linter.

## Architecture

### Three-Layer Design

1. **Raw Sources** (`raw/` in vault) — Immutable user-provided documents. Tracked via `.manifest.json` with SHA-256 hashes. Snapshots created for future diffing.
2. **Synthesized Wiki Pages** (`wiki/` in vault) — LLM-generated pages in subdirs: `concepts/`, `entities/`, `topics/`, `sources/`, `queries/`. Connected via `[[wikilinks]]` with YAML frontmatter metadata.
3. **Coordination Files** — `index.md` (page catalog), `log.md` (append-only operation history), `schema.md` (templates), `.manifest.json` (ingestion metadata).

### Key Files

- `llm-wiki/SKILL.md` — The main skill definition and operating manual (entry point for agents)
- `llm-wiki/references/schema.md` — Wiki page templates and frontmatter conventions
- `llm-wiki/references/obsidian.md` — Obsidian operating reference (URI scheme, CLI, markdown extensions)
- `llm-wiki/scripts/extract.py` — Document extraction using the `unstructured` library
- `llm-wiki/scripts/diff_sources.py` — Structured diff computation for incremental re-ingestion
- `llm-wiki/scripts/watch.py` — Cross-platform file watcher using watchdog
- `scripts/check-deps.py` — Dependency validation script
- `INSTALL.md` — Platform-specific installation instructions

### Design Principles

- **Immutable sources / synthesized output**: Raw sources never modified; wiki layer is the processing output
- **Manifest as source of truth**: `.manifest.json` tracks what's processed and which pages came from which sources
- **Diff-based incremental processing**: Only changed sections re-processed on source updates (token-efficient at scale)
- **Provenance tracking**: Claims marked as extracted/inferred/ambiguous; pages cite sources
- **Session scoping**: Each conversation focuses on what's new/changed since last session
- **Single-writer assumption**: One agent/user at a time
- **Mass update safeguard**: Pauses for confirmation when modifying >10 existing pages

## Dependencies

- **Required**: Python 3.8+, `unstructured[all-docs]`, `watchdog`
- **Recommended**: Obsidian desktop app
- **Optional**: `PyMuPDF`, `pdftotext`, Obsidian CLI (v1.12.0+)
