#!/usr/bin/env python3
"""Multi-query expansion for better retrieval recall.

Generates paraphrases of a query using either an Anthropic-compatible
or OpenAI-compatible chat API. Falls back to returning the original
query when no API key is available or the call fails.

Configuration (environment variables):
    EXPANSION_PROVIDER   Force provider: "anthropic" or "openai"
    EXPANSION_API_KEY    API key (falls back to ANTHROPIC_API_KEY then OPENAI_API_KEY)
    EXPANSION_BASE_URL   Custom endpoint URL
    EXPANSION_MODEL      Model name (default: per-provider)

Usage:
    python expansion.py "what are our biggest risks?"
    python expansion.py "when should you ignore conventional wisdom?" --json
    EXPANSION_PROVIDER=openai EXPANSION_API_KEY=sk-... python expansion.py "test"
"""
from __future__ import annotations

import argparse
import json
import os

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _expansion_prompt(query: str, max_expansions: int) -> str:
    """Build the prompt for query expansion."""
    return (
        f"Generate {max_expansions} alternative phrasings of this search query. "
        f"Each should capture different aspects or use different vocabulary. "
        f"Return ONLY the paraphrases, one per line, no numbering or bullets.\n\n"
        f"Query: {query}"
    )


def _parse_expansion_response(query: str, text: str, max_expansions: int) -> list[str]:
    """Parse expansion response text into query list."""
    text = (text or "").strip()
    expansions = [line.strip() for line in text.split("\n") if line.strip()]
    if not expansions:
        return [query]
    return [query] + expansions[:max_expansions]


def _expand_anthropic(
    query: str,
    max_expansions: int,
    *,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> list[str]:
    """Expand query using an Anthropic-compatible API."""
    if not api_key:
        return [query]
    try:
        import anthropic
    except ImportError:
        return [query]
    try:
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        client = anthropic.Anthropic(**kwargs)
        response = client.messages.create(
            model=model or DEFAULT_ANTHROPIC_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": _expansion_prompt(query, max_expansions)}],
        )
        return _parse_expansion_response(query, response.content[0].text, max_expansions)
    except Exception:
        return [query]


def _expand_openai(
    query: str,
    max_expansions: int,
    *,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> list[str]:
    """Expand query using an OpenAI-compatible chat API."""
    if not api_key:
        return [query]
    try:
        import openai
    except ImportError:
        return [query]
    try:
        kwargs: dict = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        client = openai.OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=model or DEFAULT_OPENAI_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": _expansion_prompt(query, max_expansions)}],
        )
        text = response.choices[0].message.content
        return _parse_expansion_response(query, text, max_expansions)
    except Exception:
        return [query]


def expand_query(query: str, max_expansions: int = 3) -> list[str]:
    """Expand a query into multiple paraphrases for better retrieval.

    Provider resolution:
    1. EXPANSION_PROVIDER env var ("anthropic" or "openai")
    2. Auto-detect from available API keys:
       EXPANSION_API_KEY → ANTHROPIC_API_KEY → OPENAI_API_KEY

    Returns [query] (original only) when no provider is available.
    """
    provider = os.environ.get("EXPANSION_PROVIDER", "").lower()
    api_key = os.environ.get("EXPANSION_API_KEY")
    base_url = os.environ.get("EXPANSION_BASE_URL")
    model = os.environ.get("EXPANSION_MODEL")

    # Explicit provider selection
    if provider == "anthropic":
        return _expand_anthropic(
            query, max_expansions,
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            base_url=base_url, model=model,
        )
    if provider == "openai":
        return _expand_openai(
            query, max_expansions,
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=base_url, model=model,
        )

    # Auto-detect from available keys (backward compatible)
    if api_key:
        # With a generic key, default to OpenAI-compatible
        return _expand_openai(query, max_expansions, api_key=api_key, base_url=base_url, model=model)

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        return _expand_anthropic(query, max_expansions, api_key=anthropic_key, base_url=base_url, model=model)

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return _expand_openai(query, max_expansions, api_key=openai_key, base_url=base_url, model=model)

    return [query]


def main():
    parser = argparse.ArgumentParser(
        description="Expand a query into multiple paraphrases for better retrieval.",
    )
    parser.add_argument("query", help="Query text to expand")
    parser.add_argument(
        "--max-expansions", type=int, default=3,
        help="Maximum paraphrases to generate (default: 3)",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="JSON output",
    )

    args = parser.parse_args()
    expansions = expand_query(args.query, args.max_expansions)

    if args.json_output:
        print(json.dumps({"original": args.query, "expansions": expansions}, indent=2))
    else:
        print(f"Original: {args.query}")
        for i, exp in enumerate(expansions):
            label = "Original" if i == 0 else f"Expansion {i}"
            print(f"  [{label}] {exp}")


if __name__ == "__main__":
    main()
