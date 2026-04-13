#!/usr/bin/env python3
"""
Extract text content from documents into markdown.

Requires: pip install docling pip-system-certs

Usage:
    python extract.py <input-file>                     # output to raw/extracted/
    python extract.py <input-file> <output-markdown>   # explicit output path
    python extract.py --ocr document.pdf
    python extract.py --no-ocr slides.pptx
"""

import argparse
import sys
import os

from frontmatter import atomic_write


def extract_with_docling(input_path: str, ocr: bool = True) -> str:
    """Extract text using the docling library with optimized settings."""
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableStructureOptions,
            TableFormerMode,
        )
    except ImportError:
        raise ImportError(
            "docling is required for this file type. Install: pip install docling pip-system-certs"
        )

    ext = os.path.splitext(input_path)[1].lower()

    # Configure PDF pipeline for best quality
    pdf_options = PdfPipelineOptions()
    pdf_options.do_ocr = ocr
    pdf_options.do_table_structure = True
    pdf_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True,
        mode=TableFormerMode.ACCURATE,
    )
    # Extract embedded pictures so markdown can reference them
    pdf_options.generate_picture_images = True
    pdf_options.images_scale = 2.0

    format_options = {
        InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
    }

    # Images use the same PDF pipeline internally
    if ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"):
        from docling.document_converter import ImageFormatOption
        format_options[InputFormat.IMAGE] = ImageFormatOption(
            pipeline_options=pdf_options,
        )

    converter = DocumentConverter(format_options=format_options)
    result = converter.convert(input_path)
    return result.document.export_to_markdown()


def extract_fallback(input_path: str) -> str:
    """Fallback extraction for common text/code formats without docling."""
    ext = os.path.splitext(input_path)[1].lower()

    if ext in (".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml"):
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    if ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"):
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"```{ext.lstrip('.')}\n{content}\n```"

    raise ValueError(
        f"Cannot extract text from {ext} files without the 'docling' library.\n"
        f"Install it with: pip install docling pip-system-certs"
    )


# Extensions that are handled natively (no docling needed)
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml"}
CODE_EXTENSIONS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"}
NATIVE_EXTENSIONS = TEXT_EXTENSIONS | CODE_EXTENSIONS


def default_output_path(input_path: str) -> str:
    """Derive default output path: raw/extracted/<relative-path>.md

    Preserves subdirectory structure under raw/ so that
    raw/papers/report.pdf -> raw/extracted/papers/report.pdf.md
    raw/report.pdf        -> raw/extracted/report.pdf.md
    """
    abs_input = os.path.abspath(input_path)
    input_dir = os.path.dirname(abs_input)

    # Walk up to find raw/ directory
    check_dir = input_dir
    while check_dir and check_dir != os.path.dirname(check_dir):
        if os.path.basename(check_dir) == "raw":
            # Compute path relative to raw/
            rel_to_raw = os.path.relpath(abs_input, check_dir)
            extracted_path = os.path.join(check_dir, "extracted", rel_to_raw + ".md")
            os.makedirs(os.path.dirname(extracted_path), exist_ok=True)
            return extracted_path
        check_dir = os.path.dirname(check_dir)

    # Fallback: put extracted/ next to the input file
    print(
        f"Warning: {input_path} is not under a raw/ directory. "
        f"Output will go to extracted/ next to the input file.",
        file=sys.stderr,
    )
    filename = os.path.basename(input_path)
    extracted_dir = os.path.join(input_dir, "extracted")
    os.makedirs(extracted_dir, exist_ok=True)
    return os.path.join(extracted_dir, filename + ".md")


def main():
    parser = argparse.ArgumentParser(
        description="Extract text content from documents into markdown."
    )
    parser.add_argument("input", help="Input file path")
    parser.add_argument(
        "output", nargs="?", default=None,
        help="Output markdown file path (default: raw/extracted/<filename>.md)",
    )

    ocr_group = parser.add_mutually_exclusive_group()
    ocr_group.add_argument(
        "--ocr", action="store_true", default=True,
        help="Enable OCR for scanned documents (default)",
    )
    ocr_group.add_argument(
        "--no-ocr", action="store_true",
        help="Disable OCR (faster, for native-text PDFs)",
    )

    args = parser.parse_args()
    input_path = args.input
    output_path = args.output
    ocr = not args.no_ocr

    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found")
        sys.exit(1)

    # Guard: don't re-extract files already in an extracted/ directory
    abs_input = os.path.abspath(input_path)
    parts = abs_input.split(os.sep)
    if "extracted" in parts:
        print(f"Error: {input_path} is already in an extracted/ directory. Skipping.")
        sys.exit(1)

    ext = os.path.splitext(input_path)[1].lower()

    # Text/code files don't need extraction — read directly
    if ext in NATIVE_EXTENSIONS:
        if output_path is None:
            output_path = default_output_path(input_path)

        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.isdir(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        content = extract_fallback(input_path)
        filename = os.path.basename(input_path)
        header = f"# Extracted: {filename}\n\n> Extraction method: fallback\n\n"
        atomic_write(output_path, header + content)
        print(f"Extracted {input_path} -> {output_path} (method: fallback)")
        return

    # For all other formats, use Docling
    if output_path is None:
        output_path = default_output_path(input_path)

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.isdir(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # Warn on large files but still attempt extraction
    file_size = os.path.getsize(input_path)
    if file_size > 100 * 1024 * 1024:
        print(
            f"Warning: {input_path} is {file_size / 1024 / 1024:.0f}MB. "
            f"Extraction may be slow and use significant memory.",
            file=sys.stderr,
        )

    try:
        content = extract_with_docling(input_path, ocr=ocr)
        method = "docling" + (" +ocr" if ocr else "")
    except ImportError:
        print(f"Error: The 'docling' library is required for {ext} files.")
        print("Install it with: pip install docling pip-system-certs")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: docling failed to initialize (model loading issue?): {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Extraction failed for {input_path}: {e}")
        sys.exit(1)

    filename = os.path.basename(input_path)
    header = f"# Extracted: {filename}\n\n> Extraction method: {method}\n\n"

    atomic_write(output_path, header + content)

    print(f"Extracted {input_path} -> {output_path} (method: {method})")


if __name__ == "__main__":
    main()
