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

### Overlay loop (manual on macOS — in-session autocompile is Windows-only)

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

### Ghidra

Project `~/ghidra-projects/HarvestMoonBTN`, program `SLUS_011.15.text.bin`
imported as **Raw Binary**, `MIPS:LE:32:default`, base `0x80010000`. Import the
**headerless** `.text.bin`, never the full EXE.

MCP server `ghidra-psx` (bethington/ghidra-mcp v6.0.0) gives live
`decompile_function`, `get_xrefs_to`, `search_instructions`, etc. Ghidra must be
open with the program loaded. **Do not use LaurieWired/GhidraMCP** — its latest
release declares `ghidraVersion=11.3.2` and will not load on Ghidra 12.x.

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
| Overlay shards compiled | 4; `invalidations` 0, `stale_blocked` 0 |
| Interpreted instructions @ frame 5120 | 53.2M → **2.85M** after overlay compilation |
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

1. **Static overlay extraction (highest value).** Today overlay code is captured
   from live RAM, so coverage depends on where the player walked and every user
   must repeat it. If Harvest Moon has a readable overlay table (disc LBA → RAM
   address → size), that table could live in this repo as small factual metadata
   — like `seeds/` — and `regen.sh` would extract and compile **every** overlay
   from the user's own disc at build time. `GAME_OVERLAY_STATIC_C`
   (`psxrecomp/runtime/runtime.cmake:481`) already bakes overlay C into the
   binary. Result: 100% coverage on first build, no captures, no dumps, fully
   reproducible from disc + config. Start by tracing who writes into
   `0x800B7000` (`wtrace_range`) and decompiling that loader.
   Framework design notes: `psxrecomp/docs/AOT_OVERLAY_PLAN.md`.
2. **Build the Beetle oracle** — needed before any real divergence hunt.
   Patch with the three hooks in `psxrecomp/docs/beetle_*.patch`, build static,
   then compare port 4370 (ours) against 4380 (Beetle).
3. **Mods** — walk speed and similar constants via `[[recompiler.patch]]`
   (build-time) or a `.psxmod` package (runtime, toggleable). Both guard on
   `expected` bytes and fail closed. See `psxrecomp/docs/MOD_PACKAGES.md`.
4. **MDEC** — unproven; will matter if the game has real FMV.
