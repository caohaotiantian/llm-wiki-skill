#!/usr/bin/env python3
"""Embedding provider interface for wiki index.

Providers:
- NullProvider: returns empty embeddings, query falls back to keyword-only
- LocalProvider: sentence-transformers/all-MiniLM-L6-v2 (384 dims, no API key)
- RemoteProvider: any OpenAI-compatible embedding API (configurable via env vars)

Configuration (environment variables):
    EMBEDDING_PROVIDER   Force provider: "openai"/"remote", "local", "null"
    EMBEDDING_API_KEY    API key (falls back to OPENAI_API_KEY)
    EMBEDDING_BASE_URL   Custom endpoint URL (e.g. http://localhost:11434/v1 for Ollama)
    EMBEDDING_MODEL      Model name (default: text-embedding-3-small)
    EMBEDDING_DIMENSION  Override vector dimension (default: auto-detect)

Usage:
    python embeddings.py --provider null --text "hello world"
    python embeddings.py --provider remote --text "test embedding"
    EMBEDDING_BASE_URL=http://localhost:11434/v1 python embeddings.py --text "test"
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Protocol, runtime_checkable


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


class RemoteProvider:
    """Remote embeddings via any OpenAI-compatible API.

    Works with OpenAI, Azure OpenAI, Ollama, vLLM, Together, Groq,
    DeepSeek, and any other provider exposing /v1/embeddings.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        dimension: int | None = None,
    ):
        import openai

        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self._client = openai.OpenAI(**kwargs)
        self._model = model
        self._dimension = dimension

    def dimension(self) -> int:
        if self._dimension is None:
            result = self.embed_batch(["dimension probe"])
            self._dimension = len(result[0]) if result and result[0] else 0
        return self._dimension

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]

    def name(self) -> str:
        return f"remote/{self._model}"


# Backward compatibility alias
OpenAIProvider = RemoteProvider


def _make_remote_provider() -> RemoteProvider:
    """Create a RemoteProvider from environment variables."""
    dimension_str = os.environ.get("EMBEDDING_DIMENSION")
    return RemoteProvider(
        api_key=os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("EMBEDDING_BASE_URL"),
        model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
        dimension=int(dimension_str) if dimension_str else None,
    )


def get_provider(provider_name: str | None = None) -> EmbeddingProvider:
    """Get an embedding provider by name or auto-detect.

    Resolution order (when provider_name is None):
    1. Check EMBEDDING_PROVIDER env var
    2. If EMBEDDING_API_KEY or OPENAI_API_KEY is set, use remote
    3. If sentence-transformers is installed, use local
    4. Fall back to null (keyword-only search)
    """
    if provider_name is None:
        provider_name = os.environ.get("EMBEDDING_PROVIDER")

    if provider_name == "null":
        return NullProvider()
    if provider_name == "local":
        return LocalProvider()
    if provider_name in ("openai", "remote"):
        return _make_remote_provider()

    if provider_name is None:
        api_key = os.environ.get("EMBEDDING_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if api_key:
            try:
                return _make_remote_provider()
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
    parser.add_argument("--provider", default=None,
                        help="Provider: null, local, openai/remote (default: auto-detect)")
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
