#!/usr/bin/env python3
"""Embedding provider interface for wiki index.

Three providers:
- NullProvider: returns empty embeddings, query falls back to keyword-only
- LocalProvider: sentence-transformers/all-MiniLM-L6-v2 (384 dims, no API key)
- OpenAIProvider: text-embedding-3-small (1536 dims, requires OPENAI_API_KEY)

Usage:
    python embeddings.py --provider null --text "hello world"
    python embeddings.py --provider local --text "test embedding"
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for embedding providers."""

    def dimension(self) -> int: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    def name(self) -> str: ...


class NullProvider:
    """No-op provider. Query falls back to keyword-only search."""

    def dimension(self) -> int:
        return 0

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[] for _ in texts]

    def name(self) -> str:
        return "null"


class LocalProvider:
    """Local embeddings via sentence-transformers (384 dims, CPU)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._model_name = model_name

    def dimension(self) -> int:
        return 384

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return [e.tolist() for e in embeddings]

    def name(self) -> str:
        return f"local/{self._model_name}"


class OpenAIProvider:
    """OpenAI embeddings via API (1536 dims)."""

    def __init__(self, model: str = "text-embedding-3-small"):
        import openai

        self._client = openai.OpenAI()
        self._model = model

    def dimension(self) -> int:
        return 1536

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]

    def name(self) -> str:
        return f"openai/{self._model}"


def get_provider(provider_name: str | None = None) -> EmbeddingProvider:
    """Get an embedding provider by name or auto-detect.

    Auto-detection order (when provider_name is None):
    1. If OPENAI_API_KEY is set, use OpenAI
    2. If sentence-transformers is installed, use local
    3. Fall back to null (keyword-only search)
    """
    if provider_name == "null":
        return NullProvider()
    if provider_name == "openai":
        return OpenAIProvider()
    if provider_name == "local":
        return LocalProvider()

    if provider_name is None:
        if os.environ.get("OPENAI_API_KEY"):
            try:
                return OpenAIProvider()
            except ImportError:
                pass
        try:
            return LocalProvider()
        except ImportError:
            pass
        return NullProvider()

    raise ValueError(f"Unknown embedding provider: {provider_name}")


def main():
    parser = argparse.ArgumentParser(description="Embedding provider CLI.")
    parser.add_argument("--provider", default=None, help="Provider name: null, local, openai (default: auto-detect)")
    parser.add_argument("--text", nargs="+", help="Text(s) to embed")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output")

    args = parser.parse_args()
    provider = get_provider(args.provider)

    if not args.text:
        print(f"Provider: {provider.name()}, Dimension: {provider.dimension()}")
        return

    embeddings = provider.embed_batch(args.text)
    if args.json_output:
        print(json.dumps({"provider": provider.name(), "dimension": provider.dimension(), "embeddings": embeddings}))
    else:
        print(f"Provider: {provider.name()}, Dimension: {provider.dimension()}")
        for i, (text, emb) in enumerate(zip(args.text, embeddings)):
            preview = emb[:5] if emb else []
            print(f"  [{i}] '{text[:50]}...' -> [{len(emb)} dims] {preview}...")


if __name__ == "__main__":
    main()
