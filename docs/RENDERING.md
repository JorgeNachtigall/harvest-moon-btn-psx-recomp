# Harvest Moon: Back to Nature — rendering architecture

Map of the game's draw paths, recovered by reverse engineering. Every address
here was verified against the binary or observed at runtime; anything uncertain
is labelled. `docs/METHOD.md` describes the technique used to find it, which is
reusable for the paths still unexplored.

Addresses are guest RAM in the main executable (`0x80010000`–`0x80048B08`).

---

## 1. Overview

| path | function | what it draws | screen-bounds cull |
|---|---|---|---|
| 3D world | `FUN_8001C37C` | ground, terrain, scenery geometry | `FUN_8001D21C` (3-vert) + `FUN_8001D2D8` (4-vert) |
| 2D sprites | `FUN_80016280` | characters, bushes, objects | none |
| menu wallpaper | `FUN_800223D4` | tiled pause/menu background | loop bound `0x158` |
| object visibility | `0x80018238` | (entity class unconfirmed) | `slti 0x141` |
| dead 3D paths | `FUN_8001DCB0`, `FUN_8001DE4C` | nothing — cull stub returns 0 | `FUN_8001DCA8` (stub) |

**The key asymmetry:** 2D sprites have no screen-bounds test and therefore
render happily outside the 4:3 frame, while 3D geometry is culled to it. That is
why, before the fix, widescreen showed characters and bushes floating over black
margins where the ground should be.

---

## 2. The 3D world renderer — `FUN_8001C37C`

`0x8001C37C`–`0x8001D21B`. Draws the ground and world geometry. **This is the
renderer that matters for widescreen.**

Reached via:

```
FUN_8001BFEC  --(0x8001C088)-->  FUN_8001C37C
FUN_8001C0D4  --(0x8001C170)-->  FUN_8001C37C
```

`FUN_8001C0D4` walks a chunk list, testing each with `FUN_8001C1C0` (§3) before
handing approved chunks to `FUN_8001C37C`.

### Per-primitive pipeline

```c
setCopReg(2, ..., vertex[0..2])       // load 3 vertices into the GTE
copFunction(2, 0x280030);             // RTPT  — perspective-transform 3 vertices
flag = getCopControlWord(2, 0xf800);  // cfc2 $31 (FLAG)
if (-1 < flag) {                      // bit31 = any saturation/overflow -> skip
    copFunction(2, 0x1400006);        // NCLIP — signed area
    if (getCopReg(2, 0x18) > 0) {     // MAC0 > 0 -> front-facing
        sxy0 = getCopReg(2, 0xC);     // projected screen coords
        sxy1 = getCopReg(2, 0xD);
        sxy2 = getCopReg(2, 0xE);
        if (FUN_8001D21C(sxy0, sxy1, sxy2))   // <-- SCREEN-BOUNDS CULL
            ... emit packet ...
    }
}
```

### The two bounds helpers — both hardcode 320

`FUN_8001C37C` contains **two** screen-bounds helpers. Missing the second one
cost this project several hours; see `docs/METHOD.md`.

Every call inside `FUN_8001C37C`:

```
0x8001C3B8: jal 0x8001E158   (packet-buffer reserve)
0x8001C4B4: jal 0x8001D21C   <- 3-vertex cull
0x8001C638: jal 0x8001D21C
0x8001C7CC: jal 0x8001D21C
0x8001C964: jal 0x8001D21C
0x8001CB54: jal 0x8001D2D8   <- 4-vertex cull
0x8001CD2C: jal 0x8001D2D8
0x8001CF14: jal 0x8001D2D8
0x8001D100: jal 0x8001D2D8
```

Arguments are **packed `SXY` words** straight from GTE registers `0xC`/`0xD`/
`0xE` (and `0x??` for the 4th): X in the low 16 bits, Y in the high 16. Return
value is **non-zero = draw**.

#### `FUN_8001D21C` — 3 vertices

```c
// per vertex: t = (X + 0x13) & 0xFFFF
// early-out : if ALL THREE have t > 0x1A2  -> return 0   (entirely off right)
// keep      : if ANY vertex has t < 0x153  -> return 1   (0x153 = 320 + 0x13)
```

| instruction | address | word |
|---|---|---|
| `sltiu v0,v0,0x1A3` | `0x8001D230` `0x8001D250` `0x8001D270` | `0x2C4201A3` |
| `sltiu v0,v0,0x153` | `0x8001D290` `0x8001D2B0` `0x8001D2CC` | `0x2C420153` |

