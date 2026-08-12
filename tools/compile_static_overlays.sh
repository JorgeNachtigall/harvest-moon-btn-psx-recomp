#!/usr/bin/env sh
# Compile every overlay extracted from the disc by tools/regen.sh, then persist
# the shards to the durable cache/.
#
# This is the play-free path: no capture session, no debug_client dump, no
# dependence on where the player walked. Run it once after regen.sh and every
# overlay in the game is native on the next launch.
#
# The older capture-driven loop (README "Overlays") still works and is still
# the way to pick up anything this misses -- but with the static map in
# seeds/overlays.json there should be nothing left to miss.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FRAMEWORK="$ROOT/psxrecomp"
CAPTURES="$ROOT/build/overlay_static.json"
JOBS=${JOBS:-8}

if [ ! -f "$CAPTURES" ]; then
    echo "error: $CAPTURES not found -- run: sh tools/regen.sh" >&2
    exit 1
fi

if [ ! -x "$FRAMEWORK/recompiler/build/psxrecomp-game" ]; then
    echo "error: recompiler not built -- run: sh tools/regen.sh" >&2
    exit 1
fi

echo "==> compiling static overlays (jobs=$JOBS)"
python3 "$FRAMEWORK/tools/compile_overlays.py" \
    --captures "$CAPTURES" \
    --game-toml "$ROOT/game.toml" \
    --recompiler "$FRAMEWORK/recompiler/build/psxrecomp-game" \
    --runtime-include "$FRAMEWORK/runtime/include" \
    --out-dir "$ROOT/build/cache" \
    --jobs "$JOBS"

# build/ is disposable; cache/ is the durable store. Skipping this would throw
# the shards away on the next clean build.
sh "$ROOT/tools/save_cache.sh"

echo "==> done. Restart the game: shards load at launch, never mid-session."
