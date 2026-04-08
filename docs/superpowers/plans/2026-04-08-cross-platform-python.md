# Cross-Platform Python Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all platform-specific CLI dependencies (fswatch, inotifywait, shasum) with pure Python, making the skill work on macOS, Linux, and Windows with just Python 3.8+ and pip.

**Architecture:** Create `watch.py` using the `watchdog` library as a drop-in replacement for `watch.sh` with an improved CLI interface (filter, debounce, JSON output, quiet mode) and a programmatic API. Update `check-deps.py` to check for `watchdog` instead of fswatch/inotifywait. Fix all platform-specific references in docs.

**Tech Stack:** Python 3.8+, watchdog, argparse, fnmatch, threading, json

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `llm-wiki/scripts/watch.py` | Cross-platform file watcher using watchdog |
| Delete | `llm-wiki/scripts/watch.sh` | Replaced by watch.py |
| Modify | `scripts/check-deps.py` | Remove fswatch/inotifywait checks, add watchdog check |
| Modify | `llm-wiki/SKILL.md` | Fix shasum reference, update watch.sh → watch.py |
| Modify | `README.md` | Update deps, project structure, usage |
| Modify | `INSTALL.md` | Update deps reference |
| Modify | `CLAUDE.md` | Update commands and deps |

---

### Task 1: Create `watch.py` — core Watcher class

**Files:**
- Create: `llm-wiki/scripts/watch.py`

- [ ] **Step 1: Create `watch.py` with imports, constants, and the `record_change` helper**

