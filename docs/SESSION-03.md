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

**Unproven.** `[widescreen.bg2d]` widens a 2D scrolling tile layer by prepending
and appending columns from an already-streamed ring, which sounds like the right
shape for the gameplay ground. But it rests on the tile-ring premise above,
which did not survive checking. Do not configure it until the real builder and
its column-range logic are identified.

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
