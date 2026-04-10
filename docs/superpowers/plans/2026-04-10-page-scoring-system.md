# Page Scoring System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composite scoring system that computes personalized page weights from five indicators (query frequency, access count, cross-reference density, manual weight, priority tags) and surfaces high-value content first across Query, Ingest, and Lint operations.

**Architecture:** A standalone `score_pages.py` script reads counters from `.stats.json` + scans wikilinks + reads frontmatter, then writes `computed_score` to each page's YAML frontmatter. The agent updates counters in `.stats.json` during operations and calls the script for recalculation. Integration touches SKILL.md (Query, Ingest, Lint, Setup sections), schema.md (frontmatter reference), and adds the new script.

**Tech Stack:** Python 3 (stdlib only — json, re, os, argparse, pathlib). No external dependencies.

**Spec:** `docs/superpowers/specs/2026-04-10-page-scoring-system-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `llm-wiki/scripts/score_pages.py` | Compute composite scores, write to frontmatter |
| Create | `tests/test_score_pages.py` | Unit tests for scoring logic |
| Modify | `llm-wiki/SKILL.md` | Setup, Ingest, Query, Lint, Vault Structure, Bundled Resources sections |
| Modify | `llm-wiki/references/schema.md` | Add `weight` and `computed_score` to frontmatter reference |

---

### Task 1: Core scoring computation (pure functions, no I/O)

**Files:**
- Create: `tests/test_score_pages.py`
- Create: `llm-wiki/scripts/score_pages.py`

- [ ] **Step 1: Write failing tests for normalization and score computation**

Create `tests/test_score_pages.py`:

```python
#!/usr/bin/env python3
"""Tests for score_pages.py scoring logic."""

import sys
import os

# Add scripts dir to path so we can import score_pages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from score_pages import normalize_values, compute_score


def test_normalize_values_basic():
    """Normalize maps max to 10, zero stays zero."""
    raw = {"a": 10, "b": 5, "c": 0}
    result = normalize_values(raw)
    assert result == {"a": 10.0, "b": 5.0, "c": 0.0}


def test_normalize_values_all_zero():
    """When all values are zero, all normalized values are zero."""
    raw = {"a": 0, "b": 0}
    result = normalize_values(raw)
    assert result == {"a": 0.0, "b": 0.0}


def test_normalize_values_single_page():
    """Single page with nonzero value normalizes to 10."""
    raw = {"a": 7}
    result = normalize_values(raw)
    assert result == {"a": 10.0}


def test_normalize_values_empty():
    """Empty input returns empty output."""
    assert normalize_values({}) == {}


