# Cross-Platform Python Rewrite

## Goal

Make the llm-wiki-skill work with just Python 3.8+ and pip — no platform-specific CLI tools (fswatch, inotifywait, shasum) required.

## Approach

Approach B: Replace `watch.sh` with `watch.py` using `watchdog`, fix all platform-specific references across the project, update docs.

## New File: `llm-wiki/scripts/watch.py`

Replaces `llm-wiki/scripts/watch.sh`. Uses the `watchdog` library for cross-platform filesystem event monitoring.

### CLI Interface

```
python3 watch.py <vault-path> [options]

Options:
  --filter GLOB       Only watch files matching pattern, using fnmatch (e.g. "*.md", "*.pdf")
  --debounce SECONDS  Coalesce rapid changes (default: 2.0)
  --json              Output events as JSON lines to stdout (for piping)
  --quiet             Suppress console output, only write to .pending_changes.json
```

### Behavior

- Watches `<vault-path>/raw/` recursively for creates, modifications, and moves
- Ignores dotfiles (files/dirs starting with `.`), same as current `watch.sh`
- Writes to `raw/.pending_changes.json` in the same format (backwards compatible)
- Debouncing: coalesces rapid changes to the same file within the debounce window (default 2s), recording only the latest event
- Graceful shutdown on Ctrl+C

### Programmatic API

```python
from watch import Watcher

w = Watcher(vault_path, filter_glob="*.md", debounce=2.0)
w.start()   # blocking
# or
w.start_background()  # returns threading.Event for stop signaling
```

### Output Format

Same `.pending_changes.json` format as today:

```json
{
  "changes": [
    {"file": "raw/articles/source.md", "timestamp": "2026-04-08T10:00:00Z", "type": "modified"}
  ]
}
```

Deduplication by file path, keeping the latest event (same logic as current `watch.sh`).

## Changes to Existing Files

### Delete

- `llm-wiki/scripts/watch.sh` — replaced by `watch.py`

### `scripts/check-deps.py`

- Remove `check_fswatch()` and `check_inotifywait()` functions
- Remove the "OPTIONAL — File Watcher (scripts/watch.sh)" section
- Add `check_watchdog()` under REQUIRED section (alongside `unstructured`)
- Imports watchdog, reports version

### `llm-wiki/SKILL.md`

- Line 158: Replace dual `shasum`/Python SHA-256 command with single cross-platform Python one-liner: `python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <file>`
- Line 373: Update `scripts/watch.sh <vault-path>` → `scripts/watch.py <vault-path>`
- Line 503: Update `watch.sh` → `watch.py` in file listing

### `README.md`

- Dependencies: remove `fswatch`/`inotifywait` from optional, add `watchdog` to required
- Project structure: `watch.sh` → `watch.py`
- Usage examples: update to `python3` commands

### `INSTALL.md`

- Replace any `watch.sh` references with `watch.py`
- Remove platform-specific fswatch/inotifywait install instructions

### `CLAUDE.md`

- Update commands section: `watch.sh` → `watch.py`
- Update dependencies: add `watchdog` to required, remove fswatch/inotifywait from optional

## Dependencies

**Added:**
- `watchdog` — required (cross-platform filesystem event monitoring)

**Removed (no longer needed):**
- `fswatch` (macOS CLI tool)
- `inotifywait` (Linux CLI tool, from `inotify-tools`)
