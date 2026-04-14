#!/usr/bin/env python3
"""Tests for embeddings.py."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from embeddings import NullProvider, RemoteProvider, OpenAIProvider, get_provider, EmbeddingProvider


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
    old_key = os.environ.pop("OPENAI_API_KEY", None)
    old_emb = os.environ.pop("EMBEDDING_API_KEY", None)
    old_prov = os.environ.pop("EMBEDDING_PROVIDER", None)
    try:
        p = get_provider()
        assert p.name() in ("null", "local/all-MiniLM-L6-v2")
    finally:
        if old_key is not None:
            os.environ["OPENAI_API_KEY"] = old_key
        if old_emb is not None:
            os.environ["EMBEDDING_API_KEY"] = old_emb
        if old_prov is not None:
            os.environ["EMBEDDING_PROVIDER"] = old_prov


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


def test_openai_provider_is_remote_provider():
    """OpenAIProvider is an alias for RemoteProvider (backward compat)."""
    assert OpenAIProvider is RemoteProvider


def test_remote_provider_custom_params():
    """RemoteProvider accepts custom base_url, model, and dimension."""
    mock_openai = MagicMock()
    with patch.dict("sys.modules", {"openai": mock_openai}):
        p = RemoteProvider(
            api_key="test-key",
            base_url="http://localhost:11434/v1",
            model="nomic-embed-text",
            dimension=768,
        )
        assert p.dimension() == 768
        assert p.name() == "remote/nomic-embed-text"
        mock_openai.OpenAI.assert_called_once_with(
            api_key="test-key",
            base_url="http://localhost:11434/v1",
        )


def test_get_provider_from_embedding_provider_env():
    """EMBEDDING_PROVIDER env var forces provider selection."""
    with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "null"}, clear=False):
        p = get_provider()
        assert p.name() == "null"


def test_get_provider_remote_from_env():
    """EMBEDDING_PROVIDER=remote with EMBEDDING_API_KEY creates RemoteProvider."""
    mock_openai = MagicMock()
    env = {
        "EMBEDDING_PROVIDER": "remote",
        "EMBEDDING_API_KEY": "fake-key",
        "EMBEDDING_BASE_URL": "http://custom:8080/v1",
        "EMBEDDING_MODEL": "custom-model",
        "EMBEDDING_DIMENSION": "512",
    }
    with patch.dict(os.environ, env, clear=False):
        with patch.dict("sys.modules", {"openai": mock_openai}):
            p = get_provider()
            assert isinstance(p, RemoteProvider)
            assert p.name() == "remote/custom-model"
            assert p.dimension() == 512
            mock_openai.OpenAI.assert_called_once_with(
                api_key="fake-key",
                base_url="http://custom:8080/v1",
            )


def test_get_provider_backward_compat_openai_key():
    """OPENAI_API_KEY without EMBEDDING_* vars still works (backward compat)."""
    mock_openai = MagicMock()
    env = {"OPENAI_API_KEY": "sk-old-style"}
    # Clear any EMBEDDING_* vars
    clear = {k: "" for k in os.environ if k.startswith("EMBEDDING_")}
    with patch.dict(os.environ, {**env, **clear}, clear=False):
        # Remove cleared vars
        for k in clear:
            os.environ.pop(k, None)
        with patch.dict("sys.modules", {"openai": mock_openai}):
            p = get_provider()
            assert isinstance(p, RemoteProvider)
            assert p.name() == "remote/text-embedding-3-small"


def test_remote_provider_dimension_auto_detect():
    """When dimension is not specified, probe via embed_batch on first call."""
    mock_openai = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.embedding = [0.1] * 768
    mock_response = MagicMock()
    mock_response.data = [mock_embedding]
    mock_openai.OpenAI.return_value.embeddings.create.return_value = mock_response

    with patch.dict("sys.modules", {"openai": mock_openai}):
        p = RemoteProvider(api_key="key", dimension=None)
        dim = p.dimension()
        assert dim == 768
        # Second call should use cached value
        dim2 = p.dimension()
        assert dim2 == 768
