# HarvestMoonBTNRecomp — working rules and current state

Read this first, every session. It is the project context; `README.md` is the
user-facing document.

This is a **game repository**, not the framework. The framework
([PSXRecomp](https://github.com/mstan/psxrecomp)) is a pinned submodule at
`psxrecomp/`. Its engineering constitution — `psxrecomp/CLAUDE.md` and
`psxrecomp/PRINCIPLES.md` — still applies to anything touching framework code.

---

## 0. The rules that matter here

1. **Never hand-edit generated code.** `generated/*.c` and compiled overlay
   shards are build artifacts. If the emitted C is wrong, fix the recompiler in
   `psxrecomp/recompiler/src/` and regenerate — never patch the output.
2. **No stubs, no fakes.** A thing is implemented or it fails loudly. Never
   synthesize "the answer the game would have produced" to make a symptom go
   away.
3. **No `printf` debugging, no log files.** Runtime inspection goes through the
   TCP debug server (`psxrecomp/TCP_COMMANDS.md`) and its ring buffers.
4. **Find the FIRST divergence, not the symptom.** Capture state, compare state,
   locate the earliest difference, fix its cause.
5. **Unknown is acceptable; guessing is not.** If it can't be answered from
   Ghidra, the disc, or the oracle, the answer is "I don't know yet."
6. **Fix broken tooling immediately.** Don't route around it, don't carry it
   forward as a known limitation.
7. **Game-specific work belongs HERE**, never in `psxrecomp/`. The framework
   stays game-agnostic; per-game patches and enhancements live in this repo.

---

## 1. What this is

Static recompilation of **Harvest Moon: Back to Nature (USA), SLUS-01115**. The
game's MIPS R3000A code is translated to C ahead of time and compiled native —
the CPU is not emulated. PS1 peripherals are simulated around it; the kernel is
the recompiled OpenBIOS (no retail BIOS dump present on this machine).

Verified on macOS arm64 (Apple Silicon).

---

## 2. Verified facts — do not re-derive

All read from the PS-X EXE header and confirmed against the entry-point
BSS-clear loop in Ghidra.

| | |
|---|---|
| Serial | `SLUS-01115` (boot record `cdrom:\SLUS_011.15`) |
| Disc | single track, `MODE2/2352`, 213,954,384 bytes |
| EXE | ISO9660 root, LBA 24, 323,584 bytes (`0x800` header + `0x4E800` text) |
| Load address | `0x80010000` |
| Entry point | `0x80011278` (a BSS-clear loop zeroing `0x8005E378`..`0x800B7E20`) |
| Text size | `0x4E800`; code actually ends ~`0x80048B08` |
| `0x80048B08`–`0x8005E378` | DATA — strings + pointer tables (1 `jr $ra` in the whole span) |
| `0x8005E378`–`0x8005E800` | BSS (100% zeros) |
| Stack base | `0x801FFFF0`; `initial_gp` = 0 (unused at entry) |
| Overlay region floor | `0x5E800`; the big overlay window is `0x800B7000` (~1 MB) |

**Seeds: 954** = 946 Ghidra function starts + 8 recovered by scanning the data
region for function-pointer targets. Those 8 are leaf functions with no
stack-frame prologue, reachable only indirectly — invisible to both prologue
heuristics and `jal` following. Evidence per seed: `seeds/pointer_table_seeds.json`.

**Generation output:** 1475 functions, 1474 dispatch entries, 681,560 lines of C
in 18 shards, **0 functions skipped**. 15 `out-of-function branch/jump` warnings
— boundary-detection signals; check those addresses first if a divergence
appears near them.

---

## 3. Workflows

```sh
sh tools/regen.sh    # disc -> EXE -> generated C (idempotent)
sh build.sh          # configure + build (RelWithDebInfo; stages cache/ -> build/cache)
sh run.sh            # launch; no --disc needed, it resolves from game.toml
```

Build type matters: **RelWithDebInfo** keeps the TCP debug server compiled in.
Release strips it. Never build the generated C at `-O0`.

### Overlays — static extraction (the default path)

```sh
sh tools/regen.sh                     # also writes build/overlay_static.json
sh tools/compile_static_overlays.sh   # compiles it, saves to cache/, restart
```

Overlays come off the disc at build time, not out of live RAM. `seeds/overlays.json`
holds the map (13 members, 848 KB, two windows); `tools/extract_overlays.py`
joins it to the user's disc and emits a captures-format file that the
framework's `compile_overlays.py` consumes unchanged — no framework changes.

**Verified facts about the overlay system — do not re-derive:**

| | |
|---|---|
| Archive | `A_FILE.BIN` (LBA 182, 133,935,104 B), indexed by `A_FILE.HDT` (132 B) |
| Index format | 33 LE u32 byte offsets; member *i* = `HDT[i]..HDT[i+1]`; `HDT[32]` = total size |
| Record table | `0x80048B40`, 33 × `0x28`, field 0 = HDT offset, field 2.. = ASCII path |
| Loader | `FUN_800147bc` (init), `FUN_800145f0(start, end, dest, dest)` (load) |
| LBA math | `(table[start] >> 11) + base_lba`, base from `CdSearchFile` in `0x8005E430` |
| Window A | `0x800B7E20`, constant at `0x80010098` — immediately after BSS |
| Window B | `0x8012DDE8`, constant at `0x8001009C` |
| Mode switch | `FUN_80011370`, `switch (0x8005E39C)`; entry point stored to `0x8005E384` |
| Relocation | **none** — disc bytes are the pristine loaded image (member 11 verified byte-identical to RAM across its whole code region) |

Members `MG1`–`MG5` are the five festival minigames, mutually exclusive in
window A — invisible to capture-driven workflows unless every festival is played.

### Packaging a macOS .app

```sh
sh tools/regen.sh && sh tools/bake_overlays.sh && \
sh tools/compile_static_overlays.sh && sh build.sh && sh tools/make_app.sh
```

Produces `dist/<name>.app` (~266 MB), self-contained — the binary links only
system frameworks. `dist/` is gitignored: the bundle embeds the disc image and
is a personal backup, never distributed.

**Path rules that are easy to get wrong, both verified the hard way:**

| Asset | Resolved relative to | Must live in |
|---|---|---|
| `bios/`, `mods/`, `cache/` | the **executable** | `Contents/MacOS/` |
| `disc`, `exe` in `game.toml` | **`game.toml`'s own directory** (`config_loader.cpp:1104` makes them absolute at load) | `Contents/Resources/`, as bare filenames |

A `../Resources/` prefix on `disc` looks right and fails — it resolves to
`Resources/../Resources/`, which does not validate.

The bundle executable is a launcher script, because the runtime has no `~` or
env expansion for `memcard_dir`. It redirects saves (`--memcard-dir`) and the
overlay capture store (`PSX_OVERLAY_CAPTURES`, honored at `main.cpp:2338`) to
`~/Library/Application Support/Harvest Moon BTN`.

**Install somewhere writable.** `mod_runtime_initialize` hardcodes
`exe_dir/mods` (`main.cpp:6030`) and creates it at startup; a read-only install
dies with `cannot create mods directory`. `/Applications` and `~/Applications`
are both fine.

### Capture-driven fallback (manual on macOS — in-session autocompile is Windows-only)

```sh
# 1. play into the area you want covered, then:
python3 psxrecomp/tools/debug_client.py overlay_capture_dump

# 2. compile the captures
python3 psxrecomp/tools/compile_overlays.py \
  --captures build/overlay_captures.json --game-toml game.toml \
  --recompiler psxrecomp/recompiler/build/psxrecomp-game \
  --runtime-include psxrecomp/runtime/include --out-dir build/cache --jobs 8

# 3. persist shards out of the disposable build tree  <-- do not skip
sh tools/save_cache.sh

# 4. restart — shards go native on the next launch, never mid-session
```

`cache/` (root) is durable; `build/cache` is what the runtime reads.
`build.sh` copies in, `save_cache.sh` copies out.

### Debug server

`python3 psxrecomp/tools/debug_client.py <cmd>` on port 4370. Useful:
`ping`, `get_registers`, `gpu_state`, `dispatch_stats`, `dirty_ram_stats`,
`overlay_loader_status`, `wtrace_range`/`wtrace_dump`, `cdrom_sector_history`,
`screenshot <path>` (**positional path** — `path=` is taken literally and
creates a file named `path=...`).

### Reverse engineering the game's rendering

Two documents carry everything learned so far. **Read them before touching any
draw path** — they encode several days of dead ends.

- **`docs/RENDERING.md`** — the game's draw paths: which function draws the
  ground, the sprites, the menu wallpaper; the two screen-bounds culls in the
  3D renderer and their exact constants; the chunk frustum test; dead code to
  avoid; packet double-buffering; GTE opcode reference.
- **`docs/METHOD.md`** — how to find "which function drew this pixel" in three
  steps, plus the measurement discipline. Use it first, not last.

The short version of the method, because it is the highest-value thing here:

```
pixel -> which primitive covers it (rasterise a gpu_frame_dump)
      -> its packet address (src)
      -> who writes that address (wtrace on that exact range)
      -> the writer's ra - 8 is the call site
```

Hard-won rules:

- A packet buffer address does NOT identify its producer — the game
  double-buffers, and the same range is written by different renderers in
  gameplay vs cutscenes. Trace the specific packet.
- A renderer may contain MORE THAN ONE cull. `FUN_8001C37C` has two bounds
  helpers of different arity; patching one, seeing no change and concluding the
  renderer was innocent was the single most expensive error in this project.
  Enumerate every `jal` in the function first.
- Scan instruction encodings, not just decompiler output. Ghidra had not
  analysed the region holding one of the culls and reported "no function" there.
- Measure with numbers (black fraction, per-column primitive coverage, primitive
  count). Several plausible fixes changed the image by exactly zero pixels.

### Ghidra

Project `~/ghidra-projects/HarvestMoonBTN`, program `SLUS_011.15.text.bin`
imported as **Raw Binary**, `MIPS:LE:32:default`, base `0x80010000`. Import the
**headerless** `.text.bin`, never the full EXE.

MCP server `ghidra-psx` (bethington/ghidra-mcp v6.0.0) gives live
`decompile_function`, `get_xrefs_to`, `search_instructions`, etc. Ghidra must be
open with the program loaded. **Do not use LaurieWired/GhidraMCP** — its latest
release declares `ghidraVersion=11.3.2` and will not load on Ghidra 12.x.

The plugin's HTTP bridge listens on **port 8089**, and works even when the MCP
tools are not registered in the session — which they often aren't. Drive it
directly:

```sh
curl -s "http://127.0.0.1:8089/check_connection"
curl -s "http://127.0.0.1:8089/decompile_function_by_address?address=0x80011370"
curl -s "http://127.0.0.1:8089/get_xrefs_to?address=0x80048b40&limit=25"
```

Refresh seeds (Ghidra project must be **closed** — it holds an exclusive lock):

```sh
/opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless \
  ~/ghidra-projects HarvestMoonBTN -process "SLUS_011.15.text.bin" \
  -noanalysis -scriptPath ~/ghidra_scripts -postScript ExportFunctionSeeds.java seeds
```

---

## 4. Status

| | |
|---|---|
| Boots to title, reaches gameplay, audio works | yes |
| `dispatch_stats.miss_total` | **0** across a full play session |
| `dirty_ram_stats.aborts` | **0** |
| Overlay coverage | **static, complete** — 13 members / 848 KB extracted from disc |
| Overlay shards compiled | **35**; `invalidations` 0, `stale_blocked` 0 |
| Overlay funcs registered / regions | 51 / 5 |
| `dispatch_interp_fallback` at title | 75,160 → **615** after static extraction |
| Native widescreen (16:9) | **working** — 426×240, real FOV, 0.000 black across the frame (branch `feat/native-widescreen`) |
| MDEC / FMV | **completely untested** — `mdec_decode_count` has never left 0 |
| Beetle oracle | cloned at pinned `5759277b` in the framework tree, **not built** |

---

## 5. Known issues and traps

- **`[recompiler] bios_config` is ignored on the overlay compile path.**
  `bios_profile_path` is populated only from `--config` (`main_psx.cpp:209`) but
  `compile_overlays.py` passes `--ws-config`. It falls back to searching for
  `<subdir>/bios/SCPH1001.toml` relative to `game.toml` — which works here
  **only because** the framework is at `./psxrecomp`. Upstream fix worth a PR.
- The framework's `ctest` is **40/41**: `mod_load_acceleration` asserts a stale
  doc string (`"2..16"`) that commit `f44f56b` widened to
  `1..PSX_MOD_LOAD_ACCEL_MAX`. Treat 40/41 as green.
- The built executable is named `Harvest_Moon__Back_to_Nature__Recompiled_`
  (from `WINDOW_TITLE`), though the CMake target is `psx-runtime`.
- Overlay tier logs "tcc tier active but no bundled toolchain" — harmless. gcc
  shards still load; in-session compiling is Windows-only regardless.
- No Vulkan SDK here, so that renderer is a software stub. OpenGL is the default.
- Keyboard: arrows = D-pad, X = ✕, S = ○, Z = □, A = △, Enter = Start,
  RShift = Select, Q/W = L1/R1.

---

## 6. Next threads

1. ~~**Static overlay extraction.**~~ **Done** — see §3 and `docs/SESSION-02.md`.
   Follow-ups it left open:
   - **Mode 15 loads member 11 into window B**, unlike every other reference to
     it, and records no entry point. Marked `unverified` in `seeds/overlays.json`
     and extracted anyway; it compiles to an empty shard, which is the framework
     correctly rejecting it. Decompile the mode-15 path to settle whether it
     relocates the member or is a game bug.
   - **Window B's extent is unknown** — only its base (`0x8012DDE8`) is proven.
   - ~~**`GAME_OVERLAY_STATIC_C`**~~ **Done** — `tools/bake_overlays.sh`. It does
     **not** remove the `cache/` round trip, though: shards also cover kernel
     regions (`0x00000000`, `0x0000D000`) that are not disc overlays and cannot
     be statically extracted. Baked-only measured 992K interpreter fallbacks at
     the title screen vs 5K with the cache present. Baking those kernel captures
     into the same `overlays_static.c` would finish the job.
   - Whether static extraction makes the capture path redundant enough to stop
     recording `overlay_captures.json` at runtime (`game.toml:44`).
2. **Build the Beetle oracle** — needed before any real divergence hunt.
   Patch with the three hooks in `psxrecomp/docs/beetle_*.patch`, build static,
   then compare port 4370 (ours) against 4380 (Beetle).
3. **Mods** — walk speed and similar constants via `[[recompiler.patch]]`
   (build-time) or a `.psxmod` package (runtime, toggleable). Both guard on
   `expected` bytes and fail closed. See `psxrecomp/docs/MOD_PACKAGES.md`.
4. **MDEC** — unproven; will matter if the game has real FMV.
