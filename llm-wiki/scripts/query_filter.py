#!/usr/bin/env python3
"""
Attribute-based filtering for wiki pages.

Parses a simplified filter syntax and matches against page frontmatter.

Filter syntax examples:
    type=concept tag=strategy confidence>=0.7 updated_since=30d status=active
    has=confidence  tag!=draft

Operators:
    =   exact match (or membership in list fields like tags)
    !=  not equal
    >= <= > <   numeric comparison
    updated_since=Nd   file modified within N days
    has=field   field exists in frontmatter

Usage:
    python query_filter.py <vault-path> --where "type=concept tag=strategy"
    python query_filter.py <vault-path> --where "updated_since=30d" --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Frontmatter parsing (self-contained)
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", re.DOTALL
)


def _parse_frontmatter(content: str) -> dict[str, Any]:
    """Minimal YAML frontmatter parser (no PyYAML dependency).

    Handles: scalar values, inline lists ``[a, b]``, and block lists.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}

    fm: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in m.group(1).splitlines():
        # block list item
        if current_key and re.match(r"^\s+-\s+", line):
            val = line.strip().lstrip("- ").strip().strip("\"'")
            if current_list is not None:
                current_list.append(val)
            continue
        else:
            # flush any pending block list
            if current_key and current_list is not None:
                fm[current_key] = current_list
                current_key = None
                current_list = None

        colon = line.find(":")
        if colon == -1:
            continue
        key = line[:colon].strip()
        raw_val = line[colon + 1 :].strip()

        if not key:
            continue

        # inline list
        if raw_val.startswith("["):
            inner = raw_val.strip("[]")
            items = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
            fm[key] = items
            current_key = None
            current_list = None
        elif raw_val == "" or raw_val == "~" or raw_val == "null":
            # could be start of block list
            current_key = key
            current_list = []
        else:
            fm[key] = raw_val.strip("\"'")
            current_key = None
            current_list = None

    # flush trailing block list
    if current_key and current_list is not None:
        fm[current_key] = current_list

    return fm


# ---------------------------------------------------------------------------
# Condition model
# ---------------------------------------------------------------------------

_OPERATOR_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(!=|>=|<=|>|<|=)(.+)$")


@dataclass
class Condition:
    field: str
    op: str
    value: str


def parse_filter_string(where: str) -> list[Condition]:
    """Parse a space-separated filter string into a list of Conditions.

    Special forms:
        has=field        -> Condition(field="has", op="=", value="field")
        updated_since=Nd -> Condition(field="updated_since", op="=", value="Nd")
    """
    conditions: list[Condition] = []
    if not where or not where.strip():
        return conditions

    # Tokenize respecting quoted values
    tokens = _tokenize(where)
    for token in tokens:
        m = _OPERATOR_RE.match(token)
        if not m:
            continue
        conditions.append(Condition(field=m.group(1), op=m.group(2), value=m.group(3)))
    return conditions


def _tokenize(s: str) -> list[str]:
    """Split on whitespace but respect quoted values."""
    tokens: list[str] = []
    buf = ""
    in_quote = ""
    for ch in s:
        if ch in ('"', "'") and not in_quote:
            in_quote = ch
            buf += ch
        elif ch == in_quote:
            in_quote = ""
            buf += ch
        elif ch == " " and not in_quote:
            if buf:
                tokens.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def matches_conditions(
    fm: dict[str, Any],
    conditions: list[Condition],
    file_path: str | None = None,
) -> bool:
    """Check whether frontmatter *fm* satisfies all *conditions*."""
    for cond in conditions:
        if not _check_one(fm, cond, file_path):
            return False
    return True


