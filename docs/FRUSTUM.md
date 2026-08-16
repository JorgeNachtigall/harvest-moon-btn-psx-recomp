# The chunk frustum cone — how to change it

**Status: SHIPPED at `d = 8`, vertical stock.**
Widening the two horizontal half-planes fills the black wedges at the left/right
edges of the 16:9 frame. `d = 8` was picked ON SCREEN as the smallest value that
closes them, and small is the point: **this knob costs frame rate**, and earlier
revisions of this document were wrong to say otherwise.

> ### The knob is not free — measured, on a heavy scene
> Interleaved A/B on the graveyard save (~1,500 draws/frame at stock), `d`
> switched live every few seconds so scene drift cancels:
>
> ```
>  d      game_fps   draws/frame   packet occupancy
>  +0      29.97        1,642           36.5%
>  +8      29.97        1,692           37.7%   <- shipped
> +40      19.89        1,955           43.8%
> +60      25.45        2,236           55.0%   (straddles 30 and 20)
> ```
>
> The game renders on whole vblanks, so frame rate is **quantised**: a scene
> that stops fitting in two vblank periods drops straight from 30 to 20. Heavy
> areas already sit on that boundary at stock, which is why `d = 60` costs a
> third of the frame rate in the graveyard while costing nothing in town. Do
> not tune `d` in town and assume it generalises — that mistake was made here.
>
> Vblank fires on **guest cycle count** (`interrupts.c:388`), not wall clock, so
> this is simulated PS1 time. The host is not the limit: `vsync_hz` stayed at
> 60.00 throughout, and `d` cannot change it.

> ### Read `game_fps`, never `vsync_hz`
> The runtime presents at every simulated vblank, so the present cadence is
> pinned near 60 Hz no matter what the game does. Any claim in this repo's
> history of "holds 60 fps" was that number and was meaningless. The rate a
> player perceives is the display-area flip rate, counted in
> `gpu.c:gp1_display_area_start`, reported as `frame_perf.game_fps` and shown on
> the OSD's first line next to `VSYNC`. This game runs at **30 FPS** in town and
> in the graveyard at stock, and drops to **20** when a scene stops fitting.

