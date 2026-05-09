# Wiki Page Templates

Default templates for wiki pages. These are starting points — adapt the structure to fit the domain.

> **Note:** The `[[wikilinks]]` in these templates (e.g., `[[Other Concept]]`) are **placeholders**. In actual wiki pages, always use the exact filename as the link target: `[[other-concept|Other Concept]]`. See `obsidian.md` → "Wikilink Resolution Rules" for details.

## Table of Contents
- [Concept Page](#concept-page)
- [Entity Page](#entity-page)
- [Source Summary Page](#source-summary-page)
- [Topic Page](#topic-page)
- [Query/Analysis Page](#queryanalysis-page)
- [Frontmatter Reference](#frontmatter-reference)

---

## Concept Page

For ideas, principles, patterns, methodologies.

### v2 template (footnote-citation format)

This is the current page format. Footnote refs `[^id]` cite per-sentence sources; definitions live at the bottom of the file. Frontmatter declares `format_version: 2` and may carry `claims_inferred:` / `claims_ambiguous:` lists.

```markdown
---
aliases: []
tags: [concept]
sources: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active
format_version: 2
claims_inferred: []
claims_ambiguous: []
---

# Concept Name

One-to-two sentence definition[^primary-source].

## Overview

What this concept is and why it matters[^primary-source]. Adoption has accelerated in recent surveys[^industry-survey].

## Key Principles

- Principle 1[^primary-source]
- Principle 2[^industry-survey]

## Applications

How and where this concept is applied[^primary-source].

## Relationships

- Related to [[other-concept|Other Concept]] — shared foundation in X
- Contrast with [[alternative-approach|Alternative Approach]] — differs in Y
- Used by [[system-or-entity|System or Entity]]

## Open Questions

- Unresolved aspects worth investigating

## Sources

- [[raw/source-file]] — extracted YYYY-MM-DD

---

## Timeline

- YYYY-MM-DD — Initial page created from [[raw/articles/primary-source]].
- YYYY-MM-DD — New survey data added; compiled truth refreshed.

[^primary-source]: [[raw/articles/primary-source]]
[^industry-survey]: [[raw/reports/industry-survey-2026]]
```

The compiled-truth zone sits above the `---` separator; the timeline below it; footnote definitions follow the timeline at the very bottom of the file. `lint_links.py` enforces the placement (rule L-4) on v2 pages.

### Legacy template (format_version: 1 / pre-footnote)

Pages without `format_version: 2` are legacy. They use inline `[[wikilinks]]` for citations and inline `^[inferred]` / `^[ambiguous]` markers for confidence. New v2 lint rules (L-1..L-4) do not apply. Run `lint_links.py --fix` to migrate a legacy page in place.

```markdown
---
aliases: []
tags: [concept]
sources: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active
---

# Concept Name

One-to-two sentence definition.

## Overview

What this concept is and why it matters.

## Key Principles

- Principle 1
- Principle 2

## Applications

How and where this concept is applied.

## Relationships

- Related to [[Other Concept]] — shared foundation in X
- Contrast with [[Alternative Approach]] — differs in Y
- Used by [[System or Entity]]

## Open Questions

- Unresolved aspects worth investigating

## Sources

- [[raw/source-file]] — extracted YYYY-MM-DD
```

---

## Entity Page

For people, organizations, systems, products — concrete things.

```markdown
---
aliases: []
tags: [entity]
type: person | organization | system | product
sources: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active
---

# Entity Name

One-sentence description of what this entity is.

## Overview

Key facts and context.

## Role / Function

What this entity does or is responsible for.

## Relationships

- Part of [[Parent Organization or System]]
- Works with [[Related Entity]]
- Implements [[Concept or Protocol]]

## Timeline

Key events in chronological order (if relevant).

## Sources

- [[raw/source-file]] — extracted YYYY-MM-DD
```

---

## Source Summary Page

Created for each ingested source. Lives in `wiki/sources/`.

```markdown
---
aliases: []
tags: [source]
source_type: article | paper | documentation | code | transcript
source_path: "raw/articles/filename.md"
sources: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
ingested: YYYY-MM-DD
status: active
---

# Source: Title of the Source

## Summary

2-3 paragraph summary of the source's content and significance.

## Key Takeaways

- Takeaway 1
- Takeaway 2
- Takeaway 3

## Concepts Introduced or Referenced

- [[Concept A]] — described in detail
- [[Concept B]] — mentioned briefly

## Entities Mentioned

- [[Entity X]] — primary subject
- [[Entity Y]] — referenced

## Notable Claims

- Claim 1 (supported by evidence X)
- Claim 2 (author's opinion, not independently verified)

## Questions Raised

- What about X?
- How does this relate to Y?
```

---

## Topic Page

For broad subjects that tie together multiple concepts and entities.

```markdown
---
aliases: []
tags: [topic]
sources: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active
---

# Topic Name

One-sentence description of the topic's scope.

## Overview

What this topic covers and its significance.

## Key Concepts

- [[Concept A]] — role within this topic
- [[Concept B]] — role within this topic

## Key Entities

- [[Entity X]] — involvement
- [[Entity Y]] — involvement

## Current State

What's known, what's settled, what's in flux.

## Open Questions

- Unresolved debates or gaps in knowledge

## Sources

- [[raw/source-file]] — extracted YYYY-MM-DD
```

---

## Query/Analysis Page

For filed query answers, cross-cutting analyses, and comparisons. Lives in `wiki/queries/`. This is how the wiki compounds — queries become first-class knowledge artifacts.

```markdown
---
aliases: []
tags: [query]
query: "The original question that prompted this analysis"
sources:
  - "[[wiki/concepts/concept-a]]"
  - "[[wiki/entities/entity-b]]"
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: active
---

# Analysis: Descriptive Title

One-sentence summary of the finding or answer.

## Question

The question or prompt that led to this analysis.

## Answer

Synthesized answer with citations to [[wiki pages]] and [[raw/sources]].

> [!tip] Key Insight
> The most important takeaway, highlighted for scanning.

## Evidence

| Claim | Source | Confidence |
|-------|--------|------------|
| Claim 1 | [[wiki/page]] | Extracted |
| Claim 2 | [[wiki/page]] | Inferred |

## Gaps

- What couldn't be answered with current wiki knowledge
- Suggested sources to investigate

## Pages Consulted

- [[wiki/concepts/concept-a]] — relevant because X
- [[wiki/entities/entity-b]] — mentioned Y
```

### Query response format

When the agent answers a question (whether or not the answer is filed as a Query/Analysis Page), the response is shaped as a small footnote-cited document mirroring the v2 page format: each factual sentence ends with one or more `[^id]` refs, and a block of `[^id]: …` footnote definitions follows at the end of the response.

```markdown
## Answer
The transformer architecture replaces RNNs with self-attention[^attention-paper].
Training cost was approximately $4.6M, though estimates vary[^cost-survey].

[^attention-paper]: [[raw/articles/vaswani-attention]]
[^cost-survey]: [[raw/reports/training-cost-2024]]
```

This shape is the same whether the answer is returned conversationally or filed as a page under `wiki/queries/`. When filed, the page wraps the answer with the rest of the Query/Analysis template above (Question, Evidence table, Gaps, Pages Consulted) and lists the same `[^id]: …` definitions at the bottom of the file (after the timeline, per the v2 placement rule).

---

## Compiled Truth + Timeline Model

Every wiki page is divided into two zones by a horizontal rule (`---` on its own line):

- **Above the rule: Compiled Truth** — the current best understanding of the topic. This section is rewritten whenever new evidence materially changes the picture. It should always read as a coherent, up-to-date summary — not an incremental log.
- **Below the rule: Timeline** — an append-only evidence trail of dated entries (newest first). Timeline entries are never edited or deleted; they capture what was learned and when.

### Example

```markdown
---
aliases: []
tags: [concept]
sources: []
created: 2025-01-15
updated: 2025-03-10
status: active
---

# Microservices

Microservices are an architectural style that structures an application
as a collection of loosely coupled, independently deployable services.

## Overview

Current consensus favors microservices for large teams but acknowledges
significant operational overhead for smaller organizations.

---

## Timeline

- 2025-03-10 — New survey data shows 60% of startups regret early
  microservice adoption. Updated compiled truth to reflect this.
- 2025-02-01 — Team discussed trade-offs with [[monolith]] approach.
  No change to compiled truth yet.
- 2025-01-15 — Initial page created from [[raw/articles/fowler-microservices]].
```

### Staleness and Balance

- **Stale**: A page is stale when its frontmatter `updated` date is before the date of the latest timeline entry. This means new evidence has been recorded but the compiled truth has not been rewritten to reflect it.
- **Unbalanced**: A page is unbalanced when it has 5 or more timeline entries added since the last compiled-truth update. This signals that evidence is accumulating faster than synthesis, and the compiled truth likely needs a rewrite.

Use `lint_links.py --stale` and `lint_links.py --unbalanced` to detect these conditions automatically.

---

## Typed Links

Frontmatter can carry typed relationships via the `links:` field:

```yaml
links:
  - {target: "microservices", type: "references"}
  - {target: "monolith", type: "contradicts"}
```

These typed links make relationships explicit and queryable. Wikilinks in prose (`[[target]]`) still work for navigation; frontmatter links are authoritative for graph queries and automated analysis.

### Supported Link Types

| Type | Meaning |
|------|---------|
| `references` | This page cites or builds on the target |
| `contradicts` | This page presents evidence that conflicts with the target |
| `depends_on` | This page requires the target to be understood first |
| `supersedes` | This page replaces or obsoletes the target |
| `authored_by` | The content was created by the target (a person or entity) |
| `works_at` | The subject of this page is affiliated with the target organization |
| `mentions` | The target is mentioned but not deeply engaged with |

The list is extensible — unknown types produce warnings but are never rejected. This allows domains to introduce specialized relationship types as needed.

---

## Frontmatter Reference

| Field | Required | Description |
|-------|----------|-------------|
| `aliases` | Yes | Alternative names for this page (helps Obsidian link matching) |
| `tags` | Yes | Page type: `concept`, `entity`, `topic`, `source`, `query` |
| `sources` | Yes | YAML list of wikilinks to raw source documents or wiki pages that informed this page. Use list syntax: `- "[[raw/path]]"` |
| `created` | Yes | Date page was first created |
| `updated` | Yes | Date page was last modified |
| `status` | Yes | `active`, `stub`, `needs-review`, `archived` |
| `type` | Entity only | `person`, `organization`, `system`, `product` |
| `source_type` | Source only | `article`, `paper`, `documentation`, `code`, `transcript` |
| `source_path` | Source only | Relative path to original file in `raw/` |
| `ingested` | Source only | Date the source was ingested |
| `query` | Query only | The original question that prompted the analysis |
| `links` | No | Typed relationships to other pages. List of `{target: "slug", type: "type"}` objects. See [Typed Links](#typed-links) for supported types. |
| `weight` | No | Manual importance boost (number, default 0). Added directly to `computed_score`. Set by user to surface preferred pages. |
| `computed_score` | No | Composite page score computed by `score_pages.py`. Do not edit manually — recalculated during ingest and lint. |
