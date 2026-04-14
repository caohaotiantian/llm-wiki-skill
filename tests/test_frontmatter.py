#!/usr/bin/env python3
"""Tests for frontmatter.py — shared YAML frontmatter parser."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))


class TestParse:
    def test_basic_key_value(self):
        from frontmatter import parse
        content = "---\ntitle: My Page\nstatus: active\n---\n\n# Body"
        fm, body = parse(content)
        assert fm["title"] == "My Page"
        assert fm["status"] == "active"
        assert "# Body" in body

    def test_no_frontmatter(self):
        from frontmatter import parse
        content = "# Just a heading\n\nSome text."
        fm, body = parse(content)
        assert fm == {}
        assert body == content

    def test_malformed_yaml(self):
        from frontmatter import parse
        content = "---\n: invalid: yaml: [[[broken\n---\n\nBody"
        fm, body = parse(content)
        assert fm == {}
        assert "Body" in body

    def test_inline_list(self):
        from frontmatter import parse
        content = "---\ntags: [concept, strategy, draft]\n---\n"
        fm, _ = parse(content)
        assert fm["tags"] == ["concept", "strategy", "draft"]

    def test_block_list(self):
        from frontmatter import parse
        content = "---\ntags:\n  - concept\n  - strategy\n---\n"
        fm, _ = parse(content)
        assert fm["tags"] == ["concept", "strategy"]

    def test_nested_objects(self):
        from frontmatter import parse
        content = "---\nlinks:\n  - {target: \"page-a\", type: \"references\"}\n  - {target: \"page-b\", type: \"contradicts\"}\n---\n"
        fm, _ = parse(content)
        assert len(fm["links"]) == 2
        assert fm["links"][0]["target"] == "page-a"
        assert fm["links"][0]["type"] == "references"
        assert fm["links"][1]["target"] == "page-b"
        assert fm["links"][1]["type"] == "contradicts"

    def test_quoted_values_with_commas(self):
        from frontmatter import parse
        content = '---\naliases: ["Smith, John", "Bob"]\n---\n'
        fm, _ = parse(content)
        assert fm["aliases"] == ["Smith, John", "Bob"]

    def test_boolean_values(self):
        from frontmatter import parse
        content = "---\npublished: true\ndraft: false\n---\n"
        fm, _ = parse(content)
        assert fm["published"] is True
        assert fm["draft"] is False

    def test_numeric_values(self):
        from frontmatter import parse
        content = "---\nweight: 5\nconfidence: 0.8\n---\n"
        fm, _ = parse(content)
        assert fm["weight"] == 5
        assert isinstance(fm["weight"], int)
        assert fm["confidence"] == 0.8
        assert isinstance(fm["confidence"], float)

    def test_empty_value_null(self):
        from frontmatter import parse
        content = "---\naliases:\nstatus: active\n---\n"
        fm, _ = parse(content)
        assert fm["aliases"] is None
        assert fm["status"] == "active"

    def test_tilde_null(self):
        from frontmatter import parse
        content = "---\naliases: ~\n---\n"
        fm, _ = parse(content)
        assert fm["aliases"] is None

    def test_body_preserved(self):
        from frontmatter import parse
        content = "---\ntitle: Test\n---\n\n# Heading\n\nParagraph text."
        fm, body = parse(content)
        assert body.strip().startswith("# Heading")
        assert "Paragraph text." in body

    def test_dots_closing_delimiter(self):
        from frontmatter import parse
        content = "---\ntitle: Test\n...\n\nBody."
        fm, body = parse(content)
        assert fm["title"] == "Test"
        assert "Body." in body

    def test_crlf_normalization(self):
        from frontmatter import parse
        content = "---\r\ntitle: Test\r\n---\r\n\r\nBody."
        fm, body = parse(content)
        assert fm["title"] == "Test"
        assert "Body." in body


class TestParseTypedLinks:
    def test_valid_links(self):
        from frontmatter import parse_typed_links
        fm = {"links": [
            {"target": "page-a", "type": "references"},
            {"target": "page-b", "type": "contradicts"},
        ]}
        result = parse_typed_links(fm)
        assert len(result) == 2
        assert result[0] == {"target": "page-a", "type": "references"}
        assert result[1] == {"target": "page-b", "type": "contradicts"}

    def test_missing_target(self):
        from frontmatter import parse_typed_links
        fm = {"links": [
            {"type": "references"},
            {"target": "page-b", "type": "contradicts"},
        ]}
        result = parse_typed_links(fm)
        assert len(result) == 1
        assert result[0]["target"] == "page-b"

    def test_missing_type(self):
        from frontmatter import parse_typed_links
        fm = {"links": [{"target": "page-a"}]}
        result = parse_typed_links(fm)
        assert len(result) == 0

    def test_empty_links(self):
        from frontmatter import parse_typed_links
        fm = {"links": []}
        assert parse_typed_links(fm) == []

    def test_no_links_field(self):
        from frontmatter import parse_typed_links
        fm = {"title": "Test"}
        assert parse_typed_links(fm) == []

    def test_links_is_none(self):
        from frontmatter import parse_typed_links
        fm = {"links": None}
        assert parse_typed_links(fm) == []


class TestParseAliases:
    def test_inline_list(self):
        from frontmatter import parse_aliases
        fm = {"aliases": ["AI", "Artificial Intelligence"]}
        assert parse_aliases(fm) == ["AI", "Artificial Intelligence"]

    def test_empty_list(self):
        from frontmatter import parse_aliases
        fm = {"aliases": []}
        assert parse_aliases(fm) == []

    def test_no_aliases_field(self):
        from frontmatter import parse_aliases
        fm = {"title": "Test"}
        assert parse_aliases(fm) == []

    def test_aliases_is_none(self):
        from frontmatter import parse_aliases
        fm = {"aliases": None}
        assert parse_aliases(fm) == []

    def test_single_string(self):
        from frontmatter import parse_aliases
        fm = {"aliases": "Single Alias"}
        assert parse_aliases(fm) == ["Single Alias"]


class TestParseTags:
    def test_inline_list(self):
        from frontmatter import parse_tags
        fm = {"tags": ["concept", "strategy", "draft"]}
        assert parse_tags(fm) == ["concept", "strategy", "draft"]

    def test_empty_list(self):
        from frontmatter import parse_tags
        fm = {"tags": []}
        assert parse_tags(fm) == []

    def test_no_tags_field(self):
        from frontmatter import parse_tags
        fm = {"title": "Test"}
        assert parse_tags(fm) == []

    def test_tags_is_none(self):
        from frontmatter import parse_tags
        fm = {"tags": None}
        assert parse_tags(fm) == []

    def test_single_string(self):
        from frontmatter import parse_tags
        fm = {"tags": "concept"}
        assert parse_tags(fm) == ["concept"]


class TestExtractFrontmatterBlock:
    def test_present(self):
        from frontmatter import extract_frontmatter_block
        content = "---\ntitle: Test\nstatus: active\n---\n\nBody."
        raw = extract_frontmatter_block(content)
        assert "title: Test" in raw
        assert "Body." not in raw

    def test_missing(self):
        from frontmatter import extract_frontmatter_block
        content = "# No frontmatter\n\nJust text."
        assert extract_frontmatter_block(content) is None

    def test_dots_delimiter(self):
        from frontmatter import extract_frontmatter_block
        content = "---\ntitle: Test\n...\n\nBody."
        raw = extract_frontmatter_block(content)
        assert "title: Test" in raw


class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        from frontmatter import atomic_write
        target = tmp_path / "test.md"
        atomic_write(target, "hello world")
        assert target.read_text() == "hello world"

    def test_overwrites_existing(self, tmp_path):
        from frontmatter import atomic_write
        target = tmp_path / "test.md"
        target.write_text("old content")
        atomic_write(target, "new content")
        assert target.read_text() == "new content"

    def test_no_partial_write_on_error(self, tmp_path):
        from frontmatter import atomic_write
        target = tmp_path / "test.md"
        target.write_text("original")

        class FakeError(Exception):
            pass

        # Monkey-patch os.replace to simulate failure after write
        import os as _os
        real_replace = _os.replace
        def failing_replace(src, dst):
            raise FakeError("simulated failure")
        _os.replace = failing_replace
        try:
            try:
                atomic_write(target, "should not persist")
            except FakeError:
                pass
            # Original file untouched
            assert target.read_text() == "original"
            # No temp files left
            temps = list(tmp_path.glob("*.tmp"))
            assert len(temps) == 0
        finally:
            _os.replace = real_replace

    def test_creates_parent_dirs(self, tmp_path):
        from frontmatter import atomic_write
        target = tmp_path / "sub" / "dir" / "test.md"
        atomic_write(target, "nested")
        assert target.read_text() == "nested"


class TestJsonDefault:
    def test_date_serialization(self):
        import json
        from datetime import date
        from frontmatter import json_default
        data = {"created": date(2026, 4, 1), "title": "Test"}
        result = json.dumps(data, default=json_default)
        assert '"2026-04-01"' in result
        assert '"Test"' in result

    def test_datetime_serialization(self):
        import json
        from datetime import datetime
        from frontmatter import json_default
        data = {"updated": datetime(2026, 4, 1, 14, 30, 0)}
        result = json.dumps(data, default=json_default)
        assert '"2026-04-01T14:30:00"' in result

    def test_non_date_raises(self):
        import json
        import pytest
        from frontmatter import json_default
        with pytest.raises(TypeError):
            json.dumps({"bad": object()}, default=json_default)

    def test_frontmatter_with_yaml_dates(self):
        """End-to-end: parse YAML with dates, serialize to JSON."""
        import json
        from frontmatter import parse, json_default
        content = "---\ntitle: Test\ncreated: 2026-04-01\nupdated: 2026-04-13\n---\n\nBody."
        fm, _ = parse(content)
        # PyYAML converts these to date objects
        from datetime import date
        assert isinstance(fm["created"], date)
        # json.dumps should work with our default handler
        result = json.dumps(fm, default=json_default)
        assert "2026-04-01" in result
        assert "2026-04-13" in result
