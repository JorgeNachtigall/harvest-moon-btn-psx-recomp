#!/usr/bin/env sh
# Configure and build the recompiled game.
#
# RelWithDebInfo is the development default because it keeps the TCP debug
# server (PSX_DEBUG_TOOLS) compiled in. Release strips it. Never build the
# generated C at -O0 — it compiles unusably slowly.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUILD_TYPE=${BUILD_TYPE:-RelWithDebInfo}

if [ ! -d "$ROOT/generated" ]; then
    echo "==> no generated/ yet; running tools/regen.sh first"
    sh "$ROOT/tools/regen.sh"
fi

cmake -S "$ROOT" -B "$ROOT/build" -G Ninja \
      -DCMAKE_BUILD_TYPE="$BUILD_TYPE" -DPSX_RECOMP_UI=OFF
cmake --build "$ROOT/build" --parallel

# Stage the shared overlay cache beside the executable, where the loader looks.
if [ -d "$ROOT/cache" ]; then
    mkdir -p "$ROOT/build/cache"
    cp -R "$ROOT/cache/." "$ROOT/build/cache/"
    echo "==> staged overlay cache into build/cache"
fi

echo "==> built. Run:  sh run.sh"
