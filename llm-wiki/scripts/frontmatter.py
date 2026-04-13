#!/usr/bin/env python3
"""Shared YAML frontmatter parser for all wiki scripts.

Uses PyYAML for correct parsing of all YAML features: inline lists,
block lists, nested objects, quoted values, multiline strings.

Note: PyYAML converts yes/no/true/false/on/off to Python booleans.
Wiki frontmatter uses string values like 'active', 'stub', 'archived'
which are unaffected. If you need a literal string 'true', quote it
in YAML: status: "true".
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(
    r"^---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*(?:\n|$)", re.DOTALL
)


def extract_frontmatter_block(content: str) -> str | None:
    """Return raw YAML text between --- delimiters, or None."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_RE.match(content)
    return m.group(1) if m else None


def parse(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_text). If no frontmatter found,
    returns ({}, full_content). Malformed YAML returns ({}, full_content)
    with a warning to stderr.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content

    body = content[m.end():]
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        print(f"Warning: malformed YAML frontmatter: {e}", file=sys.stderr)
        return {}, content

    if not isinstance(fm, dict):
        return {}, content

    return fm, body


def parse_typed_links(fm: dict) -> list[dict]:
    """Extract typed links from parsed frontmatter.

    Input: fm dict with optional 'links' key containing list of
    {target: str, type: str} dicts.
    Returns: list of {"target": str, "type": str} dicts.
    Skips malformed entries (missing target or type).
    """
    raw = fm.get("links")
    if not isinstance(raw, list):
        return []
    results = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        target = entry.get("target")
        link_type = entry.get("type")
        if target and link_type:
            results.append({"target": str(target), "type": str(link_type)})
    return results


def parse_aliases(fm: dict) -> list[str]:
    """Extract aliases list from parsed frontmatter.
    Returns list of strings, empty list if no aliases field.
    """
    raw = fm.get("aliases")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None]
    return []


def parse_tags(fm: dict) -> list[str]:
    """Extract tags list from parsed frontmatter.
    Returns list of strings, empty list if no tags field.
    """
    raw = fm.get("tags")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if item is not None]
    return []


def atomic_write(path: Path | str, content: str) -> None:
    """Write content to file atomically via temp file + rename.

    Creates a temp file in the same directory, writes content, then
    atomically replaces the target. If anything fails, the temp file
    is cleaned up and the original file is untouched.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
