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

> ### Editing `game.toml` silently invalidates the overlay cache
>
> The cache directory is named `cg<ver>_<emitter>_gc<CONFIG HASH>`, and that
> config hash covers `[recompiler]` **and** `[widescreen]`. Change any of it and
> the runtime looks for a directory that does not exist, finds no shards, and
> runs all ~848 KB of overlay code in the MIPS interpreter. **There is no error
> message.** The game stays correct and gets several times slower.
>
> After any `game.toml` edit:
>
> ```sh
> sh tools/regen.sh && sh build.sh && sh tools/compile_static_overlays.sh
> ```
>
> Confirm it took, via `overlay_loader_status`: `registered` should be ~942 and
> `dispatch_native` must be non-zero. `dispatch_native: 0` with a large
> `dispatch_interp_fallback` means the cache is orphaned.
>
> This cost an entire debugging session: six config edits in a row were measured
> on interpreter-only builds, which produced a phantom "the farm is too heavy"
> crash and a stream of meaningless performance numbers.

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

**Overlay function seeds — why coverage is now ~95% native.** Shards are
compiled by walking outward from seeds. With only the mode-switch entry points
and header pointer tables (a few hundred), everything reached through an
indirect call was never discovered and ran on the MIPS interpreter: **85% of
overlay dispatches**. `seeds/overlay_functions.json` adds **3279** function
starts recovered by Ghidra auto-analysis of each member's raw image, imported at
its real load address. Result:

| | before | after |
|---|---|---|
| registered overlay funcs | 942 | **1399** |
| `dispatch_native` | 113,817 | **1,599,432** |
| `dispatch_interp_fallback` | 648,441 | **84,225** |
| interpreted | 85% | **5%** |

Addresses only, so it commits like `seeds/functions.txt`, and
`tools/extract_overlays.py` consumes it automatically — **users never need
Ghidra**. Regenerate it only if the seed map changes:
`sh tools/overlay_seeds.sh` (Ghidra must be CLOSED), then
`python3 tools/merge_overlay_seeds.py ...`.

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

- **`docs/FRUSTUM.md`** — **the chunk frustum cone: SOLVED.** Widening the two
  horizontal half-planes fills the 16:9 edge wedges. **Shipped at `d = 8`** —
  the smallest value that closes them. The knob COSTS FRAME RATE in heavy
  scenes (`d = 40` drops the graveyard 30 -> 20 FPS); tune it with
  `tools/frustum_d.py` in the heaviest area you can reach, never in town.
  One tunable, the recipe to recompute the two patch words, how to retune it
  LIVE with no rebuild (`write_ram`), the measurement protocol, the cost budget,
  and three disproved mechanisms not to re-chase. Read this before touching
  anything frustum-shaped. It also carries the full RAM map and the proof that
  no free block exists in the 2 MB — do not go looking again.
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
| Native widescreen (16:9) | **working** — 426×240, real FOV; edge wedges fixed by widening the frustum cone to **`d = 8`** (`docs/FRUSTUM.md`), chosen on screen as the smallest value that closes them. 29.97 game FPS at both `d = 0` and `d = 8` on the graveyard save; `d = 40` drops it to 19.89 (branch `feat/native-widescreen`) |
| Widescreen stays on in the PAUSE MENU | **fixed** — `gte_game_mode` alone classifies gameplay by GTE vertex count and gives up 45 frames after the last 3D frame, so any long full-2D screen pillarboxed back to 4:3 (and silently wasted the menu-wallpaper widening). `[widescreen] gameplay_state_addr/values` now gates on the game's own mode word at `0x8005E39C`: **`0x02` gameplay AND pause menu → wide, `0x0D` title → wide (see the next row), everything else → 4:3.** Values = every mode loading member 11 into window A, plus `0x0D`. The RAM gate supersedes the GTE heuristic entirely (`gpu.c:ws_game_mode`) |
| Boot path: title → memory card → save | **working** — pressing Start at the title used to kill the guest (`DISPATCH FATAL`, §5); the packet-buffer save/restore was copying twice the shared buffer's size into it. Fixed by `pktbuf-save-restore-len-a/b` in `game.toml` |
| MEMORY CARD / save-select in 16:9 | **working** — mode `0x08` added to `gameplay_state_values`; nothing else needed. Its wallpaper is the same `FUN_800223D4` 24 px grid as the pause menu, already widened 4 tiles/side, so it fills the frame and keeps the seamless diagonal scroll (measured on this screen: 23 columns, x = −111..417 step 24, 23 % 4 == 3) |
| TITLE SCREEN in 16:9 | **working** — `0x0D` added to `gameplay_state_values`, plus `[widescreen] nw_backdrop_rects`. The title is all 2D (~124 GP0 cmds/frame): its grass field is a 320×240 image blitted as two opaque `0x64` rects at OT 26, and a sprite cannot scale, so the reveal margins showed only the semi-transparent scrolling overlay (same texture, grey CLUT `0x7F14`) over the black clear — the "grey streaks". The new flag stretches full-display-height textured rects, mirror-side only, so the grass fills the frame while the logo, characters and the scrolling PRESS START BUTTON keep their authored size. Audited: gate matches 0 rects in gameplay/pause/map/demo. `docs/RENDERING.md` §6 |
| Pause-menu wallpaper scroll wraps seamlessly | **fixed** — the tiled background drifts diagonally by `s3 = (frames/4) % 24` and snaps back every 24 px; the snap is invisible only if the 4-variant tile pattern survives a one-tile diagonal shift, which requires **columns per row ≡ 3 (mod 4)**. Stock is 15 ✅; widening by 3 tiles/side made it 21 ✗ and the "endless" scroll visibly reset every ~3.2 s. Now widened by **4** tiles/side → 23 ✅, and since 4 ≡ 0 (mod 4) the 4:3 centre is also phase-identical to stock. **The grid may only ever be widened in whole multiples of 4 tiles per side.** `docs/RENDERING.md` §5 |
| Full-screen tint vs the 16:9 margins | **fixed** in the framework — the margins used to render a different colour from the 4:3 centre (ΔG −24, ΔB −40, ΔR 0). `docs/RENDERING.md` §8 |
| Frustum `d` is NOT free | it buys geometry with frame rate, and the cost is invisible in light scenes. Tune live with `python3 tools/frustum_d.py` (needs a build with the two cone patches removed), **in the heaviest area you can reach**. The game also rewrites the angle RAM back to stock on its own — the tool holds the value; what performs that rewrite is still unidentified |
| Game frame rate vs VSYNC | **they are different numbers and the OSD shows both.** The runtime presents at every simulated vblank, so the present cadence is pinned at 60 Hz regardless of what the game does. The rate a player perceives is the display-area flip rate (GP1(05h) changing), counted in `gpu.c:gp1_display_area_start`. This game runs at **30 FPS** in town and was measured at **20 FPS** (3 vblanks/frame) in a denser area, at BOTH `d = 0` and `d = 60`. `frame_perf` reports `game_fps`, `vsync_hz`, `game_frames` |
| Primitive packet buffer | **192,000 B**, shared by both render contexts instead of 2 × 96,000 double-buffered — linked-list DMA is synchronous here (`runtime/src/dma.c:700`), so the second buffer bought nothing. This is what makes `d = 60` safe: 104.7% occupancy → 52.4%. Rationale + the 26 patches: `game.toml`, "PACKET BUFFER" |
| Frame-stats overlay | **off by default — press Ctrl+Y in-game to show it.** Line 1 = `game_fps` + `VSYNC` (these differ — read the first one), line 2 = frame-ms avg/max + prims. Start a session with it up via `PSX_OSD=1 sh run.sh`, or flip it remotely with `debug_client.py osd enable=1`. Timing accumulates while hidden, so it shows real numbers immediately |
| `window_capture` | new TCP command — reads back the DEFAULT framebuffer at swap, i.e. what is really on screen. `screenshot` (raw VRAM) and `screenshot_hires` (compositor surface) are both blind to GPU-side overlays |
| MDEC / FMV | **completely untested** — `mdec_decode_count` has never left 0 |
| Beetle oracle | cloned at pinned `5759277b` in the framework tree, **not built** |

