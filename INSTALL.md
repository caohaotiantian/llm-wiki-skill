# Installation Guide

This skill follows the [Agent Skills specification](https://agentskills.io) — the `llm-wiki/` directory is the skill bundle containing `SKILL.md` and supporting files. Install it by placing the bundle where your agent discovers skills.

## Quick Reference

| Agent | Install to | Bootstrap file |
|-------|-----------|----------------|
| Claude Code | `~/.claude/skills/llm-wiki/` | `CLAUDE.md` |
| Codex CLI | `~/.agents/skills/llm-wiki/` | `AGENTS.md` |
| Gemini CLI | `~/.gemini/skills/llm-wiki/` | `GEMINI.md` |
| OpenCode | `~/.opencode/skills/llm-wiki/` | `.opencode.json` |
| Cursor | `.cursor/skills/llm-wiki/` | `.cursor/rules/llm-wiki.mdc` |
| Windsurf | `.windsurf/skills/llm-wiki/` | `.windsurf/rules/llm-wiki.md` |
| GitHub Copilot | N/A (reference in instructions) | `.github/copilot-instructions.md` |

---

## Claude Code

### Global install (available in all projects)

```bash
git clone https://github.com/caohaotiantian/llm-wiki-skill.git /tmp/llm-wiki-skill
cp -r /tmp/llm-wiki-skill/llm-wiki ~/.claude/skills/llm-wiki
```

### Project-scoped install

```bash
mkdir -p .claude/skills
cp -r /path/to/llm-wiki-skill/llm-wiki .claude/skills/llm-wiki
```

### Verification

Start a Claude Code session and ask:
> Set up a wiki knowledge base in ./my-wiki

Claude should automatically invoke the `llm-wiki` skill based on the description match.

You can also invoke it directly with `/llm-wiki`.

---

## Codex CLI (OpenAI)

### Global install

```bash
mkdir -p ~/.agents/skills
cp -r /path/to/llm-wiki-skill/llm-wiki ~/.agents/skills/llm-wiki
```

The `~/.agents/skills/` path is the cross-agent standard recognized by Codex.

Alternatively, use Codex's native path:

```bash
mkdir -p ~/.codex/skills
cp -r /path/to/llm-wiki-skill/llm-wiki ~/.codex/skills/llm-wiki
```

### Project-scoped install

```bash
mkdir -p .agents/skills
cp -r /path/to/llm-wiki-skill/llm-wiki .agents/skills/llm-wiki
```

---

## Gemini CLI (Google)

### Using the CLI installer

```bash
gemini skills install https://github.com/caohaotiantian/llm-wiki-skill.git --path llm-wiki
```

### Manual install (global)

```bash
mkdir -p ~/.gemini/skills
cp -r /path/to/llm-wiki-skill/llm-wiki ~/.gemini/skills/llm-wiki
```

Or use the cross-agent path:

```bash
mkdir -p ~/.agents/skills
cp -r /path/to/llm-wiki-skill/llm-wiki ~/.agents/skills/llm-wiki
```

### Project-scoped install

```bash
mkdir -p .gemini/skills
cp -r /path/to/llm-wiki-skill/llm-wiki .gemini/skills/llm-wiki
```

### Manage via CLI

```bash
gemini skills list            # List installed skills
gemini skills enable llm-wiki # Enable
gemini skills disable llm-wiki # Disable
```

---

## OpenCode

```bash
mkdir -p ~/.opencode/skills
cp -r /path/to/llm-wiki-skill/llm-wiki ~/.opencode/skills/llm-wiki
```

OpenCode auto-discovers all `SKILL.md` files under `~/.opencode/skills/`.

---

## Cursor

Cursor uses project-scoped skills only (no global skill directory).

### Install

```bash
mkdir -p .cursor/skills
cp -r /path/to/llm-wiki-skill/llm-wiki .cursor/skills/llm-wiki
```

### Add a rule file

Create `.cursor/rules/llm-wiki.mdc`:

```markdown
---
description: LLM Wiki — autonomous knowledge base in Obsidian
alwaysApply: false
---

When the user asks about building a wiki, knowledge base, or ingesting documents,
read and follow the skill at `.cursor/skills/llm-wiki/SKILL.md`.
```

---

## Windsurf

Windsurf uses project-scoped skills only.

### Install

```bash
mkdir -p .windsurf/skills
cp -r /path/to/llm-wiki-skill/llm-wiki .windsurf/skills/llm-wiki
```

### Add a rule file

Create `.windsurf/rules/llm-wiki.md`:

```markdown
When the user asks about building a wiki, knowledge base, or ingesting documents,
read and follow the skill at `.windsurf/skills/llm-wiki/SKILL.md`.
```

---

## GitHub Copilot

Copilot has no native skill discovery. Reference the skill in your project instructions.

### Install

```bash
cp -r /path/to/llm-wiki-skill/llm-wiki .github/llm-wiki
```

### Add to instructions

Append to `.github/copilot-instructions.md`:

```markdown
## LLM Wiki Skill

When asked to build a knowledge base, wiki, or ingest documents, read and follow
the instructions in `.github/llm-wiki/SKILL.md`. This skill handles the full
lifecycle: vault setup, source ingestion, querying, and linting.
```

---

## Symlink approach (multi-agent)

If you use multiple agents on the same project, keep one canonical copy and symlink:

```bash
# Clone once
git clone https://github.com/caohaotiantian/llm-wiki-skill.git ~/.local/share/llm-wiki-skill

# Symlink to each agent's skill directory
ln -s ~/.local/share/llm-wiki-skill/llm-wiki ~/.claude/skills/llm-wiki
ln -s ~/.local/share/llm-wiki-skill/llm-wiki ~/.agents/skills/llm-wiki
ln -s ~/.local/share/llm-wiki-skill/llm-wiki ~/.gemini/skills/llm-wiki
```

This way, `git pull` in the source repo updates all agents at once.

---

## Installing dependencies

The skill works without any Python dependencies — the agent can read files directly. For better extraction quality (PDF, DOCX, PPTX, etc.), install Python 3.10+ and docling:

```bash
pip install docling pip-system-certs
```

> `pip-system-certs` ensures Python uses your system's certificate store, preventing SSL/TLS errors when docling downloads models on first run.

## Agent self-install

You can also just tell your agent to install the skill for you:

> "Install the LLM Wiki skill from https://github.com/caohaotiantian/llm-wiki-skill and set up a knowledge base in ./my-wiki"

The agent will clone the repo, copy the skill bundle to the right location, install dependencies, and initialize a wiki vault.
