#!/usr/bin/env python3
"""Compare a span of WC2.EXE's resident code with a span of PC WC1's (docs/wc1-cross-reference.md).

  wc1_span.py [--wc1 tmp/wc1/disk01/WC.EXE] [--wc2 ref/WING2/WC2.EXE] WC2_SPAN WC1_SPAN ...

A span is `R:seg:off-off2` (resident load paragraph, start and end offset, end exclusive),
the original's numbering as in `make compare`. Spans are given in pairs (WC2, WC1). Each is
decoded linearly (capstone, 16-bit) and tokenised with `tools/wc_compare.py`'s `canon`
normalisation (constants, displacements and branch targets masked; the Turbo C++ to
Borland C++ differences folded). Printed per pair: instruction counts, whether the byte
spans are identical, whether the token sequences are the same (exact), and their
SequenceMatcher ratio.

Why spans: `wc_compare.py` splits functions at Borland prologues, so frameless helpers
(near subroutines in the hand-written maths module) are joined to the function before
them, and a hot helper's function-level match can be another function's. A span compares
the helper alone.
"""
import argparse
import difflib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import bc_exe  # noqa: E402
import wc_compare  # noqa: E402

SPAN = re.compile(r'^R:([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})-([0-9A-Fa-f]{4})$')


def span(x, text):
	m = SPAN.match(text)
	if not m:
		sys.exit(f'{text}: expected R:seg:off-off2')
	seg, lo, hi = (int(g, 16) for g in m.groups())
	if hi <= lo:
		sys.exit(f'{text}: empty span')
	code = x.image[seg * 16 + lo:seg * 16 + hi]
	insns = list(wc_compare._md.disasm_lite(code, lo))
	if sum(i[1] for i in insns) != len(code):
		sys.exit(f'{text}: linear decode does not cover the span (data in code, or a bad boundary)')
	return code, wc_compare.canon([(mn, ops) for _, _, mn, ops in insns])


def main():
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument('spans', nargs='+')
	ap.add_argument('--wc1', default=os.path.join(ROOT, 'tmp/wc1/disk01/WC.EXE'))
	ap.add_argument('--wc2', default=os.path.join(ROOT, 'ref/WING2/WC2.EXE'))
	args = ap.parse_args()
	if len(args.spans) % 2:
		sys.exit('spans come in pairs: WC2_SPAN WC1_SPAN')
	wc2, wc1 = bc_exe.load(args.wc2), bc_exe.load(args.wc1)
	for b_text, a_text in zip(args.spans[::2], args.spans[1::2]):
		b_code, b_tok = span(wc2, b_text)
		a_code, a_tok = span(wc1, a_text)
		ratio = difflib.SequenceMatcher(None, a_tok, b_tok, autojunk=False).ratio()
		kind = 'identical bytes' if a_code == b_code else 'exact' if a_tok == b_tok else 'fuzzy'
		print(f'WC2 {b_text} ({len(b_tok)} tokens) ~ WC1 {a_text} ({len(a_tok)} tokens): '
			f'{kind}, ratio {ratio:.3f}')
	return 0


if __name__ == '__main__':
	sys.exit(main())