---

## 5. Known issues and traps

- **A `[[recompiler.patch]]` that changes a SIZE can break code you never
  looked at.** The packet-buffer patch (96,000 → 192,000, §4) set `ctx+0x11C`,
  and `FUN_800128DC` — the routine that parks packet RAM in overlay window B
  while a front-end overlay loads — copies `ctx[0x11C] << 1` bytes, because
  stock had TWO contiguous 96,000-byte buffers. With one shared 192,000-byte
  buffer that became a 384,000-byte copy into a 192,000-byte region: it ran off
  the top of RAM, wrapped (`& 0x1FFFFF`) into **kernel code** at `0x3D00-0x4010`
  and the next kernel dispatch jumped into the wreckage —
  `DISPATCH FATAL: misaligned target 0x170DAFB3`. Symptom: press Start at the
  title and the game died before the memory-card screen. **Fixed** by the
  `pktbuf-save-restore-len-*` patches (`sll a2,v1,1` → `sll a2,v1,0`); those two
  sites are the ONLY readers of `ctx+0x11C` in the whole text image. The lesson:
  after changing a size constant, scan for every *reader* of the field, not just
  the writers — `<< 1` on a length is a layout assumption in disguise.
- **`.pst` save states snapshot RAM, so they snapshot the render contexts too.**
  A state taken before the packet-buffer change still describes two 96,000-byte
  buffers, and the patched init (`FUN_80012598`) never runs again after a load —
  so measurements taken on an old state describe the OLD layout, and `d = 60`
  would still overrun on it. Migrate once with
  `python3 tools/migrate_savestate_pktbuf.py build/state_*.pst` (writes a
  `.pre-pktbuf` backup, refuses to touch anything it does not recognise). Normal
  play — boot to memory card — needs none of this. The general lesson: **a save
  state bypasses every `[[recompiler.patch]]` whose effect was already baked
  into RAM at capture time.** Code patches still apply; data written by patched
  code before the snapshot does not.
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
- Keyboard: **Ctrl+Y = show/hide the frame-stats overlay.** F1-F12 load save
  state 0-11, Shift+F1-F12 save; Alt+Enter or Cmd/Ctrl+F fullscreen; Ctrl+C
  forces a CD reinsert. Pad: arrows = D-pad, X = ✕, S = ○, Z = □, A = △, Enter = Start,
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
