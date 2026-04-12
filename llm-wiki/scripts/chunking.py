#!/usr/bin/env python3
"""Recursive text chunking for wiki pages.

Splits text into chunks of approximately target_words with overlap.
Respects paragraph boundaries. Used by index.py for embedding preparation.

Usage:
    python chunking.py --help
    # This module is primarily used as a library by index.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys


def chunk_text(
    text: str,
    target_words: int = 300,
    overlap: int = 50,
) -> list[str]:
    """Split text into chunks respecting paragraph boundaries.

    Uses a 5-level delimiter hierarchy (matching gbrain's recursive chunker):
    splits on double-newlines (paragraphs) first. Each chunk targets
    target_words words with overlap words carried over to the next chunk
    for context continuity.

    Args:
        text: Input text to chunk.
        target_words: Target number of words per chunk.
        overlap: Number of words to overlap between consecutive chunks.

    Returns:
        List of text chunks. Empty list for empty/whitespace input.
    """
    text = text.strip()
    if not text:
        return []

    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current: list[str] = []
    count = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        words = para.split()
        if count + len(words) <= target_words:
            current.append(para)
            count += len(words)
        else:
            if current:
                chunks.append("\n\n".join(current))
            tail_words = " ".join(current).split()[-overlap:] if current else []
            if tail_words:
                current = [" ".join(tail_words), para]
                count = len(tail_words) + len(words)
            else:
                current = [para]
                count = len(words)

    if current:
        chunks.append("\n\n".join(current))

    return chunks


def chunk_page(content: str, target_words: int = 300, overlap: int = 50) -> dict:
    """Chunk a wiki page, separating compiled truth from timeline.

    Recognizes the compiled-truth/timeline separator (--- on its own line
    after frontmatter). Returns chunks tagged with their source zone.

    Returns:
        {"compiled_truth": [str, ...], "timeline": [str, ...]}
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # Strip frontmatter
    fm_match = re.match(r"^---\s*\n.*?\n(?:---|\.\.\.)(?:\s*\n)", content, re.DOTALL)
    body = content[fm_match.end():] if fm_match else content

    # Split on horizontal rule separator
    parts = re.split(r"\n---\s*\n", body, maxsplit=1)
    compiled_truth = parts[0].strip()
    timeline = parts[1].strip() if len(parts) > 1 else ""

    result = {"compiled_truth": [], "timeline": []}
    if compiled_truth:
        result["compiled_truth"] = chunk_text(compiled_truth, target_words, overlap)
    if timeline:
        result["timeline"] = chunk_text(timeline, target_words, overlap)

    return result


def main():
    parser = argparse.ArgumentParser(description="Chunk text into overlapping segments.")
    parser.add_argument("file", nargs="?", help="File to chunk (reads stdin if omitted)")
    parser.add_argument("--target-words", type=int, default=300, help="Target words per chunk (default: 300)")
    parser.add_argument("--overlap", type=int, default=50, help="Overlap words (default: 50)")
    parser.add_argument("--page", action="store_true", help="Use page-aware chunking (separates compiled truth from timeline)")
    parser.add_argument("--json", dest="json_output", action="store_true", help="JSON output")

    args = parser.parse_args()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    if args.page:
        result = chunk_page(text, args.target_words, args.overlap)
    else:
        result = chunk_text(text, args.target_words, args.overlap)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        if isinstance(result, list):
            for i, chunk in enumerate(result):
                print(f"--- Chunk {i+1} ({len(chunk.split())} words) ---")
                print(chunk)
                print()
        else:
            for zone, chunks in result.items():
                for i, chunk in enumerate(chunks):
                    print(f"--- {zone} chunk {i+1} ({len(chunk.split())} words) ---")
                    print(chunk)
                    print()


if __name__ == "__main__":
    main()
