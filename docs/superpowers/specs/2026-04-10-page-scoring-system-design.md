# Page Scoring System Design

> Personalized page weighting for the llm-wiki-skill knowledge base. Computed scores surface important content first across Query, Ingest, and Index operations.

## Problem

All wiki pages are currently treated equally. Users want high-value content to surface first — during queries, browsing, and cross-linking. The system should learn which pages matter most over time, while allowing manual overrides.

## Approach

**Standalone scoring system (Approach B):** A dedicated `score_pages.py` script computes composite scores from multiple indicators. Volatile counters (query frequency, access count) accumulate in `.stats.json`. The script reads counters + scans wikilinks + reads frontmatter, then writes `computed_score` back to each page's frontmatter.

## Scoring Indicators

### Computed indicators (tracked automatically)

| Indicator | Source | Range |
|-----------|--------|-------|
| Query frequency | `.stats.json` — incremented each time a page is cited in a Query answer | 0–unbounded |
| Access count | `.stats.json` — incremented each time the agent reads a page for any purpose | 0–unbounded |
| Cross-reference density | Counted live by scanning all wiki pages for incoming `[[wikilinks]]` | 0–unbounded |

### Manual indicators (set by user)

| Indicator | Source | Effect |
|-----------|--------|--------|
| `weight` frontmatter field | User sets numeric value (default: 0) | Added directly to final score |
| Priority tags | `#pinned`, `#priority/high`, `#priority/medium`, `#priority/low` | Fixed bonus: `#pinned` = +10, `high` = +6, `medium` = +3, `low` = +1 |

## Composite Formula

```
computed_score = (w1 * norm(query_frequency))
              + (w2 * norm(access_count))
              + (w3 * norm(cross_ref_density))
              + weight
              + tag_bonus
```

- `norm()` normalizes each indicator to a 0–10 scale relative to the max value across all pages (top page on each indicator gets 10)
- Default weights: `w1=0.4`, `w2=0.3`, `w3=0.3` — configurable in `.stats.json`
- Final `computed_score` is rounded to 1 decimal place

## `.stats.json` Structure

Lives at vault root alongside `.manifest.json`.

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
  "pages": {
    "wiki/concepts/microservices.md": {
      "query_count": 12,
      "access_count": 34
    },
    "wiki/entities/order-service.md": {
      "query_count": 3,
      "access_count": 8
    }
  }
}
```

- `weights` and `tag_bonuses` are user-tunable
- `pages` maps wiki page paths (relative to vault root) to counters
- Cross-reference density is not stored — computed live by scanning wikilinks
- Pages not in `pages` are treated as having zero counts
- If `.stats.json` does not exist (pre-existing wiki), `score_pages.py` creates it with defaults before proceeding

## `score_pages.py` Script

### Interface

```bash
# Full recalc — score all wiki pages
python <skill-dir>/scripts/score_pages.py <vault-path>

# Incremental — score only specified pages (normalization still uses all pages)
python <skill-dir>/scripts/score_pages.py <vault-path> --pages <page1.md> <page2.md>

# JSON output for agent consumption
python <skill-dir>/scripts/score_pages.py <vault-path> --json
```

### Behavior

1. Read `.stats.json` for counters and config (weights, tag bonuses)
2. Scan all wiki pages for incoming wikilinks → build cross-reference density map
3. Compute `norm()` values across all pages (even in `--pages` mode, normalization needs the full dataset)
4. For each target page: apply formula, add manual `weight` from frontmatter, add tag bonus
5. Write `computed_score` to each target page's frontmatter
6. Output summary: pages scored, top 10 by score, any pages with zero activity

### `--pages` mode

Reads all pages for normalization, but only writes frontmatter to specified pages. Keeps incremental runs fast on large wikis.

### `--json` output

```json
{
  "scored": 42,
  "top": [
    {"page": "wiki/concepts/microservices.md", "computed_score": 9.2},
    {"page": "wiki/entities/order-service.md", "computed_score": 7.5}
  ],
  "zero_activity": ["wiki/concepts/stub-page.md"]
}
```

### Frontmatter after scoring

```yaml
---
aliases: []
tags: [concept, pinned]
sources: ["[[raw/articles/source-name]]"]
created: 2026-04-01
updated: 2026-04-10
status: active
weight: 2
computed_score: 9.2
---
```

## Integration with Existing Operations

### Query

1. **Page selection** — after identifying relevant pages via index/grep, sort candidates by `computed_score` descending. Prioritize reading high-scored pages first.
2. **Synthesis** — when multiple pages cover the same topic, give more weight to higher-scored pages in the synthesized answer. Cite them first in the sources list.
3. **Counter updates** — for every page read during the query, increment `access_count` in `.stats.json`. For every page cited in the answer, increment `query_count`.

### Ingest

After completing Steps 1–5.5, add:

- **Step 5.6: Update scores** — increment `access_count` in `.stats.json` for every existing page read during cross-linking. Then run `score_pages.py --pages <created-and-updated-pages>` to score the new/modified pages.

### Lint

New lint check:

| Check | What to look for | Auto-fixable? |
|-------|-----------------|---------------|
| **Score staleness** | Pages missing `computed_score` or scores not recalculated since last full lint | Yes — run full `score_pages.py` |

Full scoring recalc is part of every lint run. Lint report includes a scoring summary (top 10, zero-activity pages).

### Conversation Start (Auto-ingest)

No change to auto-ingest scan. Scoring recalc happens via ingest Step 5.6 for auto-ingested pages. Full recalc only during explicit lint.

## Vault Structure Changes

```
<vault-root>/
├── .obsidian/
├── raw/
│   ├── extracted/
│   └── .manifest.json
├── wiki/
├── index.md
├── log.md
├── schema.md
└── .stats.json              # NEW — scoring counters and config
```

## Setup Changes

During wiki setup, after creating `.manifest.json`, create `.stats.json` with defaults:

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

## Schema Changes

Add to `schema.md` frontmatter reference:
- `weight` (optional, number, default 0) — manual importance boost set by user
- `computed_score` (number, managed by `score_pages.py`) — do not edit manually

## Index Changes

`index.md` entries show score and are sorted by `computed_score` descending within each category:

```markdown
- [[page-name]] (score: 9.2) — one-line summary
```
