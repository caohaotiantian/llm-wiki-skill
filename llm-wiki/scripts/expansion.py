#!/usr/bin/env python3
"""Multi-query expansion via Anthropic API.

Generates paraphrases of a query to improve retrieval recall.
Gated on ANTHROPIC_API_KEY — falls back to returning the original query
when the key is absent or the API call fails.

Usage:
    python expansion.py "what are our biggest risks?"
    python expansion.py "when should you ignore conventional wisdom?" --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def expand_query(query: str, max_expansions: int = 3) -> list[str]:
    """Expand a query into multiple paraphrases for better retrieval.

    If ANTHROPIC_API_KEY is not set or the API call fails,
    returns [query] (the original query only).

    Args:
        query: The original user query.
        max_expansions: Maximum number of paraphrases to generate.

    Returns:
        List of query strings (original + paraphrases).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return [query]

    try:
        import anthropic
    except ImportError:
        return [query]

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": (
                    f"Generate {max_expansions} alternative phrasings of this search query. "
                    f"Each should capture different aspects or use different vocabulary. "
                    f"Return ONLY the paraphrases, one per line, no numbering or bullets.\n\n"
                    f"Query: {query}"
                ),
            }],
        )
        text = response.content[0].text.strip()
        expansions = [line.strip() for line in text.split("\n") if line.strip()]
        # Always include the original query first
        return [query] + expansions[:max_expansions]
    except Exception:
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
