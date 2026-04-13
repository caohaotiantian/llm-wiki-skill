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

import argparse
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from frontmatter import parse as _parse_fm, parse_tags as _parse_tags_fm


PRIORITY_TAGS = {"pinned", "priority/high", "priority/medium", "priority/low"}


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

    If the file doesn't exist or is malformed, creates it with defaults.
    Missing top-level keys are filled from defaults.
    """
    stats_path = Path(vault_path) / ".stats.json"
    if not stats_path.exists():
        stats = copy.deepcopy(DEFAULT_STATS)
        save_stats(vault_path, stats)
        return stats

    try:
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: .stats.json is malformed ({e}), resetting to defaults.",
              file=sys.stderr)
        stats = copy.deepcopy(DEFAULT_STATS)
        save_stats(vault_path, stats)
        return stats

    # Fill missing top-level keys from defaults
    defaults = DEFAULT_STATS
    for key in ("version", "weights", "tag_bonuses", "pages"):
        if key not in stats:
            stats[key] = copy.deepcopy(defaults[key])

    return stats


def save_stats(vault_path: Path, stats: dict) -> None:
    """Write .stats.json to vault root atomically (temp file + rename)."""
    stats_path = Path(vault_path) / ".stats.json"
    fd, tmp_path = tempfile.mkstemp(dir=str(vault_path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, str(stats_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def calculate_tag_bonus(priority_tags: list[str], tag_bonuses: dict[str, int | float]) -> float:
    """Sum tag bonuses for the given priority tags."""
    return sum(tag_bonuses.get(tag, 0) for tag in priority_tags)


def parse_weight_and_tags(content: str) -> tuple[int | float, list[str]]:
    """Extract manual weight and priority tags from page frontmatter."""
    fm, _ = _parse_fm(content)

    # Parse weight
    weight: int | float = 0
    raw_weight = fm.get("weight")
    if raw_weight is not None:
        try:
            weight = int(raw_weight) if isinstance(raw_weight, int) else float(raw_weight)
        except (ValueError, TypeError):
            pass

    # Parse tags — filter to priority tags only
    all_tags = _parse_tags_fm(fm)
    priority_tags = [t for t in all_tags if t in PRIORITY_TAGS]

    return weight, priority_tags


def write_computed_score(content: str, score: float) -> str:
    """Write or update computed_score in page frontmatter.

    If frontmatter exists and has computed_score, update it.
    If frontmatter exists without computed_score, insert before closing ---.
    If no frontmatter, return content unchanged.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"^(---\s*\n)(.*?\n)((?:---|\.\.\.))", content, re.DOTALL)
    if not match:
        return content

    prefix = match.group(1)    # "---\n"
    fm = match.group(2)        # frontmatter body including trailing \n
    suffix = match.group(3)    # closing "---" or "..."
    rest = content[match.end():]

    # Strip trailing newline from fm for clean manipulation, re-add later
    fm = fm.rstrip("\n")

    # Update existing or insert new
    if re.search(r"^computed_score:\s*", fm, re.MULTILINE):
        fm = re.sub(r"^computed_score:\s*.*$", f"computed_score: {score}", fm, flags=re.MULTILINE)
    else:
        fm = fm + f"\ncomputed_score: {score}"

    return prefix + fm + "\n" + suffix + rest


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
    return {k: v / max_val * 10 for k, v in raw.items()}


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


# Matches [[target]], [[target|display]], [[target#heading]]
# Does NOT match embeds (![[...]])
WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\[\]]+?)\]\]")