#### `FUN_8001D2D8` — 4 vertices  ← **the ground's cull**

Simpler: no early-out, just "keep if any vertex is on screen".

```c
// per vertex: if ((X + 0x13) & 0xFFFF) < 0x153  -> return 1
// otherwise fall through to the next vertex; none match -> return 0
```

| instruction | address | word |
|---|---|---|
| `sltiu v0,v0,0x153` | `0x8001D2E8` `0x8001D308` `0x8001D320` `0x8001D33C` | `0x2C420153` |

### The constants

`0x13` = 19 px of slack. `0x153` = `320 + 0x13` — the 4:3 display width.
`0x1A3` = `0x1A2 + 1`, ≈ `400 + 0x13`, a coarse early reject.

This is why geometry pops into view the instant it touches the original screen
edge, and why only primitives straddling that edge bleed slightly into a widened
margin. This used to be directly observable in play against the OpenGL tint seam,
which happened to mark the 4:3 boundary — that seam is fixed now (§7), so use
`wide_shot` and read the columns either side of x=53 / x=373 instead.

### Widening it

`game.toml` forces the first comparison of each chain to "on screen" via
`[[widescreen.cull.keep]]` at `0x8001D230`, `0x8001D290` and `0x8001D2E8`.
The recompiler verifies each instruction word and fails closed on a mismatch,
and the widened verdict applies only while a wide view is engaged, so 4:3 is
byte-identical.

**Measured result** (savestate slot 1, farm gameplay, 16:9):

```
before   left-margin black 0.075   right 0.273   whole frame 0.043
after    left-margin black 0.002   right 0.000   whole frame 0.000
```

---

## 3. The chunk frustum test — `FUN_8001C1C0`

**This section's old verdict ("do not relax — too expensive") was wrong, and was
based on broken instruments. The frustum is now WIDENED in the shipped build and
it fixes the 16:9 edge wedges. Shipped at `d = 8`; larger values cost frame
rate in heavy scenes.**

> **Full guide: [`FRUSTUM.md`](FRUSTUM.md)** — the one tunable, how to recompute
> the patch words, how to tune it live with no rebuild, the measurement
> protocol, the cost budget, and three disproved mechanisms not to re-chase.

`0x8001C1C0`. Per-chunk visibility, called from `FUN_8001C0D4`'s loop; rejected
chunks never have packets built at all. Returns 1 only if all four half-planes
pass; the caller draws on non-zero (`if (iVar1 != 0) FUN_8001C37C(...)`).

```c
if ((N0·v < 0) || (N1·v < 0) || (N2·v < 0)) return 0;
else return ~(N3·v) >> 31;
```

| item | address |
|---|---|
| plane normals (4 × 3 × int16, Q12, unit ≈ 4096) | `0x80061EA8`–`0x80061EBE` |
| camera position (3 × int32) | `0x80061EC8` / `0x80061ECC` / `0x80061ED0` |
| rebuilt each frame by | `FUN_8001D348` |
| **base normal set it rotates** | **`0x800A4008`** |
| **the four rotation angles (EXE data)** | **`0x800491E0`..`EC`** |
| rejections | `bltz` at `0x8001C29C` / `0x8001C2DC` / `0x8001C31C` |

**The cone is a COARSE PRE-CULL.** Final visibility is decided by the
per-primitive screen-bounds test inside `FUN_8001C37C`, already widened to the
16:9 frame by `[widescreen.cull]` (§2). That is why *disabling* planes is the
wrong lever — it admits chunks that are then drawn off-screen — while *widening*
the cone admits exactly the newly-visible ones.

**How it is widened:** the two horizontal angles are symmetric (`2156 = 2048+108`
and `-108`); opening them by `d = +8` (≈0.70°) fills the wedges. A
`[[recompiler.patch]]` cannot edit the angle *data* — the game reads it from RAM
at runtime — so the two *loads* are patched to immediates instead
(`0x8001D45C`, `0x8001D4A4`). See `FRUSTUM.md` §3.

Measured on the black-tile save (stationary, 1280×720): `gp0_draw` 412 → 469 per
frame, `total_ms` 16.667 avg / 17.210 max, and the visible wedge row band 1058 →
21 black pixels. Benefit **saturates at +60**.

