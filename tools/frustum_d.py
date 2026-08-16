#!/usr/bin/env python3
"""Tune the chunk frustum cone (`d`) live, while the game runs.

    python3 tools/frustum_d.py            # interactive: type values, see the effect
    python3 tools/frustum_d.py 30         # set d=30 and hold it, Ctrl-C to stop
    python3 tools/frustum_d.py --once 30  # set d=30 and exit (may revert, see below)

`d` widens the two horizontal frustum half-planes:

    angle[0] = 2156 + d      at 0x800491E0
    angle[1] = -108 - d      at 0x800491E4

d=0 is stock (black wedges at the 16:9 edges). Larger d admits more chunks and
fills them in, at the cost of more geometry per frame. Angle units are PSX
rotation units, 4096 = 360 degrees, so d=60 is about 5.27 degrees per side.

TWO THINGS THAT WILL WASTE YOUR TIME IF YOU DO NOT KNOW THEM:

1. This only works on a build WITHOUT the `widescreen-frustum-cone-h0/h1`
   patches in game.toml. Those patches turn the two angle LOADS into
   immediates, after which the RAM words are never read and writing them does
   nothing at all -- silently. This script checks game.toml and refuses to
   pretend otherwise.

2. The game REWRITES these angles back to stock on its own (observed reverting
   within a couple of minutes of play). So a one-shot write does not stick.
   By default this script holds the value: a background thread re-applies it
   about twice a second and reports how often it had to.

Reads out game_fps (real perceived frame rate, from display flips -- NOT the
vsync cadence), draws per frame, and packet-buffer occupancy, so you can see
both halves of the trade at once.
"""
import json
import os
import socket
import struct
import sys
import threading
import time

HOST, PORT = "127.0.0.1", 4370
ANGLE0, ANGLE1 = 0x800491E0, 0x800491E4
CTXS = (0x8005E5E8, 0x8005E71C)
PKT_LEN_OFF, PKT_WP_OFF, PKT_BASE_OFF = 0x11C, 0x118, 0x124


def cmd(**kw):
    """One request per connection -- the debug server closes after each reply."""
    s = socket.create_connection((HOST, PORT), 15)
    try:
        f = s.makefile("rwb")
        f.write((json.dumps(kw) + "\n").encode())
        f.flush()
        return json.loads(f.readline().decode())
    finally:
        s.close()


def wr32(addr, val):
    b = struct.pack("<i", val)
    for i in range(4):
        cmd(cmd="write_ram", addr=addr + i, val=b[i])


def rd(addr, n):
    return bytes.fromhex(cmd(cmd="read_ram", addr=addr, len=n)["hex"])


def get_d():
    a0, a1 = struct.unpack("<2i", rd(ANGLE0, 8))
    return a0 - 2156, (a0, a1)


def set_d(d):
    wr32(ANGLE0, 2156 + d)
    wr32(ANGLE1, -108 - d)


def occupancy():
    worst = 0.0
    used = 0
    for ctx in CTXS:
        wp, size, _ot, base = struct.unpack("<4I", rd(ctx + PKT_WP_OFF, 0x10))
        if size:
            u = wp - base
            if u > used:
                used, worst = u, 100.0 * u / size
    return used, worst


def stats(seconds=3.0):
    """Perceived FPS and draws/frame over a fresh window (no ring warm-up)."""
    t0 = time.time()
    g0 = cmd(cmd="frame_perf")["game_frames"]
    d0 = cmd(cmd="gpu_state")["gp0_draw"]
    peak = 0.0
    while time.time() - t0 < seconds:
        _, o = occupancy()
        peak = max(peak, o)
        time.sleep(0.02)
    el = time.time() - t0
    g1 = cmd(cmd="frame_perf")["game_frames"]
    d1 = cmd(cmd="gpu_state")["gp0_draw"]
    frames = g1 - g0
    return frames / el, (d1 - d0) / max(frames, 1), peak


def build_is_live_tunable():
    """False when game.toml bakes the cone into immediates (writes do nothing)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(root, "game.toml")) as fh:
            return "widescreen-frustum-cone-h" not in fh.read()
    except OSError:
        return True             # can't tell; don't block the user


class Holder(threading.Thread):
    """Re-apply d, because the game periodically restores the stock angles."""

    daemon = True

    def __init__(self):
        super().__init__()
        self.d = None
        self.reverts = 0
        self.stop = threading.Event()

    def run(self):
        while not self.stop.wait(0.5):
            if self.d is None:
                continue
            try:
                cur, _ = get_d()
                if cur != self.d:
                    self.reverts += 1
                    set_d(self.d)
            except Exception:
                pass            # game restarting / not up yet; try again


def show(holder, d):
    fps, draws, occ = stats()
    note = f"   [game reverted it {holder.reverts}x, re-applied]" if holder.reverts else ""
    print(f"  d={d:<4} game_fps {fps:5.2f}   draws/frame {draws:6.0f}   "
          f"packet buffer {occ:4.1f}%{note}")
    holder.reverts = 0


def main(argv):
    once = "--once" in argv
    args = [a for a in argv if not a.startswith("-")]

    try:
        cmd(cmd="ping")
    except OSError:
        print("error: no game on 127.0.0.1:4370 -- start it with `sh run.sh` first")
        return 1

    if not build_is_live_tunable():
        print("error: this build BAKES the cone into the recompiled code")
        print("       (game.toml has widescreen-frustum-cone-h0/h1).")
        print("       Writing the angle RAM would silently do nothing.")
        print("       Remove those two patches, rebuild, and run this again:")
        print("         sh tools/regen.sh && sh build.sh && sh tools/compile_static_overlays.sh")
        return 2

    cur, raw = get_d()
    print(f"connected. angles {raw} -> current d = {cur}")

    if once:
        if not args:
            print("error: --once needs a value")
            return 2
        set_d(int(args[0]))
        print(f"set d={int(args[0])} (one shot -- the game may revert it)")
        return 0

    holder = Holder()
    holder.start()

    if args:                                    # non-interactive: set and hold
        d = int(args[0])
        holder.d = d
        set_d(d)
        print(f"holding d={d}. Ctrl-C to stop.\n")
        try:
            while True:
                show(holder, d)
        except KeyboardInterrupt:
            print("\nstopped holding; the game will drift back to stock d=0.")
        return 0

    print("type a value for d (e.g. 30), or 'q' to quit.")
    print("the value is HELD until you change it.\n")
    try:
        while True:
            try:
                line = input("d> ").strip()
            except EOFError:
                break
            if line.lower() in ("q", "quit", "exit"):
                break
            if not line:
                if holder.d is not None:
                    show(holder, holder.d)
                continue
            try:
                d = int(line)
            except ValueError:
                print("  not a number")
                continue
            holder.d = d
            set_d(d)
            time.sleep(0.6)                     # let a frame or two rebuild
            show(holder, d)
    except KeyboardInterrupt:
        pass
    holder.stop.set()
    print("done. the game will drift back to stock d=0 on its own.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