def _check_one(fm: dict[str, Any], cond: Condition, file_path: str | None) -> bool:
    # Special: has=field
    if cond.field == "has":
        return cond.value in fm

    # Special: updated_since=Nd
    if cond.field == "updated_since":
        return _check_updated_since(cond.value, file_path)

    # Special: tag= checks inside tags list
    if cond.field == "tag":
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        return _compare_value(tags, cond.op, cond.value, is_list=True)

    # Special: type= checks first tag or explicit type field
    if cond.field == "type":
        val = fm.get("type")
        if val is None:
            tags = fm.get("tags", [])
            val = tags[0] if isinstance(tags, list) and tags else None
        if val is None:
            return cond.op == "!="
        return _compare_value(val, cond.op, cond.value)

    # Generic field
    val = fm.get(cond.field)
    if val is None:
        return cond.op == "!="
    return _compare_value(val, cond.op, cond.value)


def _compare_value(
    actual: Any, op: str, expected: str, is_list: bool = False
) -> bool:
    if is_list and isinstance(actual, list):
        if op == "=":
            return expected in actual
        if op == "!=":
            return expected not in actual
        return False

    # Try numeric comparison
    if op in (">=", "<=", ">", "<"):
        try:
            a = float(actual)
            b = float(expected)
        except (ValueError, TypeError):
            return False
        if op == ">=":
            return a >= b
        if op == "<=":
            return a <= b
        if op == ">":
            return a > b
        if op == "<":
            return a < b

    actual_str = str(actual).strip("\"'")
    if op == "=":
        return actual_str == expected
    if op == "!=":
        return actual_str != expected
    return False


def _check_updated_since(value: str, file_path: str | None) -> bool:
    """Check if file was modified within the last N days."""
    m = re.match(r"^(\d+)d$", value)
    if not m or not file_path:
        return False
    days = int(m.group(1))
    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        return False
    cutoff = time.time() - days * 86400
    return mtime >= cutoff


# ---------------------------------------------------------------------------
# SQL generation mode (for future SQLite index)
# ---------------------------------------------------------------------------

def conditions_to_sql(conditions: list[Condition]) -> tuple[str, list[Any]]:
    """Convert conditions to a SQL WHERE clause fragment and params.

    Returns ``("field1 = ? AND field2 >= ?", [val1, val2])``.
    Skips conditions that can't be expressed in SQL (updated_since, has).
    """
    clauses: list[str] = []
    params: list[Any] = []
    op_map = {"=": "=", "!=": "!=", ">=": ">=", "<=": "<=", ">": ">", "<": "<"}

    for cond in conditions:
        if cond.field in ("updated_since", "has"):
            continue
        sql_op = op_map.get(cond.op)
        if not sql_op:
            continue
        if cond.field == "tag":
            clauses.append("tags LIKE ?")
            params.append(f"%{cond.value}%")
        elif cond.field == "type":
            clauses.append("type " + sql_op + " ?")
            params.append(cond.value)
        else:
            clauses.append(f"{cond.field} {sql_op} ?")
            params.append(cond.value)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

def filter_pages(
    vault_path: str | Path,
    where: str,
) -> list[dict[str, Any]]:
    """Return matching pages from *vault_path*/wiki/.

    Each result is ``{"path": ..., "slug": ..., "frontmatter": ...}``.
    """
    vault_path = Path(vault_path)
    wiki_dir = vault_path / "wiki"
    conditions = parse_filter_string(where)

    results: list[dict[str, Any]] = []
    if not wiki_dir.is_dir():
        return results

    for fp in sorted(wiki_dir.rglob("*.md")):
        content = fp.read_text(encoding="utf-8", errors="replace")
        fm = _parse_frontmatter(content)
        if matches_conditions(fm, conditions, file_path=str(fp)):
            results.append(
                {
                    "path": str(fp),
                    "slug": fp.stem,
                    "frontmatter": fm,
                }
            )
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Filter wiki pages by frontmatter attributes"
    )
    parser.add_argument("vault", help="Path to the vault root")
    parser.add_argument(
        "--where", required=True, help='Filter expression, e.g. "type=concept tag=strategy"'
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args(argv)
    results = filter_pages(args.vault, args.where)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("No matching pages.")
        else:
            for r in results:
                print(f"  {r['slug']}  ({r['path']})")


if __name__ == "__main__":
    main()