**Judge cost by `total_ms_max`, and use `gpu_state.gp0_draw` per frame for
geometry** — `frame_perf.prims_avg` counts a narrower subset and moved the
opposite way during this work (300 → 199 while `gp0_draw` rose 387 → 652).

The real ceiling is the primitive packet buffer, which has **no bounds check**
(`FRUSTUM.md` §5): stock occupancy is 34%, and the old "full bypass" variant
crashed by overrunning it — not by being slow.

---

## 4. The 2D sprite emitter — `FUN_80016280`

`0x80016280`. Draws characters, bushes and objects. **Uses no GTE at all** —
screen positions come straight from map data. Has **no screen-bounds test**,
which is why sprites already render in widescreen margins.

Call chain (all thin shims — `FUN_80015D1C` and `FUN_80015E3C` contain no loop):

```
FUN_8001B118 -> FUN_80015D1C -> FUN_80015E3C -> FUN_80016280
```

`FUN_8001B118` calls with `(ot, &pktA, &pktB, descriptor, 0xA0, 0x78)` — the
`0xA0`/`0x78` are 160/120, the screen-centre offset added to every position:
`packet+8 = tileX + 160 + base`.

### Calling convention (read from the prologue, not guessed)

Frame size `0x28`. Ghidra's argument recovery on this chain is unreliable; these
were taken from the disassembly:

| item | location |
|---|---|
| `param_1` (OT) | `a0` → `s1` |
| `param_2` (packet ptr) | `a1` → `t1` |
| `param_4` (descriptor) | `a3` → **`t3`** |
| `param_5` | `sp+0x38` |
| `param_6` | `sp+0x3C` |
| `param_7` (160) | `sp+0x40` |
| `param_8` (120) | `sp+0x44` |

`t3` is not captured by the debug server's write-trace register set
(`v0,v1,a0–a3,t0,t1,s0–s5`), which is precisely why recovering the live
descriptor pointer proved so difficult.

### Descriptor layout

| offset | meaning |
|---|---|
| `+0x04`, `+0x05` | bytes passed as `param_5`/`param_6` — **animation state**, not spatial indices (advanced by `FUN_800158E4`) |
| `+0x1C` | tile definitions, indexed `× 8` |
| `+0x20` | counts, indexed `× 4` |
| `+0x24` | primitive list, `0xC` bytes per entry |
| `+0x28` | per-cell offsets, indexed `param_5*4 + 2` |
| `+0x2C` | cell base, `+ param_6*10` |

Emits `0x64` textured rectangles — the packet command word is the literal
`0x64808080`, 4 words + tag = the `0x14`-byte packet. It writes **two** packet
streams (`param_2` and `param_3`), so a low `0x64` count in a frame dump does
not mean this function is idle.

`FUN_800158E4`, called alongside it, is an **animation stepper** — it advances
byte `+5` as a frame index. It is not a cull.

---

## 5. The menu wallpaper — `FUN_800223D4`

`0x800223D4`. Draws the tiled pause/menu background as a 24 px grid via a
callback, bounded to the original screen plus one tile:

```
s0 = -0xC              start X, one tile left of screen
s0 += 0x18             24 px step
while (s0 < 0x158)     X bound = 344 = 320 + 24
while (a1 < 0x108)     Y bound = 264 = 240 + 24
```

| instruction | address | word |
|---|---|---|
| `addiu s0,zero,-0xC` (start) | `0x80022468` | `0x2410FFF4` |
| `addiu s0,zero,-0xC` (row reset, delay slot) | `0x800224BC` | `0x2410FFF4` |
| `slti v0,s0,0x158` (X bound) | `0x800224A0` | `0x2A020158` |
| `sltiu v0,a1,0x108` (Y bound) | `0x800224B4` | `0x2CA20108` |

`game.toml` widens X by **four** tiles each side (start `-0xC → -0x6C`, bound
`0x158 → 0x1B8`). **Verified in play**: the wallpaper fills the widened frame.
The Y bound is untouched — 16:9 widens horizontally only.

### The grid may only be widened in multiples of FOUR tiles per side

Not three, which is what the reveal arithmetic suggests and what shipped first.
This is the tightest constraint in the file and it is invisible in a still
frame — it only shows up as a hitch in the scroll every ~3.2 s.

**The scroll.** A frame counter at `gp+0xBC` gives

```
s3 = (frames / 4) % 24
```

