# Obsidian Operating Reference

A comprehensive guide to Obsidian's programmatic interfaces and flavored markdown syntax. Read the relevant section when you need to interact with Obsidian beyond basic file I/O.

## Table of Contents
- [Obsidian Flavored Markdown](#obsidian-flavored-markdown)
- [URI Scheme](#uri-scheme)
- [CLI (v1.12.0+)](#cli)
- [Vault Configuration](#vault-configuration)
- [Recommended Plugins](#recommended-plugins)
- [Retrieval Patterns](#retrieval-patterns)

---

## Obsidian Flavored Markdown

Obsidian extends standard markdown with several features. Use these in wiki pages to take full advantage of Obsidian's capabilities.

### Internal Links (Wikilinks)

```markdown
[[Note Name]]                          Link to note
[[Note Name|Display Text]]             Custom display text
[[Note Name#Heading]]                  Link to heading
[[Note Name#^block-id]]                Link to block
[[#Heading in same note]]              Same-note heading link
```

Use `[[wikilinks]]` for all vault-internal links — Obsidian tracks renames automatically. Use standard `[text](url)` only for external URLs.

Block IDs: append ` ^block-id` to any paragraph to make it linkable. For lists and blockquotes, place the ID on a separate line after the block.

### Embeds

```markdown
![[Note Name]]                         Embed full note
![[Note Name#Heading]]                 Embed specific section
![[Note Name#^block-id]]               Embed specific block
![[image.png]]                         Embed image
![[image.png|300]]                     Image with width (aspect ratio maintained)
![[document.pdf]]                      Embed PDF
![[document.pdf#page=3]]               Embed specific PDF page
![[audio.mp3]]                         Embed audio
```

Embed search results inline:
````markdown
```query
tag:#project status:done
```
````

### Callouts

```markdown
> [!note]
> Basic callout.

> [!warning] Custom Title
> Callout with a custom title.

> [!faq]- Collapsed by default
> Foldable callout (use `-` for collapsed, `+` for expanded).

> [!question] Outer
> > [!note] Nested
> > Nested callout inside another.
```

Available callout types:

| Type | Aliases | Use for |
|------|---------|---------|
| `note` | — | General notes |
| `abstract` | `summary`, `tldr` | Summaries |
| `info` | — | Informational |
| `todo` | — | Action items |
| `tip` | `hint`, `important` | Tips and highlights |
| `success` | `check`, `done` | Completed items |
| `question` | `help`, `faq` | Open questions |
| `warning` | `caution`, `attention` | Warnings |
| `failure` | `fail`, `missing` | Failed or missing items |
| `danger` | `error` | Critical issues |
| `bug` | — | Known bugs |
| `example` | — | Examples |
| `quote` | `cite` | Citations |

### Properties (Frontmatter)

```yaml
---
title: My Note Title
date: 2024-01-15
tags:
  - concept
  - architecture
aliases:
  - Alternative Name
cssclasses:
  - custom-class
status: active
rating: 4.5
completed: false
due: 2024-02-01T14:30:00
---
```

Supported property types: Text, Number, Checkbox (`true`/`false`), Date (`YYYY-MM-DD`), Date & Time (`YYYY-MM-DDTHH:MM:SS`), List (YAML list), Links (`"[[Other Note]]"`).

Default properties recognized by Obsidian: `tags`, `aliases`, `cssclasses`.

### Tags

```markdown
#tag                    Inline tag
#nested/tag             Nested hierarchy
#tag-with-dashes
#tag_with_underscores
```

Tags can contain letters (any language), numbers (not as first char), underscores, hyphens, and forward slashes (for nesting).

### Other Syntax

```markdown
==Highlighted text==                   Highlight
%%Hidden comment%%                     Comment (invisible in reading view)
$e^{i\pi} + 1 = 0$                   Inline LaTeX
$$\frac{a}{b} = c$$                   Block LaTeX
Text with a footnote[^1].             Footnote reference
[^1]: Footnote content.               Footnote definition
Inline footnote.^[This is inline.]    Inline footnote
```

### Provenance Markers

Use inline footnotes to mark the confidence level of claims:

- No marker = **extracted** (source explicitly states this)
- `^[inferred]` = **LLM-synthesized** (a connection, generalization, or implication not directly stated)
- `^[ambiguous]` = **uncertain** (sources disagree or source is unclear)

Example:
```markdown
- Transformers use self-attention for sequence modeling.
- This suggests attention mechanisms could replace RNNs entirely. ^[inferred]
- The training cost was reported as $4.6M, though other estimates differ. ^[ambiguous]
```

---

## URI Scheme

The URI scheme works whether or not Obsidian is running. On macOS, invoke with `open "obsidian://..."`.

All parameter values must be URI-encoded (`/` → `%2F`, spaces → `%20`).

### Open a vault or file

```bash
# Open vault by name
open "obsidian://open?vault=my%20vault"

# Open vault by absolute path
open "obsidian://open?path=%2FUsers%2Fme%2Fvaults%2Fmy-wiki"

# Open a specific file
open "obsidian://open?vault=my%20vault&file=wiki%2Fconcepts%2Fmicroservices"

# Open file at a heading
open "obsidian://open?vault=my%20vault&file=my%20note%23Heading%20Name"

# Open in a new tab/split/window
open "obsidian://open?vault=my%20vault&file=my%20note&paneType=tab"
```

Shorthand: `obsidian://vault/my vault/my note` or `obsidian:///absolute/path/to/note`

### Create a new note

```bash
# Create with content
open "obsidian://new?vault=my%20vault&name=New%20Note&content=Hello%20World"

# Create at a specific path
open "obsidian://new?vault=my%20vault&file=wiki%2Fconcepts%2Fnew-concept"

# Create silently (don't open in editor)
open "obsidian://new?vault=my%20vault&name=New%20Note&content=Hello&silent=true"

# Append to existing file
open "obsidian://new?vault=my%20vault&name=Existing%20Note&content=Appended&append=true"

# Overwrite existing file
open "obsidian://new?vault=my%20vault&name=Note&content=Replaced&overwrite=true"
```

### Search

```bash
open "obsidian://search?vault=my%20vault&query=microservices"
```

### Daily note

```bash
open "obsidian://daily?vault=my%20vault"
```

### Vault manager

```bash
open "obsidian://choose-vault"
```

---

## CLI

The Obsidian CLI was introduced in **v1.12.0** (February 2026). It requires Obsidian to be running, and communicates with the app to read/write vault data.

Run `obsidian help` for the always-current command list.

### Syntax

- Parameters take values with `=`: `obsidian create name="My Note" content="Hello"`
- Flags are boolean: `obsidian create name="My Note" silent overwrite`
- Multiline content: use `\n` for newline, `\t` for tab
- Quote values with spaces: `name="My Note Title"`

### Targeting

```bash
# Target a specific vault (first parameter)
obsidian vault="My Vault" search query="test"

# Target a file by wikilink-style name (resolves like [[name]])
obsidian read file="My Note"

# Target a file by exact vault-relative path
obsidian read path="wiki/concepts/microservices.md"

# Without file/path, uses the currently active file
```

### Core Commands

```bash
# Read a note's content
obsidian read file="My Note"

# Create a new note
obsidian create name="New Note" content="# Hello"
obsidian create name="New Note" template="Template Name" silent

# Append content to a note
obsidian append file="My Note" content="- New item"

# Search vault
obsidian search query="search term" limit=10

# Rename a note (updates all backlinks)
obsidian rename file="Old Name" name="New Name"

# Get backlinks to a note
obsidian backlinks file="My Note"

# List all tags (with counts)
obsidian tags sort=count counts
```

### Daily Note Commands

```bash
obsidian daily:read                    # Read today's daily note
obsidian daily:append content="- Task" # Append to daily note
obsidian daily:path                    # Get daily note file path
```

### Property Commands

```bash
# Set a frontmatter property
obsidian property:set name="status" value="done" file="My Note"
```

### Global Flags

- `--copy`: Copy command output to clipboard
- `silent`: Don't open the file in the GUI after creating
- `total`: On list commands, return a count instead

### When to Use CLI vs Filesystem

| Scenario | Approach |
|----------|----------|
| Bulk file creation/editing | Filesystem (faster, no app dependency) |
| Reading note content | Either (filesystem is simpler) |
| Rename with backlink updates | CLI (`obsidian rename` — updates all references) |
| Search across vault | CLI (`obsidian search`) or grep (both work) |
| Set properties | CLI (`obsidian property:set`) or edit frontmatter directly |
| Get backlinks | CLI (`obsidian backlinks`) |
| Trigger plugin actions | CLI or URI scheme |
| Open specific file in GUI | URI scheme (`obsidian://open?...`) |

For most wiki operations, direct filesystem access is preferred — it's faster, doesn't require Obsidian to be running, and handles bulk operations well. Use the CLI when you need Obsidian-specific features like backlink resolution, rename propagation, or plugin interaction.

---

## Vault Configuration

### Minimal `.obsidian/app.json`

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

Key settings:
- `alwaysUpdateLinks`: Automatically update links when files are moved/renamed
- `useMarkdownLinks: false`: Use `[[wikilinks]]` instead of `[]()`
- `newLinkFormat: "relative"`: Use relative paths in links

### Registering a Vault

```bash
# macOS — opens vault in Obsidian and registers it
open "obsidian://open?path=$(python3 -c 'import urllib.parse; print(urllib.parse.quote("/path/to/vault"))')"
```

Or simply open Obsidian → "Open folder as vault" → select the directory.

---

## Recommended Plugins

These optional plugins enhance the wiki experience:

| Plugin | Purpose | How it helps |
|--------|---------|-------------|
| **Dataview** | Query frontmatter as a database | Dynamic tables of pages by status, tag, date, etc. |
| **Graph Analysis** | Enhanced graph view | Visualize connection clusters and bridge nodes |
| **Templater** | Advanced templates | Quick manual page creation with auto-filled fields |
| **Obsidian Git** | Auto-backup to git | Version history and multi-device sync |

### Dataview Query Examples

List all pages with status "needs-review":
````markdown
```dataview
TABLE sources, updated
FROM "wiki"
WHERE status = "needs-review"
SORT updated DESC
```
````

List all pages tagged "concept":
````markdown
```dataview
LIST
FROM #concept
SORT file.name ASC
```
````

Count pages by category:
````markdown
```dataview
TABLE length(rows) AS Count
FROM "wiki"
GROUP BY tags[0] AS Category
```
````

---

## Retrieval Patterns

When querying the wiki, use the cheapest retrieval method that satisfies the need:

| Need | Method | Cost |
|------|--------|------|
| Does a page exist? | Check `index.md` or glob for filename | Cheapest |
| Quick summary | Read `summary:` in frontmatter | Cheap |
| Specific claim | `grep -A 5 "search term" <file>` | Medium |
| Full page content | Read the file | Expensive |
| Cross-vault relationships | Grep for `[[page-name]]` across vault | Case-by-case |
| Backlinks to a page | `obsidian backlinks file="page"` (CLI) or grep `\[\[page\]\]` | Medium |

For larger wikis (100+ pages), prefer grep/search over reading `index.md` — the index is a coordination file, not a search index.
