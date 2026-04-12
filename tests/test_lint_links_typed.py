"""Tests for typed links, stale pages, and unbalanced pages in lint_links.py."""

import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from lint_links import (
    KNOWN_LINK_TYPES,
    check_stale_pages,
    check_unbalanced_pages,
    parse_typed_links,
)


# ---------------------------------------------------------------------------
# parse_typed_links
# ---------------------------------------------------------------------------

class TestParseTypedLinks:
    def test_basic(self):
        content = textwrap.dedent("""\
            ---
            aliases: []
            links:
              - {target: "microservices", type: "references"}
              - {target: "monolith", type: "contradicts"}
            ---
            # Page
        """)
        links = parse_typed_links(content)
        assert len(links) == 2
        assert links[0] == {"target": "microservices", "type": "references"}
        assert links[1] == {"target": "monolith", "type": "contradicts"}

    def test_empty_no_frontmatter(self):
        assert parse_typed_links("# No frontmatter") == []

    def test_empty_no_links(self):
        content = textwrap.dedent("""\
            ---
            aliases: []
            ---
            # Page
        """)
        assert parse_typed_links(content) == []

    def test_unknown_type_still_parsed(self):
        content = textwrap.dedent("""\
            ---
            links:
              - {target: "foo", type: "custom_relation"}
            ---
        """)
        links = parse_typed_links(content)
        assert len(links) == 1
        assert links[0]["type"] == "custom_relation"
        assert links[0]["type"] not in KNOWN_LINK_TYPES

    def test_reversed_key_order(self):
        content = textwrap.dedent("""\
            ---
            links:
              - {type: "depends_on", target: "base-concept"}
            ---
        """)
        links = parse_typed_links(content)
        assert len(links) == 1
        assert links[0] == {"target": "base-concept", "type": "depends_on"}

    def test_unquoted_values(self):
        content = textwrap.dedent("""\
            ---
            links:
              - {target: microservices, type: references}
            ---
        """)
        links = parse_typed_links(content)
        assert len(links) == 1
        assert links[0] == {"target": "microservices", "type": "references"}


# ---------------------------------------------------------------------------
# check_stale_pages
# ---------------------------------------------------------------------------

class TestCheckStalePages:
    def test_stale_page_found(self, tmp_path):
        wiki = tmp_path / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "test.md").write_text(textwrap.dedent("""\
            ---
            updated: 2025-01-15
            ---

            # Test

            Some compiled truth.

            ---

            ## Timeline

            - 2025-03-10 — New evidence arrived.
            - 2025-01-15 — Page created.
        """))
        results = check_stale_pages(tmp_path)
        assert len(results) == 1
        assert results[0]["updated"] == "2025-01-15"
        assert results[0]["latest_timeline"] == "2025-03-10"

    def test_fresh_page_not_flagged(self, tmp_path):
        wiki = tmp_path / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "test.md").write_text(textwrap.dedent("""\
            ---
            updated: 2025-03-10
            ---

            # Test

            Up to date compiled truth.

            ---

            ## Timeline

            - 2025-03-10 — Updated compiled truth.
            - 2025-01-15 — Page created.
        """))
        results = check_stale_pages(tmp_path)
        assert len(results) == 0

    def test_no_timeline_section(self, tmp_path):
        wiki = tmp_path / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "test.md").write_text(textwrap.dedent("""\
            ---
            updated: 2025-01-15
            ---

            # Test

            No timeline section here.
        """))
        results = check_stale_pages(tmp_path)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# check_unbalanced_pages
# ---------------------------------------------------------------------------

class TestCheckUnbalancedPages:
    def test_unbalanced_found(self, tmp_path):
        wiki = tmp_path / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        entries = "\n".join(
            f"- 2025-03-{10 + i:02d} — Entry {i + 1}." for i in range(6)
        )
        content = (
            "---\nupdated: 2025-01-15\n---\n\n"
            "# Test\n\nOld compiled truth.\n\n"
            "---\n\n## Timeline\n\n"
            f"{entries}\n"
            "- 2025-01-15 — Page created.\n"
        )
        (wiki / "test.md").write_text(content)
        results = check_unbalanced_pages(tmp_path)
        assert len(results) == 1
        assert results[0]["new_entries"] == 6

    def test_below_threshold_not_flagged(self, tmp_path):
        wiki = tmp_path / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        entries = "\n".join(
            f"- 2025-03-{10 + i:02d} — Entry {i + 1}." for i in range(3)
        )
        content = (
            "---\nupdated: 2025-01-15\n---\n\n"
            "# Test\n\nCompiled truth.\n\n"
            "---\n\n## Timeline\n\n"
            f"{entries}\n"
            "- 2025-01-15 — Page created.\n"
        )
        (wiki / "test.md").write_text(content)
        results = check_unbalanced_pages(tmp_path)
        assert len(results) == 0
