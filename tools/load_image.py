#!/usr/bin/env python3
"""Rebuild the WC2 image from ref/ and compare it with a snapshot (gate 1, port-plan P1.4).

Loader model (tools/wc2_model.py, docs/pc-reference-loop.md "Loader model"):
- Root: the MZ load image at the load segment, each relocation word += load seg.
- Overlays (VROOMM): code read from the FBOV area to a buffer; each segment word w
  of the code becomes load seg + the link segment in root segment record w / 8.
  The relocation records after the code, and any other FBOV byte, are file bytes.
- Drivers (.DRV): file bytes.

Every snapshot residency row is compared with the rebuilt bytes. A differing byte
must have a CPU writer since its load (snapshot `writes.csv`) or be the byte the last
traced DOS read put there (events.csv: buffers that cover paragraphs partly); written
bytes are split into executed instruction bytes (trace bitmap + Capstone length:
self-modifying code, listed by writer) and data. A code read, and a VROOMM move, also
owns its trailing partial paragraph (the trace patch): bytes past an overlay's
code up to the paragraph after its relocation records (read but never part of the
image, or what the buffer held), and bytes in a row's last paragraph that no DOS read wrote or that
are loader input, are outside the module ("outside"). Exit 1 if any byte differs without a writer, or if no row of
the root was compared.
Adapted from Secret Weapons of Luftwaffe (docs/upstream.md).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import sys
from collections import Counter
from pathlib import Path

import capstone

import wc2_model as M


class Expected:
    """Expected bytes by module and module offset."""

    def __init__(self, ref: Path, load: int):
        self.ref = ref
        self.file = M.image_file(ref)
        self.root = M.root_image(load, ref)
        self.ovls = M.overlays(ref)
        self.starts = [o.code for o in self.ovls]
        self.code = {o.code: M.overlay_code(o, load, ref, self.file) for o in self.ovls}
        self.drivers = {d: (ref / "GAMEDAT" / d).read_bytes() for d in M.DRIVERS}

    def byte(self, module: str, off: int) -> int | None:
        if module in self.drivers:
            data = self.drivers[module]
            return data[off] if 0 <= off < len(data) else None
        if module != M.ROOT or off < 0:
            return None
        if off < len(self.root):
            return self.root[off]
        k = bisect.bisect_right(self.starts, off) - 1
        if k >= 0 and off < self.ovls[k].code + self.ovls[k].size:
            return self.code[self.ovls[k].code][off - self.ovls[k].code]
        return self.file[off] if off < len(self.file) else None

    def loader_input(self, module: str, off: int) -> bool:
        """WC2.EXE bytes past the root that are not overlay code: the FBOV header
        and relocation records, which the loader consumes."""
        if module != M.ROOT or off < len(self.root):
            return False
        k = bisect.bisect_right(self.starts, off) - 1
        return k < 0 or off >= self.ovls[k].code + self.ovls[k].size

    def overlay_tail(self, module: str, off: int) -> bool:
        """WC2.EXE bytes past an overlay's code up to the paragraph after its
        relocation records (the read): loader input, never image, or what the
        buffer held there."""
        if module != M.ROOT or off < len(self.root):
            return False
        k = bisect.bisect_right(self.starts, off) - 1
        if k < 0:
            return False
        o = self.ovls[k]
        return o.code + o.size <= off < o.code + ((o.end - o.code + 15) & ~15)

    def image(self, module: str) -> tuple[bytes, int]:
        """A flat image for instruction lengths: (bytes, module offset of byte 0)."""
        if module in self.drivers:
            return self.drivers[module], 0
        flat = bytearray(self.file)
        flat[:len(self.root)] = self.root
        for o in self.ovls:
            flat[o.code:o.code + o.size] = self.code[o.code]
        return bytes(flat), 0


def dos_reads(events: Path, until: int, ref: Path) -> dict[int, int]:
    """Linear address -> byte from the last traced DOS read before `until`."""
    files = {p.name.upper(): p for p in ref.rglob("*") if p.is_file()}
    run_root = events.parent.parent / "root"  # files the game wrote
    if run_root.exists():
        for p in run_root.rglob("*"):
            if p.is_file():
                files.setdefault(p.name.upper(), p)
    cache, out = {}, {}
    payload = None
    with events.open() as stream:
        for line in stream:
            f = line.rstrip("\n").split(",", 4)
            if len(f) < 5 or f[1] != "read" or int(f[0]) > until:
                continue
            name, *kv = f[4].split()
            kv = dict(x.split("=") for x in kv)
            lin, pos, got = int(kv["linear"], 16), int(kv["pos"], 16), int(kv["got"])
            if "data" in kv:
                if payload is None:
                    payload = (events.parent / "reads.bin").read_bytes()
                offset = int(kv["data"])
                if offset < 0:
                    raise ValueError(f"{events}: negative DOS read payload offset")
                data = payload[offset:offset + got]
            else:  # Legacy references predate DOS read payload capture.
                if (events.parent / "reads.bin").exists():
                    raise ValueError(f"{events}: DOS read missing payload offset")
                if name not in cache:
                    cache[name] = files[name].read_bytes()
                data = cache[name][pos:pos + got]
            if len(data) != got:
                raise ValueError(f"{events}: {name} read at {pos:#x}: expected {got} bytes, got {len(data)}")
            for k, byte in enumerate(data):
                out[lin + k] = byte
    return out


def code_bytes(module_image: bytes, base_off: int, bitmap: bytes) -> set[int]:
    """Module offsets covered by executed instructions (lengths from Capstone)."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    cover = set()
    for off, hit in enumerate(bitmap):
        if not hit:
            continue
        i = off - base_off
        if not 0 <= i < len(module_image):
            continue
        insn = next(md.disasm(bytes(module_image[i:i + 16]), 0), None)
        cover.update(range(off, off + (insn.size if insn else 1)))
    return cover


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", type=Path, help="tmp/pc-runs/<run>/trace/snap-<name>")
    ap.add_argument("--ref", type=Path, default=M.REF)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    snap, trace = args.snapshot, args.snapshot.parent
    regs = dict(kv.split("=") for kv in (snap / "regs.txt").read_text().split())
    load = int(regs["load_seg"], 16)
    ram = (snap / "ram.bin").read_bytes()
    want = Expected(args.ref, load)
    read = dos_reads(trace / "events.csv", int(regs["icount"]), args.ref)
    writer = {}
    for r in csv.DictReader((snap / "writes.csv").open()):
        w = f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}"
        for a in range(int(r["first_linear"], 16), int(r["last_linear"], 16) + 1):
            writer[a] = w
    cover = {}
    smc = Counter()
    failed = False
    compared = Counter()
    print(f"load segment {load:04X}")
    print(f"{'module':12} {'linear':>13} {'offset':>8} {'bytes':>7} {'same':>7} {'code-wr':>7} "
          f"{'data-wr':>7} {'outside':>7} {'unexpl':>6}")
    for r in csv.DictReader((snap / "residency.csv").open()):
        mod = r["module"]
        lo, hi = int(r["first_para"], 16) * 16, (int(r["last_para"], 16) + 1) * 16
        moff = int(r["module_offset"], 16)
        if moff >= 0x80000000:
            moff -= 1 << 32
        if mod not in cover:
            img, base = want.image(mod) if mod in want.drivers or mod == M.ROOT else (b"", 0)
            bm = trace / f"executed-{mod}.bin"
            cover[mod] = code_bytes(img, base, bm.read_bytes() if bm.exists() else b"")
        same = code_wr = data_wr = outside = 0
        bad = []
        read_loaded = mod in want.drivers or moff >= len(want.root)
        for k in range(hi - lo):
            off = moff + k
            expect = want.byte(mod, off)
            if expect is None:  # past the file's end: the read's last partial paragraph
                expect = -1
            if expect == ram[lo + k]:
                same += 1
            elif lo + k not in writer:
                if read.get(lo + k) == ram[lo + k]:
                    data_wr += 1
                elif want.overlay_tail(mod, off) or (
                        read_loaded and k >= hi - lo - 16 and (
                            lo + k not in read or want.loader_input(mod, off))):
                    outside += 1
                else:
                    bad.append(off)
            elif off in cover[mod]:
                code_wr += 1
                smc[(mod, writer[lo + k])] += 1
            else:
                data_wr += 1
        compared[mod] += hi - lo
        failed |= bool(bad)
        print(f"{mod:12} {lo:06X}-{hi:06X} {moff & 0xFFFFFFFF:8X} {hi - lo:7} {same:7} {code_wr:7} "
              f"{data_wr:7} {outside:7} {len(bad):6}")
        if args.verbose and bad:
            print("  unexplained at", " ".join(f"{o:05X}" for o in bad[:32]))
    for (mod, w), n in sorted(smc.items()):
        print(f"self-modified {mod} executed bytes: {n:5} by {w}")
    if not compared[M.ROOT]:
        print(f"no residency row of {M.ROOT}")
        failed = True
    print("gate: FAIL" if failed else "gate: every byte matches the file + loader model or has a CPU writer")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
