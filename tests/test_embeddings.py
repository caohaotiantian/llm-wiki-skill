#!/usr/bin/env python3
"""Tests for embeddings.py."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from embeddings import NullProvider, get_provider, EmbeddingProvider


def test_null_provider_dimension():
    p = NullProvider()
    assert p.dimension() == 0


def test_null_provider_embed_batch():
    p = NullProvider()
    result = p.embed_batch(["hello", "world"])
    assert result == [[], []]


def test_null_provider_name():
    p = NullProvider()
    assert p.name() == "null"


def test_null_provider_implements_protocol():
    p = NullProvider()
    assert isinstance(p, EmbeddingProvider)


def test_get_provider_null():
    p = get_provider(provider_name="null")
    assert p.name() == "null"
    assert p.dimension() == 0


def test_get_provider_default_no_deps():
    """Without sentence-transformers or OPENAI_API_KEY, falls back to null."""
    # Remove OPENAI_API_KEY if set to test fallback
    old_key = os.environ.pop("OPENAI_API_KEY", None)
    try:
        p = get_provider()
        assert p.name() in ("null", "local/all-MiniLM-L6-v2")
    finally:
        if old_key is not None:
            os.environ["OPENAI_API_KEY"] = old_key


def test_get_provider_unknown_raises():
    try:
        get_provider(provider_name="nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "nonexistent" in str(e)


def test_null_provider_empty_input():
    p = NullProvider()
    result = p.embed_batch([])
    assert result == []
