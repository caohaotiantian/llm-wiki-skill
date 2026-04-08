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
        # Ignore any file whose basename or any parent directory starts with "."
        parts = Path(path).parts
        if any(part.startswith(".") for part in parts):
            return True
        if self._filter_glob and not fnmatch.fnmatch(os.path.basename(path), self._filter_glob):
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