subtracted from **both** the tile X and the tile Y, so the sheet drifts up-left
one pixel every four frames and snaps back every 24 — exactly one tile. The
snap is meant to be invisible: slide a full tile diagonally, jump back, and if
the pattern repeats correctly the player sees endless scrolling.

**The pattern.** Cell `(i,j)` draws `tbl[(net*j + 1 + i) % 4]`, where the
4-entry table at `0x80055974` is `{0, 2, 1, 3}` (four *distinct* variants — a
phase error is visible) and `net` = columns per row. `s2` is bumped once at the
row head, once per column, and decremented once on loop exit, so `net` is just
the column count.

**The condition.** The snap is invisible iff the pattern survives a one-tile
diagonal shift — cell `(i-1,j-1)` must draw what cell `(i,j)` drew:

```
(net*(j-1) + 1 + (i-1)) ≡ (net*j + 1 + i)   (mod 4)
  ⟺  columns per row ≡ 3  (mod 4)
```

Stock: x from `-0xC` to `0x158` step `0x18` = **15** columns, `15 % 4 == 3`. ✅
That is not luck — it is why those two constants are what they are.

| widening | start | bound | columns | `% 4` | scroll |
|---|---|---|---|---|---|
| stock 4:3 | `-0xC` | `0x158` | 15 | 3 | seamless |
| +3 tiles/side | `-0x54` | `0x1A0` | 21 | 1 | **visible reset every 96 frames** |
| +4 tiles/side | `-0x6C` | `0x1B8` | 23 | 3 | seamless |

Because 4 ≡ 0 (mod 4), the four-tile widening also lands the phase at every
screen position exactly where stock had it — the 4:3 centre of the wallpaper is
identical to the original, not merely seamless.

Two tiles per side (19 columns) also satisfies `≡ 3`, but 48 px does not cover
the 53 px reveal: at `s3 = 23` the rightmost tile ends at x 373 and leaves a
one-pixel column bare. Four is the smallest widening that is both wide enough
and in phase. Cost: 23×11 = 253 rects/frame vs 231, menu-only.

**How this was found** — the wrap condition is arithmetic, so it was settled
without a rebuild: rasterise the tile-index grid for `s3 = 23` and for `s3 = 0`
shifted one more pixel along the travel direction, then count sample points
where the two disagree. Stock 0/1740, +3 tiles 1680/1740, +4 tiles 0/1740.

---

## 6. Dead and unverified paths

**`FUN_8001DCB0` and `FUN_8001DE4C`** are complete GTE renderers
(`RTPT` → `FLAG` → `NCLIP` → `RTPS` → cull → emit `0x2C`), but both call
`FUN_8001DCA8`, which is a two-instruction stub:

```
8001dca8: jr ra
8001dcac: move v0,zero        ; always returns 0
```

Their callers do `beq v0,zero,skip`, so **the draw path never executes**. Dead
code. Do not spend time here.

**Object visibility test at `0x80018238`** — entity class unconfirmed:

```
lh   v0, 0x228(gp)     ; object X
slti v0, v0, 0x141     ; X < 321 ?   (321 = 320 + 1)
beq  v0, zero, +0x50   ; X >= 321 -> skip drawing
lh   v0, 0x22A(gp)     ; object Y
slti v0, v0, 0x79      ; Y < 121 ?
beq  v0, zero, +0x4B   ; skip
```

There is **no matching left-edge test**. `game.toml` widens `321 → 374` but the
change produced no measurable effect in a test scene with few objects near the
right edge — it is labelled unverified there. Ghidra reports *no function* at
this address; it never analysed the region.

---

## 7. Frame composition and the margin-colour seam — FIXED

The runtime keeps canonical PSX VRAM faithful at 4:3 — with widescreen engaged,
`draw_area` is still `[0,240,319,479]` and `draw_offset_x` is `0`. Margin content
reaches the screen only through the wide compositor's **mirror** of framebuffer-
targeting primitives. See `psxrecomp/docs/internal/NATIVE_WIDE_PLAN.md`.

The game draws a full-screen environmental tint as one semi-transparent flat
quad, **every frame**, its colour varying with the in-game clock:

```
0x2a2d4650  0x0  0x140  0xf00000  0xf00140   (0,0)-(320,240) GP0 0x2A, ot=15
                                              semi mode 2 (B-F), colour R80 G70 B45
```

It satisfies every condition of the full-screen fast path in `gp0_exec_mono_quad`
(`gpu.c:3046`), so `ws_expand_fullscreen_rect` widens it to the full 426 px
**before it ever reaches a backend**. The software renderer applies it uniformly
edge to edge.

