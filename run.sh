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
exec "$EXE" --game game.toml "$@"
