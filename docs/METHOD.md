# Finding the code behind a pixel

A procedure for answering "**which game function drew this?**" in a recompiled
PS1 title, and the measurement discipline that goes with it.

It was developed while hunting the widescreen ground cull (`docs/RENDERING.md`),
after several hours of decompiler-driven guessing produced four confident,
wrong answers. The procedure below found the real function in **three steps and
about two minutes**, with no rebuilds. Use it first, not last.

---

## The core idea

Work **backwards from a pixel**, not forwards from code.

Every primitive in the GPU stream carries the RAM address of the packet it came
from (`src`). Every packet was written by some game function. So:

```
  a pixel you can see
        |  which primitive covers it?         (rasterise one frame)
        v
  a packet address (src)
        |  who writes that address?           (wtrace on that exact range)
        v
  the writer's PC and return address
        |  which call site is that?           (disassemble)
        v
  THE FUNCTION
```

Each arrow is a direct measurement. Nothing is inferred, so nothing can be
confidently wrong.

---

## The procedure

Prerequisites: a `RelWithDebInfo` build (TCP debug server compiled in), the game
running, and ideally a savestate so the scene is reproducible.

`DC="python3 psxrecomp/tools/debug_client.py"`

### Step 1 — capture a frame and its primitives together

```sh
$DC gpu_ring_stats                     # note newest_frame
$DC gpu_frame_dump frame=<N> count=60000 > prims.json
$DC screenshot shot.png
```

Pick `<N>` a few frames behind `newest_frame`. Frames roll out of the ring fast;
if `count` comes back 0 or tiny, try another offset. A populated gameplay frame
here is ~300 primitives.

### Step 2 — find which primitive covers your pixel

Rasterise the primitives (barycentric point-in-triangle; quads are two
triangles) and test your chosen pixel. Remember the **native-wide draw offset**:
in 16:9 at 320 wide, screen X = primitive X + 53.

Choose the pixel deliberately: unambiguous, in the middle of the thing you care
about, away from HUD, characters and overlapping layers. Report the **last**
covering primitive — later primitives draw over earlier ones.

Output is the primitive's `op`, `src` and `ot`:

```
grass (150,170):   op=0x2c  src=0x001C2B2C  ot=1463
```

### Step 3 — trace who writes that packet

Use a **narrow** range around that exact address:

```sh
$DC wtrace_clear
$DC wtrace_range lo=0x001C2B00 hi=0x001C2B80
sleep 5
$DC wtrace_dump addr_lo=0x001C2B00 addr_hi=0x001C2B80 count=200
```

Always pass the address filter to `wtrace_dump` — it is applied server-side over
the whole ring before the emit cap, so without it you only see the oldest
entries of unrelated traffic.

You get writer PCs **and return addresses**:

```
pc=0x8001CE58, 0x8001CF38, 0x8001CFB4 ...
ra=0x8001CF1C  (86)      ra=0x8001C7D4  (114)
```

### Step 4 — resolve the call site

`ra` is the instruction *after* a `jal` plus its delay slot, so the call is at
`ra - 8`. List every call in the containing function and match:

```sh
python3 - <<'EOF'
import struct
d=open('SLUS_011.15.text.bin','rb').read(); B=0x80010000
for a in range(FUNC_START, FUNC_END, 4):
    w=struct.unpack_from('<I',d,a-B)[0]
    if (w>>26)==0x03:
        print("0x%08X: jal 0x%08X  (ra=0x%08X)"%(a,((w&0x3FFFFFF)<<2)|0x80000000,a+8))
EOF
```

`ra=0x8001CF1C` → call at `0x8001CF14` → `jal 0x8001D2D8`. **That** was the cull
actually gating the ground — a function four hours of decompiler reading had
never surfaced.

---

## Supporting techniques

### Scan instruction encodings, don't only read decompiler output

Ghidra had **not analysed** the region containing one of the culls, and reported
"no function" there. Decompiler-driven search could never have found it. A
30-line scan of the raw binary for `slti`/`sltiu` with immediates near the screen
width found every candidate in the executable at once:

```python
for a in range(0x80010000, 0x80048B08, 4):
    w = struct.unpack_from('<I', d, a-0x80010000)[0]
    op, imm = w >> 26, w & 0xFFFF
    if op in (0x0A, 0x0B) and 0x138 <= imm <= 0x160:   # slti/sltiu near 320
        ...
```

Nine hits across the whole game, all quickly classified. Screen-space constants
worth scanning for: `320`/`0x140`, `321`, `339`/`0x153`, `344`/`0x158`,
`240`/`0xF0`, `264`/`0x108`.

