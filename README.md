# HarvestMoonBTNRecomp

A static recompilation of **Harvest Moon: Back to Nature (USA, SLUS-01115)**
built on [PSXRecomp](https://github.com/mstan/psxrecomp).

The game's MIPS R3000A code is translated to C ahead of time and compiled into
a **native executable** — the CPU is not emulated. The PlayStation's peripherals
(GPU, SPU, CD-ROM, DMA, timers, GTE, MDEC, controllers) are simulated around it,
and the kernel is the recompiled OpenBIOS.

**This repository contains no game data.** You supply your own legally-obtained
disc image. Nothing derived from it — the extracted executable, the generated C,
compiled overlays, or overlay captures — is tracked here.

## Status

| | |
|---|---|
| Boots to title | yes |
| Gameplay | town, farm mechanics, in-engine cutscenes |
| Audio | yes (SPU synthesis) |
| Static coverage | 1475 functions, **0 dispatch misses** |
| Overlays | captured → compiled → native, **0 invalidations** |
| MDEC (FMV) | **untested** — `mdec_decode_count` has never left 0 |
| Verified on | macOS arm64 (Apple Silicon) |

## Requirements

- CMake ≥ 3.20, Ninja, and a C/C++ toolchain (Apple Clang, GCC, or MSVC)
- Python 3
- Your own `Harvest Moon - Back to Nature (USA).cue` + `.bin`, placed in this
  directory

No PlayStation BIOS dump is required — the MIT-licensed OpenBIOS bundled with
the framework is used by default.

## Build

```sh
git clone --recurse-submodules <this-repo> HarvestMoonBTNRecomp
cd HarvestMoonBTNRecomp
# ...place your .cue and .bin here...

sh tools/regen.sh   # extract the EXE + recompile it to C
sh build.sh         # configure + build (also stages cache/ into build/)
sh run.sh           # play
```

`tools/regen.sh` is idempotent: it extracts `SLUS_011.15` from the disc, builds
the recompiler, generates the OpenBIOS backend, and emits the game C into
`generated/`.

## Layout

```
game.toml                 game + recompiler + runtime configuration
seeds/functions.txt       954 function entry points (see below)
seeds/pointer_table_seeds.json   evidence for the 8 hand-recovered seeds
seeds/overlays.json       the static overlay map (see Overlays)
psxrecomp/                the framework, pinned as a submodule
tools/extract_psx_exe.py  pulls a file out of a MODE2/2352 or 2048 disc image
tools/extract_overlays.py slices every overlay out of A_FILE.BIN
tools/regen.sh            disc -> EXE -> generated C + extracted overlays
tools/compile_static_overlays.sh   overlays -> native shards in cache/
build.sh / run.sh         build and launch
cache/                    compiled overlay shards (gitignored)
```

## Where the seeds came from

The recompiler needs function entry points it cannot infer. `seeds/functions.txt`
holds **954**:

- **946** from Ghidra auto-analysis of the headerless `SLUS_011.15.text.bin`,
  imported as Raw Binary, `MIPS:LE:32:default`, base `0x80010000`.
- **8** recovered by scanning the data region (`0x80048B08`–`0x8005E378`) for
  words pointing into code. Each is a leaf function with no stack-frame
  prologue, reachable only through a function-pointer table — invisible to both
  prologue heuristics and `jal` following. Evidence for every one is recorded in
  `seeds/pointer_table_seeds.json`.

To refresh them after more Ghidra work (the Ghidra project must be **closed**,
since it holds an exclusive lock):

```sh
analyzeHeadless ~/ghidra-projects/HarvestMoonBTN -process "SLUS_011.15.text.bin" \
  -noanalysis -scriptPath ~/ghidra_scripts -postScript ExportFunctionSeeds.java seeds
```

## Overlays

The main executable is only 321 KB. The rest of the game's code — about
**848 KB** — is streamed off the disc into RAM as **overlays**. Anything not
compiled runs on a small MIPS interpreter: correct, just slower. **The worst
case is performance, never correctness.**

Overlays are extracted **statically, from your own disc, at build time**:

```sh
sh tools/regen.sh                     # also writes build/overlay_static.json
sh tools/compile_static_overlays.sh   # compiles it and persists to cache/
# restart — shards go native on the next launch, never mid-session
```

That is the whole loop. No capture session, no playing to a particular screen,
no dependence on where you walked. Coverage is a property of the disc, so it is
identical for every user and reproducible from a clean clone.

**How it works.** The game ships one archive, `A_FILE.BIN`, indexed by the
132-byte `A_FILE.HDT` (33 little-endian offsets; member *i* spans
`HDT[i]..HDT[i+1]`). `FUN_800145f0` loads a member to a caller-supplied address,
and every caller passes one of two constants held in the executable —
`0x800B7E20` (immediately after BSS) or `0x8012DDE8`. So overlays occupy two
mutually exclusive windows, and which member goes where is decided by a
`switch` on the game mode in the main loop.

`seeds/overlays.json` records that mapping — 13 members, their window, and
their entry points. It holds **no game content**, only facts about where
content lives, exactly like `seeds/functions.txt`. `tools/extract_overlays.py`
joins it to your disc and re-derives the archive layout, the window constants,
and the member names from your own files, failing loudly on any mismatch rather
than emitting a plausible guess.

The five festival minigames (`MG1`–`MG5`) are separate overlays sharing one
window, which is why a capture-driven workflow would never find them unless you
played every festival.

### Baking overlays into the executable

`tools/compile_static_overlays.sh` produces loadable `.so` shards in `cache/`.
The alternative is to compile the same overlays into **one C file linked
straight into the binary**:

```sh
sh tools/bake_overlays.sh   # -> generated/overlays_static.c (~18 MB, 7838 functions)
sh build.sh                 # CMake picks it up automatically
```

`CMakeLists.txt` passes it as `GAME_OVERLAY_STATIC_C` when the file exists, and
says so at configure time. This is what `tools/make_app.sh` wants: one
self-contained binary with nothing alongside it to lose.

**Baking is a coverage guarantee, not a replacement for `cache/`.** The shards
also cover regions that are not disc overlays at all — code the kernel installs
into low RAM (`0x00000000`, `0x0000D000`), which exists in no file on the disc
and cannot be statically extracted. Measured at the title screen: 992K
interpreter fallbacks with baked overlays alone, 5K with the cache present.
Ship both.

### Capture-driven fallback

The older loop still works and remains the way to pick up anything static
extraction misses (it should miss nothing). On macOS it is manual, since the
in-session autocompile is Windows-only:

```sh
# 1. play into the area you want covered, then:
python3 psxrecomp/tools/debug_client.py overlay_capture_dump

# 2. compile the captures into cache/
python3 psxrecomp/tools/compile_overlays.py \
  --captures build/overlay_captures.json \
  --game-toml game.toml \
  --recompiler psxrecomp/recompiler/build/psxrecomp-game \
  --runtime-include psxrecomp/runtime/include \
  --out-dir build/cache --jobs 8

# 3. persist the new shards out of the disposable build tree
sh tools/save_cache.sh
```

Captures are additive, so coverage accumulates across sessions.

**Two directories, deliberately.** `cache/` at the repo root is the durable
store; `build/cache` is what the runtime actually reads. `build.sh` copies
root → build on the way in, and `tools/save_cache.sh` copies build → root on the
way out. Skipping step 3 means `rm -rf build/` silently discards every overlay
you compiled. Older capture files can be archived under `captures/` and fed back
in with `--captures captures/<file>` after a codegen change.

## Packaging a macOS .app

For playing on your own Macs without a checkout, `tools/make_app.sh` produces a
self-contained bundle:

```sh
sh tools/regen.sh
sh tools/bake_overlays.sh          # disc overlays -> into the binary
sh tools/compile_static_overlays.sh # kernel regions -> cache/ shards
sh build.sh
sh tools/make_app.sh               # -> dist/<name>.app  (~265 MB)
```

The binary links only system frameworks, so there is nothing to install on the
target machine. Layout:

```
<name>.app/Contents/
  MacOS/HarvestMoon        launcher script (CFBundleExecutable)
  MacOS/harvest-moon-bin   the real binary, overlays baked in
  MacOS/bios/  mods/  cache/    resolved relative to the EXECUTABLE
  Resources/   game.toml, disc image, SLUS_011.15
```

The split is not cosmetic. `bios/`, `mods/` and `cache/` are found relative to
the *executable* and must sit in `MacOS/`; `game.toml`'s `disc`/`exe` values are
made absolute against *`game.toml`'s own directory*, so they stay bare filenames
resolving inside `Resources/`.

The launcher exists because the runtime has no `~` or environment expansion for
`memcard_dir`. It redirects saves via `--memcard-dir` and the overlay capture
store via `PSX_OVERLAY_CAPTURES`, both to
`~/Library/Application Support/Harvest Moon BTN`, so nothing is written inside
the bundle.

**This bundle embeds your disc image.** It is a personal backup of your own
disc for your own machines — the same thing as the `.bin` in this directory,
in a different container. `dist/` is gitignored. Do not distribute it.

Two caveats:

- **Install it somewhere you can write.** `/Applications` and `~/Applications`
  both qualify. The mod catalog insists on creating `<exe_dir>/mods` and that
  path is hardcoded, so a genuinely read-only location fails at startup with
  `cannot create mods directory`.
- **First launch on another Mac.** The bundle is ad-hoc signed, not notarized,
  so macOS quarantines it if it arrives by AirDrop or a share:
  `xattr -dr com.apple.quarantine "/Applications/<name>.app"`.

## Known issues

- **`[recompiler] bios_config` is ignored on the overlay compile path.**
  `bios_profile_path` is populated only from `--config`, but
  `compile_overlays.py` invokes the recompiler with `--ws-config`. It falls back
  to searching for `<subdir>/bios/SCPH1001.toml` relative to `game.toml` — which
  works here **only because** the framework sits at `./psxrecomp`. Upstream fix
  needed.
- **MDEC is unexercised.** If the game has real FMV anywhere, that path is
  unproven.
- The framework's `mod_load_acceleration` test fails upstream on a stale
  assertion; a clean `ctest` run is 40/41.

## Legal

Harvest Moon: Back to Nature is © Natsume / Victor Interactive Software. This
repository ships no game code, assets, or disc data — only configuration,
factual addresses, and build tooling. Use only a disc image you obtained
legally, and do not redistribute anything generated from it.