> ### The packet-buffer crash, and why it is gone
> `FUN_8001C37C` advances its packet write pointer 5–7 words per primitive with
> **no bounds check**. At `d = 60` the densest measured frame needed 100,532
> bytes against a 96,000-byte buffer, so it wrote past the end, through aux buf
> A and into aux buf B; the GPU DMA then walked corrupted memory and hit an
> invalid GP0 opcode. The buffer is now 192,000 bytes (see `game.toml`, "PACKET
> BUFFER"), which is what made `d = 60` testable at all.
>
> **At the shipped `d = 8` the doubling is headroom, not a necessity** — d=8
> peaks at 37.7%, i.e. 75.5% of the old buffer. It is still worth having: stock
> `d = 0` already peaked at 85.2% of the old buffer while walking, which was
> thin. There is still no bounds check; the buffer is just big enough.
> **Any candidate `d` must be validated for peak occupancy (§5) in the densest
> area you can reach.**

Read this before touching anything frustum-related. §6 lists three mechanisms
that were investigated and **disproved** — do not re-run them.

---

## 0. HOW `d` WAS CHOSEN (2026-08-14) — read this first

**`d = 8`, picked on screen as the smallest value that closes the wedges.**

The history matters, because two earlier conclusions in this file were wrong and
you will otherwise repeat them:

1. **`d = 60` was chosen against a broken frame-rate meter.** The OSD was
   counting vblank presents, which are unconditional, so it read 60 FPS at all
   times. With the meter fixed (display-area flips), `d = 60` costs the
   graveyard a third of its frame rate. `d = 8` looks the same at the edges and
   costs nothing measurable.
2. **`d` was tuned in town and assumed to generalise. It does not.** Town runs
   ~718 draws/frame with slack; the graveyard runs ~1,500 and sits right on the
   two-vblank boundary. Validate any `d` in the heaviest scene you can reach.

Getting `d = 60` testable at all required doubling the packet buffer, which is
still in place and still worth having (see the header note).

Two ways to pay for a large `d` were tried and are REJECTED — do not revisit:

| approach | result |
|---|---|
| vertical narrowing (`v = -20`) | bounds occupancy to 91.2% but is NOT the same image as `v = 0`; rejected on sight |
| hard primitive cap on plane 2's slot | bounds it to 88.6% but destroys the picture: losing plane 2's culling doubles admitted geometry (§6) |

**Why the packet buffer could be doubled for free.** The arena reserves
`base+0x4290 .. base+0x33090` as TWO 96,000-byte buffers, one per render
context, because on real hardware the GPU DMAs frame N's packet list while the
CPU builds frame N+1. In this runtime that overlap does not exist: linked-list
DMA is fully synchronous (`psxrecomp/runtime/src/dma.c:700-746` walks the whole
ordering table and pushes every GP0 word inside the store to DMA2's control
register), so `DrawOTag` has entirely consumed the buffer before it returns.
Pointing both contexts at the same base yields one 192,000-byte buffer in the
exact same bytes. The ordering tables stay double-buffered. Full derivation and
the resize rules are in `game.toml` under "PACKET BUFFER".

**Why it could NOT simply be grown instead.** All 2 MB of PS1 RAM is live. The
107,464-byte hole between the top of overlay window B (`0x801A3DE8`) and the
arena base (`0x801BE1B0`) looks free and is not: it holds sprite tables pointed
to from `0x80071CA4`/`0x800781F8`/`0x80078CF0`/`0x8007926C`, allocated downward
from the arena base. The largest all-zero run anywhere in RAM is 71,680 bytes.
Measured, not assumed — see §5.

> ### Save states predate the buffer change and must be migrated
> A `.pst` is a whole-RAM snapshot, so it also captures the render contexts
> `FUN_80012598` filled in at boot. A state taken before that change still
> describes two 96,000-byte buffers, and the patched init never runs again after
> a load. Fix them once:
>
> ```sh
> python3 tools/migrate_savestate_pktbuf.py build/state_*.pst
> ```
>
> Normal play (boot -> memory card) needs none of this.

---

## 1. The one number you probably want to change

`game.toml` carries two patches, `widescreen-frustum-cone-h0` and
`widescreen-frustum-cone-h1`. They encode a single tunable, **`d`**:

```
angle[0] = 2156 + d      (patched at 0x8001D45C)
angle[1] = -108 - d      (patched at 0x8001D4A4)
```

`d = 0` is stock. **`d = 8` is shipped** (`h0 = 0x24040874`, `h1 = 0x2404FF8C`).
Larger `d` = wider cone = more chunks admitted = fewer frames per second in
heavy scenes. Angle units are PSX rotation units where `4096 = 360°`, so
`d = 8` opens each side by `8 * 360 / 4096` ≈ **0.70°**. That is all it takes;
the wedges close far earlier than the old `d = 60` implied.

### Recompute the two patch words

Both replacements are `addiu a0, zero, N`, which encodes as
`0x24040000 | (N & 0xFFFF)`:

```sh
python3 -c "
d = 8                                   # <-- change this
a0, a1 = 2156 + d, -108 - d
enc = lambda n: 0x24040000 | (n & 0xFFFF)
print('h0  0x8001D45C  expected 0x8E0491E0  replacement 0x%08X   # addiu a0,zero,%d' % (enc(a0), a0))
print('h1  0x8001D4A4  expected 0x8E040004  replacement 0x%08X   # addiu a0,zero,%d' % (enc(a1), a1))
"
```

Paste the two `replacement` values into `game.toml`, leave `expected`
untouched (the recompiler verifies it and fails closed on a mismatch), then:

```sh
sh tools/regen.sh && sh build.sh && sh tools/compile_static_overlays.sh
```

The overlay recompile is **required** — `[[recompiler.patch]]` feeds the config
hash, so the cache namespace changes. Confirm afterwards with
`overlay_loader_status`: `dispatch_native` must be non-zero and `stale_blocked`
must be 0.

---

## 2. Tune it live first — no rebuild

**Always find the value this way before patching**, then bake the result in §1.
There is a tool for exactly this:

```sh
python3 tools/frustum_d.py        # interactive: type a d, see fps/draws/occupancy
python3 tools/frustum_d.py 30     # set 30 and hold it, Ctrl-C to stop
```

It prints `game_fps` (perceived, from display flips), draws/frame and packet
occupancy after each change, refuses to run against a build that bakes the cone
(where writes silently do nothing), and **holds the value** — which you need,
because of this:

> ### ⚠ The game REWRITES the angles back to stock on its own
> A one-shot `write_ram` does not stick. Observed reverting to `(2156, -108)`
> within a couple of minutes of play, which looks exactly like "the fix stopped
> working" — the wedges come back while you are staring at them. What performs
> the rewrite has **not** been identified yet; that trace is still open. Until
> it is, `tools/frustum_d.py` re-applies the value twice a second and reports
> how often it had to. It also means a shipped `d` MUST be baked into the two
> patches; it cannot be written at runtime.

> ### ⚠ Live tuning only works on a build WITHOUT the h0/h1 patches
> Once `widescreen-frustum-cone-h0/h1` are applied, the two horizontal angles are
> **immediates in the recompiled code** and the RAM words at `0x800491E0`/`E4`
> are never read — `write_ram` there silently does nothing. Verified: on the
> shipped build, writing the stock values back left `gp0_draw` at 653.1/frame,
> unchanged.
>
> So the real workflow is: comment out the two patches → `regen` + `build`
> (config hash returns to the unpatched namespace, whose shard cache already
> exists, so **no overlay recompile**) → sweep `d` live → put the patches back
> with the winning value. The **vertical** angles (offsets 8 and 12) are still
> loaded from RAM in every build, so those stay live-tunable at any time.

On an unpatched build, the angles are re-read from RAM every frame, so
`write_ram` retunes the cone instantly:

```sh
python3 - <<'PY'
import json, socket, struct
def cmd(d):
    s = socket.create_connection(("127.0.0.1", 4370), 5); s.settimeout(30)
    s.sendall((json.dumps(d) + "\n").encode()); buf = b""
    while not buf.endswith(b"\n"):
        c = s.recv(1 << 20)
        if not c: break
        buf += c
    s.close(); return json.loads(buf.decode())
def wr32(a, v):
    b = struct.pack("<i", v)
    for i in range(4): cmd({"cmd": "write_ram", "addr": a + i, "val": b[i]})

d = 60                                   # <-- try values here
wr32(0x800491E0,  2156 + d)
wr32(0x800491E4,  -108 - d)
PY
```

Restore stock with `d = 0`. Nothing persists across a restart.

> A `[[recompiler.patch]]` **cannot** change `0x800491E0` directly. Patches are
> applied to the image the *recompiler* consumes; the game reads these angles
> from RAM at runtime, so a data patch has no effect. That is exactly why the
> shipped fix patches the **loads** instead (§3).

---

## 3. Where it lives in the game

`FUN_8001D348` rebuilds all four plane normals every frame: it takes a base
normal set at `0x800A4008` and rotates it by four angles held in **EXE data** at
`0x800491E0..EC`.

| slot | address | stock | role |
|---|---|---|---|
| `angle[0]` | `0x800491E0` | `2156` | horizontal, one side |
| `angle[1]` | `0x800491E4` | `-108` | horizontal, mirror side |
| `angle[2]` | `0x800491E8` | `93` | vertical *(untouched)* |
| `angle[3]` | `0x800491EC` | `1962` | vertical *(untouched)* |

The horizontal pair is symmetric about the view axis (`2156 = 2048 + 108`, and
`-108`), which is why `d` is added to one and subtracted from the other.

The load sequence, and why only two words needed patching:

```
0x8001D45C  lw    r4,-28192(r16)   ; angle[0]   <-- PATCHED to addiu a0,zero,2216
0x8001D460  addiu r16,r16,-28192   ; r16 = 0x800491E0   (LEFT INTACT — load base)
0x8001D49C  jal   FUN_80037E24
0x8001D4A4  lw    r4,4(r16)        ; angle[1]   <-- PATCHED to addiu a0,zero,-168
0x8001D4A8  jal   FUN_80037E24
0x8001D4B0  lw    r4,8(r16)        ; angle[2]   (vertical, still loads normally)
0x8001D4BC  lw    r4,12(r16)       ; angle[3]   (vertical, still loads normally)
```

`0x8001D460` must stay — it is what sets `r16` for the two vertical loads. To
tune the **vertical** cone, patch `0x8001D4B0` / `0x8001D4BC` the same way
(`expected` = `0x8E040008` / `0x8E04000C`), using stock `93` and `1962`.

### Downstream, for context

`FUN_8001C1C0` tests a chunk against the four resulting half-planes and returns
1 only if all pass; `FUN_8001C0D4` draws on non-zero
(`if (iVar1 != 0) FUN_8001C37C(...)`). The cone is a **coarse pre-cull** — what
decides final visibility is the per-primitive screen-bounds test inside
`FUN_8001C37C`, already widened to the 16:9 frame by `[widescreen.cull]`.

---

## 4. How to measure a change

Four traps have burned this thread. Use this protocol.

1. **Hold the scene still.** The farm drifts on its own — the character walks,
   the clock runs, NPCs open dialogs — so wall-clock A/B compares *different
   scenes*. Use the black-tile savestate (`PSX_LOAD_SLOT=1`) where the wedges are
   visible without moving, or sample at equal guest `frame_count` via
   `freeze_check`, or measure inside a dialog box (which freezes the world).
2. **Capture what is actually on screen** with `window_capture` (two calls: arm,
   then fetch). `screenshot` reads raw VRAM and `screenshot_hires` reads the
   compositor surface — **both are blind** to GPU-side overlays, and neither is
   the presented frame.
3. **Use `gpu_state.gp0_draw` per frame** as the geometry metric.
   `frame_perf.prims_avg` counts a narrower subset and moves the *opposite* way:
   it fell 300 → 199 in one test while `gp0_draw` rose 387 → 652.
4. **Judge cost by `total_ms_max`, not the average.** The average is vsync-pinned
   to 16.667 ms and hides everything.

### Measured sweep (black-tile save, character stationary, 1280×720)

| `d` | gp0_draw/frame | total_ms avg / max | black px |
|---|---|---|---|
| +0 | 412.3 | 16.667 / 16.715 | 5985 |
| **+60** | **600.0** | **16.667 / 22.004** | **4952** |
| +120 | 844.0 | 16.667 / 22.200 | 4959 |
| +200 | 705.9 | 16.667 / 22.003 | 4966 |

**The benefit saturates at +60.** Beyond it you buy draw calls and zero pixels.

Localised, the fill is exactly the missing geometry — left column band
1838 → 873, right band 91 → 0, and the visible mid-height wedge 1058 → 21. The
~4950 residual is the frame-stats OSD panel, not scene black (run with
`PSX_OSD=0` to measure without it).

Shipped build re-measured: **gp0_draw 469.4/frame, 16.667 / 17.210 ms,
scene_gpu 0.463 ms.**

---

## 5. The budget you are spending

### What it costs — measured on the heaviest scene available

Interleaved A/B on the graveyard save, `d` switched live every few seconds so
scene drift cancels (this is the protocol; a single before/after is not enough,
the scene wanders on its own):

| | `d = 0` | `d = 8` | `d = 40` | `d = 60` |
|---|---|---|---|---|
| **game_fps** | 29.97 | **29.97** | 19.89 | 25.45 |
| draws/frame | 1,642 | 1,692 | 1,955 | 2,236 |
| peak occupancy | 36.5% | 37.7% | 43.8% | 55.0% |

Frame rate is **quantised to whole vblanks**, so it does not degrade smoothly:
the scene either fits in two vblank periods (30 FPS) or it does not (20 FPS).
`d = 60` reads 25.45 because it straddles the boundary and flips between the
two. That is also why `d = 40` can read *worse* than `d = 60` — both are over
the line, and which side of it a given second lands on is scene-dependent.

For contrast, the same knob in town: `d = 0` and `d = 60` both hold 30.00 FPS,
because town runs ~718 draws/frame and has slack. **Tuning `d` in a light scene
tells you nothing about a heavy one.**

Widening is affordable but not free, and one resource has **no bounds check**.

- **GPU: irrelevant.** Total GPU work is ~1.2 ms of a 16.67 ms frame (~7%).
- **CPU: has slack.** ~34% of every frame is the game's own vblank poll loop at
  `0x80032CFC` (a `wait_until(counter >= target)` with a spin timeout).
- **Primitive packet buffer: THIS is the ceiling.** `FUN_8001C37C` advances a
  write pointer (`ctx+0x118`, reset to base `ctx+0x124` each frame by
  `FUN_800120C8`) 5–7 words per primitive and **never tests it** against the
  extent at `ctx+0x11C`. That extent is now 192,000 bytes (was 96,000), and
  `d=60` peaks at 52.4% — but the check still does not exist, so an overrun is
  still silent corruption followed by an invalid GP0 opcode. Push the cone hard
  and it climbs: the old "full bypass" variant (~2.5× the geometry) **crashed**
  for this reason, not for cost.

Check occupancy after any change:

```sh
python3 -c "
import json,socket,struct
def cmd(d):
    s=socket.create_connection(('127.0.0.1',4370),5); s.settimeout(20)
    s.sendall((json.dumps(d)+'\n').encode()); b=b''
    while not b.endswith(b'\n'): b+=s.recv(1<<20)
    s.close(); return json.loads(b.decode())
rd=lambda a,l: bytes.fromhex(cmd({'cmd':'read_ram','addr':a,'len':l})['hex'])
ctx=struct.unpack('<I',rd(0x8005E3C0,4))[0]
base=struct.unpack('<I',rd(ctx+0x124,4))[0]
wp  =struct.unpack('<I',rd(ctx+0x118,4))[0]
size=struct.unpack('<I',rd(ctx+0x11C,4))[0]
print('packet buffer %d / %d = %.1f%%' % (wp-base, size, 100*(wp-base)/size))
"
```

### The buffer, and the RAM map it lives in

`FUN_80012598` is the allocator (`FUN_8001231C` is its twin; both hand the
second half to `FUN_8001E160`):

```
arena     = 0x801BE1B0, memset 0x3EE50 = 257,616 B
OT[i]     = arena + i*0x2000 + 0x290     (2 x 8192, 0x800 entries each)
packet[i] = arena + i*SIZE   + 0x4290    (size field ctx+0x11C)
```

**As patched, the `i*SIZE` term is forced to 0 and `SIZE` is 192,000**, so both
contexts share one buffer covering exactly the bytes the two used to:

```
0x801BE440..0x801C0440  OT A            8192 B   (still double-buffered)
0x801C0440..0x801C2440  OT B            8192 B
0x801C2440..0x801F1240  packet buffer 192000 B   <- SHARED by both contexts
0x801F1240..0x801F4120  aux buf A      12000 B   (base ctx+0x12C, len +0x128)
0x801F4120..0x801F7000  aux buf B      12000 B
0x801F7000..0x801FD000  arena tail; the ptr at gp+0x144/0x148 points here
0x801FD000..0x801FFFF0  stack (sp base 0x801FFFF0)
```

**192,000 is the hard ceiling without moving other things.** The buffer starts
at `arena+0x4290` and `0x4290 + 0x2EE00 = 0x33090`, which is exactly aux buffer
A's base. Going beyond it means relocating the aux buffers.

**And there is nowhere to relocate them to.** Measured on the crash-spot save,
across all 2 MB:

- The 107,464-byte hole between overlay window B's top (`0x801A3DE8`, member 11
  at its largest) and the arena base is **not free** — it holds sprite tables
  reached from `0x80071CA4`/`0x800781F8`/`0x80078CF0`/`0x8007926C`, allocated
  downward from the arena base.