### Read calling conventions from the prologue

Ghidra's argument recovery on this game's shim-heavy call chains is unreliable —
it decompiled two functions that pass eight arguments as `void f(void)`. Read
the prologue instead:

```
80016280: addiu sp,sp,-0x28     ; frame size -> stack args at sp+0x28+0x10...
80016298: move  t3,a3           ; param_4 lives in t3
80016294: lbu   v0,0x38(sp)     ; param_5
```

MIPS o32: `a0`–`a3` are args 1–4; args 5+ arrive at the caller's `sp+0x10`,
`+0x14`, … which is `sp + framesize + 0x10` once the prologue has run.

### Verify every patch target against the binary

Before writing a `[[recompiler.patch]]` or `[[widescreen.cull.keep]]`, read the
word at the address and decode it. The recompiler also verifies and fails
closed, but checking first turns a failed build into a corrected assumption.

### Measure, don't eyeball

Objective numbers make "no change" unambiguous — several plausible fixes in this
project changed the image by *exactly zero pixels*, which eyeballing would have
missed:

- **black fraction per margin** — count `(0,0,0)` pixels in `x<53` and `x>=373`
- **per-column primitive coverage** — rasterise and count primitives covering
  each column; compare against the black profile. This is the measurement that
  distinguishes *culled* from *not authored*, and it is cheap. **Run it before
  acting on any theory.**
- **primitive count per frame** — if a change was supposed to submit more
  geometry and the count didn't move, it didn't work

### Use savestates to make scenes reproducible

`Shift+F1`–`Shift+F12` save; **plain F1–F12 load** (easy to get backwards).
Boot straight into one:

```sh
PSX_LOAD_SLOT=1 SDL_AUDIODRIVER=dummy sh run.sh
```

`PSX_LOAD_SLOT` is the framework's headless/agent load path. `SDL_AUDIODRIVER=
dummy` mutes for repeated test cycles. Savestates are keyed on the framework's
codegen identity, not `game.toml`, so config changes and regens do not
invalidate them.

Keep **two contrasting states** — this project used a cutscene and live
gameplay, which turned out to exercise entirely different renderers. A fix
verified on one proves nothing about the other.

---

## Pitfalls this project actually hit

**A packet buffer address does not identify its producer.** The game
double-buffers; the same address range is written by the sprite emitter in
gameplay and the 3D renderer in a cutscene. Trace the specific packet, never the
buffer range.

**A function may contain more than one cull.** `FUN_8001C37C` has two bounds
helpers with different arities. Patching one, seeing no change, and concluding
"this renderer is innocent" was the single most expensive error in this project.
**Enumerate every call in the function before concluding anything.**

**Dead code looks alive in a decompiler.** Two complete GTE renderers turned out
to call a cull stub that returns 0 unconditionally, so their draw paths never
run. Check what the helpers actually do before analysing the callers.

**Sibling functions are not always what they look like.** `FUN_800158E4`, called
right alongside the tile emitter, reads like a spatial walker but is an
animation stepper.

**Image cross-correlation is not a measurement.** A frame-to-frame shift
estimated by correlation gave `+60 px`; matching tile packets by texture/CLUT
identity gave `−45 px` — wrong in both magnitude and sign, because the content is
perspective-projected and does not translate rigidly. A conclusion built on it
had to be retracted. Derive shifts from packet data, and treat a high residual
as a failed match rather than a fit.

**Structure-shape scans over RAM are hopeless without strong constraints.**
Scanning 2 MB for "five consecutive pointer-looking fields" returned 319
matches, most inside code. Add ordering, clustering and a semantic check (walk
the structure and see whether the result matches something observed), or don't
bother.

**Per-frame RAM snapshots cannot capture a live call frame.** `set_snapshot` +
`read_frame_ram` works and returns coherent data, but fires at a fixed point per
frame — by which time the render call stack has unwound. There is no
call-synchronised capture for native code (`pc_break` is DuckStation-only).
Note also that `set_snapshot` accepts an out-of-range address without
validation and can take the process down.

---

## Checklist

1. Reproduce the scene from a savestate
2. Capture a frame's primitives **and** a screenshot together
3. Pick an unambiguous pixel; find the primitive covering it
4. `wtrace` that exact packet address; record PC **and** `ra`
5. `ra - 8` is the call; enumerate **all** calls in the function
6. Verify the target instruction word against the binary
7. Patch, rebuild, and **measure** — black fraction, coverage, primitive count
8. Record the result either way; a measured no-op is worth keeping
