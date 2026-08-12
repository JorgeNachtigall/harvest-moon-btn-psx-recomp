# Session 03 — native widescreen: what is proven, and what is not

*2026-08-12. Branch `feat/native-widescreen`. Working notes, deliberately split
into measured facts and open questions, because several confident-sounding
conclusions in this session turned out to be wrong and were only caught by
measuring again.*

---

## Status

Native widescreen **works**: 426×240 internal at 16:9, real rendered field of
view (not a stretch), correct proportions, ~60 fps, `miss_total` 0.

Two defects remain, with very different levels of understanding.

---

## Measured facts

Everything in this section was observed directly. Numbers are reproducible from
savestate slot 1 (farm gameplay).

### Widescreen only engages with a gameplay classifier

`[video] aspect_ratio` alone does nothing visible. `gpu_state` reported
`mode: 2` (native-wide selected) alongside `game_mode: 0` and
`present_native_43: 1` — every frame classified full-2D and pillarboxed back to
4:3. Setting `[widescreen] gte_game_mode = true` is what makes the wide
compositor actually present. This was the whole difference between "nothing
happens" and "426×240".

### The colour band at the 4:3 seam is an OpenGL backend bug

A one-pixel step at exactly x=53 and x=373 — the 4:3 core boundaries:

```
x= 52  meanR= 77.2  |  x= 53  meanR= 92.3    (+15)
x=372  meanR= 81.4  |  x=373  meanR= 64.5    (-17)
```

The cause is a single primitive:

```
0x2a000014  0x0  0x140  0xf00000  0xf00140
```

a semi-transparent flat quad `(0,0)→(320,240)`, colour `0x14` red, drawn at
`ot=15`. It satisfies every condition of the full-screen fast path in
`gp0_exec_mono_quad` (`gpu.c:3045`), so `ws_expand_fullscreen_rect` widens it
correctly — and the **software renderer proves it**, producing a uniform tint
edge to edge (seam step −0.1 vs OpenGL's +15.0).

So the framework's logic is right and `gpu_gl_renderer.c` drops the expansion
for full-screen semi-transparent flat rects. This is a framework bug and belongs
in `psxrecomp`, not here.

Note: the software renderer is only a diagnostic. It also loses dialogue text
and renders colours flatter, so it is not a workaround.

### RETRACTED: "terrain in the margins is withheld, not absent"

An earlier version of this document recorded, as a measured fact, that world
columns reading 0.52/0.41/0.24 black while in the margin read 0.00 once the
camera brought them inside the 4:3 frame.

**That test was invalid.** It relied on a +60 px screen shift between the two
frames, estimated by image cross-correlation with a mean-absolute-difference of
63.5 -- a poor fit that should have been treated as a failed match. Matching
tile packets by texture/CLUT identity instead gives the true shift as **about
-45 px, in the opposite direction**, and not even a rigid translation (per-tile
ΔX spreads -40..-49, since the tiles are perspective-projected). The test
therefore compared unrelated screen columns and shows nothing.

What IS established about the gameplay tile path:

- The map tables at `0x80060614`-`0x80060928` (reached via the map descriptor at
  `0x8005F2B8`, fields +0x1C/+0x20/+0x24/+0x28/+0x2C) receive **zero writes**
  during gameplay. They are static per area, not rebuilt from the camera.
- The emitted set is nonetheless a **sliding window** over those tables. Between
  two frames with the camera moved: 87 tiles common, 8 dropped, **9 newly
  submitted -- 8 of them landing in the right margin**, the side the camera
  moved toward. So tiles can and do reach the margins.
- Per-frame primitive counts stay near-constant (289 / 284 / 284), consistent
  with a fixed-size window sliding rather than growing.
- Margin coverage is non-zero but thin (e.g. 12 primitives covering x=425
  against ~30 mid-frame), and black fraction tracks it inversely in every
  capture taken.

Whether that window's width is bound to the 4:3 frame -- and therefore whether
widening it would fill the margins -- is **not yet established**. Deciding it
requires locating the code that advances the window, which is inside
`FUN_80016280`'s emit loop or its selection of `param_5`/`param_6` (read from
map-descriptor bytes +4 and +5).