```python
#!/usr/bin/env python3
"""
Cross-platform file watcher for LLM Wiki raw sources.

Monitors the raw/ directory for new or modified files and logs changes
to raw/.pending_changes.json so the next LLM conversation can pick them up.

Requires: pip install watchdog

Usage:
    python watch.py <vault-path>
    python watch.py <vault-path> --filter "*.md" --debounce 3.0
    python watch.py <vault-path> --json --quiet
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent


def record_change(pending_file: Path, rel_path: str, timestamp: str) -> None:
    """Append a change to .pending_changes.json, deduplicating by file path."""
    try:
        data = json.loads(pending_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"changes": []}

    data["changes"].append({
        "file": rel_path,
        "timestamp": timestamp,
        "type": "modified",
    })

    # Deduplicate by file path, keeping latest
    seen: dict[str, dict] = {}
    for c in data["changes"]:
        seen[c["file"]] = c
    data["changes"] = list(seen.values())

    pending_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

- [ ] **Step 2: Add the `_DebouncedHandler` event handler class**

Append to `watch.py`:

```python
class _DebouncedHandler(FileSystemEventHandler):
    """Watchdog handler that debounces rapid changes to the same file."""

    def __init__(
        self,
        vault_path: Path,
        pending_file: Path,
        debounce: float = 2.0,
        filter_glob: str | None = None,
        json_output: bool = False,
        quiet: bool = False,
    ) -> None:
        super().__init__()
        self._vault_path = vault_path
        self._pending_file = pending_file
        self._debounce = debounce
        self._filter_glob = filter_glob
        self._json_output = json_output
        self._quiet = quiet
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _should_ignore(self, path: str) -> bool:
        """Return True if the event should be ignored."""
        basename = os.path.basename(path)
        if basename.startswith("."):
            return True
        if self._filter_glob and not fnmatch.fnmatch(basename, self._filter_glob):
            return True
        return False

    def _handle_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src_path = event.src_path
        if self._should_ignore(src_path):
            return

        rel_path = os.path.relpath(src_path, self._vault_path)

        with self._lock:
            # Cancel any existing timer for this file
            if rel_path in self._timers:
                self._timers[rel_path].cancel()

            # Set a new debounce timer
            timer = threading.Timer(
                self._debounce,
                self._flush_change,
                args=(rel_path,),
            )
            timer.daemon = True
            timer.start()
            self._timers[rel_path] = timer

    def _flush_change(self, rel_path: str) -> None:
        """Called after debounce period — record the change."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record_change(self._pending_file, rel_path, timestamp)

        with self._lock:
            self._timers.pop(rel_path, None)

        if self._json_output:
            line = json.dumps({"file": rel_path, "timestamp": timestamp, "type": "modified"})
            print(line, flush=True)
        if not self._quiet:
            print(f"[{timestamp}] Change detected: {rel_path}", flush=True)

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle_event(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._handle_event(event)
```

- [ ] **Step 3: Add the `Watcher` class (programmatic API)**

Append to `watch.py`:

```python
class Watcher:
    """Cross-platform file watcher for an LLM Wiki vault.

    Usage:
        w = Watcher("/path/to/vault", filter_glob="*.md", debounce=2.0)
        w.start()          # blocking — Ctrl+C to stop
        # or
        w.start_background()  # returns a threading.Event; set it to stop
    """

    def __init__(
        self,
        vault_path: str | Path,
        filter_glob: str | None = None,
        debounce: float = 2.0,
        json_output: bool = False,
        quiet: bool = False,
    ) -> None:
        self._vault_path = Path(vault_path).resolve()
        self._raw_dir = self._vault_path / "raw"
        self._pending_file = self._raw_dir / ".pending_changes.json"
        self._filter_glob = filter_glob
        self._debounce = debounce
        self._json_output = json_output
        self._quiet = quiet

        if not self._raw_dir.is_dir():
            raise FileNotFoundError(
                f"{self._raw_dir} does not exist. Is this a valid wiki vault?"
            )

        # Initialize pending changes file if missing
        if not self._pending_file.exists():
            self._pending_file.write_text(
                json.dumps({"changes": []}, indent=2), encoding="utf-8"
            )

    def start(self) -> None:
        """Start watching (blocking). Press Ctrl+C to stop."""
        handler = _DebouncedHandler(
            vault_path=self._vault_path,
            pending_file=self._pending_file,
            debounce=self._debounce,
            filter_glob=self._filter_glob,
            json_output=self._json_output,
            quiet=self._quiet,
        )
        observer = Observer()
        observer.schedule(handler, str(self._raw_dir), recursive=True)
        observer.start()

        if not self._quiet:
            print(f"Watching {self._raw_dir} for changes...")
            print("Press Ctrl+C to stop.")

        try:
            while observer.is_alive():
                observer.join(timeout=1)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()

    def start_background(self) -> threading.Event:
        """Start watching in background. Set the returned Event to stop."""
        stop_event = threading.Event()

        handler = _DebouncedHandler(
            vault_path=self._vault_path,
            pending_file=self._pending_file,
            debounce=self._debounce,
            filter_glob=self._filter_glob,
            json_output=self._json_output,
            quiet=self._quiet,
        )
        observer = Observer()
        observer.schedule(handler, str(self._raw_dir), recursive=True)
        observer.start()

        def _watch_loop() -> None:
            try:
                while not stop_event.is_set():
                    stop_event.wait(timeout=1)
            finally:
                observer.stop()
                observer.join()

        thread = threading.Thread(target=_watch_loop, daemon=True)
        thread.start()

        return stop_event
```

- [ ] **Step 4: Add the CLI `main()` and entry point**

Append to `watch.py`:

```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch an LLM Wiki vault for raw source changes.",
    )
    parser.add_argument("vault_path", help="Path to the wiki vault")
    parser.add_argument(
        "--filter",
        dest="filter_glob",
        default=None,
        help="Only watch files matching this fnmatch pattern (e.g. '*.md', '*.pdf')",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=2.0,
        help="Seconds to wait before recording a change (default: 2.0)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output events as JSON lines to stdout",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output, only write to .pending_changes.json",
    )

    args = parser.parse_args()

    try:
        watcher = Watcher(
            vault_path=args.vault_path,
            filter_glob=args.filter_glob,
            debounce=args.debounce,
            json_output=args.json_output,
            quiet=args.quiet,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    watcher.start()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify `watch.py` runs with `--help`**

Run: `python3 llm-wiki/scripts/watch.py --help`

Expected output includes:
```
usage: watch.py [-h] [--filter FILTER_GLOB] [--debounce DEBOUNCE] [--json] [--quiet] vault_path
```

- [ ] **Step 6: Commit**

```bash
git add llm-wiki/scripts/watch.py
git commit -m "feat: add cross-platform watch.py using watchdog"
```

---

### Task 2: Delete `watch.sh`

**Files:**
- Delete: `llm-wiki/scripts/watch.sh`

- [ ] **Step 1: Delete watch.sh**

```bash
git rm llm-wiki/scripts/watch.sh
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove watch.sh, replaced by watch.py"
```

---

### Task 3: Update `check-deps.py`

**Files:**
- Modify: `scripts/check-deps.py:100-215`

- [ ] **Step 1: Add `check_watchdog()` function**

Replace the `check_fswatch()` function (lines 100-108) with:

```python
def check_watchdog() -> tuple[bool, str]:
    try:
        import watchdog  # noqa: F401
        version = getattr(watchdog, "VERSION_STRING", "unknown")
        return True, f"v{version}"
    except ImportError:
        return False, "pip install watchdog"
```

- [ ] **Step 2: Remove `check_inotifywait()` function**

Delete lines 111-115 (the `check_inotifywait` function):

```python
def check_inotifywait() -> tuple[bool, str]:
    found = shutil.which("inotifywait") is not None
    if found:
        return True, "Available"
    return False, "apt install inotify-tools"
```

- [ ] **Step 3: Add watchdog to the REQUIRED section in `main()`**

After the unstructured extras check block (around line 161), add:

```python
    has_watchdog, watchdog_detail = check_watchdog()
    print(f"  [{check_mark(has_watchdog):>7}]  watchdog           {watchdog_detail}")
    if not has_watchdog:
        all_ok = False
```

- [ ] **Step 4: Remove the "OPTIONAL — File Watcher" section from `main()`**

Delete lines 197-213 (the entire file watcher section):

```python
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
```

- [ ] **Step 5: Run the updated checker**

Run: `python3 scripts/check-deps.py`

Expected: watchdog appears under REQUIRED. No fswatch/inotifywait section. Script exits cleanly.

- [ ] **Step 6: Commit**

```bash
git add scripts/check-deps.py
git commit -m "feat: check for watchdog instead of fswatch/inotifywait"
```

---

### Task 4: Update `SKILL.md`

**Files:**
- Modify: `llm-wiki/SKILL.md:158,373,503`

- [ ] **Step 1: Replace the SHA-256 command (line 158)**

Replace:
```
Compute SHA-256 with: `shasum -a 256 <file> | cut -d' ' -f1` (macOS/Linux) or `python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`.
```

With:
```
Compute SHA-256 with: `python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`
```

- [ ] **Step 2: Update watch reference (line 373)**

Replace:
```
For teams that want automatic detection, provide a file watcher script. Run `scripts/watch.sh <vault-path>` to monitor the `raw/` directory and log changes. The user can integrate this with their workflow (e.g., run it in a terminal tab, add to a cron job, or wire into git hooks).
```

With:
```
For teams that want automatic detection, provide a file watcher script. Run `scripts/watch.py <vault-path>` to monitor the `raw/` directory and log changes. Supports `--filter`, `--debounce`, `--json`, and `--quiet` options. The user can integrate this with their workflow (e.g., run it in a terminal tab, add to a cron job, or wire into git hooks).
```

- [ ] **Step 3: Update bundled resources list (line 503)**

Replace:
```
- `scripts/watch.sh` — File watcher for continuous change detection
```

With:
```
- `scripts/watch.py` — Cross-platform file watcher for continuous change detection (requires `watchdog`)
```

- [ ] **Step 4: Commit**

```bash
git add llm-wiki/SKILL.md
git commit -m "docs: update SKILL.md for cross-platform Python tooling"
```

---

### Task 5: Update `README.md`

**Files:**
- Modify: `README.md:65,95-101,115`

- [ ] **Step 1: Update the file watcher feature line (line 65)**

Replace:
```
- **File watcher** — Monitor raw sources for changes (macOS + Linux)
```

With:
```
- **File watcher** — Cross-platform monitoring of raw sources for changes (requires `watchdog`)
```

- [ ] **Step 2: Update the dependencies section (lines 95-101)**

Replace:
```
**Required:**
- An AI coding agent that supports skills (Claude Code, Codex, Gemini CLI, etc.)
- Python 3.8+
- [`unstructured`](https://github.com/Unstructured-IO/unstructured) — for document extraction (PDF, DOCX, PPTX, images). Install with `pip install "unstructured[all-docs]"`.

**Recommended:**
- Obsidian — for graph view, search, and Dataview queries. The skill works without it (it's just markdown files), but Obsidian makes the wiki much more useful.

**Optional:**
- `fswatch` (macOS) or `inotifywait` (Linux) — for the file watcher script
```

With:
```
**Required:**
- An AI coding agent that supports skills (Claude Code, Codex, Gemini CLI, etc.)
- Python 3.8+
- [`unstructured`](https://github.com/Unstructured-IO/unstructured) — for document extraction (PDF, DOCX, PPTX, images). Install with `pip install "unstructured[all-docs]"`.
- [`watchdog`](https://github.com/gorakhargosh/watchdog) — for the file watcher. Install with `pip install watchdog`.

**Recommended:**
- Obsidian — for graph view, search, and Dataview queries. The skill works without it (it's just markdown files), but Obsidian makes the wiki much more useful.
```

- [ ] **Step 3: Update project structure (line 115)**

Replace:
```
│       └── watch.sh         # File watcher for continuous change detection
```

With:
```
│       └── watch.py         # Cross-platform file watcher (requires watchdog)
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README for cross-platform deps"
```

---

### Task 6: Update `INSTALL.md`

**Files:**
- Modify: `INSTALL.md:216-242`

- [ ] **Step 1: Update the dependencies section (lines 216-242)**

Replace:
```
## Installing dependencies

The skill requires Python 3.8+ and the Unstructured library for document extraction:

```bash
pip install "unstructured[all-docs]"
```

Or install only the formats you need:

```bash
pip install "unstructured[pdf,docx]"
```

## Checking dependencies

After installation, run the dependency checker:

```bash
python3 /path/to/llm-wiki-skill/scripts/check-deps.py
```

Or from the cloned repo:

```bash
python3 scripts/check-deps.py
```

This checks for Python, Obsidian, optional extraction libraries, and file watcher tools.
```

With:
````
## Installing dependencies

The skill requires Python 3.8+ and two pip packages:

```bash
pip install "unstructured[all-docs]" watchdog
```

Or install only the Unstructured formats you need:

```bash
pip install "unstructured[pdf,docx]" watchdog
```

## Checking dependencies

After installation, run the dependency checker:

```bash
python3 /path/to/llm-wiki-skill/scripts/check-deps.py
```

Or from the cloned repo:

```bash
python3 scripts/check-deps.py
```

This checks for Python, Obsidian, unstructured, watchdog, and optional PDF tools.
````

- [ ] **Step 2: Commit**

```bash
git add INSTALL.md
git commit -m "docs: update INSTALL.md for cross-platform deps"
```

---

### Task 7: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the watch command**

Replace:
```
# Watch for raw source changes (requires fswatch on macOS or inotifywait on Linux)
bash llm-wiki/scripts/watch.sh <vault-path>
```

With:
```
# Watch for raw source changes
python3 llm-wiki/scripts/watch.py <vault-path>
python3 llm-wiki/scripts/watch.py <vault-path> --filter "*.md" --debounce 3.0
```

- [ ] **Step 2: Update the dependencies section**

Replace:
```
## Dependencies

- **Required**: Python 3.8+, `unstructured[all-docs]`
- **Recommended**: Obsidian desktop app
- **Optional**: `fswatch`/`inotifywait`, `PyMuPDF`, `pdftotext`, Obsidian CLI (v1.12.0+)
```

With:
```
## Dependencies

- **Required**: Python 3.8+, `unstructured[all-docs]`, `watchdog`
- **Recommended**: Obsidian desktop app
- **Optional**: `PyMuPDF`, `pdftotext`, Obsidian CLI (v1.12.0+)
```

- [ ] **Step 3: Update the key files list**

Replace:
```
- `llm-wiki/scripts/watch.sh` — File watcher for continuous change detection
```

With:
```
- `llm-wiki/scripts/watch.py` — Cross-platform file watcher using watchdog
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for cross-platform deps"
```

---

### Task 8: Smoke test the full workflow

- [ ] **Step 1: Run the dependency checker**

Run: `python3 scripts/check-deps.py`

Expected: watchdog appears under REQUIRED with its version. No file watcher optional section.

- [ ] **Step 2: Test `watch.py --help`**

Run: `python3 llm-wiki/scripts/watch.py --help`

Expected: Shows usage with all options (vault_path, --filter, --debounce, --json, --quiet).

- [ ] **Step 3: Verify no references to watch.sh remain**

Run: `grep -r "watch\.sh" --include="*.md" --include="*.py" .`

Expected: No matches (empty output).

- [ ] **Step 4: Verify no references to fswatch/inotifywait remain in non-deleted files**

Run: `grep -r "fswatch\|inotifywait\|inotify-tools" --include="*.md" --include="*.py" .`

Expected: No matches (empty output).

- [ ] **Step 5: Verify no references to shasum remain**

Run: `grep -r "shasum" --include="*.md" .`

Expected: No matches (empty output).
