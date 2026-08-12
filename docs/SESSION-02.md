# Session 02 — overlays, from capture-and-hope to disc extraction

*2026-08-11 → 2026-08-12. Narrative record of how the overlay system was
recovered and turned into a build step. `CLAUDE.md` holds the current state;
this holds the story.*

## The problem

Session 01 left overlays working but unreproducible. Overlay code was captured
from live RAM, so coverage depended on where the player happened to walk, every
user had to repeat the capture loop, and nobody could tell how much of the game
was still on the interpreter. Four shards existed. The real total was unknown.

Worth being precise about what was and wasn't broken: uncaptured overlays still
ran correctly, on the MIPS interpreter. This was never a correctness gap. It was
an optimization that couldn't be shipped, reproduced, or measured.

## What happened, in order

1. **Boot-time write trace on the overlay window.** `PSX_WTRACE_BOOT` retains
   the first writes to a range from guest instruction zero, which beats querying
   the live ring — the first overlay load is long gone by the time you connect.
   Tracing `0x000B7000..0x000B7100` produced two writers: `FUN_8003df3c`, which
   turned out to be plain `memset`, and a cluster in the CD command queue. Both
   dead ends, but both in *already recompiled game text*, which meant the loader
   was reachable statically and the trace had done its job.

2. **The disc, read directly.** The ISO directory has only 12 entries: the game
   is one archive, `A_FILE.BIN` (133,935,104 bytes), beside a 132-byte
   `A_FILE.HDT`. 132 bytes is 33 little-endian u32s — monotonic, `0x800`-aligned,
   last entry exactly equal to `A_FILE.BIN`'s size. A sentinel-terminated offset
   table, 32 members.

3. **Correlating CD reads against it.** The sector history from a boot showed a
   236-sector run starting at LBA 59503. Converted to an archive offset that is
   `HDT[11]` exactly, and its length is `HDT[12] - HDT[11]` exactly. One member,
   read whole, in one shot.

4. **Proof by byte comparison.** Extracting member 11 from the disc and
   searching for it inside the 1 MB RAM capture located it at `0x800B7E20` with
   **482,606 of 483,328 bytes identical**. All 722 differences lie past file
   offset `0x06B168`, in trailing data mutated at runtime; the entire code
   region matches exactly. That settled two questions at once — where overlays
   load, and that **no load-time relocation is applied**, so disc bytes are the
   pristine loaded image and are in fact cleaner than a RAM capture.

5. **The loader, decompiled.** Ghidra's bridge was up on port 8089 (the MCP
   tools weren't registered in the session, so it was driven over HTTP
   directly). `FUN_800147bc` reads the HDT, scatters its offsets into a static
   33-record table at `0x80048B40` — where the *other* fields turned out to hold
   ASCII paths, giving every member a name — and resolves the archive's base LBA
   via `CdSearchFile`. `FUN_800145f0(start, end, dest, dest)` is the load
   primitive. The destination is a caller argument, always one of two constants:

   ```
   80010098 = 0x800B7E20   window A   (immediately after BSS)
   8001009C = 0x8012DDE8   window B
   ```

   `0x800B7E20` was already known from step 4. Two independent methods, same
   answer.

6. **The map.** `FUN_80011370`, the main loop, is a `switch` on the game mode
   that pairs a member with a window and an entry point. Harvesting its 21 call
   sites gave 13 distinct overlays, 848 KB — including `MG1`–`MG5`, the five
   festival minigames, which share window A and would never appear in captures
   unless someone played every festival.

7. **Turned into a build step.** `seeds/overlays.json` records the mapping;
   `tools/extract_overlays.py` joins it to the user's disc and emits a file in
   the framework's own captures format, so `compile_overlays.py` consumes it
   unchanged. One contract had to be met on the way — `static_dispatch_entry_pcs`
   must be a subset of `dispatch_entry_pcs`, the first carrying provenance and
   the second the proof.

## Result

| | before | after |
|---|---|---|
| Overlay shards | 4 | **35** |
| Registered overlay functions | 19 | **51** |
| Regions loaded | 3 | **5** |
| `dispatch_interp_fallback` at title | 75,160 | **615** |
| Coverage depends on | where the player walked | the disc |

`miss_total` 0, `invalidations` 0, `stale_blocked` 0, `aborts` 0. Those zeros
are the real confirmation: the runtime CRC-checks every shard against live RAM
before going native, so zero invalidations means the statically extracted bytes
and load addresses match what the game actually loads.

## Decisions worth remembering

- **Metadata, not content.** `seeds/overlays.json` holds indices, window bases,
  and entry points — facts *about* where content lives, never content. The bytes
  come from the user's own disc at build time, so the repo's legal position is
  unchanged from `seeds/functions.txt`.

- **The extractor re-derives and cross-checks.** Archive layout, window
  constants, and member names are read back from the user's own executable and
  disc, and any mismatch against the seed file is a hard error. A wrong disc or
  a changed game fails loudly instead of emitting a plausible lie.

- **No framework changes.** Emitting the framework's existing captures format
  kept this entirely in the game repo, where game-specific work belongs.

## Loose ends

- **Mode 15 loads member 11 into window B**, unlike every other reference to it,
  and records no entry point. Extracted anyway and marked `unverified` — the
  runtime's CRC gate makes a wrong shard dead weight, never a correctness risk.
  It compiled to an empty shard, which is the framework correctly rejecting it.
  Not yet chased.
- **Member 31 is named `NOTHING`** in the record table but is a real 4 KB
  overlay with a real entry point.
- **Window B's extent is unmeasured.** Window A is the ~1 MB region the runtime
  already tracks; B is only known by its base.
- **MDEC/FMV still untested.** The disc has four `.XA` streams under `/STR/`.
