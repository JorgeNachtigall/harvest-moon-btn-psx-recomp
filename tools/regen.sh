#!/usr/bin/env sh
# Regenerate the recompiled game C from your disc's PS-X EXE.
#
# Run this after a fresh clone, after changing seeds/functions.txt, after
# editing [recompiler] in game.toml, or after bumping the psxrecomp submodule.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FRAMEWORK="$ROOT/psxrecomp"
EXE="$ROOT/SLUS_011.15"

if [ ! -d "$FRAMEWORK/recompiler" ]; then
    echo "error: framework missing at $FRAMEWORK" >&2
    echo "       run: git submodule update --init --recursive" >&2
    exit 1
fi

# Extract the executable from the disc if it is not already present.
if [ ! -f "$EXE" ]; then
    CUE=$(ls "$ROOT"/*.cue 2>/dev/null | head -1 || true)
    IMG=$(ls "$ROOT"/*.bin "$ROOT"/*.iso "$ROOT"/*.img 2>/dev/null | head -1 || true)
    if [ -z "$IMG" ]; then
        echo "error: no disc image found in $ROOT" >&2
        echo "       place your legally-obtained Harvest Moon: Back to Nature" >&2
        echo "       (SLUS-01115) .cue + .bin there." >&2
        exit 1
    fi
    echo "==> extracting SLUS_011.15 from $(basename "$IMG")"
    python3 "$ROOT/tools/extract_psx_exe.py" "$IMG" SLUS_011.15 "$EXE"
    # Headerless image for Ghidra import at base 0x80010000.
    python3 -c "import sys; d=open(sys.argv[1],'rb').read(); open(sys.argv[2],'wb').write(d[0x800:])" \
        "$EXE" "$ROOT/SLUS_011.15.text.bin"
fi

# Build the recompiler tool once.
if [ ! -x "$FRAMEWORK/recompiler/build/psxrecomp-game" ]; then
    echo "==> building the recompiler"
    cmake -S "$FRAMEWORK/recompiler" -B "$FRAMEWORK/recompiler/build" \
          -G Ninja -DCMAKE_BUILD_TYPE=Release
    cmake --build "$FRAMEWORK/recompiler/build"
fi

# The runtime links a recompiled BIOS backend; OpenBIOS is bundled and
# MIT-licensed, so this needs no BIOS dump. Its C is build output, not tracked.
if [ ! -f "$FRAMEWORK/generated/OpenBIOS_full.c" ]; then
    echo "==> generating the OpenBIOS backend"
    ( cd "$FRAMEWORK" && sh tools/regen_bios.sh --config bios/OpenBIOS.toml )
fi

echo "==> recompiling SLUS_011.15"
"$FRAMEWORK/recompiler/build/psxrecomp-game" --config "$ROOT/game.toml"

# Overlays: the game streams ~848 KB of code out of A_FILE.BIN into two fixed
# RAM windows. seeds/overlays.json says which archive members those are and
# where they land; the bytes come from the user's own disc, here, at build
# time. This is what makes overlay coverage a property of the disc rather than
# of how far the player happened to walk before dumping RAM.
if [ -f "$ROOT/seeds/overlays.json" ]; then
    IMG=${IMG:-$(ls "$ROOT"/*.bin "$ROOT"/*.iso "$ROOT"/*.img 2>/dev/null | head -1 || true)}
    if [ -z "$IMG" ]; then
        echo "warning: no disc image found -- skipping overlay extraction." >&2
        echo "         Overlays will run interpreted (correct, just slower)." >&2
    else
        echo "==> extracting overlays from $(basename "$IMG")"
        mkdir -p "$ROOT/build"
        python3 "$ROOT/tools/extract_overlays.py" \
            "$IMG" "$EXE" "$ROOT/seeds/overlays.json" "$ROOT/build/overlay_static.json"
        echo "    compile them with:  sh tools/compile_static_overlays.sh"
    fi
fi

echo "==> done. Next: sh build.sh"
