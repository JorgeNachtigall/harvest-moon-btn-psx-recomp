# Session 01 — disc image to playable native build

*2026-08-09 → 2026-08-10. Narrative record of how this project was bootstrapped,
kept so the reasoning behind each decision survives. `CLAUDE.md` holds the
current state; this holds the story.*

## What happened, in order

1. **Framework verified on macOS arm64.** Built the recompiler (40/41 ctest —
   one stale upstream assertion), generated the OpenBIOS backend (650 functions,
   3911 dispatch entries), built and booted the BIOS-only runtime. Confirmed
   with a screenshot of OpenBIOS's rotating-cube shell and live TCP debug queries
   — pixels, not a clean link step.

2. **Disc identified.** `MODE2/2352`, single track. Boot record scan gave
   `cdrom:\SLUS_011.15` → serial **SLUS-01115**.

3. **EXE extracted.** The framework ships no extractor (it lives in game repos),
   so `tools/extract_psx_exe.py` was written: auto-detects sector layout, walks
   ISO9660, dumps the file, prints the PS-X EXE header. Validated two ways —
   `0x800` header + `0x4E800` text exactly matched the ISO directory length, and
   the entry point disassembled to a textbook BSS-clear loop.

4. **Ghidra.** Installed 12.1.2 (a Homebrew *formula*, not a cask — my first
   instruction was wrong). Imported the **headerless** text image as Raw Binary,
   `MIPS:LE:32:default`, base `0x80010000`. Disassembly at the entry point
   matched the predicted `lui/addiu/sw/sltu/bne` loop instruction for
   instruction, confirming base address and endianness before analyzing.

5. **946 functions** from auto-analysis, exported headlessly via a Java
   GhidraScript (Python failed — headless Ghidra has no PyGhidra without an
   extra pip launcher).

6. **The tail check that paid off.** Seeds stopped at `0x80048518` while text ran
   to `0x8005E800` — ~90 KB unaccounted for. Rather than assume it was data,
   scanned it: 1 `jr $ra` in the whole span vs 1136 in the code region, 24.7%
   zeros, 12.4% ASCII → data, confirmed. But the scan also found **39 words
   pointing into code, 8 of which were not known functions**. Every one sits
   immediately after a `jr $ra` — real functions, leaf-shaped with no prologue,
   reachable only through pointer tables. Invisible to both prologue heuristics
   and `jal` following. Seeds: 946 → **954**.

7. **First generation.** 1475 functions, 1474 dispatch entries, 681,560 lines of
   C, **0 skipped**, in 0.13 s. Spot-checked the emitted C: branch condition
   captured *before* the delay slot, delay slot executed unconditionally,
   interrupt check on the backward branch — faithful MIPS semantics.

8. **First boot: the title screen**, first attempt. Then town, mechanics,
   in-engine cutscenes, audio. `dispatch_stats.miss_total` **0**;
   `dirty_ram_stats.aborts` **0**.

9. **Overlays.** 783 M instructions were running interpreted. Enabled
   `overlay_cache`, dumped a capture (562 entries; the big region is ~1 MB at
   `0x800B7000` with 230 entry points), compiled it. Result: interpreted
   instructions at matched frame count **53.2M → 2.85M (18.7×)**, 92.6% of
   overlay dispatches native, 0 invalidations. This proved the overlay pipeline
   works on Apple Silicon, which was previously unverified.

10. **This repo.** Extracted from the framework tree into a standalone game repo
    with the framework as a pinned submodule.

## Decisions worth remembering

- **`discovery = "whole-image"`** over `"reachable"`. With 954 evidence-backed
  seeds and a proven code/data boundary, the broader sweep was safe; it found
  521 functions beyond the seeds and produced zero dispatch misses.
- **OpenBIOS, not retail.** No SCPH1001 dump on this machine. `bios_config`
  points at OpenBIOS and `PSXRECOMP_BIOS_STEMS` is pinned to it, since the
  default stem list expects a retail backend that would fail configure.
- **Standalone repo over living in the framework tree.** This wasn't cosmetic —
  it fixed two real path bugs. The runtime resolves `disc` against the exe dir
  while the recompiler resolves against the project root; nesting the game made
  those disagree, forcing an explicit `--disc`. Separately, overlay compilation
  needed a `bios → ../../bios` symlink to satisfy the recompiler's profile
  search. Both disappear when the framework sits at `./psxrecomp`. Verified by
  deleting the symlink and rebuilding.
- **Real git submodule over a symlinked framework.** The framework's `.git` is
  only 38 MB and the working tree was clean at `483a0d4`, so a proper pinned
  submodule cost little and keeps the repo genuinely clonable.

## Mistakes made here, so they aren't repeated

- Told the user `brew install --cask ghidra`; it's a formula.
- Read a `pgrep` result with `\|` in an extended regex as "Ghidra isn't running"
  and called a live project lock stale. Nearly deleted a lock file out from under
  a running Ghidra. `ps aux` caught it.
- Flagged a black screen after the title as the first bug to hunt. It was a
  transition; the game was loading normally.
- Guessed a decoder warning was GTE. It was data misread as code
  (`0x00200000`, an invalid `SLL` encoding).
- Copied overlay captures to the repo root where nothing reads them, and left
  newly compiled shards only in the disposable `build/` tree. Both fixed —
  `captures/` and `tools/save_cache.sh`.

## Open threads

See `CLAUDE.md` §6. The highest-value one is **static overlay extraction**: if
Harvest Moon's overlay table can be read, this repo could ship that table as
factual metadata and every user would get 100% native coverage from their own
disc at build time — no captures, no dumps, no dependence on where anyone
walked.
