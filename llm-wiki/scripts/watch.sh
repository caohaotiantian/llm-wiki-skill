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
# Requirements: fswatch (macOS: brew install fswatch, Linux: apt install fswatch)

set -euo pipefail

VAULT_PATH="${1:?Usage: $0 <vault-path>}"
RAW_DIR="$VAULT_PATH/raw"
PENDING_FILE="$RAW_DIR/.pending_changes.json"

if ! command -v fswatch &>/dev/null; then
    echo "Error: fswatch is required. Install with: brew install fswatch"
    exit 1
fi

if [ ! -d "$RAW_DIR" ]; then
    echo "Error: $RAW_DIR does not exist. Is this a valid wiki vault?"
    exit 1
fi

# Initialize pending changes file if it doesn't exist
if [ ! -f "$PENDING_FILE" ]; then
    echo '{"changes": []}' > "$PENDING_FILE"
fi

echo "Watching $RAW_DIR for changes..."
echo "Press Ctrl+C to stop."

fswatch -0 --event Created --event Updated --event Renamed "$RAW_DIR" | while IFS= read -r -d '' file; do
    # Skip hidden files and the pending changes file itself
    basename=$(basename "$file")
    if [[ "$basename" == .* ]]; then
        continue
    fi

    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    rel_path="${file#$VAULT_PATH/}"

    echo "[$timestamp] Change detected: $rel_path"

    # Append to pending changes using python for safe JSON manipulation
    python3 -c "
import json, sys
path = '$PENDING_FILE'
try:
    with open(path) as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {'changes': []}
data['changes'].append({
    'file': '$rel_path',
    'timestamp': '$timestamp',
    'type': 'modified'
})
# Deduplicate by file path, keeping latest
seen = {}
for c in data['changes']:
    seen[c['file']] = c
data['changes'] = list(seen.values())
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
"
done
