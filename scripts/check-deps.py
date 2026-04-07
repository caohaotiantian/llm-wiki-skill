#!/usr/bin/env python3
"""
Dependency checker for LLM Wiki Skill.

Checks for required and optional dependencies and reports their status.
Run this after installation to verify your environment is ready.

Usage:
    python3 check-deps.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import os
import platform


def check_mark(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def check_python() -> tuple[bool, str]:
    version = sys.version.split()[0]
    major, minor = sys.version_info[:2]
    ok = major >= 3 and minor >= 8
    detail = f"Python {version}"
    if not ok:
        detail += " (need 3.8+)"
    return ok, detail


def check_obsidian() -> tuple[bool, str]:
    system = platform.system()
    if system == "Darwin":
        exists = os.path.isdir("/Applications/Obsidian.app")
        if not exists:
            # Check Homebrew cask location
            exists = os.path.isdir(os.path.expanduser("~/Applications/Obsidian.app"))
        return exists, "Obsidian.app" if exists else "Not found in /Applications"
    elif system == "Linux":
        found = shutil.which("obsidian") is not None
        if not found:
            # Check common Flatpak/Snap locations
            found = os.path.exists("/var/lib/flatpak/app/md.obsidian.Obsidian")
            if not found:
                found = os.path.exists("/snap/obsidian")
        return found, "obsidian" if found else "Not found in PATH or common locations"
    elif system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        exists = os.path.isdir(os.path.join(local_app_data, "Obsidian"))
        return exists, "Obsidian" if exists else "Not found in LOCALAPPDATA"
    else:
        return False, f"Unknown platform: {system}"


def check_obsidian_cli() -> tuple[bool, str]:
    found = shutil.which("obsidian") is not None
    if found:
        try:
            result = subprocess.run(
                ["obsidian", "help"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True, "Available (v1.12.0+)"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return False, "Not found (requires Obsidian Desktop v1.12.0+)"


def check_unstructured() -> tuple[bool, str]:
    try:
        import unstructured  # noqa: F401
        version = getattr(unstructured, "__version__", "unknown")
        return True, f"v{version}"
    except ImportError:
        return False, 'pip install "unstructured[all-docs]"'


def check_unstructured_extras() -> list[tuple[str, bool, str]]:
    results = []
    extras = {
        "docx": "unstructured.partition.docx",
        "pdf": "unstructured.partition.pdf",
        "pptx": "unstructured.partition.pptx",
        "html": "unstructured.partition.html",
    }
    for name, module_path in extras.items():
        try:
            __import__(module_path)
            results.append((f"  unstructured[{name}]", True, "Available"))
        except ImportError:
            results.append((f"  unstructured[{name}]", False, f'pip install "unstructured[{name}]"'))
    return results


def check_fswatch() -> tuple[bool, str]:
    found = shutil.which("fswatch") is not None
    if found:
        return True, "Available"
    system = platform.system()
    if system == "Darwin":
        return False, "brew install fswatch"
    else:
        return False, "apt install inotify-tools (or build fswatch from source)"


def check_inotifywait() -> tuple[bool, str]:
    found = shutil.which("inotifywait") is not None
    if found:
        return True, "Available"
    return False, "apt install inotify-tools"


def check_pymupdf() -> tuple[bool, str]:
    try:
        import fitz  # noqa: F401
        return True, f"v{fitz.version[0]}"
    except ImportError:
        return False, "pip install PyMuPDF (optional PDF reader)"


def check_pdftotext() -> tuple[bool, str]:
    found = shutil.which("pdftotext") is not None
    if found:
        return True, "Available"
    system = platform.system()
    if system == "Darwin":
        return False, "brew install poppler"
    else:
        return False, "apt install poppler-utils"


def main():
    print("=" * 60)
    print("LLM Wiki Skill — Dependency Check")
    print("=" * 60)
    print()

    all_ok = True

    # Required
    print("REQUIRED")
    print("-" * 40)

    ok, detail = check_python()
    print(f"  [{check_mark(ok):>7}]  Python 3.8+        {detail}")
    if not ok:
        all_ok = False
    print()

    # Recommended
    print("RECOMMENDED")
    print("-" * 40)

    ok, detail = check_obsidian()
    print(f"  [{check_mark(ok):>7}]  Obsidian           {detail}")
    if not ok:
        print("           Download: https://obsidian.md")
        print("           The skill works without it, but you lose graph view and Dataview")
    print()

    # Optional: Obsidian CLI
    print("OPTIONAL — Obsidian CLI")
    print("-" * 40)

    ok, detail = check_obsidian_cli()
    print(f"  [{check_mark(ok):>7}]  Obsidian CLI       {detail}")
    if not ok:
        print("           Enables: rename with backlink updates, search, backlinks")
        print("           The skill works fine without it (uses filesystem directly)")
    print()

    # Optional: Document extraction
    print("OPTIONAL — Document Extraction")
    print("-" * 40)

    has_unstructured, unstructured_detail = check_unstructured()
    print(f"  [{check_mark(has_unstructured):>7}]  unstructured       {unstructured_detail}")
    if has_unstructured:
        for name, extra_ok, extra_detail in check_unstructured_extras():
            print(f"  [{check_mark(extra_ok):>7}]  {name:<18} {extra_detail}")
    else:
        print("           Enables: PDF, DOCX, PPTX, image OCR extraction")

    has_pymupdf, pymupdf_detail = check_pymupdf()
    print(f"  [{check_mark(has_pymupdf):>7}]  PyMuPDF            {pymupdf_detail}")

    has_pdftotext, pdftotext_detail = check_pdftotext()
    print(f"  [{check_mark(has_pdftotext):>7}]  pdftotext          {pdftotext_detail}")

    if not any([has_unstructured, has_pymupdf, has_pdftotext]):
        print()
        print("  NOTE: No PDF extraction tools found.")
        print("  The skill can still ingest markdown, text, and code files.")
        print("  For PDF/DOCX support, install one of the above.")
    print()

    # Optional: File watcher
    print("OPTIONAL — File Watcher (scripts/watch.sh)")
    print("-" * 40)

    system = platform.system()
    if system == "Darwin":
        ok, detail = check_fswatch()
        print(f"  [{check_mark(ok):>7}]  fswatch            {detail}")
    elif system == "Linux":
        ok_fs, detail_fs = check_fswatch()
        ok_in, detail_in = check_inotifywait()
        print(f"  [{check_mark(ok_fs):>7}]  fswatch            {detail_fs}")
        print(f"  [{check_mark(ok_in):>7}]  inotifywait        {detail_in}")
        if not ok_fs and not ok_in:
            print("           Install either one for file watching support")
    else:
        print(f"  [   N/A]  File watcher not supported on {system}")

    print()
    print("=" * 60)

    if all_ok:
        print("All required dependencies are ready.")
    else:
        print("Some required dependencies are missing. See above.")

    print()
    print("To get started, ask your agent:")
    print('  "Set up a wiki knowledge base in ./my-wiki"')
    print()


if __name__ == "__main__":
    main()
