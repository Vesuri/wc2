#!/usr/bin/env python3
"""Each FM effect's OPL writes, alone, from the original game code and STRAX.DRV:
the oracle of the runtime's effect capture (src/runtime/sfx.c, owner decision D13).

An effect is a chain of 8-byte records (flags, program, note, velocity, duration in
driver ticks, target note) in the game's effect table at DS:0540h, id k at + 8k, ids
1-55; WC2.EXE holds the table (FX.000, loaded into a heap buffer beside it, differs
in 6 records and is not what the starts use: MEASURED on the m4 snapshot). The game
starts one through WC2.EXE+1254D (its callers push flags 0, volume 7Fh, a pan and
1, 1) and steps it in WC2.EXE+123F4, the effect tick, from STRAX.DRV's per-tick
callback (`[1Ch]` → WC2.EXE+132CC) on every INT 08h at 60 Hz (divisor 4DAEh).
DERIVED by reading (docs/drivers.md "FM effects").

Under Unicorn x86, from a reference snapshot's RAM (default: the m4 host reference's
snap-m4-1, in flight) or a guest RAM image (--ram, tests/host_run.py --sfx-capture),
the steps of sfx.c: the callback gated to the effect tick (DGROUP A53Ch 0, A801h 1,
A544h/A546h 0: no fade, no song), the BIOS chain after it (WC2.EXE+10080) kept from
the BIOS before every tick (its divider step 1, accumulator 0); every effect slot
cleared, all notes off on the 16 MIDI channels, 120 ticks; then per id from that
state the start through WC2.EXE+1254D (flags 0, volume 7Fh, pan 40h, 1, 1) and the
driver's tick (STRAX.DRV entry 4) until the slot is released plus a 1.5 s tail, at
most 8 s. PIT counter 0 latches read a count falling 40h a latch from FFFFh. Code
outside WC2.EXE and the driver, a write outside DGROUP, the driver, the divider and
the stack, or a port other than the OPL's, the PIT's and the PIC's EOI stops the
tool. Only writes that change a register are kept, from the chip as STRAX.DRV
initialises it (every register 0, 01h = 20h; each effect writes its channels' whole
patch before its key-on).

Writes, from the snapshot: tmp/sound/sfx/ID.csv in trace/opl.csv's format
(ms,reg,value: the registers at 0 ms, then the effect's writes at their tick), the
input of tools/fm_check.cpp; tmp/sound/sfx-capture.csv (id, the record chain,
writes, ticks to the release, held); tmp/sound/sfx-writes.csv, X-Wing's format
(tools/fm_effect_check.cpp, tests/test_fm_effect_asm.py): "# opl" the registers
the captures start from, "# loop ID" for an effect still held at 8 s, then
tick,id,reg,value rows.

    tools/sfx_capture.py [--snapshot DIR | --ram FILE --ds SEG] [ID ...]
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
# WC2.EXE link segments (sfx.c's names)
DGROUP, ROOT, TIMER = 0x1976, 0x1207, 0x0FD1
START, CALLBACK = 0x04DD, 0x125C            # WC2.EXE+1254D, +132CC in ROOT
TIMER_INC, TIMER_ACC = 0x1B2, 0x1B8         # code words of WC2.EXE+10080
FX_TABLE = 0x0540
SLOTS, SLOT_BYTES, SLOT_COUNT = 0xA54C, 14, 32
GATE_FADE, GATE_SONG, GATE_SONG_PTR = 0xA53C, 0xA801, 0xA544
DRV_CS, DRV_NOTE = 0xAE56, 0xAE54           # DS words: STRAX.DRV's CS, its note entry
DRV_BYTES, DRV_TICK, DRV_CONTROL, DRV_NOTE_IP, DRV_CALLBACK = 3986, 0x0DDD, 0x0B61, 0x074D, 0x1C
ALL_NOTES_OFF = 0x7B
TICK_HZ = 1193182 / 0x4DAE
SETTLE, TAIL, TICKS_MAX = 120, 90, 480
IDS = 56                                    # runtime.h RT_SFX_IDS: ids 1-55
STUB_SEG = 0xFFFF                           # above 1 MB: the far return (hlt)
STACK_SS, STACK_SP = 0xFFFF, 0x8000


def residency(snap: Path) -> dict[str, int]:
    """Each module's first resident paragraph (residency.csv)."""
    out = {}
    for r in list(csv.reader((snap / "residency.csv").open()))[1:]:
        if r[2] not in out:
            out[r[2]] = int(r[0], 16)
    return out