### Packet buffers alternate — buffer address does not identify a renderer

Two captures seconds apart in the same scene used `0x1D9–0x1DB` and
`0x1C2–0x1C4` respectively. Tracing writes to `0x1C2400–0x1C7400` during
gameplay found `0x800163xx`; the same range during a cutscene found
`0x8001D0xx`. So the game double-buffers its packet memory and the buffer
address says nothing about which builder produced the contents.

An earlier conclusion in this session — "the farm and the forest use different
rendering paths" — was drawn from exactly this confusion and is withdrawn.

### The cutscene world renderer is understood

Verified by tracing packet writes during a cutscene:

- `FUN_8001C0D4` walks a chunk list, calling `FUN_8001C1C0` per chunk (a
  four-plane frustum test against normals rebuilt each frame at `0x80061EA8` by
  `FUN_8001D348`; rejections are `bltz` at `0x8001C29C/2DC/31C`).
- Approved chunks go to `FUN_8001C37C`, which does `RTPT` + `NCLIP` and then
  asks `FUN_8001D21C` whether the projected triangle is on screen.
- `FUN_8001D21C` hardcodes the 4:3 width (`0x153 = 320 + 0x13`).

The two `[[widescreen.cull.keep]]` sites in `game.toml` disable that screen-X
test. Measured effect on the cutscene farm: right-margin black 0.493 → 0.481.

---

## Things tried that did nothing

Recorded so they are not retried. All measured, all no-ops here:

| attempt | result |
|---|---|
| `[widescreen.cull] auto_screen_x` | no change |
| `nw_backdrop` | no change (targets *backdrops*; the tint quad is a front overlay at ot=15) |
| `clear_reveal` | no change (margins are not stale VRAM) |
| `nw_textured_edges` | no change (keyed to a backdrop address range this game never sets) |
| `nw_full_mirror` (`gl_wide_fast on=0`, live) | no change to margins |
| Patching the chunk frustum test to always report visible | **no pixel change, cost frame rate** — reverted |

That last one is worth remembering: forcing every map chunk visible submitted
far more geometry (visible as a slowdown) and changed the rendered image by
literally zero pixels, because the extra chunks were all off-screen.

---

## Open questions

### The 4:3 bound is a literal constant -- and widening it works

The decisive insight came from observing the game, not the code: **things pop
into view the instant they touch the 4:3 edge**, which is visible directly
because the OpenGL tint seam marks that boundary. That is the signature of a
per-item test against the original 320-wide screen, not a frustum or a data
limit.

Acting on it produced the session's first real fix.

**VERIFIED -- menu wallpaper.** `FUN_800223D4` (0x800223D4) draws the tiled
menu background as a 24px grid, bounded to the original screen plus one tile:

```
s0 = -0xC                start X, one tile left of screen
s0 += 0x18               24px step
while (s0 < 0x158)       X bound = 344 = 320 + 24
while (a1 < 0x108)       Y bound = 264 = 240 + 24
```

Three `[[recompiler.patch]]` entries widen it by three tiles each side
(start -0xC -> -0x54, bound 0x158 -> 0x1A0). Confirmed in play: the wallpaper
now fills the widened frame. First attempt, no iteration.

This establishes the method for this game: find the constant encoding the 4:3
bound, verify its instruction word, widen it, and let the recompiler fail
closed on a mismatch.

**UNVERIFIED -- per-object right-edge cull.** At 0x80018238 an object's X is
loaded from `gp+0x228` and tested `slti v0,v0,0x141` (321 = 320+1); on failure
the code branches past the draw. There is no matching left-edge test, which
would neatly explain why the left margin has measured cleaner than the right
all session (0.075 vs 0.273 black). Widened 321 -> 374; the patch is live in
the generated C but produced no measurable change in the test scene, which has
few discrete objects near the right edge. Retest where objects sit at the edge.

