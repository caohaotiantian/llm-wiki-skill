#!/usr/bin/env bash
#
# File watcher for LLM Wiki raw sources.
# Monitors the raw/ directory for new or modified files and logs changes.
#
# Usage:
#   ./watch.sh <vault-path>
#   ./watch.sh ~/Documents/obsidian/my-wiki
#
# The watcher logs detected changes to raw/.pending_changes.json
# so the next LLM conversation can pick them up and suggest ingestion.
#
# Platform support:
#   macOS:  brew install fswatch
#   Linux:  apt install inotify-tools  (preferred; or build fswatch from source)

set -euo pipefail

VAULT_PATH="${1:?Usage: $0 <vault-path>}"
RAW_DIR="$VAULT_PATH/raw"
PENDING_FILE="$RAW_DIR/.pending_changes.json"

if [ ! -d "$RAW_DIR" ]; then
    echo "Error: $RAW_DIR does not exist. Is this a valid wiki vault?"
    exit 1
fi

# Initialize pending changes file if it doesn't exist
if [ ! -f "$PENDING_FILE" ]; then
    echo '{"changes": []}' > "$PENDING_FILE"
fi

# Detect available file watcher
if command -v fswatch &>/dev/null; then
    WATCHER="fswatch"
elif command -v inotifywait &>/dev/null; then
    WATCHER="inotifywait"
else
    echo "Error: No file watcher found."
    echo "  macOS:  brew install fswatch"
    echo "  Linux:  apt install inotify-tools  (or build fswatch from source)"
    exit 1
fi

record_change() {
    local pending_file="$1"
    local rel_path="$2"
    local timestamp="$3"

    python3 - "$pending_file" "$rel_path" "$timestamp" <<'PYEOF'
import json, sys

path, rel_path, timestamp = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {"changes": []}
data["changes"].append({
    "file": rel_path,
    "timestamp": timestamp,
    "type": "modified"
})
# Deduplicate by file path, keeping latest
seen = {}
for c in data["changes"]:
    seen[c["file"]] = c
data["changes"] = list(seen.values())
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PYEOF
}

echo "Watching $RAW_DIR for changes (using $WATCHER)..."
echo "Press Ctrl+C to stop."

if [ "$WATCHER" = "fswatch" ]; then
    fswatch -0 --event Created --event Updated --event Renamed "$RAW_DIR" | while IFS= read -r -d '' file; do
        basename=$(basename "$file")
        if [[ "$basename" == .* ]]; then
            continue
        fi
        timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        rel_path="${file#"$VAULT_PATH"/}"
        echo "[$timestamp] Change detected: $rel_path"
        record_change "$PENDING_FILE" "$rel_path" "$timestamp"
    done
else
    # inotifywait fallback for Linux
    inotifywait -m -r -e create -e modify -e moved_to --format '%w%f' "$RAW_DIR" | while IFS= read -r file; do
        basename=$(basename "$file")
        if [[ "$basename" == .* ]]; then
            continue
        fi
        timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
        rel_path="${file#"$VAULT_PATH"/}"
        echo "[$timestamp] Change detected: $rel_path"
        record_change "$PENDING_FILE" "$rel_path" "$timestamp"
    done
fi
