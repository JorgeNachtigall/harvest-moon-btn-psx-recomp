#!/usr/bin/env python3
"""Fold Ghidra-recovered overlay function starts into the overlay captures.

The overlay shards are compiled by walking outward from seeds. Without this,
the only seeds are the mode-switch entry points and header pointer tables in
seeds/overlays.json -- a few hundred -- so anything reached only through an
indirect call is never discovered and falls back to the MIPS interpreter.

This adds every function start Ghidra found in each member's raw image, keeping
only addresses inside that member's own [load_addr, load_addr+size) range.

Usage: merge_overlay_seeds.py build/overlay_static.json build/overlay_seeds [out.json]
"""
import json
import os
import sys


def load_seeds(path):
    out = []
    if not os.path.isfile(path):
        return out
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        try:
            out.append(int(line, 16))
        except ValueError:
            pass
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    caps_path, seed_root = sys.argv[1], sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else caps_path

    caps = json.load(open(caps_path))

    # Map each capture to its Ghidra seed directory by the dumped binary's name.
    by_dir = {}
    for name in sorted(os.listdir(seed_root)):
        d = os.path.join(seed_root, name)
        if os.path.isdir(d):
            by_dir[name] = load_seeds(os.path.join(d, 'functions.txt'))

    total_added = 0
    for cap in caps:
        base = int(cap['load_addr'], 16)
        size = cap['size']
        member = cap.get('producer_name', '').split(' ')[0]
        key = '%08X_%s' % (base, member.replace('\\', '_').replace('/', '_'))

        seeds = by_dir.get(key)
        if seeds is None:
            # fall back to a prefix match on the load address
            cand = [v for k, v in by_dir.items() if k.startswith('%08X_' % base)]
            seeds = max(cand, key=len) if cand else []

        inrange = sorted({a for a in seeds if base <= a < base + size})
        before = set(int(x, 16) if isinstance(x, str) else x
                     for x in cap.get('function_entry_pcs', []))
        merged = sorted(before | set(inrange))
        cap['function_entry_pcs'] = merged
        added = len(merged) - len(before)
        total_added += added
        print('  %-24s base 0x%08X  had %4d  +%4d ghidra  -> %4d'
              % (member[:24], base, len(before), added, len(merged)))

    json.dump(caps, open(out_path, 'w'))
    print('\nadded %d seeds across %d captures -> %s'
          % (total_added, len(caps), out_path))


if __name__ == '__main__':
    main()