class Machine:
    def __init__(self, ram: bytes, ds: int):
        self.ds = ds
        self.load = ds - DGROUP
        self.root = self.load + ROOT
        self.timer = (self.load + TIMER) * 16
        self.e = U.Engine(U.ARCH_X86, U.MODE_16)
        self.e.map(0, 0x110000)
        self.e.write(0, ram[:0x110000])
        self.drv = self.word(ds * 16 + DRV_CS)
        if (self.word(ds * 16 + DRV_NOTE) != DRV_NOTE_IP
                or self.word(self.drv * 16 + DRV_CALLBACK) != CALLBACK
                or self.word(self.drv * 16 + DRV_CALLBACK + 2) != self.root):
            raise SystemExit("DGROUP does not hold STRAX.DRV with the game's callback")
        self.ret = STUB_SEG * 16 + 0x10
        self.e.write(self.ret, b"\xf4")      # hlt: the far return lands here
        self.tick_n, self.writes, self.index, self.recording = 0, [], 0, False
        self.shadow = bytearray(256)
        self.shadow[1] = 0x20
        self.pit, self.pit_bytes = 0xFFFF, []
        self.stray: list[str] = []

        @U.OUT_CB
        def out(h, port, size, value, user):
            v = value & 0xFF
            if port == 0x388:
                self.index = v
            elif port == 0x389:     # a write that changes no register is not kept
                if self.shadow[self.index] != v and self.recording:
                    self.writes.append((self.tick_n, self.index, v))
                self.shadow[self.index] = v
            elif port == 0x43 and v == 0x06:
                self.pit = (self.pit - 0x40) & 0xFFFF
                self.pit_bytes = [self.pit & 0xFF, self.pit >> 8]
            elif not (port == 0x20 and v == 0x20):
                self.stray.append(f"out {port:x},{v:x}")

        @U.IN_CB
        def inp(h, port, size, user):
            if port == 0x40 and self.pit_bytes:
                return self.pit_bytes.pop(0)
            self.stray.append(f"in {port:x}")
            return 0

        self.e.hook(U.HOOK_INSN, out, U.X86_INS_OUT)
        self.e.hook(U.HOOK_INSN, inp, U.X86_INS_IN)
        exe = (self.load * 16, self.load * 16 + 0x60000)
        drv = (self.drv * 16, self.drv * 16 + DRV_BYTES)
        stub = (STUB_SEG * 16, STUB_SEG * 16 + 0x40)
        stack = STACK_SS * 16 + STACK_SP
        dgroup = ds * 16
        self.writable = [(dgroup, dgroup + 0x10000), drv, (self.timer + TIMER_INC, self.timer + TIMER_ACC + 2),
                         (stack - 0x800, stack)]

        @U.CODE_CB
        def code(h, addr, size, user):
            if not any(lo <= addr < hi for lo, hi in (exe, drv, stub)):
                self.stray.append(f"code at {addr:05x}")
                self.e.stop()

        @U.MEM_CB
        def write(h, access, addr, size, value, user):
            if not any(lo <= addr and addr + size <= hi for lo, hi in self.writable):
                self.stray.append(f"write {size} at {addr:05x}")
            return True

        self.e.hook(U.HOOK_CODE, code)
        self.e.hook(U.HOOK_MEM_WRITE, write)

    def word(self, a: int) -> int:
        return struct.unpack("<H", self.e.read(a, 2))[0]

    def put(self, a: int, w: int) -> None:
        self.e.write(a, struct.pack("<H", w & 0xFFFF))

    def push(self, *words: int) -> None:
        sp = self.e.reg_read(U.X86["sp"])
        for w in words:
            sp = (sp - 2) & 0xFFFF
            self.put(STACK_SS * 16 + sp, w)
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
        self.put(self.timer + TIMER_INC, 1)
        self.put(self.timer + TIMER_ACC, 0)
        self.run(self.drv, DRV_TICK, 0x0202, STUB_SEG, 0x10)

    def record(self, rid: int) -> bytes:
        return self.e.read(self.ds * 16 + FX_TABLE + 8 * rid, 8)

    def ram(self) -> bytes:
        return bytes(self.e.read(0, 0x110000))


