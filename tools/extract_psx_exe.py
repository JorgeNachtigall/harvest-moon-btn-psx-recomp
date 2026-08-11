#!/usr/bin/env python3
"""Extract a file (typically the PS-X EXE) from a PS1 disc image.

Handles MODE2/2352 (the common PSX raw layout) and plain 2048-byte ISO
images by auto-detecting the sector size from the ISO9660 signature.

Usage: extract_psx_exe.py <image.bin> <FILENAME> <output>
"""
import struct
import sys


def detect_layout(fh):
    """Return (sector_size, data_offset) by locating 'CD001' at LBA 16."""
    for sector_size, data_offset in ((2352, 24), (2048, 0), (2352, 16), (2336, 8)):
        fh.seek(16 * sector_size + data_offset)
        block = fh.read(6)
        if len(block) == 6 and block[1:6] == b"CD001":
            return sector_size, data_offset
    raise SystemExit("could not find an ISO9660 PVD — not a recognised disc image")


def read_sector(fh, sector_size, data_offset, lba):
    fh.seek(lba * sector_size + data_offset)
    return fh.read(2048)


def read_extent(fh, sector_size, data_offset, lba, length):
    out = bytearray()
    n = (length + 2047) // 2048
    for i in range(n):
        out += read_sector(fh, sector_size, data_offset, lba + i)
    return bytes(out[:length])


def walk_dir(records):
    """Yield (name, lba, length, flags) from a directory extent."""
    pos = 0
    while pos < len(records):
        dr_len = records[pos]
        if dr_len == 0:
            # Padding to the end of this logical sector; jump to the next one.
            pos = (pos // 2048 + 1) * 2048
            if pos >= len(records):
                return
            continue
        rec = records[pos:pos + dr_len]
        lba = struct.unpack_from("<I", rec, 2)[0]
        length = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        name_len = rec[32]
        name = rec[33:33 + name_len].decode("ascii", "replace")
        yield name, lba, length, flags
        pos += dr_len


def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    image, wanted, output = sys.argv[1], sys.argv[2].upper(), sys.argv[3]

    with open(image, "rb") as fh:
        sector_size, data_offset = detect_layout(fh)
        print(f"layout: {sector_size}-byte sectors, user data at +{data_offset}")

        pvd = read_sector(fh, sector_size, data_offset, 16)
        root = pvd[156:156 + 34]
        root_lba = struct.unpack_from("<I", root, 2)[0]
        root_len = struct.unpack_from("<I", root, 10)[0]
        print(f"root directory: LBA {root_lba}, {root_len} bytes")

        entries = read_extent(fh, sector_size, data_offset, root_lba, root_len)
        for name, lba, length, flags in walk_dir(entries):
            base = name.split(";")[0].upper()
            if base == wanted or name.upper() == wanted:
                print(f"found {name}: LBA {lba}, {length} bytes")
                data = read_extent(fh, sector_size, data_offset, lba, length)
                with open(output, "wb") as out:
                    out.write(data)
                describe(data)
                return
        print(f"'{wanted}' not found. Root directory contains:")
        for name, lba, length, flags in walk_dir(entries):
            kind = "dir " if flags & 0x02 else "file"
            print(f"  {kind} {name:24s} LBA {lba:8d}  {length:10d} bytes")
        raise SystemExit(1)


def describe(data):
    """Print the PS-X EXE header fields the recompiler config needs."""
    if data[:8] != b"PS-X EXE":
        print("WARNING: no 'PS-X EXE' magic — this is not a PSX executable")
        return
    pc0, gp0, t_addr, t_size = struct.unpack_from("<IIII", data, 0x10)
    s_addr, s_size = struct.unpack_from("<II", data, 0x30)
    print("\nPS-X EXE header:")
    print(f"  entry_pc     = 0x{pc0:08X}")
    print(f"  initial_gp   = 0x{gp0:08X}")
    print(f"  load_address = 0x{t_addr:08X}   (Ghidra import base)")
    print(f"  text_size    = 0x{t_size:08X}   ({t_size} bytes)")
    print(f"  stack_base   = 0x{s_addr:08X}   (size 0x{s_size:08X})")
    print(f"  text payload starts at file offset 0x800")


if __name__ == "__main__":
    main()
