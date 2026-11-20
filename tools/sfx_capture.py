#!/usr/bin/env python3
"""Each FM effect's OPL writes, alone, from the original game code and STRAX.DRV.

An effect is an FX.000 record chain (8 bytes a record: flags, program, note,
velocity, duration in driver ticks, target note; DS:0540h + 8 * id, the container's
8-byte header first, so ids start at 1). The game starts one through
WC2.EXE+1254D (the slot allocator; its callers push flags 0, volume 7Fh, a pan and
1, 1: WC2.EXE+0AB40, +0BC59, +2917B, +375C0) and steps it in WC2.EXE+123F4, the
effect tick, from STRAX.DRV's per-tick callback (`[1Ch]` → WC2.EXE+132CC) on every
INT 08h at 60 Hz (divisor 4DAEh, docs/external-surface.md). DERIVED by reading.

Under Unicorn x86 from a reference snapshot's RAM (default: the m4 host reference's
snap-m4-1, in flight): the driver's callback pointer is redirected to a stub that
calls only the effect tick (no music sequencer, fades or file loads); every MIDI
channel gets all-notes-off and every effect slot is cleared; 2 s of ticks let the
releases end; then the effect starts through WC2.EXE+1254D and the driver's tick
(STRAX.DRV entry 4) runs until the slot is released plus a 1.5 s tail, at most 8 s.
PIT counter 0 reads (the driver's OPL delay loop) see a counter that falls 40h per
latch. Code outside the root and the driver or a write outside them, DGROUP and the
call stack stops the tool.

Per id: tmp/sound/sfx/ID.csv in trace/opl.csv's format (ms,reg,value: the OPL
registers as the writes since the snapshot left them at 0 ms, then the effect's
writes at their tick), the input of tools/fm_check.cpp; a row of
tmp/sound/sfx-capture.csv (id, the record chain, writes, ticks to the release, loop).

    tools/sfx_capture.py [--snapshot DIR] [ID ...]
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
import uc as U  # noqa: E402

SNAPSHOT = REPO / "tmp/pc-runs/host-m4/trace/snap-m4-1"
OUT = REPO / "tmp/sound"
ROOT_SEG = 0x1207                   # the root code segment of the sound routines (link value)
START_SOUND, EFFECT_TICK = 0x04DD, 0x0384   # WC2.EXE+1254D, +123F4 in that segment
DGROUP = 0x1976                     # link value (WC2.EXE+132D5: mov bp,1976h; mov ds,bp)
FX_TABLE = 0x0540                   # DS: FX.000 as loaded; record id at + 8 * id
SLOTS, SLOT_BYTES, SLOT_COUNT = 0xA54C, 14, 0x20    # DS: the effect slots (+1254D)
DRV_TICK, DRV_CONTROL, DRV_CALLBACK = 0x0DDD, 0x0B61, 0x1C  # STRAX.DRV entry 4, entry 6, CS:[1Ch]
ALL_NOTES_OFF = 0x7B
TICK_HZ = 1193182 / 0x4DAE
SETTLE, TAIL, TICKS_MAX = 120, 90, 480
STUB_SEG = 0xFFFF                   # above 1 MB: the far return (hlt) and the callback stub
STACK_SS, STACK_SP = 0xFFFF, 0x8000
RECORDS = 55                        # FX.000: (448 - 8) / 8


def residency(snap: Path) -> dict[str, int]:
    """Each module's first resident paragraph (residency.csv): WC2.EXE's load segment;
    a driver's block, its CS (IP 0 = the loaded entry's first byte, docs/drivers.md)."""
    out = {}
    for r in list(csv.reader((snap / "residency.csv").open()))[1:]:
        if r[2] not in out:
            out[r[2]] = int(r[0], 16)
    return out


class Machine:
    def __init__(self, snap: Path):
        ram = (snap / "ram.bin").read_bytes()
        seg = residency(snap)
        self.load = seg["WC2.EXE"]
        self.root = ROOT_SEG + self.load
        self.ds = DGROUP + self.load
        self.drv = seg["STRAX.DRV"]
        self.drv_lin = self.drv * 16
        self.e = U.Engine(U.ARCH_X86, U.MODE_16)
        self.e.map(0, 0x110000)
        self.e.write(0, ram[:0x100000])
        self.ret = STUB_SEG * 16 + 0x10          # hlt
        stub_ip = 0x20
        # callback stub: push ds; push ax; mov ax, DS; mov ds, ax; call far root:tick;
        # pop ax; pop ds; iret
        stub = (b"\x1e\x50\xb8" + struct.pack("<H", self.ds) + b"\x8e\xd8\x9a"
                + struct.pack("<HH", EFFECT_TICK, self.root) + b"\x58\x1f\xcf")
        self.e.write(self.ret, b"\xf4")
        self.e.write(STUB_SEG * 16 + stub_ip, stub)
        self.e.write(self.drv_lin + DRV_CALLBACK, struct.pack("<HH", stub_ip, STUB_SEG))
        self.tick_n, self.writes, self.index = 0, [], 0
        self.shadow = bytearray(256)
        self.pit, self.pit_bytes = 0xFFFF, []

        @U.OUT_CB
        def out(h, port, size, value, user):
            if port == 0x388:
                self.index = value & 0xFF
            elif port == 0x389:
                self.writes.append((self.tick_n, self.index, value & 0xFF))
                self.shadow[self.index] = value & 0xFF
            elif port == 0x43 and value & 0xFF == 0x06:
                self.pit = (self.pit - 0x40) & 0xFFFF
                self.pit_bytes = [self.pit & 0xFF, self.pit >> 8]
            else:
                self.stray.append(f"out {port:x}")

        @U.IN_CB
        def inp(h, port, size, user):
            if port == 0x40 and self.pit_bytes:
                return self.pit_bytes.pop(0)
            self.stray.append(f"in {port:x}")
            return 0

        self.e.hook(U.HOOK_INSN, out, U.X86_INS_OUT)
        self.e.hook(U.HOOK_INSN, inp, U.X86_INS_IN)
        self.stray: list[str] = []
        root_lo = self.load * 16
        root_hi = root_lo + 0x60000
        drv_lo, drv_hi = self.drv_lin, self.drv_lin + 3986
        stub_lo, stub_hi = STUB_SEG * 16, STUB_SEG * 16 + 0x40
        stack = STACK_SS * 16 + STACK_SP
        ds_lo = self.ds * 16

        @U.CODE_CB
        def code(h, addr, size, user):
            if not (root_lo <= addr < root_hi or drv_lo <= addr < drv_hi or stub_lo <= addr < stub_hi):
                self.stray.append(f"code at {addr:05x}")
                self.e.stop()

        @U.MEM_CB
        def write(h, access, addr, size, value, user):
            if not (drv_lo <= addr < drv_hi or ds_lo <= addr < ds_lo + 0x10000
                    or stack - 0x800 <= addr < stack):
                self.stray.append(f"write {size} at {addr:05x}")
            return True

        self.e.hook(U.HOOK_CODE, code)
        self.e.hook(U.HOOK_MEM_WRITE, write)

    def push(self, *words: int) -> None:
        sp = self.e.reg_read(U.X86["sp"])
        for w in words:
            sp = (sp - 2) & 0xFFFF
            self.e.write(STACK_SS * 16 + sp, struct.pack("<H", w & 0xFFFF))
        self.e.reg_write(U.X86["sp"], sp)

    def run(self, cs: int, ip: int, *frame: int) -> int:
        """Enter cs:ip with `frame` pushed (first pushed first), return at the hlt."""
        self.e.reg_write(U.X86["ss"], STACK_SS)
        self.e.reg_write(U.X86["sp"], STACK_SP)
        self.e.reg_write(U.X86["ds"], self.ds)
        self.e.reg_write(U.X86["es"], self.ds)
        self.e.reg_write(U.X86["flags"], 0x0202)
        self.push(*frame)
        self.e.reg_write(U.X86["cs"], cs)
        self.e.reg_write(U.X86["ip"], ip)
        err = self.e.start(cs * 16 + ip, self.ret)
        pc = self.e.reg_read(U.X86["cs"]) * 16 + self.e.reg_read(U.X86["ip"])
        if err or pc not in (self.ret, self.ret + 1) or self.stray:
            raise SystemExit(f"{cs:04x}:{ip:04x}: stopped at {pc:05x} "
                             f"({U.uc.uc_strerror(err).decode()}; {', '.join(self.stray[:4])})")
        return self.e.reg_read(U.X86["ax"]) | self.e.reg_read(U.X86["dx"]) << 16

    def far_call(self, cs: int, ip: int, *args: int) -> int:     # C far call, args left to right
        return self.run(cs, ip, *reversed(args), STUB_SEG, 0x10)

    def tick(self) -> None:                                       # interrupt frame: FLAGS, CS, IP
        self.run(self.drv, DRV_TICK, 0x0202, STUB_SEG, 0x10)

    def slot(self, n: int) -> bytes:
        return self.e.read(self.ds * 16 + SLOTS + SLOT_BYTES * n, SLOT_BYTES)

    def record(self, rid: int) -> bytes:
        return self.e.read(self.ds * 16 + FX_TABLE + 8 * rid, 8)


def chain(m: Machine, rid: int) -> list[int]:
    out = [rid]
    while m.record(out[-1])[0] & 1 and out[-1] < RECORDS:
        out.append(out[-1] + 1)
    return out


def capture(snap: Path, rid: int, pan: int = 0x40) -> tuple[bytes, list, int, bool, list[int]]:
    """(the OPL registers at the start, the writes as (tick, reg, value), ticks until
    the slot's channel was released, whether it was still held at TICKS_MAX, the
    record chain)."""
    m = Machine(snap)
    for n in range(SLOT_COUNT):
        m.e.write(m.ds * 16 + SLOTS + SLOT_BYTES * n + 1, b"\0")
    for ch in range(1, 17):
        m.far_call(m.drv, DRV_CONTROL, 0, ALL_NOTES_OFF, ch)
    for _ in range(SETTLE):
        m.tick()
    opl0 = bytes(m.shadow)
    m.writes.clear()
    m.tick_n = 0
    ptr = m.far_call(m.root, START_SOUND, FX_TABLE + 8 * rid, m.ds, 0, 0x7F, pan, 1, 1)
    if not ptr:
        raise SystemExit(f"id {rid}: WC2.EXE+1254D found no slot or channel")
    slot = ((ptr & 0xFFFF) - SLOTS) // SLOT_BYTES
    released = 0
    for t in range(1, TICKS_MAX + 1):
        m.tick_n = t
        m.tick()
        if not released and m.slot(slot)[1] == 0:
            released = t
        if released and t >= released + TAIL:
            break
    return opl0, m.writes, released, not released, chain(m, rid)


def write_log(path: Path, opl0: bytes, writes: list) -> None:
    with path.open("w") as f:
        f.write("ms,reg,value\n")
        f.write("0.000000,0x01,0x%02x\n" % (opl0[1] | 0x20))
        for r in range(0x20, 0xF6):
            if r != 0x01:
                f.write("0.000000,0x%02x,0x%02x\n" % (r, opl0[r]))
        for t, r, v in writes:
            f.write("%.6f,0x%02x,0x%02x\n" % (1 + t * 1000 / TICK_HZ, r, v))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    ap.add_argument("ids", nargs="*", type=int)
    args = ap.parse_args()
    m = Machine(args.snapshot)
    ids = args.ids or [i for i in range(1, RECORDS + 1) if i == 1 or not m.record(i - 1)[0] & 1]
    (OUT / "sfx").mkdir(parents=True, exist_ok=True)
    rows = []
    for rid in ids:
        opl0, writes, released, loop, ch = capture(args.snapshot, rid)
        write_log(OUT / "sfx" / f"{rid}.csv", opl0, writes)
        rows.append((rid, " ".join(map(str, ch)), len(writes), released, int(loop)))
        print(f"id {rid}: records {ch[0]}-{ch[-1]}, {len(writes)} writes, "
              f"{'held at 8 s' if loop else f'released at tick {released}'}")
    with (OUT / "sfx-capture.csv").open("w") as f:
        f.write("id,records,writes,released,loop\n")
        for r in rows:
            f.write(",".join(map(str, r)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
