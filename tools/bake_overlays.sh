#!/usr/bin/env sh
# Compile the statically extracted overlays into ONE C file, linked straight
# into the executable instead of loaded from cache/ as shared objects.
#
# Same overlays, same recompiler, same bytes off your disc -- only the delivery
# changes. The result is a single self-contained binary: no cache/ directory to
# carry alongside it, no dlopen at launch, nothing that can get separated from
# the executable. That is what tools/make_app.sh needs to produce a .app you can
# drop on another Mac.
#
# The shard route (tools/compile_static_overlays.sh) remains perfectly good for
# ordinary development, and is faster to iterate on: a changed overlay rebuilds
# one .so instead of relinking the whole binary.
#
# Run after tools/regen.sh, then rebuild with build.sh.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FRAMEWORK="$ROOT/psxrecomp"
CAPTURES="$ROOT/build/overlay_static.json"
OUT_DIR="$ROOT/generated"
OUT="$OUT_DIR/overlays_static.c"

if [ ! -f "$CAPTURES" ]; then
    echo "error: $CAPTURES not found -- run: sh tools/regen.sh" >&2
    exit 1
fi

if [ ! -x "$FRAMEWORK/recompiler/build/psxrecomp-game" ]; then
    echo "error: recompiler not built -- run: sh tools/regen.sh" >&2
    exit 1
fi

# --static skips the file when it already exists unless forced; we always want
# it to track the current captures, so force and let it rebuild.
echo "==> baking overlays into C (this runs sequentially and takes a few minutes)"
python3 "$FRAMEWORK/tools/compile_overlays.py" \
    --captures "$CAPTURES" \
    --game-toml "$ROOT/game.toml" \
    --recompiler "$FRAMEWORK/recompiler/build/psxrecomp-game" \
    --runtime-include "$FRAMEWORK/runtime/include" \
    --out-dir "$OUT_DIR" \
    --static \
    --force

if [ ! -f "$OUT" ]; then
    echo "error: expected $OUT, but it was not produced" >&2
    exit 1
fi

echo "==> $OUT ($(du -h "$OUT" | cut -f1))"
echo "==> now rebuild:  sh build.sh"
