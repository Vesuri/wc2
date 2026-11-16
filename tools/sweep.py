#!/usr/bin/env python3
"""Recursive-descent sweep of the root, every VROOMM overlay and the drivers (port-plan P2.3).

Adapted from Secret Weapons of Luftwaffe's tools/sweep.py by way of X-Wing's (units per
overlay; docs/upstream.md), for Borland C++ and VROOMM (docs/vroomm.md, docs/drivers.md).

Units:
- the root's code segments (WC2.EXE image 0..16B80h; CS from the segment records);
- each of the 124 overlays (its code at its image offsets, relocated at load segment 0:
  segment words are link segments; IP 0 is its first byte);
- the loaded entry of each driver (TM.DRV and SUPERTM.DRV entry 0, STRAX.DRV entry 1;
  IP 0 is the entry's first byte).
A far target in a stub segment at an entry (20h + 5k) is the overlay's entry k; in a
root code segment, the root; anything else is listed in far-refs.csv, not followed.

Seeds, static: the MZ entry, every stub entry, the startup and exit tables (_INIT_,
_EXIT_), the driver entry tables (docs/drivers.md), far code pointers built in registers or
stored in the root's data (a relocated segment word after an offset word: an overlay entry
or a root prologue), functions after a RETF, switch tables. Calls to annotations/noreturn.csv end a flow. Live,
from the trace corpus: the handlers of the interrupts taken (hardware, and INT 3Fh and the
other vectors set through AH=25h), and the traced targets of the indirect sites. The sweep
follows fall-through, near and far direct jumps and calls; stops at returns and indirect
jumps; never sweeps linearly. Switch forms (Borland): `cmp bx,N; ja/jbe; shl bx,1;
jmp cs:[bx+T]` (N+1 entries) and the value search `mov cx,N ... mov ax,cs:[bx+V];
cmp; je; inc bx; inc bx; loop; ...; jmp cs:[bx+V+2N]`; others come from
annotations/tables.csv.

Agreement (gate 2): every executed instruction start is a start reached from the seeds
above (`executed_not_reached` 0) and no flow conflicts with another (`conflicts` 0);
stub entries and headers that executed are the two-form cells (class 6).

Outputs in tmp/sweep/: <module>.cls (byte per module offset: 0 unknown, 1 instruction
start, 2 instruction body, 3 executed start, 4 executed body, 5 switch table, 6 stub
cell), coverage.csv, conflicts.csv, far-refs.csv, indirect.csv, code-pointers.csv. With
--annotations, annotations/indirect.csv and annotations/entries.csv are written too.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import defaultdict
from dataclasses import dataclass

import capstone
from capstone import x86

import wc2_model as M

OUT = M.REPO / "tmp/sweep"
UNKNOWN, START, BODY, TABLE, STUB = 0, 1, 2, 5, 6
ROOT_CODE_END = M.ROOT_CODE_END
DRIVERS = M.DRIVER_ENTRY
DRIVER_TABLE = M.DRIVER_TABLE
STARTUP = (0x244DC, 0x244F4)            # _INIT_ and _EXIT_ records (6 bytes; 0x244F4 is _EXIT_)
PROLOGUES = (b"\x55\x8b\xec", b"\xc8")


@dataclass
class Unit:
    name: str
    file: str
    lo: int
    hi: int
    kind: str                   # root, overlay, driver

    def has(self, off: int) -> bool:
        return self.lo <= off < self.hi


records = M.records
driver_entry = M.driver_entry


class Program:
    def __init__(self) -> None:
        image = M.image_file()
        self.ovls = M.overlays()
        self.data = {M.ROOT: M.program_image(ovls=self.ovls)}
        self.stubs = {o.stub: o for o in self.ovls}
        self.recs = records(image)
        self.code_segs = M.root_code_segs(image)
        _, rels, _ = M.mz(M.REF / M.ROOT)
        self.fixups = {M.ROOT: {s * 16 + o for o, s in rels} | {o.code + f for o in self.ovls for f in o.relocs}}
        self.units = {M.ROOT: Unit(M.ROOT, M.ROOT, 0, ROOT_CODE_END, "root")}
        for o in self.ovls:
            n = f"O{o.stub // 16:04X}"
            self.units[n] = Unit(n, M.ROOT, o.code, o.code + o.size, "overlay")
        for f, index in DRIVERS.items():
            raw = (M.REF / "GAMEDAT" / f).read_bytes()
            lo, hi = driver_entry(raw, index)
            self.data[f] = raw
            self.fixups[f] = set()
            self.units[f] = Unit(f, f, lo, hi, "driver")
        self.by_code = {o.code: f"O{o.stub // 16:04X}" for o in self.ovls}

    def unit_at(self, file: str, off: int) -> Unit | None:
        if file == M.ROOT and off < ROOT_CODE_END:
            return self.units[M.ROOT]
        for u in self.units.values():
            if u.file == file and u.kind != "root" and u.has(off):
                return u
        return None

    def cs_of(self, u: Unit, off: int) -> int:
        """The CS a unit's code runs with, as a link segment (overlays and drivers: 0 = IP
        from the unit's first byte)."""
        if u.kind != "root":
            return 0
        return max(s for s in self.code_segs if s * 16 <= off)

    def ip(self, u: Unit, off: int, cs: int) -> int:
        return off - u.lo if u.kind != "root" else off - cs * 16

    def near(self, u: Unit, cs: int, ip: int) -> int:
        return u.lo + ip if u.kind != "root" else cs * 16 + ip

    def far(self, seg: int, off: int) -> tuple[Unit | None, int, int, str]:
        """(unit, module offset, CS, why) of a far target given as link segment:offset."""
        o = self.stubs.get(seg * 16)
        if o is not None:
            k, r = divmod(off - 0x20, 5)
            if r == 0 and 0 <= k < len(o.entries):
                u = self.units[f"O{seg:04X}"]
                return u, o.code + o.entries[k], 0, f"stub {seg:04X} entry {k}"
            return None, 0, 0, f"stub {seg:04X}+{off:X} not an entry"
        lin = seg * 16 + off
        if seg in self.code_segs and lin < ROOT_CODE_END:
            return self.units[M.ROOT], lin, seg, "root"
        return None, 0, 0, "not code"


