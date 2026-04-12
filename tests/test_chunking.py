#!/usr/bin/env python3
"""Tests for chunking.py."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from chunking import chunk_text, chunk_page


def test_chunk_short_text():
    """Short text stays in one chunk."""
    text = "Short paragraph."
    chunks = chunk_text(text, target_words=300, overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == "Short paragraph."


def test_chunk_splits_long_text():
    """Long text is split into multiple chunks."""
    paras = [f"Paragraph {i}. " + "word " * 100 for i in range(5)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, target_words=150, overlap=20)
    assert len(chunks) > 1


def test_chunk_overlap_present():
    """Overlap words from end of one chunk appear in next chunk."""
    para1 = "alpha " * 200
    para2 = "beta " * 200
    text = para1.strip() + "\n\n" + para2.strip()
    chunks = chunk_text(text, target_words=250, overlap=50)
    assert len(chunks) >= 2
    # Last words of chunk 0 should appear at start of chunk 1
    last_words_set = set(chunks[0].split()[-30:])
    first_words_set = set(chunks[1].split()[:60])
    overlap_count = len(last_words_set & first_words_set)
    assert overlap_count > 0


def test_chunk_empty():
    """Empty and whitespace-only input returns empty list."""
    assert chunk_text("") == []
    assert chunk_text("   ") == []
    assert chunk_text("\n\n") == []


def test_chunk_single_paragraph_within_limit():
    """Single paragraph within limit stays as one chunk."""
    words = "word " * 299
    chunks = chunk_text(words.strip(), target_words=300, overlap=50)
    assert len(chunks) == 1


def test_chunk_preserves_paragraph_structure():
    """Multiple short paragraphs within limit are joined."""
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_text(text, target_words=1000, overlap=50)
    assert len(chunks) == 1
    assert "First paragraph." in chunks[0]
    assert "Second paragraph." in chunks[0]
    assert "Third paragraph." in chunks[0]


def test_chunk_page_basic():
    """chunk_page separates compiled truth from timeline."""
    content = """---
tags: [concept]
updated: 2026-01-01
---

# My Concept

This is the compiled truth about the concept.

---

## Timeline

- 2026-01-01: Initial creation
- 2025-12-15: Preliminary research
"""
    result = chunk_page(content)
    assert "compiled_truth" in result
    assert "timeline" in result
    assert len(result["compiled_truth"]) >= 1
    assert len(result["timeline"]) >= 1
    assert "compiled truth" in result["compiled_truth"][0].lower()
    assert "2026-01-01" in result["timeline"][0]


def test_chunk_page_no_timeline():
    """Page without timeline separator has empty timeline chunks."""
    content = """---
tags: [concept]
---

# Just Content

No timeline here.
"""
    result = chunk_page(content)
    assert len(result["compiled_truth"]) >= 1
    assert result["timeline"] == []


def test_chunk_page_no_frontmatter():
    """Page without frontmatter still chunks the body."""
    content = "# Title\n\nSome content here.\n\n---\n\n## Timeline\n\n- 2026-01-01: Event"
    result = chunk_page(content)
    assert len(result["compiled_truth"]) >= 1
    assert len(result["timeline"]) >= 1
