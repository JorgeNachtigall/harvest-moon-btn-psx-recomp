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
margin. With the OpenGL tint seam marking the 4:3 boundary (§7), the behaviour is
directly observable in play.

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

`0x8001C1C0`. Per-chunk visibility, called from `FUN_8001C0D4`'s loop; rejected
chunks never have packets built at all.

Transforms the chunk position into view space, then tests four half-planes:

```c
if ((N0·v < 0) || (N1·v < 0) || (N2·v < 0)) return 0;
else return ~(N3·v) >> 31;
```

| item | address |
|---|---|
| plane normals (4 × 3 × int16, Q12, unit ≈ 4096) | `0x80061EA8`–`0x80061EBE` |
| camera position (3 × int32) | `0x80061EC8` / `0x80061ECC` / `0x80061ED0` |
| rebuilt each frame by | `FUN_8001D348` (writers `0x8001D59C/5E8/61C`) |
| rejections | `bltz` at `0x8001C29C` / `0x8001C2DC` / `0x8001C31C` |

Typical live values: `P0=(-2434,-303,-3291)`, `P1=(3289,-303,2434)`,
`P2=(1655,3381,-1657)`, `P3=(-947,-3890,947)`. **The normals are identical
across different areas and camera positions** — they are camera-relative
constants, not per-map data.

**Do not bother widening this.** Forcing it to report every chunk visible was
tested: it submitted far more geometry (a visible frame-rate cost) and changed
the rendered image by **zero pixels**, because the extra chunks were all
off-screen. The screen-bounds culls in §2 are the real limiter.

Note the rejections are `bltz` (REGIMM), so `[[widescreen.cull.keep]]` cannot
reach them — that key only accepts `SLT`/`SLTU`/`SLTI`/`SLTIU`.

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

`game.toml` widens X by three tiles each side (start `-0xC → -0x54`, bound
`0x158 → 0x1A0`). **Verified in play**: the wallpaper fills the widened frame.
The Y bound is untouched — 16:9 widens horizontally only.

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

## 7. Frame composition and the OpenGL seam

The runtime keeps canonical PSX VRAM faithful at 4:3 — with widescreen engaged,
`draw_area` is still `[0,240,319,479]` and `draw_offset_x` is `0`. Margin content
reaches the screen only through the wide compositor's **mirror** of framebuffer-
targeting primitives. See `psxrecomp/docs/internal/NATIVE_WIDE_PLAN.md`.

The game draws a full-screen tint as a single semi-transparent flat quad:

```
0x2a000014  0x0  0x140  0xf00000  0xf00140     (0,0)-(320,240), colour 0x14 red, ot=15
```

It satisfies every condition of the full-screen fast path in `gp0_exec_mono_quad`
(`gpu.c:3045`), so `ws_expand_fullscreen_rect` widens it correctly — and the
**software renderer proves it**, producing a uniform tint edge to edge (seam step
−0.1 vs OpenGL's +15.0). The OpenGL backend drops that expansion.

**This is a framework bug** in `gpu_gl_renderer.c`, not a game issue, and is
still open. The visible one-pixel step at x=53 and x=373 is an accidental gift:
it marks the exact 4:3 boundary on screen, which is how the "geometry pops in
when it touches the line" behaviour was spotted in the first place.

---

## 8. Packet buffers

The game **double-buffers** its GPU packet memory, alternating between roughly
`0x801C2000`–`0x801C7400` and `0x801D9000`–`0x801E0000`. Consecutive frames in
the same scene use different buffers.

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
