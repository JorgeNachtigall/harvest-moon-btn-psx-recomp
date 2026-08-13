#!/usr/bin/env sh
# Recover overlay function entry points with Ghidra headless analysis.
#
# The overlay shards are compiled by walking outward from seeds. Until now the
# only seeds were the mode-switch entry points and the header pointer tables in
# seeds/overlays.json -- a few hundred. Anything reached only through an
# indirect/computed call was never discovered, had no native function, and fell
# back to the MIPS interpreter (measured: 648k interpreted dispatches against
# 114k native).
#
# This is the same treatment the main executable already got: import the raw
# image at its load address, let Ghidra find function starts, export them, feed
# them back as seeds.
#
# GHIDRA MUST BE CLOSED -- the project holds an exclusive lock.
#
# Usage: sh tools/overlay_seeds.sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BINS="$ROOT/build/overlay_bins"
OUT="$ROOT/build/overlay_seeds"
GHIDRA=$(ls -d /opt/homebrew/Cellar/ghidra/*/libexec/support/analyzeHeadless 2>/dev/null | head -1)
PROJ_DIR="$HOME/ghidra-projects"
PROJ="HMOverlays"

if [ -z "$GHIDRA" ]; then
    echo "error: analyzeHeadless not found" >&2; exit 1
fi
if [ ! -d "$BINS" ]; then
    echo "error: $BINS missing -- run tools/regen.sh first" >&2; exit 1
fi
if pgrep -f ghidra >/dev/null 2>&1; then
    echo "error: Ghidra is running. Close it -- the project lock is exclusive." >&2
    exit 1
fi

mkdir -p "$OUT"

for bin in "$BINS"/*.bin; do
    base=$(basename "$bin" .bin)
    addr=$(echo "$base" | cut -d_ -f1)
    echo "==> $base  (base 0x$addr)"
    # -import with a raw-binary loader at the overlay's real load address, full
    # analysis, then export every function start the analyser found.
    "$GHIDRA" "$PROJ_DIR" "$PROJ" \
        -import "$bin" \
        -overwrite \
        -processor "MIPS:LE:32:default" \
        -loader BinaryLoader \
        -loader-baseAddr "0x$addr" \
        -scriptPath "$HOME/ghidra_scripts" \
        -postScript ExportFunctionSeeds.java "$OUT/$base" \
        > "$OUT/$base.log" 2>&1 || {
            echo "    FAILED -- see $OUT/$base.log" >&2; continue; }
    if [ -f "$OUT/$base/functions.txt" ]; then
        echo "    $(wc -l < "$OUT/$base/functions.txt" | tr -d ' ') function starts"
    else
        echo "    no seed file produced -- see $OUT/$base.log" >&2
    fi
done

echo
echo "==> seeds in $OUT"
echo "    next: sh tools/merge_overlay_seeds.sh && sh tools/compile_static_overlays.sh"
