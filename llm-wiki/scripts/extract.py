#!/usr/bin/env python3
"""
Extract text content from documents into markdown.

Requires: pip install "unstructured[all-docs]"
Or for specific formats: pip install "unstructured[docx]", "unstructured[pdf]", etc.

Usage:
    python extract.py <input-file> <output-markdown>
    python extract.py document.pdf output.md
    python extract.py report.docx output.md
"""

import sys
import os


def extract_with_unstructured(input_path: str) -> str:
    """Extract text using the unstructured library."""
    from unstructured.partition.auto import partition

    elements = partition(input_path)
    sections = []
    for el in elements:
        el_type = type(el).__name__
        text = str(el).strip()
        if not text:
            continue
        if el_type == "Title":
            sections.append(f"## {text}")
        elif el_type == "Header":
            sections.append(f"### {text}")
        elif el_type == "ListItem":
            sections.append(f"- {text}")
        elif el_type == "Table":
            sections.append(f"```\n{text}\n```")
        else:
            sections.append(text)
    return "\n\n".join(sections)


def extract_fallback(input_path: str) -> str:
    """Fallback extraction for common formats without unstructured."""
    ext = os.path.splitext(input_path)[1].lower()

    if ext in (".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml"):
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    if ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"):
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"```{ext.lstrip('.')}\n{content}\n```"

    raise ValueError(
        f"Cannot extract text from {ext} files without the 'unstructured' library.\n"
        f"Install it with: pip install \"unstructured[all-docs]\""
    )


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input-file> <output-markdown>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found")
        sys.exit(1)

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        print(f"Error: Output directory {output_dir} does not exist")
        sys.exit(1)

    # Warn on large files (>100MB) that could cause memory issues
    file_size = os.path.getsize(input_path)
    max_size = 100 * 1024 * 1024  # 100MB
    if file_size > max_size:
        print(f"Warning: {input_path} is {file_size / 1024 / 1024:.0f}MB.")
        print(f"Files over 100MB may cause memory issues during extraction.")
        print(f"Consider splitting the file or extracting manually.")
        sys.exit(1)

    # Try plain text/code formats first (no dependencies needed)
    ext = os.path.splitext(input_path)[1].lower()
    text_extensions = {".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml"}
    code_extensions = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"}

    if ext in text_extensions or ext in code_extensions:
        try:
            content = extract_fallback(input_path)
            method = "fallback"
        except ValueError:
            pass
        else:
            filename = os.path.basename(input_path)
            header = f"# Extracted: {filename}\n\n> Extraction method: {method}\n\n"
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(header + content)
            print(f"Extracted {input_path} -> {output_path} (method: {method})")
            return

    # For all other formats, use Unstructured (required)
    try:
        content = extract_with_unstructured(input_path)
        method = "unstructured"
    except ImportError:
        print(f"Error: The 'unstructured' library is required for {ext} files.")
        print(f'Install it with: pip install "unstructured[all-docs]"')
        sys.exit(1)
    except Exception as e:
        print(f"Extraction failed for {input_path}: {e}")
        sys.exit(1)

    filename = os.path.basename(input_path)
    header = f"# Extracted: {filename}\n\n> Extraction method: {method}\n\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + content)

    print(f"Extracted {input_path} -> {output_path} (method: {method})")


if __name__ == "__main__":
    main()