def _extract_target(wikilink_content: str) -> str:
    """Extract resolution target: [[target|display]] -> target, [[target#h]] -> target."""
    target = wikilink_content.split("|")[0].split("#")[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def _collect_wiki_files(vault_path: Path) -> dict[str, str]:
    """Collect all .md files under wiki/.

    Returns {normalized_key: relative_path} for resolving link targets.
    Keys include both bare stems and vault-relative paths (without .md),
    matching lint_links.py's resolution behavior.
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
                if stem in files and files[stem] != rel:
                    print(f"Warning: duplicate filename '{fname}' — "
                          f"{files[stem]} and {rel}. "
                          f"Scoring may be incomplete for one of these.",
                          file=sys.stderr)
                files[stem] = rel
                # Also register path-qualified key (e.g. "wiki/concepts/microservices")
                rel_no_ext = os.path.splitext(rel)[0].lower()
                if rel_no_ext != stem:
                    files[rel_no_ext] = rel
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

        # Strip inline code spans (single and multi-backtick, including empty spans)
        scannable = re.sub(r"(`+)(?:(?!\1).)*\1", "", line)
        for match in WIKILINK_RE.finditer(scannable):
            target = _extract_target(match.group(1))
            if target:
                targets.append(target)

    return targets


def count_incoming_links(
    vault_path: Path,
    file_index: dict[str, str] | None = None,
    resolution_index: dict | None = None,
) -> dict[str, int]:
    """Count incoming wikilinks for each wiki page.

    Uses the same resolution logic as lint_links.py (filename + alias + fuzzy matching)
    to ensure cross-reference counts are consistent with link validation.

    Args:
        vault_path: Path to the vault root.
        file_index: Pre-built file index from _collect_wiki_files (avoids redundant scan).
        resolution_index: Pre-built alias index from _build_resolution_index (avoids redundant scan).

    Returns {relative_path: count} for all pages that have at least one incoming link.
    """
    vault_path = Path(vault_path)
    if file_index is None:
        file_index = _collect_wiki_files(vault_path)
    if not file_index:
        return {}

    if resolution_index is None:
        resolution_index = _build_resolution_index(vault_path)

    counts: dict[str, int] = {}

    # Deduplicate: file_index may have multiple keys for the same file
    # (bare stem + path-qualified). Iterate unique files only.
    seen_files: set[str] = set()
    for stem, rel_path in file_index.items():
        if rel_path in seen_files:
            continue
        seen_files.add(rel_path)
        abs_path = os.path.join(str(vault_path), rel_path)
        targets = _scan_links_in_file(abs_path)
        for target in targets:
            target_path = _resolve_link_target(target, file_index, resolution_index)
            if target_path and target_path != rel_path:
                counts[target_path] = counts.get(target_path, 0) + 1

    return counts


def _normalize_for_matching(name: str) -> str:
    """Normalize a name for fuzzy matching (same as lint_links.py).

    Case-insensitive, treats spaces/hyphens/underscores as equivalent.
    """
    return re.sub(r"[\s\-_]+", " ", name).strip().lower()


def _build_resolution_index(vault_path: Path) -> dict:
    """Build alias resolution index from wiki pages.

    Returns {"by_alias": {normalized_alias: relative_path}} for alias-aware
    link resolution. Mirrors lint_links.py's build_resolution_index but only
    the alias portion (filenames are already in _collect_wiki_files).
    """
    by_alias: dict[str, str] = {}
    wiki_dir = vault_path / "wiki"
    if not wiki_dir.is_dir():
        return {"by_alias": by_alias}

    for root, dirs, files in os.walk(str(wiki_dir)):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md") or fname.endswith(".snapshot.md"):
                continue
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, vault_path)
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            # Parse aliases from frontmatter
            content_norm = content.replace("\r\n", "\n").replace("\r", "\n")
            match = re.match(r"^---\s*\n(.*?)\n(?:---|\.\.\.)(?:\s*\n|$)", content_norm, re.DOTALL)
            if not match:
                continue
            fm = match.group(1)
            # Inline format: aliases: [a, b, c]
            inline = re.search(r"^aliases:\s*\[([^\]]*)\]", fm, re.MULTILINE)
            if inline:
                for m in re.finditer(r'"([^"]*?)"|\'([^\']*?)\'|([^,\s][^,]*)', inline.group(1)):
                    val = (m.group(1) or m.group(2) or m.group(3) or "").strip()
                    if val:
                        norm_alias = _normalize_for_matching(val)
                        if norm_alias:
                            if norm_alias in by_alias and by_alias[norm_alias] != rel_path:
                                print(f"Warning: duplicate alias '{val}' — "
                                      f"{by_alias[norm_alias]} and {rel_path}. "
                                      f"First registration wins.",
                                      file=sys.stderr)
                            elif norm_alias not in by_alias:
                                by_alias[norm_alias] = rel_path
            else:
                # List format: aliases:\n  - a\n  - b
                list_match = re.search(r"^aliases:\s*\n((?:\s+-\s+.+\n?)+)", fm, re.MULTILINE)
                if list_match:
                    items = re.findall(r"^\s+-\s+(.+)", list_match.group(1), re.MULTILINE)
                    for item in items:
                        val = item.strip().strip("\"'")
                        if val:
                            norm_alias = _normalize_for_matching(val)
                            if norm_alias:
                                if norm_alias in by_alias and by_alias[norm_alias] != rel_path:
                                    print(f"Warning: duplicate alias '{val}' — "
                                          f"{by_alias[norm_alias]} and {rel_path}. "
                                          f"First registration wins.",
                                          file=sys.stderr)
                                elif norm_alias not in by_alias:
                                    by_alias[norm_alias] = rel_path

    return {"by_alias": by_alias}


def _resolve_link_target(
    target: str,
    file_index: dict[str, str],
    resolution_index: dict,
) -> str | None:
    """Resolve a link target to a relative file path.

    Resolution order (matching lint_links.py):
    1. Exact filename match (case-insensitive)
    2. Fuzzy filename match (hyphens/spaces/underscores equivalent)
    3. Alias match (from frontmatter aliases)
    Returns None if unresolved.
    """
    # 1. Exact filename (lowered)
    norm = target.lower()
    if norm in file_index:
        return file_index[norm]

    # 2. Fuzzy filename match
    fuzzy = _normalize_for_matching(target)
    for stem, rel_path in file_index.items():
        if _normalize_for_matching(stem) == fuzzy:
            return rel_path

    # 3. Alias match
    by_alias = resolution_index.get("by_alias", {})
    if fuzzy in by_alias:
        return by_alias[fuzzy]

    return None


def score_all_pages(
    vault_path,
    target_pages=None,
):
    """Run the full scoring pipeline.

    Args:
        vault_path: Path to the vault root.
        target_pages: If set, only write scores to these pages (relative paths).
                      Normalization still uses all pages. Note: pages outside
                      target_pages that gain new incoming links are NOT re-scored —
                      their on-disk computed_score may be stale until the next full
                      recalc (during lint). Use full mode for vault-wide accuracy.

    Returns:
        {"scored": int, "top": [{"page": str, "computed_score": float}], "zero_activity": [str]}

    Note: In incremental mode (target_pages set), zero_activity only covers the
    scored pages, not the full vault. Use full mode for a complete zero-activity list.
    """
    vault_path = Path(vault_path)

    # Load stats (creates defaults if missing)
    stats = load_stats(vault_path)
    weights = stats["weights"]
    tag_bonuses = stats["tag_bonuses"]
    page_stats = stats["pages"]

    # Collect all wiki pages and build resolution index (single traversal each)
    file_index = _collect_wiki_files(vault_path)
    if not file_index:
        return {"scored": 0, "top": [], "zero_activity": []}

    resolution_index = _build_resolution_index(vault_path)

    # Deduplicate: file_index has both stem and path keys pointing to same rel_path
    all_pages = sorted(set(file_index.values()))

    # Build raw indicator maps for all pages
    raw_query_freq = {}
    raw_access_count = {}
    for rel_path in all_pages:
        ps = page_stats.get(rel_path, {})
        raw_query_freq[rel_path] = ps.get("query_count", 0)
        raw_access_count[rel_path] = ps.get("access_count", 0)

    # Count incoming links (reuse file_index and resolution_index)
    raw_cross_ref = count_incoming_links(vault_path, file_index, resolution_index)
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
    results = []
    zero_activity = []

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


def print_report(result, json_output=False):
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
