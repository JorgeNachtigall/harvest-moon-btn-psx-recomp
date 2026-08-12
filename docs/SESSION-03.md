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

### Terrain in the margins is withheld, not absent

The decisive measurement. Take world columns that sit in the left margin in one
frame, move the camera, and find the same columns inside the frame:

| world column | in margin | same column inside frame |
|---|---|---|
| x=0 → 60 | 0.52 black | **0.00** |
| x=4 → 64 | 0.41 black | **0.00** |
| x=8 → 68 | 0.24 black | **0.00** |

Mean 0.086 black in the margin → **0.000** for identical terrain once inside the
4:3 frame. The tile data exists. It is withheld specifically while it lies in
the widened margin.

Corollary, from rasterising the submitted triangles of one frame: **93% of black
pixels are covered by no submitted primitive**. The geometry is not being
emitted, rather than emitted-and-clipped.

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

**Unknown.** Not yet identified, and two guesses have already failed:

- `FUN_80016280` emits `0x64` textured rectangles (the packet's command word is
  the literal `0x64808080`, 4 words + tag = the 0x14-byte packet). But a
  gameplay frame contains only ~10 `0x64` primitives against ~123 `0x2C`
  textured quads, so this is not the bulk of the ground.
- Its two `andi ..., 0x3F` instructions were briefly read as a 64-column tile
  ring. They are not: both feed texture fields (`packet+0xC` = U coordinate,
  `packet+0xE` = CLUT/texpage). There is no evidence of a 64-column ring.

The next step is to find the emitter of the dominant `0x2C` primitives
specifically, rather than sampling whichever function happens to be writing the
packet buffer when a trace is armed.

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