def noreturn() -> set[tuple[str, int]]:
    with (M.REPO / "annotations/noreturn.csv").open() as f:
        return {(r["module"], int(r["offset"], 16)) for r in csv.DictReader(f)}


def tables() -> dict[tuple[str, int], int]:
    with (M.REPO / "annotations/tables.csv").open() as f:
        return {(r["module"], int(r["site"], 16)): int(r["entries"]) for r in csv.DictReader(f)}


class Sweep:
    def __init__(self, prog: Program):
        self.p = prog
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
        self.md.detail = True
        self.cls = {f: bytearray(len(d)) for f, d in prog.data.items()}
        self.insn: dict[str, dict[int, object]] = {f: {} for f in prog.data}
        self.cs_at: dict[str, dict[int, int]] = {f: {} for f in prog.data}
        self.work: list[tuple[Unit, int, int, str]] = []
        self.conflicts: list[tuple[str, int, str]] = []
        self.far_refs: set[tuple[str, int, int, int, str]] = set()
        self.indirect: dict[tuple[str, int], str] = {}
        self.tables: dict[tuple[str, int], list[int]] = {}
        self.pending: list[tuple[Unit, int, int, object]] = []
        self.curated = tables()
        self.noreturn = noreturn()
        self.code_ptrs: set[tuple[str, int, str, int]] = set()
        self.searches: dict[tuple[str, int], tuple[int, int, int]] = {}
        self.data_ptrs: set[tuple[int, str, int]] = set()
        self.retf_funcs: set[tuple[str, int]] = set()
        self.entries: dict[tuple[str, int], str] = {}  # annotations/entries.csv rows

    def entry(self, u: Unit, off: int, why: str, cs: int | None = None) -> None:
        """A seed the translator's descent (translator/cfg.py) does not find by itself."""
        self.entries.setdefault((u.file, off), why)
        self.seed(u, off, why, cs)

    def seed(self, u: Unit, off: int, why: str, cs: int | None = None) -> None:
        self.work.append((u, off, self.p.cs_of(u, off) if cs is None else cs, why))

    def decode(self, u: Unit, off: int, cs: int):
        ip = self.p.ip(u, off, cs)
        data = self.p.data[u.file]
        return next(self.md.disasm(data[off:off + 16], ip), None) if 0 <= ip < 0x10000 else None

    def run(self) -> None:
        while self.work or self.pending or self.code_pointers() or self.after_retf():
            while self.work:
                self.flow(*self.work.pop())
            pending, self.pending = self.pending, []
            for u, off, cs, i in pending:
                if (u.file, off) not in self.tables:
                    self.switch(u, off, cs, i)

    def flow(self, u: Unit, off: int, cs: int, why: str) -> None:
        f = u.file
        cls = self.cls[f]
        if not u.has(off):
            self.conflicts.append((f, off, f"flow outside {u.name} ({why})"))
            return
        while u.has(off):
            if cls[off] == START:
                return
            if cls[off] == BODY:
                self.conflicts.append((f, off, f"start inside an instruction ({why})"))
                return
            i = self.decode(u, off, cs)
            if i is None:
                self.conflicts.append((f, off, f"undecodable ({why})"))
                return
            span = range(off, off + i.size)
            if off + i.size > u.hi or any(cls[k] for k in span):
                self.conflicts.append((f, off, f"overlaps ({why})"))
                return
            cls[off] = START
            for k in span[1:]:
                cls[k] = BODY
            self.insn[f][off] = i
            self.cs_at[f][off] = cs
            g = set(i.groups)
            ops = i.operands
            if capstone.CS_GRP_RET in g or capstone.CS_GRP_IRET in g or i.mnemonic == "hlt":
                return
            if i.mnemonic in ("ljmp", "lcall") and len(ops) == 2 and ops[0].type == x86.X86_OP_IMM:
                self.far_target(u, off, ops[0].imm & 0xFFFF, ops[1].imm & 0xFFFF)
                if i.mnemonic == "ljmp":
                    return
            elif capstone.CS_GRP_JUMP in g or capstone.CS_GRP_CALL in g or \
                    i.mnemonic in ("loop", "loope", "loopne", "jcxz"):
                if ops and ops[0].type == x86.X86_OP_IMM:
                    t = self.p.near(u, cs, ops[0].imm & 0xFFFF)
                    self.seed(u, t, f"{u.name}+{off:X}", cs)
                    if i.mnemonic == "call" and (f, t) in self.noreturn:
                        return
                else:
                    self.indirect[(f, off)] = f"{i.mnemonic} {i.op_str}"
                    self.pending.append((u, off, cs, i))
                if i.mnemonic == "loop":
                    self.search_loop(u, off, cs, i)
                if i.mnemonic in ("jmp", "ljmp"):  # an indirect far jump ends the flow too
                    return
            elif i.mnemonic == "int" and ops and ops[0].imm == 0x3F:
                self.conflicts.append((f, off, f"INT 3Fh in code ({why})"))
            off += i.size
        self.conflicts.append((f, off, f"flow past the end of {u.name} ({why})"))

    def far_target(self, u: Unit, at: int, seg: int, off: int) -> None:
        if u.kind == "driver":
            self.far_refs.add((u.file, at, seg, off, "driver: no relocation"))
            return
        t, to, cs, why = self.p.far(seg, off)
        self.far_refs.add((u.file, at, seg, off, f"{t.name}+{to:X}" if t else why))
        if t:
            self.seed(t, to, f"far from {u.name}+{at:X}", cs)

    def before(self, f: str, off: int, n: int = 12) -> list:
        out, k = [], off
        ins = self.insn[f]
        while len(out) < n:
            prev = next((ins[j] for j in range(k - 1, max(k - 8, 0), -1)
                         if j in ins and j + ins[j].size == k), None)
            if prev is None:
                break
            k -= prev.size
            out.append((k, prev))
        return out

    def switch(self, u: Unit, off: int, cs: int, i) -> None:
        ops = i.operands
        if i.mnemonic != "jmp" or not ops or ops[0].type != x86.X86_OP_MEM:
            return
        mem = ops[0].mem
        if i.reg_name(mem.segment) != "cs" or i.reg_name(mem.base) != "bx" or mem.index:
            return
        f = u.file
        disp = mem.disp & 0xFFFF
        prev = self.before(f, off)
        n = self.curated.get((f, off))
        if n is None and prev and prev[0][1].mnemonic == "shl" and prev[0][1].op_str == "bx, 1":
            cmp = next((p for _, p in prev[1:6] if p.mnemonic == "cmp" and p.op_str.startswith("bx, ")
                        and p.operands[1].type == x86.X86_OP_IMM), None)
            if cmp is not None:
                n = (cmp.operands[1].imm & 0xFFFF) + 1
        base = 0
        if n is None and (f, off) in self.searches:
            # value search: N word values at cs:[T+V] read in a loop (bx = T, cx = N before
            # it), the N targets at cs:[bx+V+2N] (the jump runs with bx at the match); a
            # long switch also compares the N high words at cs:[bx+V+2N], targets at +4N
            t, v, n = self.searches[(f, off)]
            if disp not in (v + 2 * n, v + 4 * n):
                self.conflicts.append((f, off, "value-search table bounds"))
                return
            for k in range(t + v, t + disp):
                self.mark_table(u, f, self.p.near(u, cs, k), off)
            base = t
        if n is None:
            return
        table = self.p.near(u, cs, (base + disp) & 0xFFFF)
        if not 0 < n <= 512 or not u.has(table) or not u.has(table + 2 * n - 1):
            self.conflicts.append((f, off, "switch table out of range"))
            return
        data = self.p.data[f]
        targets = []
        for k in range(n):
            ip, = struct.unpack_from("<H", data, table + 2 * k)
            targets.append(self.p.near(u, cs, ip))
            self.mark_table(u, f, table + 2 * k, off)
            self.mark_table(u, f, table + 2 * k + 1, off)
        self.tables[(f, off)] = targets
        for t in targets:
            self.seed(u, t, f"switch {u.name}+{off:X}", cs)

    def search_loop(self, u: Unit, off: int, cs: int, i) -> None:
        """Borland's value search: `mov cx,N; mov bx,T; L: mov ax,cs:[bx+V]; cmp ax,x;
        je F; inc bx; inc bx; loop L; jmp default; F: jmp cs:[bx+V+2N]`: remember (T, V,
        N) for the jump at F."""
        f = u.file
        body = self.before(f, off, 6)
        if len(body) < 5 or [p.mnemonic for _, p in body[:2]] != ["inc", "inc"]:
            return
        top = self.p.near(u, cs, i.operands[0].imm & 0xFFFF)
        load = self.insn[f].get(top)
        je = next((p for a, p in body if p.mnemonic == "je" and a > top), None)
        if load is None or je is None or load.mnemonic != "mov" or len(load.operands) != 2:
            return
        mem = load.operands[1]
        if mem.type != x86.X86_OP_MEM or load.reg_name(mem.mem.segment) != "cs" or \
                load.reg_name(mem.mem.base) != "bx":
            return
        setup = self.before(f, top, 4)
        cnt = next((p for _, p in setup if p.mnemonic == "mov" and p.op_str.startswith("cx, ")
                    and p.operands[1].type == x86.X86_OP_IMM), None)
        tbl = next((p for _, p in setup if p.mnemonic == "mov" and p.op_str.startswith("bx, ")
                    and p.operands[1].type == x86.X86_OP_IMM), None)
        if cnt is None or tbl is None:
            return
        found = self.p.near(u, cs, je.operands[0].imm & 0xFFFF)
        self.searches[(f, found)] = (tbl.operands[1].imm & 0xFFFF, mem.mem.disp & 0xFFFF,
                                     cnt.operands[1].imm & 0xFFFF)

    def mark_table(self, u: Unit, f: str, b: int, site: int) -> None:
        if self.cls[f][b] in (START, BODY):
            self.conflicts.append((f, b, f"switch table over code ({f}+{site:X})"))
        self.cls[f][b] = TABLE

    def code_pointers(self) -> bool:
        """`mov r,off; mov r,seg` (the segment relocated) to a far function prologue."""
        new = False
        for f, ins in self.insn.items():
            fix = self.p.fixups[f]
            for at, i in list(ins.items()):
                if i.mnemonic != "mov" or i.size != 3 or (at + 1) not in fix:
                    continue
                prev = next((ins[j] for j in (at - 3,) if j in ins), None)
                if not (prev and prev.mnemonic == "mov" and prev.size == 3 and
                        prev.operands[0].type == x86.X86_OP_REG and prev.operands[1].type == x86.X86_OP_IMM):
                    continue
                seg, off = i.operands[1].imm & 0xFFFF, prev.operands[1].imm & 0xFFFF
                t, to, cs, _ = self.p.far(seg, off)
                if t is None or (f, at - 3, t.file, to) in self.code_ptrs:
                    continue
                if t.kind == "root" and not any(self.p.data[t.file].startswith(p, to) for p in PROLOGUES):
                    continue
                self.code_ptrs.add((f, at - 3, t.file, to))
                self.entry(t, to, f"far pointer {f}+{at - 3:X}", cs)
                new = True
        return new

    def after_retf(self) -> bool:
        """A far function right after a decoded RETF (prologue), unreached otherwise."""
        new = False
        for f, ins in self.insn.items():
            cls, data = self.cls[f], self.p.data[f]
            for at, i in list(ins.items()):
                nxt = at + i.size
                if i.mnemonic != "retf" or nxt >= len(cls) or cls[nxt]:
                    continue
                u = self.p.unit_at(f, nxt)
                if u is None or not any(data.startswith(p, nxt) for p in PROLOGUES):
                    continue
                if (f, nxt) not in self.retf_funcs:
                    self.retf_funcs.add((f, nxt))
                    self.entry(u, nxt, f"after retf {f}+{at:X}")
                    new = True
        return new