**The OpenGL backend applied it to the reveal margins on a different schedule
from the 4:3 centre**, so the margins came out visibly darker in G/B — a hard
colour seam at the old screen edge. Measured on the graveyard save, margins vs
centre: **ΔG −24, ΔB −40, ΔR 0** (ΔR exactly zero, which is what ruled out every
"the tint is simply missing / applied twice" theory).

**Cause.** `gpu_flat_rect` (`gpu_gl_renderer.c`) has a full-screen-overlay
special case: it sets `s_wide_suppress`, draws the two canonical triangles, then
paints the overlay across the whole wide surface itself via
`wide_flat_rect_direct`. But the canonical triangles go through the **deferred
flat batch** — `gpu_geometry` only *queues* them, and `flush_flat_batch` draws
them later. `s_wide_suppress` is cleared as soon as they are queued, so it never
reaches the flush that actually mirrors them. The wide surface therefore received
the overlay out of step with the canonical framebuffer.

The special case was also **redundant here**: once `ws_expand_fullscreen_rect`
has widened the rect, the generic per-prim mirror's own x-translation
(`wide_dx`) already spans `[0, g_wide_w)`.

**Fix** (`gpu_gl_renderer.c`, `gpu_flat_rect`): take the direct wide pass **only
when the generic mirror would not already cover the whole wide surface** — i.e.
skip it when `x + wide_dx() <= 0 && x + wide_dx() + w >= g_wide_w`. The
pre-widened rect then rides the same batch, in the same order, as its canonical
twin. The direct pass is retained for the case where the rect was *not*
pre-widened (a framebuffer at `base_x != 0`, which
`ws_expand_fullscreen_rect`'s VRAM-x test cannot recognise as full-screen).

**Verified** against the software renderer as reference: centre and both margins
agree to within the usual ~8/255 backend dithering offset, at two very different
times of day. Seam step at x=53 fell from 25–29 to <1.5 (monotonic scene
gradient). 4:3 is untouched by construction — the whole block is inside
`if (g_wide_cur)`, which is 0 unless native-wide is engaged.

> The old seam had one accidental use: it marked the exact 4:3 boundary on
> screen, which is how the "geometry pops in when it touches the line" behaviour
> was originally spotted. That crutch is gone — use `wide_shot` (native 426×240,
> both backends) and compare the x=52|53 and x=372|373 pixel pairs instead.

---

## 8. Packet buffers

The game **double-buffers** its GPU packet memory, alternating between roughly
`0x801C2000`–`0x801C7400` and `0x801D9000`–`0x801E0000`. Consecutive frames in
the same scene use different buffers.

> **Not any more, as patched.** `game.toml` ("PACKET BUFFER") points both render
> contexts at the single base `0x801C2440` with a 192,000-byte extent, because
> linked-list DMA is synchronous in this runtime and the second buffer bought
> nothing. Packets now always live in `0x801C2440`–`0x801F1240`. The **ordering
> tables** are still double-buffered (`0x801BE440` / `0x801C0440`). Old traces
> and any of the addresses below that fall in the second buffer predate this.

**A packet's address does not identify its producer.** Tracing writes to
`0x1C2400`–`0x1C7400` during gameplay finds the sprite emitter; the same range
during a cutscene finds the 3D renderer. Always confirm the producer by tracing
the specific packet you care about (`docs/METHOD.md`), never by buffer range.

---

## 9. GTE instruction reference

COP2 command instructions are `0x4A000000 | cofun`:

| command | cofun | meaning |
|---|---|---|
| `RTPS` | `0x180001` | perspective-transform 1 vertex |
| `RTPT` | `0x280030` | perspective-transform 3 vertices |
| `NCLIP` | `0x1400006` | signed area → backface test |
| `AVSZ3/4` | `0x158002D` / `0x168002E` | average Z → OT index |

Every projection site in the executable lies in `0x8001C400`–`0x8001E000`, split
between `FUN_8001C37C` (live) and `FUN_8001DCB0`/`FUN_8001DE4C` (dead).

Useful GTE register reads: `getCopReg(2,0xC/0xD/0xE)` = `SXY0/1/2`,
`getCopReg(2,0x18)` = `MAC0`, `getCopControlWord(2,0xf800)` = `cfc2 $31` (FLAG;
bit 31 set = saturation/overflow occurred).
