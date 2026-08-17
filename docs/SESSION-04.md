# Session 04 — the front end goes 16:9, and the boot path stops crashing

*2026-08-16/17. Branch `feat/widescreen-title-menu`. What started as "make the
title screen widescreen too" turned into four screens and one crash that had
been sitting in the boot path unnoticed. As in Session 03, this is split into
what was measured, what was disproved, and what is still open — three
confident-sounding theories died here, each killed by one measurement.*

---

## Status

| screen | mode word `0x8005E39C` | result |
|---|---|---|
| Natsume logo → title | `0x0D` | **16:9**, grass fills the frame |
| Memory card / save select | `0x08` | **16:9**, scrolling wallpaper fills the frame |
| Map screen (Select) | `0x02` | **16:9**, margins painted the map's paper white |
| Diary / pause menu | `0x02` | unchanged — wallpaper fills, panel at authored width |
| Gameplay | `0x02` | unchanged |
| Press START at the title | `0x0D → 0x08` | **no longer crashes** |

Two framework keys were added (`nw_backdrop_rects`, `nw_backdrop_fill`); the
rest is `game.toml`.

---

## The crash: a size patch broke code nobody had read

**Symptom.** Boot, press Start at the title. The mode word goes `0x0D → 0x08`,
the screen stops swapping, and the runtime halts:

```
DISPATCH FATAL: misaligned target 0x170DAFB3
  $ra 0x80012954   $v0 0x801C2440   $a1 0x8012DDE8   $a2 0x0005DC00
  $a0 0x80203D8F                       <- past the 2 MB RAM top
  dispatch_tail: ... 0x3F00 0x3F0C 0x3F18 0x3F24 0x3F30 0x4000 ... 0x29CC
```

**Reading the registers is the whole diagnosis.** `$a0 & 0x1FFFFF = 0x3D8F`,
and the dispatch tail is executing kernel addresses `0x3D00–0x4010` — i.e. a
copy ran off the top of RAM, wrapped into kernel code, and the next kernel
dispatch jumped into the wreckage. `$a1` is overlay window B, `$a2` is 384,000,
`$v0` is the packet buffer base.

**Cause.** `FUN_800128DC` parks the primitive packet RAM in overlay window B
while a front-end overlay loads over window A, and copies it back after:

```
lw   v1, 0x11C(v0)     ; packet buffer LENGTH from the active render context
sll  a2, v1, 1         ; length * 2
lw   a0, 0x130(...)    ; packet base, 0x801C2440
jal  0x80041C24        ; BIOS memcpy(dst, src, bytes)
```

That `<< 1` encodes the **stock** layout: two contiguous 96,000-byte packet
buffers, one per render context, so "length × 2" was exactly both. The
packet-buffer work in `game.toml` (§ "PACKET BUFFER") made the two contexts
share one 192,000-byte buffer and set `ctx+0x11C = 0x2EE00` — so the same
expression asked for 384,000 bytes out of a 192,000-byte region.

**Fix.** `sll a2,v1,1` → `sll a2,v1,0` at `0x80012914` (restore) and
`0x80012994` (save): copy one buffer's length, which is the same
`0x801C2440..0x801F1240` bytes the two stock buffers occupied. Patches
`pktbuf-save-restore-len-a/b`.

**The generalisable part.** After changing a size constant, scan for every
*reader* of the field, not just the writers. Here that was one grep — every
load/store with immediate `0x11C` in the 0x4E800 text image — and it returned
exactly two instructions, both in this function. `<< 1` on a length is a layout
assumption in disguise.

**Bisected before blaming anything.** The crash surfaced during the widescreen
work, so it was rebuilt with the framework changes stashed and the stock
`game.toml`: identical signature. Only then was it attributed to the packet
buffer.

---

## The title screen is not the 3D scene it looks like

Full anatomy in `RENDERING.md` §6. The short version: a settled title frame is
**~124 GP0 commands, all 2D**.

| OT | layer |
|---|---|
| — | `0x02` black fill |
| 26 | grass backdrop: two opaque `0x64` rects, `256×240` + `64×240`, CLUT `0x7F54` |
| 27 | 36 semi-transparent `0x66` rects — the SAME texture under the grey CLUT `0x7F14`, tiled 3×3 and drifting |
| 28 | plants, horse, boy, dog — 14 `0x2C` quads |
| 29 | logo `256×136`, plus the PRESS START / copyright strips |

Decoded straight out of VRAM under CLUT `0x7F54`, the ot-26 image is **plain
grass** — no logo, no text, no characters. Everything readable is a separate
prim drawn on top. That is why stretching the backdrop is invisible and the
logo stays pixel-correct.

`PRESS START BUTTON` scrolls horizontally on purpose. Catching it half off the
frame edge is the effect, not a bug — an hour went into "fixing" that before
the user pointed it out.

**Fix:** `0x0D` added to `gameplay_state_values`, plus `[widescreen]
nw_backdrop_rects`, which stretches full-display-height textured rects — and
only those — into the wide frame, mirror-side only.

---

## The three theories that died

### "The grey margins are a CLUT / colour bug in the mirror"

The margins came up **exactly `R=G=B`** while the 4:3 centre was green. Exact
greys look like a palette that was lost somewhere in the wide mirror, and the
software renderer showed the same thing, which seemed to place the bug in
shared `gpu.c` code rather than a backend.

