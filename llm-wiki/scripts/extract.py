#!/usr/bin/env python3
"""
Extract text content from documents into markdown.

Requires: pip install "mineru[all]"

Usage:
    python extract.py <input-file>                     # output to raw/extracted/
    python extract.py <input-file> <output-markdown>   # explicit output path
    python extract.py <input-dir>                      # batch-extract every file in dir
    python extract.py --ocr document.pdf               # force OCR
    python extract.py --no-ocr slides.pptx             # force text-only (fastest)
    python extract.py --fast document.pdf               # pipeline backend (CPU, faster)
    python extract.py --start 0 --end 10 large.pdf      # extract pages 0-10 only
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

from frontmatter import atomic_write


def _require_mineru() -> None:
    if shutil.which("mineru") is None:
        raise FileNotFoundError(
            "mineru CLI is required for this file type. Install: pip install \"mineru[all]\""
        )


def _mineru_mode_args(ocr: bool | None) -> list[str]:
    if ocr is True:
        return ["-m", "ocr"]
    if ocr is False:
        return ["-m", "txt"]
    return []  # auto-detect


def _materialize_mineru_output(md_file: str, output_path: str | None) -> str:
    """Read a mineru-produced .md, copy its images/ sibling to <output_path>.images/,
    rewrite 'images/' refs to the per-document dir, and return the rewritten content."""
    md_dir = os.path.dirname(md_file)
    with open(md_file, "r", encoding="utf-8") as f:
        content = f.read()

    src_images = os.path.join(md_dir, "images")
    if output_path and os.path.isdir(src_images) and os.listdir(src_images):
        dest_images = output_path + ".images"
        if os.path.exists(dest_images):
            shutil.rmtree(dest_images)
        shutil.copytree(src_images, dest_images)
        content = content.replace("images/", os.path.basename(dest_images) + "/")

    return content


def extract_with_mineru(
    input_path: str,
    ocr: bool | None = None,
    output_path: str | None = None,
    backend: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
) -> str:
    """Extract text using the MineRU CLI.

    Args:
        input_path: Path to the input file.
        ocr: True to force OCR, False to force text-only, None for auto-detect.
        output_path: If provided, images are copied to <output_path>.images/.
        backend: MineRU backend ('pipeline' for CPU/fast, 'hybrid-auto-engine' for GPU/quality).
        start_page: First page to process (0-based).
        end_page: Last page to process (0-based).
    """
    _require_mineru()

    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = ["mineru", "-p", os.path.abspath(input_path), "-o", tmpdir]
        cmd += _mineru_mode_args(ocr)
        if backend:
            cmd += ["-b", backend]
        if start_page is not None:
            cmd += ["-s", str(start_page)]
        if end_page is not None:
            cmd += ["-e", str(end_page)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"mineru failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )

        md_files = glob.glob(os.path.join(tmpdir, "**", "*.md"), recursive=True)
        if not md_files:
            raise RuntimeError(
                f"mineru produced no markdown output for {input_path}"
            )

        return _materialize_mineru_output(md_files[0], output_path)


def extract_directory_with_mineru(
    input_dir: str,
    ocr: bool | None = None,
    backend: str | None = None,
    start_page: int | None = None,
    end_page: int | None = None,
) -> list[tuple[str, str | None, str | None]]:
    """Batch-extract every mineru-eligible file in ``input_dir`` with one CLI call.

    Returns a list of ``(source_path, output_path, error)`` tuples — ``error`` is
    ``None`` on success, otherwise a short reason string and ``output_path`` is
    ``None``. Non-mineru (``NATIVE_EXTENSIONS``) files are not handled here; the
    CLI wrapper processes those separately.
    """
    _require_mineru()

    stem_to_source: dict[str, str] = {}
    for name in sorted(os.listdir(input_dir)):
        full = os.path.join(input_dir, name)
        if not os.path.isfile(full) or name.startswith("."):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in NATIVE_EXTENSIONS:
            continue
        stem = os.path.splitext(name)[0]
        # If multiple files share a stem, later entries win — mineru's per-stem
        # output dir would collide anyway, so the ambiguity is upstream.
        stem_to_source[stem] = full

    if not stem_to_source:
        return []

    results: list[tuple[str, str | None, str | None]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = ["mineru", "-p", os.path.abspath(input_dir), "-o", tmpdir]
        cmd += _mineru_mode_args(ocr)
        if backend:
            cmd += ["-b", backend]
        if start_page is not None:
            cmd += ["-s", str(start_page)]
        if end_page is not None:
            cmd += ["-e", str(end_page)]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"mineru failed (exit {result.returncode}):\n{result.stderr.strip()}"
            )

        seen_stems: set[str] = set()
        for stem_dir in sorted(glob.glob(os.path.join(tmpdir, "*") + os.sep)):
            stem = os.path.basename(os.path.normpath(stem_dir))
            source = stem_to_source.get(stem)
            if source is None:
                continue
            seen_stems.add(stem)

            md_matches = glob.glob(os.path.join(stem_dir, "*", f"{stem}.md"))
            if not md_matches:
                results.append((source, None, "no markdown output"))
                continue

            output_path = default_output_path(source)
            content = _materialize_mineru_output(md_matches[0], output_path)

            method = "mineru"
            if ocr is True:
                method += " +ocr"
            elif ocr is False:
                method += " +txt"
            header = (
                f"# Extracted: {os.path.basename(source)}\n\n"
                f"> Extraction method: {method}\n\n"
            )
            atomic_write(output_path, header + content)
            results.append((source, output_path, None))

        for stem, source in stem_to_source.items():
            if stem not in seen_stems:
                results.append((source, None, "mineru produced no output"))

    return results


def extract_fallback(input_path: str) -> str:
    """Fallback extraction for common text/code formats without mineru."""
    ext = os.path.splitext(input_path)[1].lower()

    if ext in (".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml"):
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    if ext in (".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".rb", ".sh"):
        with open(input_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return f"```{ext.lstrip('.')}\n{content}\n```"

    raise ValueError(
        f"Cannot extract text from {ext} files without the 'mineru' CLI.\n"
        f"Install it with: pip install \"mineru[all]\""
    )


# Extensions that are handled natively (no mineru needed)
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


def _run_batch(
    input_dir: str,
    ocr: bool | None,
    fast: bool,
    start_page: int | None,
    end_page: int | None,
) -> None:
    """Extract every file in ``input_dir`` (native files inline, the rest in one
    mineru invocation). Summarises counts and non-fatal failures on stderr."""
    native_sources: list[str] = []
    mineru_candidates = 0
    for name in sorted(os.listdir(input_dir)):
        full = os.path.join(input_dir, name)
        if not os.path.isfile(full) or name.startswith("."):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in NATIVE_EXTENSIONS:
            native_sources.append(full)
        else:
            mineru_candidates += 1

    if not native_sources and mineru_candidates == 0:
        print(f"No extractable files in {input_dir}")
        return

    succeeded = 0
    failed: list[tuple[str, str]] = []

    for src in native_sources:
        try:
            out = default_output_path(src)
            content = extract_fallback(src)
            header = f"# Extracted: {os.path.basename(src)}\n\n> Extraction method: fallback\n\n"
            atomic_write(out, header + content)
            succeeded += 1
            print(f"  [{succeeded}] {src} -> {out} (method: fallback)")
        except Exception as e:
            failed.append((src, str(e)))

    if mineru_candidates:
        print(f"Running mineru on {mineru_candidates} file(s) in {input_dir} ...")
        backend = "pipeline" if fast else None
        try:
            results = extract_directory_with_mineru(
                input_dir,
                ocr=ocr,
                backend=backend,
                start_page=start_page,
                end_page=end_page,
            )
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)
        except RuntimeError as e:
            print(f"Error: mineru extraction failed: {e}")
            sys.exit(1)

        method = "mineru"
        if ocr is True:
            method += " +ocr"
        elif ocr is False:
            method += " +txt"
        for src, out, err in results:
            if err is None:
                succeeded += 1
                print(f"  [{succeeded}] {src} -> {out} (method: {method})")
            else:
                failed.append((src, err))

    print(f"\nDone: {succeeded} succeeded, {len(failed)} failed")
    if failed:
        for src, err in failed:
            print(f"  FAILED {src}: {err}", file=sys.stderr)
        sys.exit(1)


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
        "--ocr", action="store_true", default=False,
        help="Force OCR (for scanned documents)",
    )
    ocr_group.add_argument(
        "--no-ocr", action="store_true",
        help="Force text-only extraction, skip OCR (fastest)",
    )

    parser.add_argument(
        "--fast", action="store_true",
        help="Use pipeline backend (CPU-friendly, faster, slightly lower accuracy)",
    )
    parser.add_argument(
        "--start", type=int, default=None,
        help="First page to process (0-based, for large PDFs)",
    )
    parser.add_argument(
        "--end", type=int, default=None,
        help="Last page to process (0-based, for large PDFs)",
    )

    args = parser.parse_args()
    input_path = args.input
    output_path = args.output

    # OCR mode: None = auto-detect (default), True = force OCR, False = force text-only
    if args.ocr:
        ocr = True
    elif args.no_ocr:
        ocr = False
    else:
        ocr = None  # let MineRU auto-detect

    if not os.path.exists(input_path):
        print(f"Error: {input_path} not found")
        sys.exit(1)

    # Guard: don't re-extract files already in an extracted/ directory
    abs_input = os.path.abspath(input_path)
    parts = abs_input.split(os.sep)
    if "extracted" in parts:
        print(f"Error: {input_path} is already in an extracted/ directory. Skipping.")
        sys.exit(1)

    if os.path.isdir(input_path):
        if output_path is not None:
            print("Error: explicit output path is not supported for directory input.")
            sys.exit(1)
        _run_batch(
            input_path,
            ocr=ocr,
            fast=args.fast,
            start_page=args.start,
            end_page=args.end,
        )
        return

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

    # For all other formats, use MineRU
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
        backend = "pipeline" if args.fast else None
        content = extract_with_mineru(
            input_path,
            ocr=ocr,
            output_path=output_path,
            backend=backend,
            start_page=args.start,
            end_page=args.end,
        )
        method = "mineru"
        if ocr is True:
            method += " +ocr"
        elif ocr is False:
            method += " +txt"
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: mineru extraction failed: {e}")
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
