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
    ok = major >= 3 and minor >= 10
    detail = f"Python {version}"
    if not ok:
        detail += " (need 3.10+)"
    return ok, detail


def check_venv() -> tuple[bool, str]:
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        return True, sys.prefix
    return False, "Not in a virtual environment (recommended: python3 -m venv .venv)"


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


def check_docling() -> tuple[bool, str]:
    try:
        from importlib.metadata import version, PackageNotFoundError
        ver = version("docling")
        return True, f"v{ver}"
    except PackageNotFoundError:
        return False, "pip install docling"


def check_watchdog() -> tuple[bool, str]:
    try:
        from importlib.metadata import version, PackageNotFoundError
        ver = version("watchdog")
        return True, f"v{ver}"
    except PackageNotFoundError:
        return False, "pip install watchdog"


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

    # Required
    print("REQUIRED")
    print("-" * 40)
    print("  (none — the skill works with just an AI agent)")
    print()

    # Recommended
    print("RECOMMENDED")
    print("-" * 40)

    ok, detail = check_python()
    print(f"  [{check_mark(ok):>7}]  Python 3.10+       {detail}")

    venv_ok, venv_detail = check_venv()
    venv_status = "OK" if venv_ok else "WARN"
    print(f"  [{venv_status:>7}]  Virtual env        {venv_detail}")

    has_docling, docling_detail = check_docling()
    print(f"  [{check_mark(has_docling):>7}]  docling            {docling_detail}")
    if not has_docling:
        print("           Install: pip install docling")
        print("           Without it, the agent reads files directly (less accurate for complex docs)")

    has_watchdog, watchdog_detail = check_watchdog()
    print(f"  [{check_mark(has_watchdog):>7}]  watchdog           {watchdog_detail}")
    if not has_watchdog:
        print("           Install: pip install watchdog")

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

    # Optional: Additional PDF tools
    print("OPTIONAL — Additional PDF Tools")
    print("-" * 40)

    has_pymupdf, pymupdf_detail = check_pymupdf()
    print(f"  [{check_mark(has_pymupdf):>7}]  PyMuPDF            {pymupdf_detail}")

    has_pdftotext, pdftotext_detail = check_pdftotext()
    print(f"  [{check_mark(has_pdftotext):>7}]  pdftotext          {pdftotext_detail}")
    print()

    print("=" * 60)

    if has_docling and has_watchdog:
        print("All recommended dependencies are ready.")
    else:
        print("Some recommended dependencies are missing. See above.")
        print("The skill works without them, but with reduced capabilities.")

    print()
    print("To get started, ask your agent:")
    print('  "Set up a wiki knowledge base in ./my-wiki"')
    print()


if __name__ == "__main__":
    main()