**Killed by:** `ws_nw on=0` (squash mode) put the wider FOV inside the
canonical 320-wide buffer, and its edges were ordinary green grass. The same
geometry renders correctly; nothing was losing a palette. The greys were the
scrolling overlay layer (grey CLUT `0x7F14`) over the black clear, with the
backdrop simply absent.

### "Something is drawing the margins wrong"

**Killed by:** rasterising the frame dump. Point tests at margin coordinates
matched **zero** primitives. Nothing was being mis-drawn; something was missing.
`docs/METHOD.md`'s pixel → primitive → writer chain, run in reverse.

### "The stale-margin theory"

Margins looked like frozen ghosts of earlier frames. **Killed by** diffing two
`wide_full` dumps seconds apart: 8,047 margin pixels changed vs 1,016 identical.
They were being repainted every frame — by the overlay layer.

---

## Things tried that were wrong in an instructive way

- **`ws_dbg_stretch mode=6`** (stretch every textured prim) and **`[widescreen]
  nw_phase_backdrop`** both filled the title's margins with grass — and
  duplicated the horse, dog, flowers and text into them. The GL fast path
  splices the canonical centre in at present, so a stretched prim contributes
  only its margin part: the original stays put in the centre and a second copy
  appears in the margin. Useful as proof of concept, unusable as a fix. The
  lesson: stretch the backdrop layer, never the frame.
- **`[widescreen] nw_backdrop` on the map screen** stretched the panel *behind*
  the map — a backing layer the player never sees in 4:3 — putting cream bars
  either side of a white map.
- **The first margin fill whited out the pause/diary menus.** Two mistakes at
  once, and both are now rules in the code:
  1. it reused the stretch detector's 24 px edge slack, which matches *window
     panels* (the pause menu's is x 18..302 of 320) — a backdrop runs to the
     frame edge, so the fill demands 8 px on both sides (the map's panel is
     2..318);
  2. it painted where the panel is drawn, but the pause menu draws its wallpaper
     grid (OT 34) **before** its panel (OT 35), so the fill erased margin
     content the screen had already produced. The fill now arms a latch and
     paints at the framebuffer **clear**, underneath everything.

> **The reveal margins are shared state that any layer can overwrite.** *When*
> something paints them matters as much as *what*. The clear is the safe slot;
> anything later fights the game's own draw order.

---

## What shipped

### `game.toml`

- `gameplay_state_values` gains `0x08` (memory card / save select) and `0x0D`
  (logo → title). Not part of the overlay codegen hash — takes effect on the
  next launch, no rebuild.
- `nw_backdrop_rects = true` — the title's grass.
- `nw_backdrop = false`, `nw_backdrop_fill = "0xFFFFFF"` — the map screen's
  paper white. Every full-width quad this game draws is a window panel, so the
  stretch stays off.
- `pktbuf-save-restore-len-a/b` — the crash. **Instruction patches ARE hashed:
  this one needs the full three-step regen.**

### Framework (`psxrecomp`)

Two opt-in `[widescreen]` keys, both mirror-side only (canonical 4:3 untouched),
both inert when unset:

- **`nw_backdrop_rects`** — a 2D screen that paints its background as textured
  RECTANGLES spanning the full display height (one per texture page, laid side
  by side) has nothing to reveal in the margins, because a PS1 sprite cannot
  scale. Stretch that layer, and only that layer.
- **`nw_backdrop_fill = "0xRRGGBB"`** — for a screen whose backdrop *material*
  continues past the frame (paper, cloud, sky) but whose art must not be
  touched: paint the margins that colour, full bleed only, at the clear.

### Audit method for both keys

Dump every candidate prim per screen and count the matches. For
`nw_backdrop_rects` (rects with `y <= 0 && y+h >= 240`): title 2/frame,
gameplay 0/1530, pause menu 0/65, map 0/284, attract demo 0. Only the title
matches. Repeat this before trusting any per-prim gate.

---

## Screens and how to reach them

| save state | screen |
|---|---|
| slot 0 | map screen (Select) |
| slot 1 | diary / pause menu |
| slot 2 | whatever the last debugging session parked there |

The title has to be reached by booting: mode `0x0D` lasts ~72 s from boot
(logo ≈ 25 s, then the title, then the attract demo takes over). Waiting on the
mode word alone is not enough — `0x0D` covers the Natsume logo too. Poll for the
title's own backdrop rect (a `0x64` with CLUT `0x7F54`) instead;
`scratchpad/shot_title.py` in this session did exactly that.

`set_input` drives menus but is unreliable at ~0.5 s holds; ~0.8–1.2 s presses
landed consistently. The memory-card screen ignored Cross entirely in testing.

---

## Open

- **No end-to-end save load.** `build/card1.mcd` has no diary on it — the card
  screen reports "No loadable diary in MEMORY CARD slot 1" — so boot → card →
  save → gameplay has not been walked once. Everything downstream of the card
  screen is untested.
- **The map screen's right edge is not always white.** Canonical x 0..8 is pure
  white on every scanline sampled, but at some rows the map's water reaches
  x=319. The fill is flat white, not an edge extend, so if a row ever looks like
  it cuts off hard, that is where to look.
- **Window B's extent is still unproven** (Session 02's open thread). The crash
  landed in code that copies 384,000 bytes into it and would have overflowed a
  smaller window; the fix removed the pressure without answering the question.
- **Mode `0x08` renders wide but nothing else about it was audited** — only the
  card-select screen was seen. Later screens in that flow may have their own
  4:3 assumptions.