Ghidra reports **no function** at 0x80018240 -- it never analysed that region,
which is why decompiler-driven searching could not have found it. Scanning
instruction encodings did.

### Which builder draws the gameplay ground?

**Identified: `FUN_80016280`** (0x80016280), reached as
`FUN_8001B118` -> `FUN_80015D1C` -> `FUN_80015E3C` -> `FUN_80016280`. Verified by
tracing writes to the exact packet addresses of the dominant `0x2C` quads
(`0x001D9B84`+, 40-byte stride): every writer PC is `0x800163xx`, with
`ra = 0x80015E68`.

An earlier note here said this function "is not the ground" because a frame holds
only ~10 `0x64` rects against ~123 `0x2C` quads. That reasoning was wrong: the
function writes **two** packet streams (`param_2` receives the `0x64` rects,
`param_3` the quads), so the low `0x64` count says nothing.

The two `andi ..., 0x3F` instructions in it are still NOT a 64-column tile ring --
they feed texture fields (`packet+0xC` = U coordinate, `packet+0xE` =
CLUT/texpage). No evidence of a 64-column ring exists.

Call-chain facts:

- `FUN_8001B118` calls with `(ot, &pktA, &pktB, 0x8005F2B8, 0xA0, 0x78)`. The
  `0xA0`/`0x78` are 160/120 -- the screen-centre offset added to every tile's X/Y
  (`packet+8 = tileX + 160 + base`), not a range bound.
- `FUN_80015D1C` and `FUN_80015E3C` are thin shims with no loop; `FUN_80015D1C`
  reads map-descriptor bytes +4/+5 and forwards them as `param_5`/`param_6`.
- All iteration is inside `FUN_80016280`, whose count comes from map data
  (`iVar9 = *psVar8`, via descriptor +0x20).

### Is the framework's `bg2d` tile-layer widening applicable?

**No, and this is now settled.** `bg2d` is a generic column-scroll widener that
rewrites three specific instruction shapes:

| site | expected opcode | meaning |
|---|---|---|
| `count_site` | `addiu`/`ori`, or `slti`/`sltiu` | literal column count / loop bound |
| `startcol_site` | `andi` | start tile-column mask |
| `startx_site` | `sra`, or `subu rd,zero,rt` | start screen X from scroll |

That is the classic scrolling-background shape. Harvest Moon's ground emitter
is not that shape: `FUN_80016280` loops on a count read from map data, with no
column-count immediate, no `andi` start-column mask and no scroll-derived
`sra`. There is nothing for `bg2d` to bind to.

### Option A (synchronised capture) -- tried and failed

`set_snapshot` + `read_frame_ram` does work: it returns coherent per-frame RAM
snapshots, and scratchpad addresses are safe (an earlier crash was specific to
`0x1F800300`). But snapshots are taken at a **fixed point each frame**, not
synchronised to a function's execution, so by capture time the render call stack
has unwound and been overwritten. Testing every RAM pointer across 384 bytes of
captured stack yielded only two descriptor-shaped candidates (0 and 1 tiles),
neither the ground. Without a capture point tied to the call -- which the debug
server does not offer for native code, `pc_break` being DuckStation-only -- this
approach cannot work.

### Savestates and the widescreen latch

Loading a savestate sometimes comes up 4:3. Widescreen is host-side state
latched once at game entry (`main.cpp:4055`, gated on
`fntrace_is_game_started()`); `ws_mode: 0` and `x_margin: 0` after such a load
mean `gpu_ws_configure` ran with a 4:3 aspect. Neither `savestate.c` nor `gpu.c`
serialises the widescreen mode, so this is a startup race, not a property of the
state file. Relaunching usually fixes it. Not chased further.

---

## Method note

Three separate hypotheses about the black margins were pursued to the point of a
full regen+rebuild before being falsified, twice by a measurement that already
existed in a dump taken earlier. The measurement that settles "culled vs not
authored" is cheap — per-column primitive coverage against per-column black
fraction — and should be run *first* next time, before any theory is acted on.
