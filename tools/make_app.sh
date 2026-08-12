#!/usr/bin/env sh
# Package the recompiled game as a self-contained macOS .app bundle.
#
# The result is a single folder you can copy to any Apple Silicon Mac you own
# and double-click. It carries the executable, your disc image, the game config
# and the overlays. There is nothing to install and no dependency beyond macOS
# itself -- the binary links only system frameworks.
#
# THIS BUNDLE CONTAINS YOUR GAME DATA. It is a copy of your own disc, for your
# own machines, exactly like any other personal backup. Do not distribute it:
# that is the difference between format-shifting something you own and
# publishing someone else's game. The repository stays clean either way -- the
# bundle is built into dist/, which is gitignored.
#
# Usage: sh tools/make_app.sh [output-dir]     (default: dist/)
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT_DIR=${1:-"$ROOT/dist"}
APP_NAME="Harvest Moon - Back to Nature"
BUNDLE_ID="com.shearwaterdata.harvestmoonbtn"
APP="$OUT_DIR/$APP_NAME.app"

EXE=$(ls "$ROOT"/build/Harvest_Moon* 2>/dev/null | head -1 || true)
if [ -z "$EXE" ]; then
    echo "error: no built executable -- run: sh build.sh" >&2
    exit 1
fi

CUE=$(ls "$ROOT"/*.cue 2>/dev/null | head -1 || true)
IMG=$(ls "$ROOT"/*.bin 2>/dev/null | grep -v 'text\.bin' | head -1 || true)
if [ -z "$CUE" ] || [ -z "$IMG" ]; then
    echo "error: need your .cue + .bin in $ROOT" >&2
    exit 1
fi

# Overlay code reaches the bundle by TWO routes, and it needs both.
#
#   baked (tools/bake_overlays.sh) covers the 13 disc overlays exhaustively,
#   straight from A_FILE.BIN -- including the five festival minigames that a
#   capture-driven workflow only finds if someone plays every festival.
#
#   cache/ shards cover regions that are NOT disc overlays at all: code the
#   kernel installs into low RAM (0x00000000, 0x0000D000). That is generated at
#   runtime, exists in no file on the disc, and cannot be statically extracted.
#
# Measured: a baked-only binary runs 992K interpreter fallbacks at the title
# screen against 5K with the cache present. Baking is a coverage guarantee, not
# a replacement. Ship both.
BAKED=no
if [ -f "$ROOT/generated/overlays_static.c" ]; then BAKED=yes; fi

echo "==> packaging $APP_NAME"
echo "    disc overlays: $([ "$BAKED" = yes ] && echo 'baked into the executable' || echo 'NOT baked — run tools/bake_overlays.sh')"
echo "    kernel regions: $([ -d "$ROOT/cache" ] && echo 'shipped as cache/ shards' || echo 'MISSING — no cache/ present')"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# --- the real binary, and a launcher in front of it ----------------------
# CFBundleExecutable is a shell script, because the runtime has no tilde or
# environment expansion for memcard_dir: writable state has to be pointed at
# ~/Library/Application Support from outside. Writing saves inside the bundle
# would break its code signature and lose them whenever the app is replaced.
cp "$EXE" "$APP/Contents/MacOS/harvest-moon-bin"

cat > "$APP/Contents/MacOS/HarvestMoon" <<'LAUNCHER'
#!/bin/sh
# Bundle launcher: keep every writable file outside the .app.
set -eu
HERE=$(cd -- "$(dirname -- "$0")" && pwd)
STATE="$HOME/Library/Application Support/Harvest Moon BTN"
mkdir -p "$STATE"
# Keep every writable file outside the bundle. The runtime would otherwise put
# its overlay capture store next to the executable (main.cpp: exe_dir /
# "overlay_captures.json"), which means inside the .app -- breaking its
# signature and failing outright if it is installed somewhere read-only.
export PSX_OVERLAY_CAPTURES="$STATE/overlay_captures.json"
cd "$STATE"
exec "$HERE/harvest-moon-bin" \
    --game "$HERE/../Resources/game.toml" \
    --memcard-dir "$STATE" \
    "$@"
LAUNCHER
chmod +x "$APP/Contents/MacOS/HarvestMoon"

# --- game data ------------------------------------------------------------
echo "==> copying disc image ($(du -h "$IMG" | cut -f1)) -- this takes a moment"
cp "$CUE" "$IMG" "$APP/Contents/Resources/"
cp "$ROOT/SLUS_011.15" "$APP/Contents/Resources/"

# A bundle-specific config.
#
# disc/exe stay BARE FILENAMES. The config loader makes them absolute against
# game.toml's OWN directory (config_loader.cpp: fs::absolute(root / d)), not
# against the executable's -- so a bare name resolves inside Resources/, which
# is exactly where they are. A "../Resources/" prefix looks correct and is not:
# it resolves to Resources/../Resources/, which fails validation.
#
# overlay_capture_history off, and the launcher redirects the capture file
# itself via PSX_OVERLAY_CAPTURES, so nothing is ever written inside the .app.
python3 - "$ROOT/game.toml" "$APP/Contents/Resources/game.toml" "$(basename "$CUE")" <<'PY'
import re, sys
src, dst, cue = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src).read()
text = re.sub(r'^\s*overlay_capture_history\s*=.*$',
              'overlay_capture_history = false   # bundle: nothing written inside the .app',
              text, flags=re.M)
text = re.sub(r'^\s*disc\s*=.*$', f'disc = "{cue}"', text, flags=re.M)
text = re.sub(r'^\s*exe\s*=.*$', 'exe = "SLUS_011.15"', text, flags=re.M)
open(dst, 'w').write(text)
PY

# build.sh stages runtime assets NEXT TO the binary, and the runtime resolves
# them relative to the executable -- so they must land in MacOS/, not
# Resources/. Missing bios/ is a hard failure: the recompiled OpenBIOS backend
# still loads its ROM image from disk at startup.
for staged in bios mods; do
    if [ -d "$ROOT/build/$staged" ]; then
        echo "==> copying $staged/"
        cp -R "$ROOT/build/$staged" "$APP/Contents/MacOS/$staged"
    fi
done
if [ ! -f "$APP/Contents/MacOS/bios/openbios.bin" ]; then
    echo "error: build/bios/openbios.bin missing -- run: sh build.sh" >&2
    exit 1
fi

# The loader looks for <exe_dir>/cache (main.cpp: cache_dir = exe_dir/"cache"),
# so this has to sit beside the binary in MacOS/, not in Resources/.
if [ -d "$ROOT/cache" ]; then
    echo "==> copying overlay shards ($(find "$ROOT/cache" -name '*.so' | wc -l | tr -d ' ') shards)"
    mkdir -p "$APP/Contents/MacOS/cache"
    cp -R "$ROOT/cache/." "$APP/Contents/MacOS/cache/"
fi

# --- bundle metadata ------------------------------------------------------
VERSION=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "dev")
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>              <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>       <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>        <string>$BUNDLE_ID</string>
    <key>CFBundleVersion</key>           <string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleExecutable</key>        <string>HarvestMoon</string>
    <key>CFBundlePackageType</key>       <string>APPL</string>
    <key>LSMinimumSystemVersion</key>    <string>11.0</string>
    <key>NSHighResolutionCapable</key>   <true/>
    <key>LSApplicationCategoryType</key> <string>public.app-category.games</string>
</dict>
</plist>
PLIST
printf 'APPL????' > "$APP/Contents/PkgInfo"

# --- signing --------------------------------------------------------------
# Ad-hoc signature. Enough for the app to run on your own Macs; it is not
# notarized, so the first launch on another machine needs the quarantine flag
# cleared (see the note this script prints at the end).
echo "==> ad-hoc signing"
codesign --force --deep --sign - "$APP" 2>/dev/null \
    || echo "    warning: codesign failed; the app will still run locally" >&2

SIZE=$(du -sh "$APP" | cut -f1)
echo
echo "==> built $APP  ($SIZE)"
echo
echo "    Run it:      open \"$APP\""
echo "    Saves live:  ~/Library/Application Support/Harvest Moon BTN"
echo
echo "    Copying to another Mac: macOS quarantines apps that arrive over"
echo "    AirDrop or a network share. On the target machine, once:"
echo "        xattr -dr com.apple.quarantine \"/Applications/$APP_NAME.app\""
echo
echo "    Install it somewhere YOU can write (/Applications and ~/Applications"
echo "    both qualify). The framework's mod catalog insists on creating and"
echo "    writing <exe_dir>/mods, so a genuinely read-only location fails at"
echo "    startup with 'cannot create mods directory'. Saves and overlay"
echo "    captures are already redirected out of the bundle; this one is not"
echo "    redirectable — the path is hardcoded in main.cpp."
