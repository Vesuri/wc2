#!/usr/bin/env python3
"""Compare the code of two Borland VROOMM executables (PC WC1 and WC2) function by function.

  python3 tools/wc_compare.py WC.EXE WC2.EXE [--csv OUT.csv]

Method (all heuristics are counted in the output):
- Code units: each resident code segment below DGROUP (segment bases are the relocated
  words; DGROUP is the `mov dx,imm` at the entry) except overlay stubs, and each overlay's
  code. Names use the original's numbering: `R:ssss:oooo` (resident, load paragraph:offset),
  `O:ssss+oooo` (overlay whose stub is at load paragraph ssss, offset in its code).
- Functions: a unit is decoded linearly with capstone (16-bit) and split before every
  `push bp; mov bp,sp` or `enter`. Code without a frame stays with the preceding function.
- Tokens: mnemonic plus operand shapes, every constant, displacement and branch target
  masked (`--norm loose`). `--norm canon` (default) also removes what the compiler change
  (Turbo C++ 1990 8086 code -> Borland C++ 1991 186 code) alters: general registers become
  `r16`/`r8`, displacement signs go, `mov r,#; push r` folds to `push #`, runs of
  `shl/shr/sar r,#` fold to one, callee-saved `push/pop si|di` and caller stack cleanup
  (`pop cx`, `add sp,#` after a call) are dropped. Exact matches compare token sequences;
  fuzzy matches take the best SequenceMatcher ratio among candidates sharing 4-gram
  shingles.
- `--control C.EXE`: also match B against an unrelated program built with the same
  compiler family (the installer) to measure false matches per band.
- Coverage is reported in WC2 code bytes; one WC1 function may match several WC2 ones.
"""
import argparse
import collections
import csv
import difflib
import hashlib
import re
import struct
import sys
import os
import zlib

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bc_exe  # noqa: E402

MIN_INSNS = 6
SHINGLE = 4
FUZZY_BANDS = (0.95, 0.85, 0.70)

_md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
_num = re.compile(r'(?<![\w])(0x[0-9a-f]+|\d+)(?![\w])')


_r16 = re.compile(r'\b(ax|bx|cx|dx|si|di)\b')
_r8 = re.compile(r'\b(al|ah|bl|bh|cl|ch|dl|dh)\b')
NORM = 'canon'


def tokenize(op_str):
	return _num.sub('#', op_str)


def canon(seq):
	"""seq: list of (mnemonic, op_str) -> compiler-invariant tokens."""
	out = []
	prev_call = False
	for mn, ops in seq:
		if mn in ('push', 'pop') and ops in ('si', 'di'):
			continue
		if prev_call and ((mn == 'pop' and ops == 'cx') or (mn == 'add' and ops.startswith('sp, '))):
			continue
		prev_call = mn in ('call', 'lcall')
		o = _num.sub('#', ops).replace(' - #', ' + #')
		o = _r8.sub('r8', _r16.sub('r16', o))
		t = f'{mn} {o}'
		if t == 'push r16' and out and out[-1].startswith('mov r') and out[-1].endswith(', #'):
			out[-1] = 'push #'
			continue
		if mn in ('shl', 'shr', 'sar', 'sal') and out and out[-1] == t:
			continue
		out.append(t)
	return tuple(out)


class Func:
	__slots__ = ('name', 'unit', 'size', 'tokens', 'raw', 'n386')

	def __init__(self, name, unit, size, tokens, raw, n386):
		self.name, self.unit, self.size, self.tokens, self.raw, self.n386 = name, unit, size, tokens, raw, n386


def dgroup(x):
	e = x.cs * 16 + x.ip
	if x.image[e] != 0xBA:
		raise SystemExit('entry does not start with mov dx,DGROUP')
	return struct.unpack_from('<H', x.image, e + 1)[0]


