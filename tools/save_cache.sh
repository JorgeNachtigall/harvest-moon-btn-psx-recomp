#!/usr/bin/env sh
# Copy newly compiled overlay shards out of the build tree into the durable
# cache/ at the repo root.
#
# The runtime and compile_overlays.py both work inside build/, which is
# disposable — wiping it would otherwise throw away every overlay you compiled.
# build.sh copies cache/ -> build/cache on the way in; this is the way out.
# Run it after compiling overlays.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ ! -d "$ROOT/build/cache" ]; then
    echo "nothing to save: $ROOT/build/cache does not exist" >&2
    exit 0
fi

mkdir -p "$ROOT/cache"
cp -R "$ROOT/build/cache/." "$ROOT/cache/"

echo "saved $(find "$ROOT/cache" -name '*.so' | wc -l | tr -d ' ') overlay shard(s) to cache/"