- The largest all-zero run anywhere in RAM is **71,680 bytes** (`0x800A4400`),
  and that is a work buffer that merely happened to be clear.
- The runtime masks RAM to `0x1FFFFF` (`psxrecomp/runtime/include/psx_cyc.h`),
  so there is no expansion region to escape into.

To re-derive the map: `read_ram` the whole 2 MB in 128 KB chunks and look for
all-zero runs, then `wtrace_range` any candidate and confirm zero writes during
play. Arm a control range on the live packet buffer at the same time — it should
log ~100k writes/second, which proves the trace is working and the silence
elsewhere is real.

---

## 6. Dead ends — do NOT re-investigate

Three mechanisms were built, applied, and measured. All three are ruled out.

- **Disabling frustum planes** (NOP the `bltz` at `0x8001C29C` / `0x8001C2DC`).
  Works, and takes packet-buffer occupancy 34% → 90% — but it
  admits chunks that are drawn **off-screen**. Widening the cone is strictly
  better: same visual result for far less geometry. Do not disable planes.
- **Unclamped ordering-table index.** `idx = OTZ>>2` into a 2048-entry OT, and
  GTE `OTZ` is unsigned to 65535, so it *looks* like it must overflow. A real
  clamp was built and applied at all 8 insert sites (`sltiu`/`bne`/`addiu` into
  the spare `nop` and the provably-dead negative-rounding path, with `r2`
  liveness verified per site). It changed **nothing** — identical `gp0_draw`,
  identical image. The surviving plane-3 test already bounds Z.
