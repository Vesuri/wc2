#!/usr/bin/env python3
"""Origin resource container of Wing Commander I and II (`.V00`, `.VGA`, `.DRV`, `.000`, ...).

  python3 tools/origin_pak.py list FILE...
  python3 tools/origin_pak.py unpack SRC DST          rebuild SRC with every entry unpacked
  python3 tools/origin_pak.py verify DISKDIR GAMEDAT  rebuild every disk file, compare with
                                                      the installer's unpacked copy

Layout (DERIVED; `verify` against WC2's installed GAMEDAT is the check):
  u32 total file size
  table of u32 entries: low 24 bits offset, high byte flags; it ends at the lowest offset
  flags & 0xC0 == 0: packed: u32 unpacked size, then LZW (LSB-first codes of 9..12 bits,
    256 = reset dictionary and width, 257 = end, no early width change)
  flags & 0xC0 != 0: stored; the installer sets 0xC0 on every entry it unpacks
  flags == 0xFF: alias of the entry at the same offset (or of the file end); kept as is
`SPEECH.S00` is not handled: its entries are flagged 0xE0 on disk, yet the installer
doubles their size (a speech codec; the installer has a "Speech de-compression error").
The installer leaves some files packed (`verify` counts them).
WC1 marks packed entries 0x01 and WC2 0x20; the payloads of a shared file are identical.
"""
import os
import struct
import sys


def lzw(data):
	out = bytearray()
	dic = [bytes([i]) for i in range(256)] + [b'', b'']
	pos = bits = nb = 0
	width = 9
	prev = None
	while True:
		while nb < width:
			if pos >= len(data):
				raise ValueError('LZW stream ends without an end code')
			bits |= data[pos] << nb
			pos += 1
			nb += 8
		code = bits & ((1 << width) - 1)
		bits >>= width
		nb -= width
		if code == 256:
			dic = dic[:258]
			width = 9
			prev = None
			continue
		if code == 257:
			return bytes(out)
		if code < len(dic):
			e = dic[code]
		elif code == len(dic) and prev is not None:
			e = prev + prev[:1]
		else:
			raise ValueError(f'bad LZW code {code} at output {len(out)}')
		out += e
		if prev is not None and len(dic) < 4096:
			dic.append(prev + e[:1])
		prev = e
		if len(dic) >= (1 << width) and width < 12:
			width += 1


def parse(b):
	"""-> list of (offset, flags, end) in table order."""
	total = struct.unpack_from('<I', b, 0)[0]
	if total != len(b):
		raise ValueError(f'size field {total} != file size {len(b)}')
	ents = []
	first = len(b)
	off = 4
	while off < first:
		v = struct.unpack_from('<I', b, off)[0]
		o, fl = v & 0xFFFFFF, v >> 24
		ents.append((o, fl))
		if o:
			first = min(first, o)
		off += 4
	starts = sorted({o for o, _ in ents if o} | {len(b)})
	return [(o, fl, starts[starts.index(o) + 1] if 0 < o < len(b) else o) for o, fl in ents]


def entry_data(b, o, fl, end):
	if fl & 0xC0:
		return b[o:end]
	size = struct.unpack_from('<I', b, o)[0]
	d = lzw(b[o + 4:end])
	if len(d) != size:
		raise ValueError(f'entry at {o:#x}: unpacked {len(d)} != declared {size}')
	return d


def unpack(b):
	ents = parse(b)
	head = 4 + 4 * len(ents)
	body = bytearray()
	table = []
	done = {}
	for o, fl, end in ents:
		if not o:
			table.append(fl << 24)
			continue
		if fl == 0xFF:
			table.append(None)
			continue
		if o not in done:
			done[o] = head + len(body)
			body += entry_data(b, o, fl, end)
		table.append(done[o] | (fl | 0xC0) << 24)
	for i, (o, fl, end) in enumerate(ents):
		if fl == 0xFF:
			table[i] = (done[o] if o < len(b) else head + len(body)) | 0xFF << 24
	out = struct.pack('<I', head + len(body)) + b''.join(struct.pack('<I', t) for t in table) + body
	return out


def main():
	cmd, args = sys.argv[1], sys.argv[2:]
	if cmd == 'list':
		for p in args:
			b = open(p, 'rb').read()
			ents = parse(b)
			print(f'{p}: {len(b)} B, {len(ents)} entries, flags ' +
				' '.join(sorted({f'{fl:02X}' for _, fl, _ in ents})))
	elif cmd == 'unpack':
		open(args[1], 'wb').write(unpack(open(args[0], 'rb').read()))
	elif cmd == 'verify':
		src, inst = args
		ok = bad = skip = same = 0
		for n in sorted(os.listdir(inst)):
			sp = os.path.join(src, n)
			if not os.path.exists(sp):
				continue
			b = open(sp, 'rb').read()
			ib = open(os.path.join(inst, n), 'rb').read()
			if b == ib:
				same += 1
				continue
			try:
				u = unpack(b)
			except (ValueError, IndexError, struct.error) as e:
				print(f'not a container: {n} ({e})')
				skip += 1
				continue
			if u == ib:
				ok += 1
			else:
				print(f'MISMATCH {n}')
				bad += 1
		print(f'{ok} unpacked and match, {same} left packed by the installer, {bad} mismatch, '
			f'{skip} not containers')
		sys.exit(1 if bad else 0)


if __name__ == '__main__':
	main()
