#!/usr/bin/env python3
"""Borland C++ DOS executable with VROOMM overlays (FBOV): layout reader.

  python3 tools/bc_exe.py FILE.EXE      summary of the MZ image and the overlay stubs

Stub segments are found by scanning the load image at paragraph boundaries for the
32-byte VROOMM stub header (INT 3Fh, saveret 0, file offset, code size, relocation
size, entry count, previous stub, 16 bytes of zero workspace) followed by `nentries`
5-byte entries `CD 3F lo hi 00`. File offsets are relative to the end of the 16-byte
FBOV header (MEASURED: every overlay then starts at a function prologue but 3 of WC2's).
"""
import struct
import sys
from dataclasses import dataclass, field


@dataclass
class Overlay:
	stub_off: int        # offset of the stub segment in the load image
	file_off: int        # code offset relative to the FBOV header
	code_size: int
	reloc_size: int
	entries: list = field(default_factory=list)   # entry offsets inside the overlay code


@dataclass
class BcExe:
	data: bytes
	header: int
	image: bytes
	relocs: list
	cs: int
	ip: int
	fbov: int
	overlays: list

	def overlay_code(self, ov):
		start = self.fbov + 16 + ov.file_off
		return self.data[start:start + ov.code_size]


def load(path):
	b = open(path, 'rb').read()
	lastp, pages, nrel, hdrp = struct.unpack_from('<HHHH', b, 2)
	ip, cs, relo = struct.unpack_from('<HHH', b, 0x14)[0], struct.unpack_from('<H', b, 0x16)[0], \
		struct.unpack_from('<H', b, 0x18)[0]
	end = pages * 512 - ((512 - lastp) if lastp else 0)
	header = hdrp * 16
	image = b[header:end]
	relocs = [struct.unpack_from('<HH', b, relo + 4 * i) for i in range(nrel)]
	overlays = []
	if b[end:end + 4] != b'FBOV':     # no overlays (the installers)
		return BcExe(b, header, image, relocs, cs, ip, end, overlays)
	ovsize = struct.unpack_from('<I', b, end + 4)[0]
	for off in range(0, len(image) - 32, 16):
		if image[off:off + 4] != b'\xcd\x3f\x00\x00' or any(image[off + 16:off + 32]):
			continue
		fo, csz, rsz, n, prev = struct.unpack_from('<IHHHH', image, off + 4)
		if not (0 < n < 512 and 0 < csz and fo + csz <= ovsize + 16):
			continue
		ents = []
		ok = True
		for i in range(n):
			e = image[off + 32 + 5 * i:off + 37 + 5 * i]
			if e[:2] != b'\xcd\x3f' or e[4] != 0:
				ok = False
				break
			ents.append(e[2] | e[3] << 8)
		if ok:
			overlays.append(Overlay(off, fo, csz, rsz, ents))
	return BcExe(b, header, image, relocs, cs, ip, end, overlays)


def main():
	for p in sys.argv[1:]:
		x = load(p)
		code = sum(o.code_size for o in x.overlays)
		print(f'{p}: image {len(x.image)} B, {len(x.relocs)} relocs, entry {x.cs:04X}:{x.ip:04X}, '
			f'FBOV at {x.fbov:#x}, {len(x.overlays)} overlays, {code} B overlay code, '
			f'{sum(len(o.entries) for o in x.overlays)} entries')
		bad = [o for o in x.overlays if x.overlay_code(o)[:3] not in (b'\x55\x8b\xec', b'\xc8\x00\x00')]
		print(f'  overlays not starting with a push bp/mov bp,sp prologue: {len(bad)}')


if __name__ == '__main__':
	main()
