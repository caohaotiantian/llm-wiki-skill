#!/usr/bin/env bash
# Batch extract all PDFs in raw/ with a single mineru invocation,
# then move output into raw/extracted/<stem>.pdf.md convention.
#
# Usage: ./batch_extract.sh <vault-root>

set -euo pipefail

VAULT="${1:?usage: $0 <vault-root>}"
VAULT="$(cd "$VAULT" && pwd)"
RAW="$VAULT/raw"
EXTRACTED="$RAW/extracted"
TMP="${BATCH_TMP:-$(mktemp -d -t mineru-batch.XXXXXX)}"
VENV_BIN="$VAULT/.venv/bin"

export PATH="$VENV_BIN:$PATH"
export MINERU_MODEL_SOURCE="${MINERU_MODEL_SOURCE:-modelscope}"

mkdir -p "$EXTRACTED"

shopt -s nullglob
PDFS=("$RAW"/*.pdf)
if [ ${#PDFS[@]} -eq 0 ]; then
    echo "No PDFs in $RAW"; exit 0
fi
echo "Found ${#PDFS[@]} PDFs. Extracting to $TMP ..."

if [ ! -d "$TMP" ] || [ -z "$(ls -A "$TMP" 2>/dev/null)" ]; then
    mineru -p "$RAW" -o "$TMP" -m txt -b pipeline
fi

moved=0
for d in "$TMP"/*/; do
    stem="$(basename "$d")"
    # mineru writes <stem>/<mode>/<stem>.md where mode is txt|auto|ocr
    md="$(ls "$d"/*/"$stem".md 2>/dev/null | head -1)"
    if [ -z "$md" ] || [ ! -f "$md" ]; then
        echo "Warning: no .md for $stem under $d"
        continue
    fi
    dst="$EXTRACTED/$stem.pdf.md"
    cp "$md" "$dst"

    imgs_src="$(dirname "$md")/images"
    if [ -d "$imgs_src" ] && [ -n "$(ls -A "$imgs_src" 2>/dev/null)" ]; then
        dst_imgs="$EXTRACTED/$stem.pdf.md.images"
        rm -rf "$dst_imgs"
        cp -r "$imgs_src" "$dst_imgs"
        python3 -c "
import sys, os
md, imgdir = sys.argv[1], os.path.basename(sys.argv[2])
with open(md, 'r', encoding='utf-8') as f: t = f.read()
t = t.replace('images/', imgdir + '/')
with open(md, 'w', encoding='utf-8') as f: f.write(t)
" "$dst" "$dst_imgs"
    fi
    moved=$((moved + 1))
    echo "  [$moved] $stem -> $(basename "$dst")"
done

echo "Done: $moved of ${#PDFS[@]} PDFs moved to $EXTRACTED"
echo "Tmp dir: $TMP (can delete after verification)"
