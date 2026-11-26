#!/usr/bin/env python3
"""Compare the 3D maths module's tables in WC2, PC WC1 and the CD32 WC1 (docs/wc1-cross-reference.md).

  cd32_tables.py --cd32 PATH/wing.english [--wc2 ref/WING2/WC2.EXE] [--wc1 tmp/wc1/disk01/WC.EXE]

The CD32 file is the English executable the Wing Commander project pins (its
`inputs.sha256`, SHA-256 0935…e657, checked here); it is never copied into this repository.
Its hunk 0 starts at file offset 2Ch, so `E:x` is file offset x + 2Ch (that project's
docs/internals.md, "Input identity and executable layout").

Tables (each read by the routine named; the addresses were found by reading the routines):
- cosine, 91 entries Q8, degrees 0..90: WC2 DS:0BD4 (`R:0E9B:0101`, `:015D`), WC1 DS:3C92
  (`R:077E:0109`..), CD32 `E:2bdc2` (PC-relative from `E:2bf7a`, `E:2bfe4`), big-endian words;
- arccosine, 257 entries, degrees by ratio 0..256: WC2 DS:0C8A (`R:0E9B:01B9`, `:01E3`),
  WC1 DS:3D48 (`R:077E:01EB`..), CD32 `E:2be78` (from `E:2c04a`, `E:2c07e`), bytes.

Prints, per table, whether the three agree value for value, and the first difference.
DGROUP is the entry's `mov dx,imm` (tools/wc_compare.py); WC2 1976h, WC1 1231h.
"""
import argparse
import hashlib
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import bc_exe  # noqa: E402
import wc_compare  # noqa: E402

CD32_SHA256 = '093505483aed4c9dbd1b97484c3336e92fdb156be9c15a67ed0199bd4dade657'
HUNK0 = 0x2C

# name, count, WC2 DS offset, WC1 DS offset, CD32 E offset, CD32 element format
TABLES = (
	('cosine', 91, 0x0BD4, 0x3C92, 0x2BDC2, 'h'),
	('arccosine', 257, 0x0C8A, 0x3D48, 0x2BE78, 'b'),
)


def ds_words(x, off, n):
	base = wc_compare.dgroup(x) * 16
	return list(struct.unpack_from(f'<{n}h', x.image, base + off))


def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('--cd32', required=True)
	ap.add_argument('--wc2', default=os.path.join(ROOT, 'ref/WING2/WC2.EXE'))
	ap.add_argument('--wc1', default=os.path.join(ROOT, 'tmp/wc1/disk01/WC.EXE'))
	args = ap.parse_args()
	cd = open(args.cd32, 'rb').read()
	if hashlib.sha256(cd).hexdigest() != CD32_SHA256:
		sys.exit(f'{args.cd32}: not the pinned English CD32 executable')
	wc2, wc1 = bc_exe.load(args.wc2), bc_exe.load(args.wc1)
	bad = 0
	for name, n, o2, o1, oc, fmt in TABLES:
		a = ds_words(wc2, o2, n)
		b = ds_words(wc1, o1, n)
		c = list(struct.unpack_from(f'>{n}{fmt}', cd, HUNK0 + oc))
		same = a == b == c
		first = next((i for i in range(n) if not a[i] == b[i] == c[i]), None)
		print(f'{name} ({n} entries, {a[0]}..{a[-1]}): WC2 DS:{o2:04X}, WC1 DS:{o1:04X}, '
			f'CD32 E:{oc:05x}: ' + ('equal' if same else
			f'differ first at {first}: {a[first]} {b[first]} {c[first]}'))
		bad += not same
	return 1 if bad else 0


if __name__ == '__main__':
	sys.exit(main())
