# Wiki Page Templates

Default templates for wiki pages. These are starting points — adapt the structure to fit the domain.

## Table of Contents
- [Concept Page](#concept-page)
- [Entity Page](#entity-page)
- [Source Summary Page](#source-summary-page)
- [Topic Page](#topic-page)
- [Frontmatter Reference](#frontmatter-reference)

---

## Concept Page

For ideas, principles, patterns, methodologies.

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

## Frontmatter Reference

| Field | Required | Description |
|-------|----------|-------------|
| `aliases` | Yes | Alternative names for this page (helps Obsidian link matching) |
| `tags` | Yes | Page type: `concept`, `entity`, `topic`, `source` |
| `sources` | Yes | Links to raw source documents that informed this page |
| `created` | Yes | Date page was first created |
| `updated` | Yes | Date page was last modified |
| `status` | Yes | `active`, `stub`, `needs-review`, `archived` |
| `type` | Entity only | `person`, `organization`, `system`, `product` |
| `source_type` | Source only | `article`, `paper`, `documentation`, `code`, `transcript` |
| `source_path` | Source only | Relative path to original file in `raw/` |
| `ingested` | Source only | Date the source was ingested |