- **Packet-buffer overrun as the cause of lost geometry.** Disproved by reading
  the live write pointer: 34% at stock. It is a *future* risk (§5), not the
  explanation for anything observed.

- **A hard primitive cap built on plane 2's slot — TRIED, FAILED, REVERTED.**
  The idea: repurpose plane 2's dot product inside `FUN_8001C1C0` (14 contiguous
  instructions, `0x8001C2E4`..`0x8001C318`) into a budget test, so the EXISTING
  `bltz a1,0x8001C368` at `0x8001C31C` rejects the chunk when over budget — no
  new branch needed. Cap derived exactly: primitives cost a rock-steady
  **44.4–44.5 bytes** each (1751/1928/2028 prims → 77,700/85,796/90,120 B), so
  1900 prims ≈ 84,550 B ≈ 88%.

  **It did bound the buffer**: at the crash spot with `d=60` it held **88.6%**
  (1928 prims — the cap plus one chunk's overshoot, since the test is per-chunk)
  and a perfect 16.667/16.698 ms. No crash.

  **But the picture was destroyed** — a large black hole where the town ground
  belongs. Cause is in one number: `gp0_draw` went **469 → 975/frame**. Losing
  plane 2's culling MORE THAN DOUBLED admitted geometry, so the budget was spent
  on chunks plane 2 used to reject, starving the visible ground. Chunks are not
  distance-ordered, so exhausting the budget drops arbitrary (here, central)
  geometry rather than distant geometry.

  **Lesson: plane 2 is worth far more than the cap.** Any future cap must keep
  all four planes. That needs a spare instruction slot which does not exist —
  `FUN_8001C1C0`'s epilogue has none, `FUN_8001C0D4`'s chunk loop has none, and
  plane 2's block has only 3 usable load-delay `nop`s (`0x8001C2E8`,
  `0x8001C2F8`, `0x8001C308`) while the check needs 4 instructions
  (`lhu` / `sltiu` / `addiu` / `or a1,a1,rX`). So a word-level patch cannot do
  it; it would need a recompiler-level hook or a `.psxmod`.

### Instrument bugs that produced the earlier wrong verdicts

All fixed in `psxrecomp/runtime/src/gpu_gl_renderer.c` / `debug_server.c`:

- `scene_gpu_ms` was a **whole-frame span**, not GPU busy time — one
  `TIME_ELAPSED` query held open across the inter-present interval, so emulated
  CPU idle counted as GPU time. It read 9.084 ms; the truth is 0.2–0.8 ms. Now
  one `TIME_ELAPSED` per `hr_begin`/`hr_end` draw bracket, summed.
- `mirror_gpu_ms` silently published **0.000** because `glQueryCounter` returns 0
  on Apple GL. Now probed at init and withheld behind `mirror_timing_ok`.
- Nothing could see the presented frame. Added **`window_capture`**, which reads
  back the default framebuffer at swap time.
