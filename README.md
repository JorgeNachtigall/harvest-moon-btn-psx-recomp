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
psxrecomp/                the framework, pinned as a submodule
tools/extract_psx_exe.py  pulls a file out of a MODE2/2352 or 2048 disc image
tools/regen.sh            disc -> EXE -> generated C
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

The main executable is only 321 KB; the rest of the game's code is streamed off
the disc into RAM as **overlays**, which cannot be seen at build time. They are
captured from live RAM, compiled by the same recompiler, and cached — after
which they run native. Anything not yet captured runs on a small MIPS
interpreter: correct, just slower. **The worst case is performance, never
correctness.**

On macOS the loop is manual (the in-session autocompile is Windows-only):

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

# 4. restart — shards go native on the next launch, never mid-session
```

Captures are additive, so coverage accumulates across sessions.

**Two directories, deliberately.** `cache/` at the repo root is the durable
store; `build/cache` is what the runtime actually reads. `build.sh` copies
root → build on the way in, and `tools/save_cache.sh` copies build → root on the
way out. Skipping step 3 means `rm -rf build/` silently discards every overlay
you compiled. Older capture files can be archived under `captures/` and fed back
in with `--captures captures/<file>` after a codegen change.

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
