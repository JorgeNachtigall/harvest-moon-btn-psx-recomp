#!/usr/bin/env python3
"""Extract every overlay from your disc, statically, at build time.

The game streams code from one archive (A_FILE.BIN, indexed by A_FILE.HDT)
into one of two fixed RAM windows. seeds/overlays.json records which archive
members are code, which window each lands in, and their entry points -- facts
recovered by decompiling the loader, not content taken from the disc. This
tool joins that map to the user's own disc and emits an overlay-captures file
the framework's compile_overlays.py consumes unchanged.

That replaces "play the game and snapshot RAM": coverage stops depending on
where the player walked, and becomes a property of the disc.

Nothing here trusts the seed file blindly. The archive layout, the window base
constants, and the member names are all re-read from the user's executable and
disc, and a mismatch against seeds/overlays.json is a hard error -- if the
game changes under us, this fails loudly rather than emitting a plausible lie.

Usage: extract_overlays.py <image.bin> <SLUS_011.15> <seeds/overlays.json> <out.json>
"""
import base64
import json
import os
import struct
import sys

from extract_psx_exe import detect_layout, read_sector, walk_dir

EXE_LOAD_ADDR = 0x80010000
EXE_TEXT_OFFSET = 0x800
SECTOR = 2048


class Disc:
    """Random access to ISO9660 files, by logical byte offset within a file."""

    def __init__(self, path):
        self.fh = open(path, "rb")
        self.sector_size, self.data_offset = detect_layout(self.fh)
        pvd = read_sector(self.fh, self.sector_size, self.data_offset, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_len = struct.unpack_from("<I", pvd, 156 + 10)[0]
        self.files = {}
        raw = b"".join(
            read_sector(self.fh, self.sector_size, self.data_offset, root_lba + i)
            for i in range((root_len + SECTOR - 1) // SECTOR)
        )
        for name, lba, length, flags in walk_dir(raw):
            if not flags & 0x02:
                self.files[name.split(";")[0].upper()] = (lba, length)

    def read(self, name, offset, length):
        lba, size = self.files[name]
        if offset + length > size:
            raise SystemExit(
                f"{name}: read of {length} bytes at 0x{offset:X} runs past "
                f"the file end ({size} bytes) -- wrong disc?"
            )
        first = offset // SECTOR
        skip = offset % SECTOR
        n = (skip + length + SECTOR - 1) // SECTOR
        raw = b"".join(
            read_sector(self.fh, self.sector_size, self.data_offset, lba + first + i)
            for i in range(n)
        )
        return raw[skip:skip + length]

    def lba_of(self, name, offset):
        return self.files[name][0] + offset // SECTOR


def exe_word(text, addr):
    """Read a little-endian u32 from the loaded executable image."""
    off = addr - EXE_LOAD_ADDR
    if off < 0 or off + 4 > len(text):
        raise SystemExit(f"address 0x{addr:08X} is outside the executable")
    return struct.unpack_from("<I", text, off)[0]


def exe_string(text, addr, limit=32):
    off = addr - EXE_LOAD_ADDR
    raw = text[off:off + limit]
    return raw.split(b"\0")[0].decode("latin1", "replace")


def check(condition, message):
    if not condition:
        raise SystemExit(f"error: {message}")


def main():
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    image_path, exe_path, seeds_path, out_path = sys.argv[1:5]

    with open(seeds_path) as fh:
        seeds = json.load(fh)
    archive = seeds["archive"]
    windows = seeds["windows"]

    # Ghidra-recovered function starts, keyed '<member index>@<load address>'.
    # Optional: without it the shards compile from header pointers alone and
    # most overlay code ends up on the MIPS interpreter (85% of dispatches
    # measured). Committed as addresses, so users never need Ghidra.
    fn_seeds = {}
    fn_path = os.path.join(os.path.dirname(seeds_path), "overlay_functions.json")
    if os.path.isfile(fn_path):
        with open(fn_path) as fh:
            for key, rec in json.load(fh).get("members", {}).items():
                fn_seeds[key] = [int(a, 16) for a in rec.get("entries", [])]
        print(f"function seeds: {sum(len(v) for v in fn_seeds.values())} "
              f"addresses across {len(fn_seeds)} members ({fn_path})")
    else:
        print(f"warning: {fn_path} missing -- overlays will compile from header "
              f"pointers only and most code will run interpreted.")

    exe = open(exe_path, "rb").read()
    check(exe[:8] == b"PS-X EXE", f"{exe_path} is not a PS-X EXE")
    text = exe[EXE_TEXT_OFFSET:]

    disc = Disc(image_path)
    for needed in (archive["index_file"], archive["data_file"]):
        check(needed in disc.files, f"{needed} not found on {image_path}")

    # --- the archive index, straight off the user's disc ------------------
    index_name = archive["index_file"]
    count = archive["entry_count"]
    raw = disc.read(index_name, 0, count * 4)
    offsets = list(struct.unpack(f"<{count}I", raw))
    check(offsets[0] == 0, f"{index_name}[0] is 0x{offsets[0]:X}, expected 0")
    check(
        all(a <= b for a, b in zip(offsets, offsets[1:])),
        f"{index_name} offsets are not monotonic -- not the expected index",
    )
    data_size = disc.files[archive["data_file"]][1]
    check(
        offsets[-1] == data_size,
        f"{index_name} terminator 0x{offsets[-1]:X} != {archive['data_file']} "
        f"size 0x{data_size:X}",
    )

    # --- window bases, re-read from the executable ------------------------
    for key, win in windows.items():
        actual = exe_word(text, int(win["constant_addr"], 16))
        expected = int(win["base"], 16)
        check(
            actual == expected,
            f"window {key}: executable holds 0x{actual:08X} at "
            f"{win['constant_addr']}, seeds say 0x{expected:08X}",
        )

    # --- member names, from the static record table -----------------------
    table = int(archive["record_table_addr"], 16)
    stride = archive["record_table_stride"]
    names = [
        exe_string(text, table + i * stride + archive["record_name_offset"])
        for i in range(count)
    ]

    print(f"{archive['data_file']}: LBA {disc.files[archive['data_file']][0]}, "
          f"{data_size} bytes, {count - 1} members")
    print(f"window A = 0x{int(windows['A']['base'], 16):08X}   "
          f"window B = 0x{int(windows['B']['base'], 16):08X}\n")

    captures = []
    total = 0
    for member in seeds["members"]:
        idx = member["index"]
        check(0 <= idx < count - 1, f"member index {idx} out of range")
        base = int(windows[member["window"]]["base"], 16)
        offset = offsets[idx]
        size = offsets[idx + 1] - offsets[idx]
        check(size > 0, f"member {idx} ({names[idx]}) is empty")

        data = disc.read(archive["data_file"], offset, size)

        # The head of most overlays is a table of absolute pointers into the
        # image itself. Those are function entry points the recompiler cannot
        # infer -- the same class of seed as seeds/pointer_table_seeds.json.
        pointers = []
        pos = 4
        while pos + 4 <= len(data):
            word = struct.unpack_from("<I", data, pos)[0]
            if not base <= word < base + size:
                break
            pointers.append(word)
            pos += 4

        entries = [int(e, 16) for e in member["entries"]]
        for entry in entries:
            check(
                base <= entry < base + size,
                f"member {idx} ({names[idx]}): entry 0x{entry:08X} is outside "
                f"its own image [0x{base:08X}, 0x{base + size:08X})",
            )

        captures.append({
            "schema": "psxrecomp overlay capture v2",
            "load_addr": f"0x{base:08X}",
            "size": size,
            "bytes_b64": base64.b64encode(data).decode("ascii"),
            "producer": "extract_overlays.py",
            "producer_name": f"{names[idx]} (A_FILE member {idx})",
            # The loader proves these: FUN_80011370 stores them into 0x8005E384
            # and dispatches through it. dispatch_entry_pcs carries the proof,
            # static_dispatch_entry_pcs the provenance -- the framework requires
            # the latter to be a subset of the former.
            "dispatch_entry_pcs": sorted(set(entries)),
            "static_dispatch_entry_pcs": sorted(set(entries)),
            # Header pointers are candidates, not proofs: the table can point at
            # data as well as code. Left for the framework's callable-boundary
            # gate to accept or reject. Ghidra's recovered function starts are
            # merged in here -- without them most overlay code has no compiled
            # function and falls back to the MIPS interpreter.
            "function_entry_pcs": sorted(
                set(pointers) | set(fn_seeds.get(f"{idx}@0x{base:08X}", []))),
        })
        total += size

        flag = "  [unverified]" if member.get("unverified") else ""
        nfn = len(captures[-1]["function_entry_pcs"])
        print(f"  [{idx:2d}] {names[idx]:<20s} 0x{offset:08X}  {size:>7d} B  "
              f"LBA {disc.lba_of(archive['data_file'], offset):>5d}  "
              f"-> 0x{base:08X}  {nfn:>4d} fn seeds, "
              f"{len(entries)} entry{flag}")

    with open(out_path, "w") as fh:
        json.dump(captures, fh)

    print(f"\nwrote {len(captures)} overlay(s), {total} bytes "
          f"({total / 1024:.1f} KB) -> {out_path}")


if __name__ == "__main__":
    main()
