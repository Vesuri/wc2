#!/usr/bin/env python3
"""Origin resource container of Wing Commander I and II (`.V00`, `.VGA`, `.DRV`, `.000`, ...).

  python3 tools/origin_pak.py list FILE...
  python3 tools/origin_pak.py unpack SRC DST          rebuild SRC with every entry unpacked
  python3 tools/origin_pak.py program SRC.LZC DST     the program in a one-entry `.LZC`
  python3 tools/origin_pak.py verify DISKDIR WING2    install DISKDIR (the 7 disks' files) by
                                                      its INSTALL.DAT, compare with the
                                                      original installer's WING2 tree

Layout (DERIVED; `verify` against WC2's installed GAMEDAT is the check):
  u32 total file size
  table of u32 entries: low 24 bits offset, high byte flags; it ends at the lowest offset
  flags & 0xC0 == 0: packed: u32 unpacked size, then LZW (LSB-first codes of 9..12 bits,
    256 = reset dictionary and width, 257 = end, no early width change)
  flags & 0xC0 != 0: stored; the installer sets 0xC0 on every entry it unpacks
  flags == 0xFF: alias of the entry at the same offset (or of the file end); kept as is
  flags == 0xE0 (`SPEECH.S00`): speech, 8-bit unsigned PCM in 4-bit deltas: the first byte
    is the first sample, then two codes per byte, high nibble first: bit 3 the sign, m the
    low 3 bits, delta (m << L) + (L ? 1 << (L - 1) : 0) at level L (0..3, from 0); the
    sample clamps to 0..255; m >= 5 raises L, m == 0 lowers it. n bytes give 2n - 1
    samples; the installer keeps the flag. Only in files of method 8 below: elsewhere
    (`COMMUNIC.T*`, `INTEL.*`) 0xE0 entries are stored data
`.LZC` (`WC2.LZC`, `README.LZC`): a one-entry container; the installer writes the entry's
data as the `.EXE`.
INSTALL.DAT (disk 1), the installer's file table: 20-byte records, the last all zero:
  name[13] (NUL-padded), disk (1..7), method, 0, u16 unknown, u16 size & FFFFh
  method 1, 7: copied (some stay packed: `BRIEF.PAL`); 2, 3: container unpacked;
  6: `.LZC` -> `.EXE` beside GAMEDAT; 8: container unpacked, every entry speech (a packed
  entry is LZW, then speech). `INSTALL.*` is the installer itself, in WING2 (DERIVED;
  `verify` against the original installer's tree is the check)
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


def speech(data):
	out = bytearray(data[:1])
	s, lev = data[0], 0
	for c in data[1:]:
		for code in (c >> 4, c & 15):
			m = code & 7
			d = (m << lev) + (1 << (lev - 1) if lev else 0)
			s = max(0, min(255, s - d if code & 8 else s + d))
			out.append(s)
			lev = min(3, lev + 1) if m >= 5 else max(0, lev - 1) if m == 0 else lev
	return bytes(out)


def entry_data(b, o, fl, end, voice=False):
	if fl == 0xE0 and voice:
		return speech(b[o:end])
	if fl & 0xC0:
		return b[o:end]
	size = struct.unpack_from('<I', b, o)[0]
	d = lzw(b[o + 4:end])
	if len(d) != size:
		raise ValueError(f'entry at {o:#x}: unpacked {len(d)} != declared {size}')
	return speech(d) if voice else d


def unpack(b, voice=False):
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
			body += entry_data(b, o, fl, end, voice)
		table.append(done[o] | (fl | 0xC0) << 24)
	for i, (o, fl, end) in enumerate(ents):
		if fl == 0xFF:
			table[i] = (done[o] if o < len(b) else head + len(body)) | 0xFF << 24
	out = struct.pack('<I', head + len(body)) + b''.join(struct.pack('<I', t) for t in table) + body
	return out


def program(b):
	ents = parse(b)
	if len(ents) != 1:
		raise ValueError(f'{len(ents)} entries, not a one-entry .LZC')
	return entry_data(b, *ents[0])


def table(b):
	"""INSTALL.DAT -> [(name, disk, method)]."""
	out = []
	for i in range(0, len(b) - 19, 20):
		r = b[i:i + 20]
		name = r[:13].split(b'\0')[0].decode('ascii')
		if not name:
			break
		out.append((name, r[13], r[14]))
	return out


def install(name, method, b):
	"""-> (path under WING2, bytes) for one disk file, as the installer writes it."""
	if name.upper().startswith('INSTALL.'):
		return name, b
	if method in (1, 7):
		return 'GAMEDAT/' + name, b
	if method in (2, 3, 8):
		return 'GAMEDAT/' + name, unpack(b, method == 8)
	if method == 6:
		return name.rsplit('.', 1)[0] + '.EXE', program(b)
	raise ValueError(f'{name}: install method {method}')


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
	elif cmd == 'program':
		open(args[1], 'wb').write(program(open(args[0], 'rb').read()))
	elif cmd == 'verify':
		src, inst = args
		got = {}
		for name, disk, method in table(open(os.path.join(src, 'INSTALL.DAT'), 'rb').read()):
			path, data = install(name, method, open(os.path.join(src, name), 'rb').read())
			got[path] = data
		want = set()
		for d, _, files in os.walk(inst):
			for f in files:
				want.add(os.path.relpath(os.path.join(d, f), inst).replace(os.sep, '/'))
		ok = bad = 0
		for path in sorted(want | set(got)):
			if path == 'WC2.CFG':     # the answers, not a disk file
				continue
			if path not in got or path not in want:
				print(f'{"MISSING" if path not in got else "EXTRA"} {path}')
				bad += 1
			elif got[path] == open(os.path.join(inst, path), 'rb').read():
				ok += 1
			else:
				print(f'MISMATCH {path}')
				bad += 1
		print(f'{ok} files match the installed tree, {bad} differ')
		sys.exit(1 if bad else 0)

if __name__ == '__main__':
	main()