def units(x):
	dg = dgroup(x)
	segs = set()
	for off, seg in x.relocs:
		v = struct.unpack_from('<H', x.image, seg * 16 + off)[0]
		if v < dg:
			segs.add(v)
	segs.add(0)
	segs = sorted(segs) + [dg]
	stubs = {o.stub_off for o in x.overlays}
	out = []
	for a, b in zip(segs, segs[1:]):
		if a * 16 in stubs:
			continue
		out.append((f'R:{a:04X}', f'R:{a:04X}:{{:04X}}', x.image[a * 16:b * 16]))
	for o in x.overlays:
		sid = o.stub_off // 16
		out.append((f'O:{sid:04X}', f'O:{sid:04X}+{{:04X}}', x.overlay_code(o)))
	return out


def split(unit, fmt, code):
	insns = list(_md.disasm_lite(code, 0))
	decoded = sum(i[1] for i in insns)
	starts = [0]
	for k, (addr, size, mn, ops) in enumerate(insns):
		if addr == 0:
			continue
		if mn == 'enter' or (mn == 'push' and ops == 'bp' and k + 1 < len(insns)
				and insns[k + 1][2] == 'mov' and insns[k + 1][3] == 'bp, sp'):
			starts.append(k)
	starts.append(len(insns))
	funcs = []
	for a, b in zip(starts, starts[1:]):
		seq = insns[a:b]
		if not seq:
			continue
		lo = seq[0][0]
		hi = seq[-1][0] + seq[-1][1]
		if NORM == 'canon':
			toks = canon([(mn, ops) for _, _, mn, ops in seq])
		else:
			toks = tuple(f'{mn} {tokenize(ops)}' for _, _, mn, ops in seq)
		n386 = sum(1 for _, _, mn, ops in seq if re.search(r'\be[abcd]x\b|\be[sd]i\b|\bebp\b|\besp\b', ops)
			or mn in ('movzx', 'movsx', 'shld', 'shrd', 'bt', 'bts', 'btr', 'setne', 'sete'))
		funcs.append(Func(fmt.format(lo), unit, hi - lo, toks, code[lo:hi], n386))
	return funcs, decoded, len(code)


def analyse(path):
	x = bc_exe.load(path)
	funcs, dec, tot = [], 0, 0
	for unit, fmt, code in units(x):
		f, d, t = split(unit, fmt, code)
		funcs += f
		dec += d
		tot += t
	return x, funcs, dec, tot


def shingles(toks):
	return {zlib.crc32('\n'.join(toks[i:i + SHINGLE]).encode())
		for i in range(max(1, len(toks) - SHINGLE + 1))}


def main():
	ap = argparse.ArgumentParser()
	ap.add_argument('a', help='older executable (WC1)')
	ap.add_argument('b', help='newer executable (WC2)')
	ap.add_argument('--csv', help='write per-function matches of b here')
	ap.add_argument('--norm', choices=('canon', 'loose'), default='canon')
	ap.add_argument('--control', help='unrelated executable of the same compiler family')
	args = ap.parse_args()
	global NORM
	NORM = args.norm
	if args.control:
		_, fc, _, _ = analyse(args.control)
		_, fb, _, _ = analyse(args.b)
		report(fc, fb, None, 'control')
		print()

	xa, fa, da, ta = analyse(args.a)
	xb, fb, db, tb = analyse(args.b)
	for name, x, f, d, t in (('A', xa, fa, da, ta), ('B', xb, fb, db, tb)):
		n386 = sum(g.n386 for g in f)
		print(f'{name}: {len(f)} functions in {len({g.unit for g in f})} units, {t} code bytes, '
			f'{d} decoded linearly, {n386} instructions using 386 registers or opcodes')
	report(fa, fb, args.csv, 'A')