def static_seeds(sw: Sweep, prog: Program) -> None:
    root = prog.units[M.ROOT]
    cs, ip = M.mz(M.REF / M.ROOT)[2]
    sw.seed(root, cs * 16 + ip, "MZ entry", cs)
    for o in prog.ovls:
        u = prog.units[f"O{o.stub // 16:04X}"]
        for k, e in enumerate(o.entries):
            sw.seed(u, o.code + e, f"stub {o.stub // 16:04X} entry {k}", 0)
    data = prog.data[M.ROOT]
    for a in range(STARTUP[0], STARTUP[1] + 6, 6):
        kind, _, off, seg = struct.unpack_from("<BBHH", data, a)
        if kind == 1:
            t, to, tcs, _ = prog.far(seg, off)
        else:
            t, to, tcs = root, off, 0
        if t:
            sw.entry(t, to, f"startup table {a:X}", tcs)
    # far pointers in the root's data: a relocated segment word after an offset word
    _, rels, _ = M.mz(M.REF / M.ROOT)
    for o, sg in rels:
        a = sg * 16 + o
        if a < ROOT_CODE_END or a < 2:
            continue
        seg, = struct.unpack_from("<H", data, a)
        off, = struct.unpack_from("<H", data, a - 2)
        t, to, tcs, _ = prog.far(seg, off)
        if t is None or (t.kind == "root" and not any(data.startswith(p, to) for p in PROLOGUES)):
            continue
        sw.data_ptrs.add((a - 2, t.file, to))
        sw.entry(t, to, f"far pointer in data {a - 2:X}", tcs)
    for f, n in DRIVER_TABLE.items():
        u = prog.units[f]
        d = prog.data[f]
        for k in range(1, n):
            w, = struct.unpack_from("<H", d, u.lo + 2 * k)
            if w and u.has(u.lo + w):
                sw.entry(u, u.lo + w, f"{f} entry table {k}", 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=M.CORPUS, help="tmp/pc-runs globs for the trace corpus (wc2_model.CORPUS)")
    ap.add_argument("--annotations", action="store_true", help="write annotations/indirect.csv")
    args = ap.parse_args()
    prog = Program()
    traces = M.runs(args.runs)
    exe = M.executed(traces)
    irq = M.csv_rows(traces, "interrupts.csv")
    hw = {(r["target_module"], int(r["target_offset"], 16)) for r in irq
          if r["type"] == "0" and r["target_module"] != "-"}
    handlers = {(r["target_module"], int(r["target_offset"], 16)) for r in irq if r["target_module"] != "-"}
    edge_set = M.edges(traces)

    sw = Sweep(prog)
    static_seeds(sw, prog)
    sw.run()
    static_starts = {f: {o for o, c in enumerate(cls) if c == START} for f, cls in sw.cls.items()}
    for tm, to in sorted(handlers):
        u = prog.unit_at(tm, to)
        if u:
            sw.entry(u, to, "interrupt handler")
    sw.run()
    targets: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    while True:
        new = False
        for fm, fo, tm, to in edge_set:
            if (fm, fo) in sw.indirect and (tm, to) not in targets[(fm, fo)]:
                targets[(fm, fo)].add((tm, to))
                u = prog.unit_at(tm, to)
                if u:
                    sw.seed(u, to, f"indirect {fm}+{fo:X}")
                    new = True
        sw.run()
        if not new:
            break

    # stub cells: executed stub bytes are the two-form entries and the return-trap header
    stub_cells = 0
    for o in prog.ovls:
        cells = [(o.stub, o.stub + 2)] + [(o.stub + 0x20 + 5 * k, o.stub + 0x25 + 5 * k)
                                          for k in range(len(o.entries))]
        for lo, hi in cells:
            for b in range(lo, hi):
                sw.cls[M.ROOT][b] = STUB
            stub_cells += 1

    OUT.mkdir(parents=True, exist_ok=True)
    not_reached: dict[str, list[int]] = {}
    with (OUT / "coverage.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["module", "unit_bytes", "static_code", "code", "executed_code", "unexecuted_code",
                    "switch_tables", "stub_cells", "executed_starts", "executed_not_reached",
                    "executed_not_static", "indirect_sites", "indirect_traced"])
        for f, cls in sw.cls.items():
            units = [u for u in prog.units.values() if u.file == f]
            body = sum(u.hi - u.lo for u in units)
            starts = exe.get(f, set())
            miss = sorted(s for s in starts if s >= len(cls) or cls[s] not in (START, STUB))
            not_reached[f] = miss
            not_static = sum(1 for s in starts if s not in static_starts[f] and
                             (s >= len(cls) or cls[s] != STUB))
            ex = bytearray(len(cls))
            for s in starts:
                if s < len(cls) and cls[s] == START:
                    for k in range(s, s + sw.insn[f][s].size):
                        ex[k] = 1
            code = sum(1 for c in cls if c in (START, BODY))
            stat = sum(1 for s in static_starts[f] for _ in [0])
            out = bytearray(c + (2 if ex[k] and c in (START, BODY) else 0) for k, c in enumerate(cls))
            (OUT / f"{f}.cls").write_bytes(bytes(out))
            sites = [s for s in sw.indirect if s[0] == f]
            w.writerow([f, body, stat, code, sum(ex), code - sum(ex), sum(1 for c in cls if c == TABLE),
                        sum(1 for c in cls if c == STUB), len(starts), len(miss), not_static,
                        len(sites), sum(1 for s in sites if targets.get(s))])
    with (OUT / "not-reached.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["module", "offset"])
        for f, miss in not_reached.items():
            for s in miss:
                w.writerow([f, f"0x{s:05x}"])
    with (OUT / "conflicts.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["module", "offset", "reason"])
        for mod, off, why in sorted(set(sw.conflicts)):
            w.writerow([mod, f"0x{off:05x}", why])
    with (OUT / "far-refs.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["module", "offset", "segment", "target", "resolved"])
        for mod, at, seg, off, why in sorted(sw.far_refs):
            w.writerow([mod, f"0x{at:05x}", f"0x{seg:04x}", f"0x{off:04x}", why])
    rows = []
    for (mod, off), text in sorted(sw.indirect.items()):
        ts = sorted(targets.get((mod, off), ()))
        table = sw.tables.get((mod, off), [])
        rows.append([mod, f"0x{off:05x}", text, int(off in exe.get(mod, ())),
                     " ".join(f"{mod}+0x{t:05x}" for t in sorted(set(table))),
                     " ".join(f"{tm}+0x{to:05x}" + (" (isr)" if (tm, to) in hw else "")
                              for tm, to in ts)])
    paths = [OUT / "entries.csv"] + ([M.REPO / "annotations/entries.csv"] if args.annotations else [])
    for path in paths:
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["module", "offset", "reason"])
            for (mod, off), why in sorted(sw.entries.items()):
                w.writerow([mod, f"0x{off:05x}", why])
    paths = [OUT / "indirect.csv"] + ([M.REPO / "annotations/indirect.csv"] if args.annotations else [])
    for path in paths:
        with path.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["module", "offset", "instruction", "executed", "switch_targets", "traced_targets"])
            w.writerows(rows)
    with (OUT / "code-pointers.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["module", "offset", "kind", "target"])
        out = [(m, a, "pointer", f"{tm}+0x{to:05x}") for m, a, tm, to in sw.code_ptrs]
        out += [(m, n, "after retf", f"{m}+0x{n:05x}") for m, n in sw.retf_funcs]
        out += [(M.ROOT, a, "data pointer", f"{tm}+0x{to:05x}") for a, tm, to in sw.data_ptrs]
        for m, a, k, t in sorted(out):
            w.writerow([m, f"0x{a:05x}", k, t])
    print((OUT / "coverage.csv").read_text(), end="")
    nconf = len(set(sw.conflicts))
    miss = sum(len(v) for v in not_reached.values())
    print(f"traces {len(traces)}, conflicts {nconf}, executed starts not reached {miss}, "
          f"far refs {len(sw.far_refs)}, code pointers {len(sw.code_ptrs)}, after retf "
          f"{len(sw.retf_funcs)}, data pointers {len(sw.data_ptrs)}, switch tables {len(sw.tables)}, stub cells {stub_cells}")
    return 1 if nconf or miss or not traces else 0


if __name__ == "__main__":
    sys.exit(main())
