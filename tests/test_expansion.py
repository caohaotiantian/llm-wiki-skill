#!/usr/bin/env python3
"""Tests for expansion.py."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "llm-wiki", "scripts"))

from expansion import expand_query


def test_expand_query_no_api_key():
    """Without ANTHROPIC_API_KEY, returns original query only."""
    with patch.dict(os.environ, {}, clear=True):
        # Remove any existing key
        os.environ.pop("ANTHROPIC_API_KEY", None)
        result = expand_query("test query")
        assert result == ["test query"]


def test_expand_query_no_anthropic_module():
    """Without anthropic module installed, returns original query only."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"anthropic": None}):
            result = expand_query("test query")
            assert result == ["test query"]


def test_expand_query_with_mock_api():
    """With a mocked API, returns original + expansions."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="paraphrase one\nparaphrase two\nparaphrase three")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test query", max_expansions=3)
            assert result[0] == "test query"
            assert len(result) == 4  # original + 3 expansions
            assert "paraphrase one" in result


def test_expand_query_api_error():
    """API errors should return original query only."""
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value.messages.create.side_effect = Exception("API error")

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test query")
            assert result == ["test query"]


def test_expand_query_max_expansions():
    """Should respect max_expansions limit."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="a\nb\nc\nd\ne")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test", max_expansions=2)
            assert len(result) <= 3  # original + max 2


def test_expand_query_empty_response():
    """Empty API response returns original only."""
    mock_anthropic = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="")]
    mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_response

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-key"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = expand_query("test query")
            assert result == ["test query"]
