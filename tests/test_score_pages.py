#!/usr/bin/env python3
"""Tests for score_pages.py scoring logic."""

import json
import subprocess
import sys
import os

# Add scripts dir to path so we can import score_pages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from score_pages import normalize_values, compute_score, parse_weight_and_tags, write_computed_score, count_incoming_links
from score_pages import load_stats, save_stats, calculate_tag_bonus, DEFAULT_STATS
from score_pages import score_all_pages


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


def test_count_incoming_links_basic(tmp_path):
    """Counts incoming [[wikilinks]] per target page."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text("---\ntags: [concept]\n---\n# A\nSee [[b]] and [[c]].\n")
    (wiki / "b.md").write_text("---\ntags: [concept]\n---\n# B\nRelated to [[a]] and [[c]].\n")
    (wiki / "c.md").write_text("---\ntags: [concept]\n---\n# C\nStandalone.\n")

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/a.md", 0) == 1
    assert counts.get("wiki/b.md", 0) == 1
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


def test_load_stats_missing_file(tmp_path):
    """Missing .stats.json returns defaults and creates the file."""
    stats = load_stats(tmp_path)
    assert stats["version"] == 1
    assert stats["weights"]["query_frequency"] == 0.4
    assert stats["pages"] == {}
    assert (tmp_path / ".stats.json").exists()


def test_load_stats_existing(tmp_path):
    """Reads existing .stats.json correctly."""
    import json
    data = {
        "version": 1,
        "weights": {"query_frequency": 0.5, "access_count": 0.3, "cross_ref_density": 0.2},
        "tag_bonuses": {"pinned": 10, "priority/high": 6, "priority/medium": 3, "priority/low": 1},
        "pages": {"wiki/a.md": {"query_count": 5, "access_count": 10}},
    }
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


def _make_vault(tmp_path, pages_content, stats=None):
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
    scores = {entry["page"]: entry["computed_score"] for entry in result["top"]}
    assert scores["wiki/b.md"] > scores["wiki/a.md"]
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
    a_content = (tmp_path / "wiki" / "a.md").read_text()
    assert "computed_score:" in a_content
    b_content = (tmp_path / "wiki" / "b.md").read_text()
    assert "computed_score:" not in b_content


def test_score_all_pages_no_stats(tmp_path):
    """Creates .stats.json if missing, scores all pages with zero counters."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\nweight: 5\n---\n# A\n",
    })

    result = score_all_pages(tmp_path)

    assert result["scored"] == 1
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


def test_full_workflow_simulation(tmp_path):
    """Simulate: setup -> ingest (counters update) -> score -> query (counters update) -> re-score."""
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


def test_count_incoming_links_alias_resolution(tmp_path):
    """Links via frontmatter alias resolve to the aliased page."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "artificial-intelligence.md").write_text(
        "---\naliases: [AI]\ntags: [concept]\n---\n# Artificial Intelligence\n"
    )
    (wiki / "overview.md").write_text(
        "---\ntags: [topic]\n---\n# Overview\nSee [[AI]] for details.\n"
    )

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/artificial-intelligence.md", 0) == 1


def test_count_incoming_links_path_qualified(tmp_path):
    """Path-qualified links like [[wiki/concepts/page]] resolve correctly."""
    concepts = tmp_path / "wiki" / "concepts"
    concepts.mkdir(parents=True)
    topics = tmp_path / "wiki" / "topics"
    topics.mkdir(parents=True)
    (concepts / "api-gateway.md").write_text(
        "---\ntags: [concept]\n---\n# API Gateway\n"
    )
    (topics / "overview.md").write_text(
        "---\ntags: [topic]\n---\n# Overview\nSee [[wiki/concepts/api-gateway]].\n"
    )

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/concepts/api-gateway.md", 0) == 1


def test_count_incoming_links_multi_backtick_code(tmp_path):
    """Links inside multi-backtick inline code are not counted."""
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "a.md").write_text(
        "---\ntags: [concept]\n---\n# A\n``[[b]]`` and [[c]].\n"
    )
    (wiki / "b.md").write_text("---\ntags: [concept]\n---\n# B\n")
    (wiki / "c.md").write_text("---\ntags: [concept]\n---\n# C\n")

    counts = count_incoming_links(tmp_path)
    assert counts.get("wiki/b.md", 0) == 0
    assert counts.get("wiki/c.md", 0) == 1


def test_write_computed_score_dots_delimiter():
    """Handles ... as frontmatter closing delimiter."""
    content = "---\ntags: [concept]\n...\n# Page\n\nBody.\n"
    result = write_computed_score(content, 4.2)
    assert "computed_score: 4.2" in result
    assert "# Page" in result


def test_load_stats_malformed_json(tmp_path):
    """Malformed .stats.json resets to defaults."""
    (tmp_path / ".stats.json").write_text("{bad json")
    stats = load_stats(tmp_path)
    assert stats["version"] == 1
    assert stats["weights"]["query_frequency"] == 0.4


def test_load_stats_missing_keys(tmp_path):
    """Missing top-level keys filled from defaults."""
    (tmp_path / ".stats.json").write_text(json.dumps({"version": 1, "pages": {}}))
    stats = load_stats(tmp_path)
    assert "weights" in stats
    assert "tag_bonuses" in stats


def test_score_all_pages_incremental_zero_activity_is_partial(tmp_path):
    """zero_activity in incremental mode only covers target pages, not full vault."""
    _make_vault(tmp_path, {
        "a.md": "---\ntags: [concept]\n---\n# A\n",
        "b.md": "---\ntags: [concept]\n---\n# B\n",
    })
    result = score_all_pages(tmp_path, target_pages=["wiki/a.md"])
    # a.md is zero-activity and was scored — should appear
    assert "wiki/a.md" in result["zero_activity"]
    # b.md is also zero-activity but was NOT scored — should NOT appear
    assert "wiki/b.md" not in result["zero_activity"]
