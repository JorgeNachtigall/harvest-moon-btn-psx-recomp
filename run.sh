#!/usr/bin/env sh
# Launch the recompiled game.
#
# No --disc is needed: game.toml's relative disc path resolves against the
# executable's directory, and the runtime walks up from build/ to this
# directory to find it.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
EXE=$(ls "$ROOT"/build/Harvest_Moon* 2>/dev/null | head -1 || true)

if [ -z "$EXE" ]; then
    echo "error: no built executable in $ROOT/build — run: sh build.sh" >&2
    exit 1
fi

cd "$ROOT"

# Frame-stats overlay in the top-left corner. Line 1 is the REAL frame rate
# (display-area flips) next to the VSYNC cadence -- they are different numbers
# and only the first one means anything about how the game is running. Line 2
# is host frame-ms avg/max and primitives.
#
# OFF by default -- press Ctrl+Y in-game to show it. Start a session with it
# already up using PSX_OSD=1, or flip it remotely at any time with:
#   python3 psxrecomp/tools/debug_client.py osd enable=1
#
# Timing accumulates whether or not it is visible, so it shows real numbers the
# instant you bring it up -- no warm-up.
PSX_OSD=${PSX_OSD:-0}
export PSX_OSD

exec "$EXE" --game game.toml "$@"