def test_compute_score_basic():
    """Compute score with all indicators."""
    score = compute_score(
        norm_query_freq=10.0,
        norm_access_count=10.0,
        norm_cross_ref=10.0,
        manual_weight=0,
        tag_bonus=0,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    # 0.4*10 + 0.3*10 + 0.3*10 = 10.0
    assert score == 10.0


def test_compute_score_with_manual_weight():
    """Manual weight is additive."""
    score = compute_score(
        norm_query_freq=5.0,
        norm_access_count=5.0,
        norm_cross_ref=5.0,
        manual_weight=3,
        tag_bonus=0,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    # 0.4*5 + 0.3*5 + 0.3*5 + 3 = 2+1.5+1.5+3 = 8.0
    assert score == 8.0


def test_compute_score_with_tag_bonus():
    """Tag bonus is additive."""
    score = compute_score(
        norm_query_freq=0.0,
        norm_access_count=0.0,
        norm_cross_ref=0.0,
        manual_weight=0,
        tag_bonus=10,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    assert score == 10.0


def test_compute_score_rounds_to_one_decimal():
    """Score is rounded to 1 decimal place."""
    score = compute_score(
        norm_query_freq=3.33,
        norm_access_count=3.33,
        norm_cross_ref=3.33,
        manual_weight=0,
        tag_bonus=0,
        weights={"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
    )
    # 0.4*3.33 + 0.3*3.33 + 0.3*3.33 = 1.332 + 0.999 + 0.999 = 3.33
    assert score == 3.3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'score_pages'`

- [ ] **Step 3: Write the pure functions in score_pages.py**

Create `llm-wiki/scripts/score_pages.py` with just the computation functions:

```python
#!/usr/bin/env python3
"""
Compute composite page scores for wiki pages.

Reads counters from .stats.json, scans wikilinks for cross-reference density,
reads frontmatter for manual weight and priority tags, then writes computed_score
to each page's YAML frontmatter.

Usage:
    python score_pages.py <vault-path>                              # full recalc
    python score_pages.py <vault-path> --pages wiki/a.md wiki/b.md  # incremental
    python score_pages.py <vault-path> --json                       # JSON output
"""

from __future__ import annotations


def normalize_values(raw: dict[str, int | float]) -> dict[str, float]:
    """Normalize values to 0-10 scale relative to max.

    The page with the highest value gets 10. Zero stays zero.
    If all values are zero, all normalized values are zero.
    """
    if not raw:
        return {}
    max_val = max(raw.values())
    if max_val == 0:
        return {k: 0.0 for k in raw}
    return {k: round(v / max_val * 10, 2) for k, v in raw.items()}


def compute_score(
    norm_query_freq: float,
    norm_access_count: float,
    norm_cross_ref: float,
    manual_weight: int | float,
    tag_bonus: int | float,
    weights: dict[str, float],
) -> float:
    """Compute composite score from normalized indicators + manual adjustments.

    Formula:
        score = (w1 * norm_query_freq)
              + (w2 * norm_access_count)
              + (w3 * norm_cross_ref)
              + manual_weight
              + tag_bonus

    Returns score rounded to 1 decimal place.
    """
    score = (
        weights["query_frequency"] * norm_query_freq
        + weights["access_count"] * norm_access_count
        + weights["cross_ref_density"] * norm_cross_ref
        + manual_weight
        + tag_bonus
    )
    return round(score, 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_score_pages.py llm-wiki/scripts/score_pages.py
git commit -m "feat: add core scoring computation functions (normalize, compute_score)"
```

---

### Task 2: Frontmatter parsing and writing

**Files:**
- Modify: `tests/test_score_pages.py`
- Modify: `llm-wiki/scripts/score_pages.py`

- [ ] **Step 1: Write failing tests for frontmatter parsing and writing**

Append to `tests/test_score_pages.py`:

```python
import tempfile

from score_pages import parse_weight_and_tags, write_computed_score


def test_parse_weight_and_tags_defaults():
    """No weight or priority tags returns defaults."""
    content = "---\naliases: []\ntags: [concept]\nstatus: active\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 0
    assert tags == []


def test_parse_weight_and_tags_with_weight():
    """Reads numeric weight from frontmatter."""
    content = "---\nweight: 5\ntags: [concept]\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 5
    assert tags == []


def test_parse_weight_and_tags_with_priority_tags():
    """Extracts priority tags from tag list."""
    content = "---\ntags: [concept, pinned, priority/high]\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 0
    assert set(tags) == {"pinned", "priority/high"}


def test_parse_weight_and_tags_list_format():
    """Handles YAML list format for tags."""
    content = "---\ntags:\n  - entity\n  - priority/medium\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert tags == ["priority/medium"]


def test_parse_weight_and_tags_float_weight():
    """Handles float weight values."""
    content = "---\nweight: 2.5\ntags: [concept]\n---\n# Page\n"
    weight, tags = parse_weight_and_tags(content)
    assert weight == 2.5


def test_write_computed_score_new_field():
    """Adds computed_score to frontmatter that doesn't have it."""
    content = "---\naliases: []\ntags: [concept]\nstatus: active\n---\n# Page\n\nBody text.\n"
    result = write_computed_score(content, 7.3)
    assert "computed_score: 7.3" in result
    assert "# Page" in result
    assert "Body text." in result


def test_write_computed_score_update_existing():
    """Updates existing computed_score value."""
    content = "---\naliases: []\ncomputed_score: 3.1\ntags: [concept]\n---\n# Page\n"
    result = write_computed_score(content, 8.5)
    assert "computed_score: 8.5" in result
    assert "computed_score: 3.1" not in result


def test_write_computed_score_no_frontmatter():
    """Returns content unchanged if no frontmatter."""
    content = "# Page\n\nNo frontmatter here.\n"
    result = write_computed_score(content, 5.0)
    assert result == content
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: New tests FAIL with `ImportError: cannot import name 'parse_weight_and_tags'`

- [ ] **Step 3: Implement frontmatter parsing and writing**

Add to `llm-wiki/scripts/score_pages.py`:

```python
import re


PRIORITY_TAGS = {"pinned", "priority/high", "priority/medium", "priority/low"}


def parse_weight_and_tags(content: str) -> tuple[int | float, list[str]]:
    """Extract manual weight and priority tags from page frontmatter.

    Returns (weight, priority_tags) where priority_tags is a list of
    matching tag strings from PRIORITY_TAGS.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content, re.DOTALL)
    if not match:
        return 0, []

    fm = match.group(1)

    # Parse weight
    weight: int | float = 0
    weight_match = re.search(r"^weight:\s*(.+)$", fm, re.MULTILINE)
    if weight_match:
        try:
            val = weight_match.group(1).strip()
            weight = float(val) if "." in val else int(val)
        except ValueError:
            pass

    # Parse tags — inline format: tags: [a, b, c]
    priority_tags: list[str] = []
    inline = re.search(r"^tags:\s*\[([^\]]*)\]", fm, re.MULTILINE)
    if inline:
        raw_tags = [t.strip().strip("\"'") for t in inline.group(1).split(",")]
        priority_tags = [t for t in raw_tags if t in PRIORITY_TAGS]
    else:
        # List format: tags:\n  - a\n  - b
        list_match = re.search(r"^tags:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.MULTILINE)
        if list_match:
            items = re.findall(r"^\s+-\s+(.+)", list_match.group(1), re.MULTILINE)
            priority_tags = [
                t.strip().strip("\"'") for t in items if t.strip().strip("\"'") in PRIORITY_TAGS
            ]

    return weight, priority_tags


def write_computed_score(content: str, score: float) -> str:
    """Write or update computed_score in page frontmatter.

    If frontmatter exists and has computed_score, update it.
    If frontmatter exists without computed_score, insert before closing ---.
    If no frontmatter, return content unchanged.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^(---\s*\n)(.*?)(\n---)", content, re.DOTALL)
    if not match:
        return content

    prefix = match.group(1)
    fm = match.group(2)
    suffix = match.group(3)
    rest = content[match.end():]

    # Update existing or insert new
    if re.search(r"^computed_score:\s*", fm, re.MULTILINE):
        fm = re.sub(r"^computed_score:\s*.*$", f"computed_score: {score}", fm, flags=re.MULTILINE)
    else:
        fm = fm + f"\ncomputed_score: {score}"

    return prefix + fm + suffix + rest
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_score_pages.py llm-wiki/scripts/score_pages.py
git commit -m "feat: add frontmatter parsing (weight, tags) and computed_score writing"
```

---

### Task 3: Cross-reference density scanning

**Files:**
- Modify: `tests/test_score_pages.py`
- Modify: `llm-wiki/scripts/score_pages.py`

- [ ] **Step 1: Write failing tests for cross-reference counting**

Append to `tests/test_score_pages.py`:

```python
from score_pages import count_incoming_links


def test_count_incoming_links_basic(tmp_path):
    """Counts incoming [[wikilinks]] per target page."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntags: [concept]\n---\n# A\nSee [[b]] and [[c]].\n")
    (wiki / "b.md").write_text("---\ntags: [concept]\n---\n# B\nRelated to [[a]] and [[c]].\n")
    (wiki / "c.md").write_text("---\ntags: [concept]\n---\n# C\nStandalone.\n")

    counts = count_incoming_links(tmp_path)
    # a.md is linked from b.md → 1
    assert counts.get("wiki/a.md", 0) == 1
    # b.md is linked from a.md → 1
    assert counts.get("wiki/b.md", 0) == 1
    # c.md is linked from a.md and b.md → 2
    assert counts.get("wiki/c.md", 0) == 2


def test_count_incoming_links_pipe_syntax(tmp_path):
    """Pipe syntax [[target|display]] counts toward target."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "microservices.md").write_text("---\ntags: [concept]\n---\n# MS\n")
    (wiki / "overview.md").write_text(
        "---\ntags: [topic]\n---\n# Overview\nSee [[microservices|Microservices Architecture]].\n"
    )

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/microservices.md", 0) == 1


def test_count_incoming_links_skips_code_blocks(tmp_path):
    """Links inside fenced code blocks are not counted."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntags: [concept]\n---\n# A\n```\n[[b]]\n```\n")
    (wiki / "b.md").write_text("---\ntags: [concept]\n---\n# B\n")

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/b.md", 0) == 0


def test_count_incoming_links_heading_links(tmp_path):
    """[[target#heading]] counts toward target page."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntags: [concept]\n---\n# A\nSee [[b#details]].\n")
    (wiki / "b.md").write_text("---\ntags: [concept]\n---\n# B\n## Details\n")

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/b.md", 0) == 1


def test_count_incoming_links_empty_wiki(tmp_path):
    """Empty wiki returns empty dict."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    counts = count_incoming_links(tmp_path)
    assert counts == {}
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_score_pages.py::test_count_incoming_links_basic -v`
Expected: FAIL with `ImportError: cannot import name 'count_incoming_links'`

- [ ] **Step 3: Implement cross-reference counting**

Add to `llm-wiki/scripts/score_pages.py`. Reuse `scan_file_for_links` pattern from `lint_links.py` but simplified — only needs link targets, not full diagnostics:

```python
import os
from pathlib import Path


# Matches [[target]], [[target|display]], [[target#heading]]
# Does NOT match embeds (![[...]])
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]]+?)\]\]")


def _extract_target(wikilink_content: str) -> str:
    """Extract resolution target: [[target|display]] → target, [[target#h]] → target."""
    target = wikilink_content.split("|")[0].split("#")[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def _collect_wiki_files(vault_path: Path) -> dict[str, str]:
    """Collect all .md files under wiki/.

    Returns {normalized_stem: relative_path} for resolving link targets.
    """
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return {}

    files: dict[str, str] = {}
    for root, dirs, filenames in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in filenames:
            if fname.endswith(".md") and not fname.endswith(".snapshot.md"):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, vault_path)
                stem = os.path.splitext(fname)[0].lower()
                files[stem] = rel
    return files


def _scan_links_in_file(file_path: str) -> list[str]:
    """Extract all wikilink targets from a file, skipping frontmatter and code blocks."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []

    targets = []
    in_frontmatter = False
    code_fence_marker = ""

    for i, line in enumerate(lines):
        if i == 0 and line.strip() == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if line.strip() in ("---", "..."):
                in_frontmatter = False
            continue

        stripped = line.strip()
        if not code_fence_marker:
            fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence_match:
                code_fence_marker = fence_match.group(1)
                continue
        else:
            fence_char = code_fence_marker[0]
            fence_len = len(code_fence_marker)
            close_match = re.match(
                r"^" + re.escape(fence_char) + r"{" + str(fence_len) + r",}\s*$",
                stripped,
            )
            if close_match:
                code_fence_marker = ""
            continue

        # Strip inline code spans
        scannable = re.sub(r"`[^`]+`", "", line)
        for match in WIKILINK_RE.finditer(scannable):
            target = _extract_target(match.group(1))
            if target:
                targets.append(target)

    return targets


def count_incoming_links(vault_path: Path) -> dict[str, int]:
    """Count incoming wikilinks for each wiki page.

    Returns {relative_path: count} for all pages that have at least one incoming link.
    """
    vault_path = Path(vault_path)
    file_index = _collect_wiki_files(vault_path)
    if not file_index:
        return {}

    counts: dict[str, int] = {}

    for stem, rel_path in file_index.items():
        abs_path = os.path.join(str(vault_path), rel_path)
        targets = _scan_links_in_file(abs_path)
        for target in targets:
            norm = target.lower()
            if norm in file_index:
                target_path = file_index[norm]
                counts[target_path] = counts.get(target_path, 0) + 1

    return counts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 21 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_score_pages.py llm-wiki/scripts/score_pages.py
git commit -m "feat: add cross-reference density counting via wikilink scanning"
```

---

### Task 4: Stats file I/O and tag bonus calculation

**Files:**
- Modify: `tests/test_score_pages.py`
- Modify: `llm-wiki/scripts/score_pages.py`

- [ ] **Step 1: Write failing tests for stats I/O and tag bonus**

Append to `tests/test_score_pages.py`:

```python
from score_pages import load_stats, save_stats, calculate_tag_bonus, DEFAULT_STATS


def test_load_stats_missing_file(tmp_path):
    """Missing .stats.json returns defaults and creates the file."""
    stats = load_stats(tmp_path)
    assert stats["version"] == 1
    assert stats["weights"]["query_frequency"] == 0.4
    assert stats["pages"] == {}
    assert (tmp_path / ".stats.json").exists()


def test_load_stats_existing(tmp_path):
    """Reads existing .stats.json correctly."""
    data = {
        "version": 1,
        "weights": {"query_frequency": 0.5, "access_count": 0.3, "cross_ref_density": 0.2},
        "tag_bonuses": {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1},
        "pages": {"wiki/a.md": {"query_count": 5, "access_count": 10}},
    }
    import json
    (tmp_path / ".stats.json").write_text(json.dumps(data))
    stats = load_stats(tmp_path)
    assert stats["weights"]["query_frequency"] == 0.5
    assert stats["pages"]["wiki/a.md"]["query_count"] == 5


def test_save_stats_roundtrip(tmp_path):
    """Save then load preserves data."""
    import json
    stats = DEFAULT_STATS.copy()
    stats["pages"] = {"wiki/x.md": {"query_count": 3, "access_count": 7}}
    save_stats(tmp_path, stats)
    loaded = json.loads((tmp_path / ".stats.json").read_text())
    assert loaded["pages"]["wiki/x.md"]["query_count"] == 3


def test_calculate_tag_bonus_pinned():
    """Pinned tag gives highest bonus."""
    bonuses = {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1}
    assert calculate_tag_bonus(["pinned"], bonuses) == 10


def test_calculate_tag_bonus_multiple():
    """Multiple tags stack."""
    bonuses = {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1}
    assert calculate_tag_bonus(["pinned", "priority/high"], bonuses) == 16


def test_calculate_tag_bonus_none():
    """No priority tags gives zero bonus."""
    bonuses = {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1}
    assert calculate_tag_bonus([], bonuses) == 0
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_score_pages.py::test_load_stats_missing_file -v`
Expected: FAIL with `ImportError: cannot import name 'load_stats'`

- [ ] **Step 3: Implement stats I/O and tag bonus**

Add to `llm-wiki/scripts/score_pages.py`:

```python
import json
import copy


DEFAULT_STATS = {
    "version": 1,
    "weights": {
        "query_frequency": 0.4,
        "access_count": 0.3,
        "cross_ref_density": 0.3,
    },
    "tag_bonuses": {
        "pinned": 10,
        "priority/high": 6,
        "priority/medium": 3,
        "priority/low": 1,
    },
    "pages": {},
}


def load_stats(vault_path: Path) -> dict:
    """Load .stats.json from vault root.

    If the file doesn't exist, creates it with defaults and returns defaults.
    """
    stats_path = Path(vault_path) / ".stats.json"
    if not stats_path.exists():
        stats = copy.deepcopy(DEFAULT_STATS)
        save_stats(vault_path, stats)
        return stats

    with open(stats_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_stats(vault_path: Path, stats: dict) -> None:
    """Write .stats.json to vault root."""
    stats_path = Path(vault_path) / ".stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
        f.write("\n")


def calculate_tag_bonus(priority_tags: list[str], tag_bonuses: dict[str, int | float]) -> float:
    """Sum tag bonuses for the given priority tags."""
    return sum(tag_bonuses.get(tag, 0) for tag in priority_tags)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 27 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_score_pages.py llm-wiki/scripts/score_pages.py
git commit -m "feat: add stats file I/O (load/save .stats.json) and tag bonus calculation"
```

---

### Task 5: End-to-end scoring pipeline

**Files:**
- Modify: `tests/test_score_pages.py`
- Modify: `llm-wiki/scripts/score_pages.py`

- [ ] **Step 1: Write failing tests for the full scoring pipeline**

Append to `tests/test_score_pages.py`:

```python
import json

from score_pages import score_all_pages


def _make_vault(tmp_path, pages_content: dict[str, str], stats: dict | None = None):
    """Helper: create a vault with wiki pages and optional .stats.json."""
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    for rel_name, content in pages_content.items():
        page_path = wiki / rel_name
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(content)
    if stats:
        (tmp_path / ".stats.json").write_text(json.dumps(stats))


def test_score_all_pages_basic(tmp_path):
    """Full scoring pipeline: computes and writes computed_score."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\nSee [[b]].\n",
        "b.md": "---\ntags: [concept, pinned]\n---\n# B\nSee [[a]].\n",
    }, {
        "version": 1,
        "weights": {"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
        "tag_bonuses": {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1},
        "pages": {
            "wiki/a.md": {"query_count": 10, "access_count": 20},
            "wiki/b.md": {"query_count": 5, "access_count": 10},
        },
    })

    result = score_all_pages(tmp_path)

    assert result["scored"] == 2
    # b.md has pinned tag → should score higher
    scores = {entry["page"]: entry["computed_score"] for entry in result["top"]}
    assert scores["wiki/b.md"] > scores["wiki/a.md"]

    # Verify frontmatter was updated
    b_content = (tmp_path / "wiki" / "b.md").read_text()
    assert "computed_score:" in b_content


def test_score_all_pages_incremental(tmp_path):
    """--pages mode only writes to specified pages."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\nSee [[b]].\n",
        "b.md": "---\ntags: [concept]\n---\n# B\n",
    }, {
        "version": 1,
        "weights": {"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
        "tag_bonuses": {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1},
        "pages": {},
    })

    result = score_all_pages(tmp_path, target_pages=["wiki/a.md"])

    assert result["scored"] == 1
    # a.md was written
    a_content = (tmp_path / "wiki" / "a.md").read_text()
    assert "computed_score:" in a_content
    # b.md was NOT written
    b_content = (tmp_path / "wiki" / "b.md").read_text()
    assert "computed_score:" not in b_content


def test_score_all_pages_no_stats(tmp_path):
    """Creates .stats.json if missing, scores all pages with zero counters."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\nweight: 5\n---\n# A\n",
    })

    result = score_all_pages(tmp_path)

    assert result["scored"] == 1
    # Only manual weight contributes → score should be 5.0
    assert result["top"][0]["computed_score"] == 5.0
    assert (tmp_path / ".stats.json").exists()


def test_score_all_pages_zero_activity(tmp_path):
    """Pages with no counters, no links, no weight appear in zero_activity."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\n",
    }, {
        "version": 1,
        "weights": {"query_frequency": 0.4, "access_count": 0.3, "cross_ref_density": 0.3},
        "tag_bonuses": {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1},
        "pages": {},
    })

    result = score_all_pages(tmp_path)

    assert "wiki/a.md" in result["zero_activity"]
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_score_pages.py::test_score_all_pages_basic -v`
Expected: FAIL with `ImportError: cannot import name 'score_all_pages'`

- [ ] **Step 3: Implement the scoring pipeline**

Add to `llm-wiki/scripts/score_pages.py`:

```python
def score_all_pages(
    vault_path: Path | str,
    target_pages: list[str] | None = None,
) -> dict:
    """Run the full scoring pipeline.

    Args:
        vault_path: Path to the vault root.
        target_pages: If set, only write scores to these pages (relative paths).
                      Normalization still uses all pages.

    Returns:
        {"scored": int, "top": [{"page": str, "computed_score": float}], "zero_activity": [str]}
    """
    vault_path = Path(vault_path)

    # Load stats (creates defaults if missing)
    stats = load_stats(vault_path)
    weights = stats["weights"]
    tag_bonuses = stats["tag_bonuses"]
    page_stats = stats["pages"]

    # Collect all wiki pages
    file_index = _collect_wiki_files(vault_path)
    if not file_index:
        return {"scored": 0, "top": [], "zero_activity": []}

    all_pages = list(file_index.values())

    # Build raw indicator maps for all pages
    raw_query_freq: dict[str, int] = {}
    raw_access_count: dict[str, int] = {}
    for rel_path in all_pages:
        ps = page_stats.get(rel_path, {})
        raw_query_freq[rel_path] = ps.get("query_count", 0)
        raw_access_count[rel_path] = ps.get("access_count", 0)

    # Count incoming links
    raw_cross_ref = count_incoming_links(vault_path)
    # Ensure all pages have an entry
    for rel_path in all_pages:
        if rel_path not in raw_cross_ref:
            raw_cross_ref[rel_path] = 0

    # Normalize
    norm_qf = normalize_values(raw_query_freq)
    norm_ac = normalize_values(raw_access_count)
    norm_cr = normalize_values(raw_cross_ref)

    # Determine which pages to write
    pages_to_write = target_pages if target_pages else all_pages

    # Compute and write scores
    results: list[dict] = []
    zero_activity: list[str] = []

    for rel_path in pages_to_write:
        abs_path = vault_path / rel_path
        if not abs_path.exists():
            continue

        content = abs_path.read_text(encoding="utf-8", errors="replace")
        manual_weight, priority_tags = parse_weight_and_tags(content)
        tag_bonus = calculate_tag_bonus(priority_tags, tag_bonuses)

        score = compute_score(
            norm_query_freq=norm_qf.get(rel_path, 0.0),
            norm_access_count=norm_ac.get(rel_path, 0.0),
            norm_cross_ref=norm_cr.get(rel_path, 0.0),
            manual_weight=manual_weight,
            tag_bonus=tag_bonus,
            weights=weights,
        )

        # Track zero-activity pages
        if (raw_query_freq.get(rel_path, 0) == 0
                and raw_access_count.get(rel_path, 0) == 0
                and raw_cross_ref.get(rel_path, 0) == 0
                and manual_weight == 0
                and tag_bonus == 0):
            zero_activity.append(rel_path)

        # Write to frontmatter
        updated = write_computed_score(content, score)
        abs_path.write_text(updated, encoding="utf-8")

        results.append({"page": rel_path, "computed_score": score})

    # Sort by score descending, take top 10
    results.sort(key=lambda x: x["computed_score"], reverse=True)
    top = results[:10]

    return {
        "scored": len(results),
        "top": top,
        "zero_activity": sorted(zero_activity),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 31 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_score_pages.py llm-wiki/scripts/score_pages.py
git commit -m "feat: add end-to-end scoring pipeline (score_all_pages)"
```

---

### Task 6: CLI (argparse main) and human/JSON output

**Files:**
- Modify: `llm-wiki/scripts/score_pages.py`

- [ ] **Step 1: Write failing test for CLI**

Append to `tests/test_score_pages.py`:

```python
import subprocess


def test_cli_full_recalc(tmp_path):
    """CLI runs full recalc and prints summary."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\nSee [[b]].\n",
        "b.md": "---\ntags: [concept]\n---\n# B\n",
    })

    script = os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts", "score_pages.py")
    result = subprocess.run(
        [sys.executable, script, str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "Scored 2 pages" in result.stdout


def test_cli_json_output(tmp_path):
    """CLI --json outputs valid JSON."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\n",
    })

    script = os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts", "score_pages.py")
    result = subprocess.run(
        [sys.executable, script, str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "scored" in data
    assert "top" in data


def test_cli_pages_flag(tmp_path):
    """CLI --pages only scores specified pages."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\n",
        "b.md": "---\ntags: [concept]\n---\n# B\n",
    })

    script = os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts", "score_pages.py")
    result = subprocess.run(
        [sys.executable, script, str(tmp_path), "--pages", "wiki/a.md"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "Scored 1 page" in result.stdout
```

- [ ] **Step 2: Run tests to verify new tests fail**

Run: `python -m pytest tests/test_score_pages.py::test_cli_full_recalc -v`
Expected: FAIL (script has no `main()` or arg parsing)

- [ ] **Step 3: Implement CLI with argparse and output formatting**

Add to `llm-wiki/scripts/score_pages.py`:

```python
import argparse
import sys


def print_report(result: dict, json_output: bool = False) -> None:
    """Print scoring results in human-readable or JSON format."""
    if json_output:
        print(json.dumps(result, indent=2))
        return

    count = result["scored"]
    label = "page" if count == 1 else "pages"
    print(f"Scored {count} {label}.\n")

    if result["top"]:
        print("Top pages by score:")
        for entry in result["top"]:
            print(f"  {entry['computed_score']:>5.1f}  {entry['page']}")
        print()

    if result["zero_activity"]:
        print(f"Zero activity ({len(result['zero_activity'])} pages):")
        for page in result["zero_activity"]:
            print(f"  {page}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Compute composite page scores for wiki pages.",
    )
    parser.add_argument("vault_path", help="Path to the wiki vault")
    parser.add_argument(
        "--pages", nargs="+", default=None, metavar="PAGE",
        help="Score only these pages (vault-relative paths). Default: all wiki pages.",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()
    vault_path = Path(args.vault_path).resolve()

    if not vault_path.is_dir():
        print(f"Error: {vault_path} is not a directory.", file=sys.stderr)
        sys.exit(1)

    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        print(f"Error: {wiki_dir} does not exist. Is this a valid wiki vault?",
              file=sys.stderr)
        sys.exit(1)

    result = score_all_pages(vault_path, target_pages=args.pages)
    print_report(result, json_output=args.json_output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 34 tests PASS

- [ ] **Step 5: Commit**

```bash
git add llm-wiki/scripts/score_pages.py tests/test_score_pages.py
git commit -m "feat: add CLI with argparse, human-readable and JSON output"
```

---

### Task 7: Update SKILL.md — Setup and Vault Structure

**Files:**
- Modify: `llm-wiki/SKILL.md:46-60` (Vault Structure)
- Modify: `llm-wiki/SKILL.md:136-144` (Initial .manifest.json)
- Modify: `llm-wiki/SKILL.md:611-619` (Bundled Resources)

- [ ] **Step 1: Add `.stats.json` to Vault Structure diagram**

In `llm-wiki/SKILL.md`, in the Vault Structure section (around line 48), add `.stats.json` to the tree. Change:

```
└── schema.md               # Wiki conventions and page templates
```

to:

```
├── schema.md               # Wiki conventions and page templates
└── .stats.json             # Page scoring counters and config
```

- [ ] **Step 2: Add `.stats.json` initialization after `.manifest.json` in Setup**

In `llm-wiki/SKILL.md`, after the "Initial `.manifest.json`" block (around line 144), insert a new subsection:

```markdown
### Initial `.stats.json`

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

This file tracks page access counters and scoring configuration. The `weights` control how much each computed indicator contributes to the final score. The `tag_bonuses` define fixed score additions for priority tags. Both are user-tunable. See **Page Scoring** below for details.
```

- [ ] **Step 3: Add `score_pages.py` to Bundled Resources**

In `llm-wiki/SKILL.md`, in the Bundled Resources section (around line 618), add:

```markdown
- `scripts/score_pages.py` — Computes composite page scores from query frequency, access count, cross-reference density, manual weight, and priority tags. Writes `computed_score` to page frontmatter. Supports `--pages` for incremental scoring and `--json` for structured output.
```

- [ ] **Step 4: Verify the edits read correctly**

Read the modified sections of `SKILL.md` to confirm formatting is correct.

- [ ] **Step 5: Commit**

```bash
git add llm-wiki/SKILL.md
git commit -m "docs: add .stats.json to vault structure, setup, and bundled resources"
```

---

### Task 8: Update SKILL.md — Ingest integration (Step 5.6)

**Files:**
- Modify: `llm-wiki/SKILL.md:274-296` (Ingest Steps 5-5.5 area)

- [ ] **Step 1: Add Step 5.6 after Step 5.5**

In `llm-wiki/SKILL.md`, after the Step 5.5 section (around line 292), insert:

```markdown
### Step 5.6: Update page scores

After validation passes:

1. **Update counters** — increment `access_count` in `.stats.json` for every existing wiki page that was read during cross-linking in Steps 3–4. Use a single read-modify-write cycle to avoid partial updates.

2. **Score affected pages** — run the scoring script on all pages created and updated in this ingest:

```bash
python <skill-dir>/scripts/score_pages.py <vault-path> --pages <page1.md> <page2.md> ... --json
```

This computes scores using the latest counters and cross-reference data. New pages start with a low computed score (since they have no access history), which will increase as they get queried and referenced.
```

- [ ] **Step 2: Verify the edit reads correctly**

Read the modified section to confirm formatting and step numbering.

- [ ] **Step 3: Commit**

```bash
git add llm-wiki/SKILL.md
git commit -m "docs: add ingest Step 5.6 for page score updates"
```

---

### Task 9: Update SKILL.md — Query integration

**Files:**
- Modify: `llm-wiki/SKILL.md:386-408` (Query section)

- [ ] **Step 1: Update the Query section**

In `llm-wiki/SKILL.md`, modify the Query section. After step 1 ("Search"), add scoring guidance. Replace the existing Query steps with:

```markdown
When the user asks a question about the wiki's knowledge:

1. **Search**: Read `index.md` to identify relevant pages. For larger wikis, use grep/glob to find pages mentioning key terms.
2. **Rank by score**: Sort candidate pages by `computed_score` descending (from frontmatter). Prioritize reading high-scored pages first — they represent the most valued content in the wiki.
3. **Retrieve**: Read the relevant wiki pages, starting with the highest-scored candidates.
4. **Synthesize**: Answer the question using the wiki's compiled knowledge. When multiple pages cover the same topic, give more weight to higher-scored pages. Cite sources with `[[wikilinks]]` — list higher-scored sources first.
5. **Update counters**: After the query completes:
   - Increment `access_count` in `.stats.json` for every wiki page **read** during this query.
   - Increment `query_count` in `.stats.json` for every wiki page **cited in the answer**.
6. **File the answer**: Save the answer as a wiki page under `wiki/queries/` if it synthesizes across 3+ wiki pages or reveals a non-obvious connection. Don't file simple single-page lookups. This is how the wiki compounds — queries produce new artifacts that future queries can build on. Ask the user if borderline.
```

- [ ] **Step 2: Verify the edit reads correctly**

Read the modified Query section to confirm formatting.

- [ ] **Step 3: Commit**

```bash
git add llm-wiki/SKILL.md
git commit -m "docs: add score-based ranking and counter updates to Query workflow"
```

---

### Task 10: Update SKILL.md — Lint integration

**Files:**
- Modify: `llm-wiki/SKILL.md:410-457` (Lint section)

- [ ] **Step 1: Add Score staleness to the lint checks table**

In `llm-wiki/SKILL.md`, in the Lint section's "Checks to perform" table (around line 416), add a new row:

```markdown
| **Score staleness** | Pages missing `computed_score` or scores not recalculated since last full lint | Yes — run full `score_pages.py` |
```

- [ ] **Step 2: Add scoring recalc instructions after the lint checks**

After the "Dead link resolution" subsection (around line 436), add:

```markdown
#### Score recalculation

Run a full scoring recalc as part of every lint:

```bash
python <skill-dir>/scripts/score_pages.py <vault-path> --json
```

Include the scoring summary in the lint report:
- Top 10 pages by score
- Pages with zero activity (no queries, no access, no incoming links, no manual weight)
```

- [ ] **Step 3: Update the lint report template**

In the lint report template (around line 440), add a scoring section:

```markdown
## Scoring Summary
- Top: [[highest-scored-page]] (score: 9.2), [[second-page]] (score: 8.1), ...
- X pages with zero activity — consider reviewing or archiving
```

- [ ] **Step 4: Verify the edit reads correctly**

Read the modified Lint section to confirm formatting.

- [ ] **Step 5: Commit**

```bash
git add llm-wiki/SKILL.md
git commit -m "docs: add score staleness check and scoring summary to Lint workflow"
```

---

### Task 11: Add Page Scoring section to SKILL.md

**Files:**
- Modify: `llm-wiki/SKILL.md` (insert before Bundled Resources section)

- [ ] **Step 1: Add a dedicated Page Scoring section**

In `llm-wiki/SKILL.md`, before the "Bundled Resources" section (around line 611), insert a new top-level section:

```markdown
## Page Scoring

The wiki uses a composite scoring system to surface high-value content. Each page gets a `computed_score` in its frontmatter, computed from five indicators:

### Indicators

| Indicator | Type | Source | Effect |
|-----------|------|--------|--------|
| Query frequency | Computed | `.stats.json` `query_count` | Pages cited in query answers score higher |
| Access count | Computed | `.stats.json` `access_count` | Pages read more often score higher |
| Cross-reference density | Computed | Incoming `[[wikilinks]]` scanned live | Well-connected pages score higher |
| Manual weight | Manual | `weight` frontmatter field (default: 0) | User-set additive boost |
| Priority tags | Manual | `#pinned`, `#priority/high\|medium\|low` | Fixed bonus: pinned=+10, high=+6, medium=+3, low=+1 |

### Formula

```
computed_score = (w1 * norm(query_frequency))
              + (w2 * norm(access_count))
              + (w3 * norm(cross_ref_density))
              + weight
              + tag_bonus
```

`norm()` normalizes to 0–10 relative to the max across all pages. Default weights: `w1=0.4`, `w2=0.3`, `w3=0.3` — configurable in `.stats.json`.

### When scores are computed

- **After ingest** (Step 5.6): Incremental — only pages created/updated in this ingest
- **During lint**: Full recalc of all pages
- **Manual**: Run `python <skill-dir>/scripts/score_pages.py <vault-path>` for a full recalc at any time

### Counter tracking

The agent updates `.stats.json` counters during operations:
- **Query**: `access_count` for every page read; `query_count` for every page cited in the answer
- **Ingest**: `access_count` for every existing page read during cross-linking

### User controls

Users can adjust scoring behavior in two ways:

1. **Per-page**: Set `weight: N` in frontmatter (additive boost) or add `#pinned` / `#priority/high|medium|low` tags
2. **Global**: Edit `.stats.json` to change `weights` (indicator multipliers) or `tag_bonuses` (per-tag values)

### Index ordering

`index.md` entries are sorted by `computed_score` descending within each category, with the score shown inline:

```markdown
- [[page-name]] (score: 9.2) — one-line summary
```

---
```

- [ ] **Step 2: Verify the edit reads correctly**

Read the new section to confirm formatting and positioning.

- [ ] **Step 3: Commit**

```bash
git add llm-wiki/SKILL.md
git commit -m "docs: add Page Scoring section with indicators, formula, and user controls"
```

---

### Task 12: Update schema.md frontmatter reference

**Files:**
- Modify: `llm-wiki/references/schema.md:260-275` (Frontmatter Reference table)

- [ ] **Step 1: Add weight and computed_score to the frontmatter reference table**

In `llm-wiki/references/schema.md`, at the end of the Frontmatter Reference table (around line 275), add two new rows:

```markdown
| `weight` | No | Manual importance boost (number, default 0). Added directly to `computed_score`. Set by user to surface preferred pages. |
| `computed_score` | No | Composite page score computed by `score_pages.py`. Do not edit manually — recalculated during ingest and lint. |
```

- [ ] **Step 2: Verify the edit reads correctly**

Read the modified frontmatter reference to confirm the table formats correctly.

- [ ] **Step 3: Commit**

```bash
git add llm-wiki/references/schema.md
git commit -m "docs: add weight and computed_score to frontmatter reference"
```

---

### Task 13: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add score_pages.py to Useful Commands**

In `CLAUDE.md`, in the Useful Commands section, add:

```bash
# Compute page scores (full recalc)
python llm-wiki/scripts/score_pages.py <vault-path>
python llm-wiki/scripts/score_pages.py <vault-path> --json            # structured output for agents
python llm-wiki/scripts/score_pages.py <vault-path> --pages <pages>   # incremental (specific pages only)
```

- [ ] **Step 2: Add to Key Files**

In the Key Files section, add:

```markdown
- `llm-wiki/scripts/score_pages.py` — Composite page scoring. Reads `.stats.json` counters + scans wikilinks + reads frontmatter weight/tags, computes `computed_score`, writes it to each page's frontmatter. Supports `--pages` for incremental and `--json` for structured output.
```

- [ ] **Step 3: Add design decision**

In the Design Decisions section, add:

```markdown
- **Composite page scoring**: Five indicators (query frequency, access count, cross-reference density, manual weight, priority tags) feed a weighted formula. Counters live in `.stats.json` (separate from page files) to avoid rewriting frontmatter on every read. Cross-ref density is computed live (not cached) since it changes whenever any page is edited. Manual `weight` is additive (not multiplicative) so users can boost pages without needing to understand the computed baseline.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add score_pages.py to CLAUDE.md commands, key files, and design decisions"
```

---

### Task 14: Final integration test

**Files:**
- Modify: `tests/test_score_pages.py`

- [ ] **Step 1: Write an end-to-end test simulating a real workflow**

Append to `tests/test_score_pages.py`:

```python
def test_full_workflow_simulation(tmp_path):
    """Simulate: setup → ingest (counters update) → score → query (counters update) → re-score."""
    # Setup: create vault with pages and empty stats
    _make_vault(tmp_path, {
        "concepts/microservices.md": (
            "---\naliases: []\ntags: [concept, pinned]\nweight: 2\n"
            "status: active\n---\n# Microservices\nSee [[api-gateway]].\n"
        ),
        "concepts/api-gateway.md": (
            "---\naliases: []\ntags: [concept, priority/high]\n"
            "status: active\n---\n# API Gateway\nUsed by [[microservices]].\n"
        ),
        "concepts/monolith.md": (
            "---\naliases: []\ntags: [concept]\n"
            "status: active\n---\n# Monolith\nContrast with [[microservices]].\n"
        ),
    })

    # Step 1: Initial score with no activity
    result1 = score_all_pages(tmp_path)
    assert result1["scored"] == 3
    scores1 = {e["page"]: e["computed_score"] for e in result1["top"]}
    # microservices has pinned(+10) + weight(2) + cross-ref links
    # api-gateway has priority/high(+6) + cross-ref links
    # monolith has only cross-ref (zero)
    assert scores1["wiki/concepts/microservices.md"] > scores1["wiki/concepts/api-gateway.md"]
    assert scores1["wiki/concepts/api-gateway.md"] > scores1["wiki/concepts/monolith.md"]

    # Step 2: Simulate query activity — monolith gets queried a lot
    stats = load_stats(tmp_path)
    stats["pages"]["wiki/concepts/monolith.md"] = {"query_count": 50, "access_count": 100}
    stats["pages"]["wiki/concepts/microservices.md"] = {"query_count": 5, "access_count": 10}
    stats["pages"]["wiki/concepts/api-gateway.md"] = {"query_count": 2, "access_count": 5}
    save_stats(tmp_path, stats)

    # Step 3: Re-score — monolith should rise due to high query/access counts
    result2 = score_all_pages(tmp_path)
    scores2 = {e["page"]: e["computed_score"] for e in result2["top"]}
    # monolith now has max query_freq (10.0) and max access_count (10.0)
    # but microservices still has pinned + weight + cross-ref advantage
    assert scores2["wiki/concepts/monolith.md"] > scores1["wiki/concepts/monolith.md"]

    # Verify frontmatter was written for all pages
    for page_dir in ["microservices.md", "api-gateway.md", "monolith.md"]:
        content = (tmp_path / "wiki" / "concepts" / page_dir).read_text()
        assert "computed_score:" in content
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/test_score_pages.py -v`
Expected: All 38 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_score_pages.py
git commit -m "test: add full workflow simulation test for scoring pipeline"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-04-10-page-scoring-system.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?