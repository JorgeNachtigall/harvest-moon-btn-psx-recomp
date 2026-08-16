#!/usr/bin/env python3
"""Migrate a .pst save state to the shared 192,000-byte packet buffer.

A .pst is a whole-RAM snapshot, so it also snapshots the render contexts that
FUN_80012598 filled in at boot. States captured before the "pktbuf-*" patches
in game.toml therefore still describe TWO 96,000-byte packet buffers, and the
game keeps using them after the state is loaded -- the patched init never runs
again. At d=60 that is exactly the configuration that overruns and crashes.

This rewrites the four fields the patched init would have written. Normal play
(boot -> memory card) needs none of this; only debug save states do.

Usage:  python3 tools/migrate_savestate_pktbuf.py build/state_*.pst
        python3 tools/migrate_savestate_pktbuf.py --check build/state_*.pst
"""
import struct
import sys

RAM_ORIGIN = 0x250          # RAM base inside the .pst container
CTX = (0x8005E5E8, 0x8005E71C)
OFF_WRITE_PTR, OFF_SIZE, OFF_BASE = 0x118, 0x11C, 0x124

SHARED_BASE = 0x801C2440    # arena + 0x4290, unchanged
SHARED_SIZE = 192000        # was 2 x 96000
OLD_SIZE = 96000


def field(ctx, off):
    return RAM_ORIGIN + (ctx - 0x80000000) + off


def main(argv):
    check = "--check" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        print(__doc__)
        return 2
    rc = 0
    for path in paths:
        with open(path, "rb") as fh:
            buf = bytearray(fh.read())
        cur = [struct.unpack_from("<I", buf, field(c, OFF_SIZE))[0] for c in CTX]
        if all(s == SHARED_SIZE for s in cur):
            print(f"{path}: already migrated")
            continue
        if not all(s == OLD_SIZE for s in cur):
            print(f"{path}: UNEXPECTED sizes {cur} -- refusing to touch it")
            rc = 1
            continue
        if check:
            print(f"{path}: needs migration (sizes {cur})")
            rc = 1
            continue
        for c in CTX:
            struct.pack_into("<I", buf, field(c, OFF_SIZE), SHARED_SIZE)
            struct.pack_into("<I", buf, field(c, OFF_BASE), SHARED_BASE)
            struct.pack_into("<I", buf, field(c, OFF_WRITE_PTR), SHARED_BASE)
        with open(path + ".pre-pktbuf", "wb") as fh:
            fh.write(open(path, "rb").read())
        with open(path, "wb") as fh:
            fh.write(buf)
        print(f"{path}: migrated (backup at {path}.pre-pktbuf)")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