def report(fa, fb, csv_path, label):

	exact_a = collections.defaultdict(list)
	for g in fa:
		exact_a[hashlib.sha1('\n'.join(g.tokens).encode()).digest()].append(g)
	raw_a = {g.raw for g in fa}
	index = collections.defaultdict(set)
	for i, g in enumerate(fa):
		if len(g.tokens) >= MIN_INSNS:
			for s in shingles(g.tokens):
				index[s].add(i)

	rows = []
	for g in fb:
		best, ratio, kind = None, 0.0, 'none'
		if len(g.tokens) < MIN_INSNS:
			kind = 'tiny'
		else:
			h = hashlib.sha1('\n'.join(g.tokens).encode()).digest()
			if h in exact_a:
				best, ratio = exact_a[h][0], 1.0
				kind = 'identical' if g.raw in raw_a else 'exact'
			else:
				cnt = collections.Counter()
				for s in shingles(g.tokens):
					for i in index.get(s, ()):
						cnt[i] += 1
				for i, _ in cnt.most_common(8):
					c = fa[i]
					sm = difflib.SequenceMatcher(None, g.tokens, c.tokens, autojunk=False)
					if sm.real_quick_ratio() <= ratio or sm.quick_ratio() <= ratio:
						continue
					r = sm.ratio()
					if r > ratio:
						best, ratio = c, r
				kind = 'fuzzy'
		rows.append((g, best, ratio, kind))

	def band(r, k):
		if k == 'tiny':
			return 'tiny (< %d insns)' % MIN_INSNS
		if k in ('identical', 'exact'):
			return k
		for t in FUZZY_BANDS:
			if r >= t:
				return f'similar >= {t:.2f}'
		return 'no match'

	order = ['identical', 'exact'] + [f'similar >= {t:.2f}' for t in FUZZY_BANDS] + \
		['no match', 'tiny (< %d insns)' % MIN_INSNS]
	agg = collections.OrderedDict((k, [0, 0]) for k in order)
	for g, c, r, k in rows:
		a = agg[band(r, k)]
		a[0] += 1
		a[1] += g.size
	tot = sum(g.size for g in fb)
	print(f'\nB functions against {label} ({tot} B in functions, norm {NORM}):')
	for k, (n, sz) in agg.items():
		print(f'  {k:22s} {n:5d} functions {sz:7d} B {100 * sz / tot:5.1f}%')

	if label == 'control':
		return
	used = {c.name: c.size for g, c, r, k in rows if c is not None and r >= 0.85}
	ta = sum(g.size for g in fa)
	print(f'\nA code with a >= 0.85 counterpart in B: {sum(used.values())} of {ta} B '
		f'({100 * sum(used.values()) / ta:.1f}%)')
	# per-unit view: share of each B unit at >= 0.85, and the A unit it mostly matches
	print('\nB units (bytes; share >= 0.85; share 0.70-0.85; main A unit by bytes >= 0.85):')
	per = collections.OrderedDict()
	for g, c, r, k in rows:
		u = per.setdefault(g.unit, [0, 0, 0, collections.Counter()])
		u[0] += g.size
		if c is not None and r >= 0.85:
			u[1] += g.size
			u[3][c.unit] += g.size
		elif c is not None and r >= 0.70:
			u[2] += g.size
	hist = collections.Counter()
	for unit, (sz, m, m7, cu) in per.items():
		share = m / sz if sz else 0
		hist[min(4, int(share * 5))] += sz
		top = ', '.join(f'{a} {n}' for a, n in cu.most_common(2))
		print(f'  {unit} {sz:6d} {100 * share:5.1f}% {100 * m7 / sz:5.1f}%  {top}')
	print('\nB code bytes by unit share >= 0.85: ' + ', '.join(
		f'{20 * i}-{20 * i + 20}%: {hist[i]}' for i in range(5)))

	if csv_path:
		with open(csv_path, 'w', newline='') as fh:
			w = csv.writer(fh)
			w.writerow(['b_func', 'b_size', 'b_insns', 'kind', 'ratio', 'a_func', 'a_size'])
			for g, c, r, k in rows:
				w.writerow([g.name, g.size, len(g.tokens), k, f'{r:.3f}', c.name if c else '',
					c.size if c else ''])


if __name__ == '__main__':
	main()