def chain(m: Machine, rid: int) -> list[int]:
    out = [rid]
    while m.record(out[-1])[0] & 1 and out[-1] < IDS - 1:
        out.append(out[-1] + 1)
    return out


def capture(ram: bytes, ds: int, ids: list[int] | None = None) -> tuple[bytes, dict]:
    """sfx.c's capture: (the registers the captures start from, per id (the writes as
    (tick, reg, value), the tick its slot was released, 0 held))."""
    m = Machine(ram, ds)
    d = ds * 16
    m.put(d + GATE_FADE, 0)
    m.put(d + GATE_SONG, 1)
    m.put(d + GATE_SONG_PTR, 0)
    m.put(d + GATE_SONG_PTR + 2, 0)
    for n in range(SLOT_COUNT):
        m.e.write(d + SLOTS + SLOT_BYTES * n + 1, b"\0")
    for ch in range(1, 17):
        m.far_call(m.drv, DRV_CONTROL, 0, ALL_NOTES_OFF, ch)
    for _ in range(SETTLE):
        m.tick()
    opl0, settled, shadow = bytes(m.shadow), m.ram(), bytes(m.shadow)
    out = {}
    for rid in range(1, IDS):
        if rid > 1 and m.record(rid - 1)[0] & 1 or ids and rid not in ids:
            continue
        m.e.write(0, settled)
        m.shadow[:] = shadow
        m.writes, m.tick_n, m.recording = [], 0, True
        ptr = m.far_call(m.root, START, FX_TABLE + 8 * rid, ds, 0, 0x7F, 0x40, 1, 1)
        released = 0
        if ptr:
            channel = (ptr >> 16) * 16 + (ptr & 0xFFFF) + 1
            for t in range(1, TICKS_MAX + 1):
                m.tick_n = t
                m.tick()
                if not released and m.e.read(channel, 1)[0] == 0:
                    released = t
                if released and t >= released + TAIL:
                    break
        m.recording = False
        out[rid] = (m.writes, released)
    return opl0, out


def write_log(path: Path, opl0: bytes, writes: list) -> None:
    with path.open("w") as f:
        f.write("ms,reg,value\n")
        for r in range(0x01, 0xF6):
            if r == 0x01 or r >= 0x20:
                f.write("0.000000,0x%02x,0x%02x\n" % (r, opl0[r]))
        for t, r, v in writes:
            f.write("%.6f,0x%02x,0x%02x\n" % (1 + t * 1000 / TICK_HZ, r, v))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    ap.add_argument("--ram", type=Path, help="a guest RAM image (linear order) instead of a snapshot")
    ap.add_argument("--ds", type=lambda s: int(s, 16), help="with --ram: DGROUP")
    ap.add_argument("--out", type=Path, default=OUT, help="the output directory")
    ap.add_argument("ids", nargs="*", type=int)
    args = ap.parse_args()
    if args.ram:
        ram, ds = args.ram.read_bytes(), args.ds
    else:
        ram = (args.snapshot / "ram.bin").read_bytes()
        ram += bytes(0x110000 - len(ram))
        ds = residency(args.snapshot)["WC2.EXE"] + DGROUP
    opl0, caps = capture(ram, ds, args.ids)
    m = Machine(ram, ds)
    (args.out / "sfx").mkdir(parents=True, exist_ok=True)
    with (args.out / "sfx-capture.csv").open("w") as f:
        f.write("id,records,writes,released,loop\n")
        for rid, (writes, released) in caps.items():
            write_log(args.out / "sfx" / f"{rid}.csv", opl0, writes)
            f.write(f"{rid},{' '.join(map(str, chain(m, rid)))},{len(writes)},{released},{int(not released)}\n")
            print(f"id {rid}: {len(writes)} writes, "
                  f"{'held at 8 s' if not released else f'released at tick {released}'}")
    with (args.out / "sfx-writes.csv").open("w") as f:
        f.write("# opl " + opl0.hex() + "\n")
        for rid, (writes, released) in caps.items():
            if not released:
                f.write(f"# loop {rid}\n")
            for t, r, v in writes:
                f.write(f"{t},{rid},0x{r:02x},0x{v:02x}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
