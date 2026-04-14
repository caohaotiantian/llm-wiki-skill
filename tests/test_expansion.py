#!/usr/bin/env python3
"""Tests for expansion.py."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from expansion import expand_query


def test_expand_query_no_api_key():
    """Without any API key, returns original query only."""
    with patch.dict(os.environ, {}, clear=True):
        result = expand_query("test query")
        assert result == ["test query"]


def test_expand_query_no_anthropic_module():
    """Without anthropic module installed, returns original query only."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=True):
        with patch.dict("sys.modules", {"anthropic": None}):
            result = expand_query("test query")
            assert result == ["test query"]


def test_expand_query_with_mock_anthropic():
    """With a mocked Anthropic API, returns original + expansions."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="paraphrase one\nparaphrase two\nparaphrase three")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=True):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test query", max_expansions=3)
            assert result[0] == "test query"
            assert len(result) == 4  # original + 3 expansions
            assert "paraphrase one" in result


def test_expand_query_api_error():
    """API errors should return original query only."""
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value.messages.create.side_effect = Exception("API error")

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=True):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test query")
            assert result == ["test query"]


def test_expand_query_max_expansions():
    """Should respect max_expansions limit."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="a\nb\nc\nd\ne")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=True):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test", max_expansions=2)
            assert len(result) <= 3  # original + max 2


def test_expand_query_empty_response():
    """Empty API response returns original only."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}, clear=True):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test query")
            assert result == ["test query"]


# --- OpenAI-compatible provider tests ---


def test_expand_query_openai_provider():
    """EXPANSION_PROVIDER=openai uses OpenAI chat completions."""
    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="rephrase A\nrephrase B"))]
    mock_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

    env = {"EXPANSION_PROVIDER": "openai", "EXPANSION_API_KEY": "fake-key"}
    with patch.dict(os.environ, env, clear=True):
        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = expand_query("test query", max_expansions=3)
            assert result[0] == "test query"
            assert "rephrase A" in result
            assert "rephrase B" in result


def test_expand_query_openai_custom_model():
    """EXPANSION_MODEL env var overrides default model."""
    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="alt query"))]
    mock_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

    env = {
        "EXPANSION_PROVIDER": "openai",
        "EXPANSION_API_KEY": "key",
        "EXPANSION_MODEL": "deepseek-chat",
    }
    with patch.dict(os.environ, env, clear=True):
        with patch.dict("sys.modules", {"openai": mock_openai}):
            expand_query("test")
            call_kwargs = mock_openai.OpenAI.return_value.chat.completions.create.call_args
            assert call_kwargs.kwargs.get("model") == "deepseek-chat" or call_kwargs[1].get("model") == "deepseek-chat"


def test_expand_query_openai_custom_base_url():
    """EXPANSION_BASE_URL configures custom endpoint."""
    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="alt"))]
    mock_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

    env = {
        "EXPANSION_PROVIDER": "openai",
        "EXPANSION_API_KEY": "key",
        "EXPANSION_BASE_URL": "http://localhost:11434/v1",
    }
    with patch.dict(os.environ, env, clear=True):
        with patch.dict("sys.modules", {"openai": mock_openai}):
            expand_query("test")
            mock_openai.OpenAI.assert_called_once_with(
                api_key="key",
                base_url="http://localhost:11434/v1",
            )


def test_expand_query_auto_detect_openai():
    """With only OPENAI_API_KEY (no ANTHROPIC_API_KEY), auto-detects OpenAI."""
    mock_openai = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="rephrased"))]
    mock_openai.OpenAI.return_value.chat.completions.create.return_value = mock_response

    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True):
        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = expand_query("test query")
            assert result[0] == "test query"
            assert "rephrased" in result


def test_expand_query_openai_error():
    """OpenAI API errors should return original query only."""
    mock_openai = MagicMock()
    mock_openai.OpenAI.return_value.chat.completions.create.side_effect = Exception("error")

    env = {"EXPANSION_PROVIDER": "openai", "EXPANSION_API_KEY": "key"}
    with patch.dict(os.environ, env, clear=True):
        with patch.dict("sys.modules", {"openai": mock_openai}):
            result = expand_query("test")
            assert result == ["test"]


def test_expand_query_anthropic_explicit_provider():
    """EXPANSION_PROVIDER=anthropic explicitly selects Anthropic."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="alt phrasing")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    env = {"EXPANSION_PROVIDER": "anthropic", "EXPANSION_API_KEY": "key"}
    with patch.dict(os.environ, env, clear=True):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test")
            assert "alt phrasing" in result
