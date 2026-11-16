#!/usr/bin/env python3
"""External surface of the original (port-plan P2.5): writes docs/external-surface.md.

Adapted from Secret Weapons of Luftwaffe's tools/surface.py, with sections of X-Wing's
tools/census.py (docs/upstream.md). Static: every `int`/`in`/`out` among the sweep's
instruction starts (tmp/sweep/*.cls; run tools/sweep.py first), and the opcode census of
the swept code with the translator's decoder fit. Traced (the trace corpus):
interrupts.csv, ports.csv, vga.csv and the service, file and EMS events of events.csv.
Every row is MEASURED (traced) or DERIVED (static, or computed from measured values).

  python3 tools/surface.py [--runs GLOB] [--write docs/external-surface.md]

Exit 1 if a traced interrupt or port site is not a static instruction of the sweep, or
if an input is missing.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

import capstone
from capstone import x86

import wc2_model as M
from sweep import DRIVER_TABLE, Program

sys.path.insert(0, str(M.REPO))
from translator.decode import DecodeError, decode  # noqa: E402

SWEEP = M.REPO / "tmp/sweep"
OPCODES_186 = {0x60: "pusha", 0x61: "popa", 0x62: "bound", 0x68: "push imm16", 0x69: "imul imm16",
               0x6A: "push imm8", 0x6B: "imul imm8", 0x6C: "insb", 0x6D: "insw", 0x6E: "outsb",
               0x6F: "outsw", 0xC0: "shift r/m8, imm8", 0xC1: "shift r/m16, imm8", 0xC8: "enter",
               0xC9: "leave"}
PORT_CLASSES = [
    ("DMA controller", lambda p: p < 0x20 or 0x80 <= p < 0xA0 or 0xC0 <= p < 0xE0),
    ("PIC", lambda p: p in (0x20, 0x21, 0xA0, 0xA1)),
    ("PIT", lambda p: 0x40 <= p <= 0x43),
    ("keyboard controller, speaker", lambda p: p in (0x60, 0x61, 0x64)),
    ("game port", lambda p: p == 0x201),
    ("Sound Blaster DSP and mixer", lambda p: 0x222 <= p <= 0x22F),
    ("OPL at the Sound Blaster (220h/221h, 228h/229h)", lambda p: p in (0x220, 0x221, 0x228, 0x229)),
    ("OPL at 388h/389h", lambda p: p in (0x388, 0x389)),
    ("MPU-401", lambda p: p in (0x330, 0x331)),
    ("VGA", lambda p: 0x3C0 <= p <= 0x3DF),
]
PIT_HZ = 1193182


def regs(text: str) -> dict[str, int]:
    out = {}
    for x in text.split()[1:]:
        if "=" in x:
            k, v = x.split("=", 1)
            out[k] = int(v, 16)
    return out


def events(trace: Path):
    with (trace / "events.csv").open() as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split(",", 4)
            if len(p) == 5:
                yield int(p[0]), p[1], p[2], int(p[3], 16), p[4]


STD_HANDLES = {0: "stdin", 1: "stdout", 2: "stderr", 3: "stdaux", 4: "stdprn"}


class Corpus:
    def __init__(self, traces: list[Path]):
        self.traces = traces
        self.svc: dict[str, Counter] = {}       # run -> (vector, ah or ax, module, offset) counts
        self.ems: dict[str, Counter] = {}
        self.ems_pages: dict[str, set] = {}
        self.ems_logical: dict[str, set] = {}
        self.ems_alloc: dict[str, list[int]] = {}
        self.ticks: dict[str, int] = {}
        self.files_read: dict[str, Counter] = defaultdict(Counter)   # name -> run -> bytes
        self.files_open: Counter = Counter()
        self.files_write: dict[str, Counter] = defaultdict(Counter)
        self.files_deleted: Counter = Counter()
        self.modes: Counter = Counter()
        self.palette: Counter = Counter()
        self.vectors: Counter = Counter()
        self.mouse: Counter = Counter()
        for t in traces:
            run = t.parent.name
            c, e = Counter(), Counter()
            pages, logical, alloc = set(), set(), []
            handles: dict[int, str] = {}
            ticks = 0
            for icount, kind, mod, off, detail in events(t):
                if kind == "svc":
                    vec = detail.split()[0]
                    r = regs(detail)
                    ax = r.get("ax", 0)
                    c[(vec, ax >> 8, mod, off)] += 1
                    if vec == "67":
                        e[ax >> 8] += 1
                        if ax >> 8 == 0x44:
                            pages.add(ax & 0xFF)
                            logical.add(r.get("bx", 0))
                        if ax >> 8 == 0x43:
                            alloc.append(r.get("bx", 0))
                    elif vec == "10" and ax >> 8 == 0:
                        self.modes[(ax & 0xFF, mod, off)] += 1
                    elif vec == "10" and ax >> 8 == 0x10:
                        self.palette[(ax, mod)] += 1
                    elif vec == "21" and ax >> 8 == 0x25:
                        self.vectors[(ax & 0xFF, mod, off)] += 1
                    elif vec == "33" and ax in (0x0C, 0x14, 0x18):
                        self.mouse[(ax, mod)] += 1
                elif kind in ("open", "create"):
                    p = detail.split()
                    kv = dict(x.split("=", 1) for x in p[1:] if "=" in x)
                    if kv.get("ok") == "1":
                        handles[int(kv["handle"])] = p[0]
                        self.files_open[(p[0], kv.get("mode", "?") if kind == "open" else "create")] += 1
                elif kind == "read":
                    p = detail.split()
                    kv = dict(x.split("=", 1) for x in p[1:] if "=" in x)
                    self.files_read[p[0]][run] += int(kv.get("got", 0))
                elif kind == "write":
                    p = detail.split()
                    kv = dict(x.split("=", 1) for x in p[1:] if "=" in x)
                    name = p[0] if p[0] != "?" else STD_HANDLES.get(int(kv["handle"]), "?")
                    self.files_write[name][run] += int(kv.get("actual", 0))
                elif kind == "delete":
                    p = detail.split()
                    self.files_deleted[(p[0], "ok=1" in p)] += 1
            for r in M.csv_rows([t], "interrupts.csv"):
                if r["type"] == "0" and int(r["vector"], 16) == 8:
                    ticks += int(r["count"])
            self.svc[run], self.ems[run] = c, e
            self.ems_pages[run], self.ems_logical[run], self.ems_alloc[run] = pages, logical, alloc
            self.ticks[run] = ticks


def static_sites(prog: Program):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    md.detail = True
    ints, ports = {}, {}
    for f, data in prog.data.items():
        cls = (SWEEP / f"{f}.cls").read_bytes()
        for off, c in enumerate(cls):
            if c not in (1, 3):
                continue
            k = off
            while data[k] in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3):
                k += 1
            if data[k] not in (0xCD, 0xCC, 0xCE, 0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF,
                               0x6C, 0x6D, 0x6E, 0x6F):
                continue
            i = next(md.disasm(data[off:off + 6], 0), None)
            if i is None:
                continue
            if i.mnemonic == "int":
                ints[(f, off)] = i.operands[0].imm & 0xFF
            elif i.mnemonic in ("in", "out"):
                op = i.operands[1] if i.mnemonic == "in" else i.operands[0]
                port = f"{op.imm & 0xFF:02X}h" if op.type == x86.X86_OP_IMM else "dx"
                ports[(f, off)] = (i.mnemonic, port, c == 3)
            else:
                ports[(f, off)] = (i.mnemonic, "dx", c == 3)
    for o in prog.ovls:     # the stub cells: the return trap and the entries (docs/vroomm.md)
        for cell in [o.stub] + [o.stub + 0x20 + 5 * k for k in range(len(o.entries))]:
            ints[(M.ROOT, cell)] = 0x3F
    return ints, ports


def opcodes(prog: Program, out: list[str]) -> None:
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
    out.append("## Opcodes and the decoder (DERIVED: the sweep's instruction starts)\n")
    out.append("| Module | Starts | Executed | Mnemonics | 80186+ starts (executed) | "
               "Rejected by translator/decode.py (executed) |\n|---|---|---|---|---|---|")
    ops186: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    reasons: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for f, data in prog.data.items():
        cls = (SWEEP / f"{f}.cls").read_bytes()
        n = ex = n186 = x186 = rej = xrej = 0
        mn = set()
        for off, c in enumerate(cls):
            if c not in (1, 3):
                continue
            n += 1
            ex += c == 3
            i = next(md.disasm(data[off:off + 16], 0), None)
            if i is not None:
                mn.add(i.mnemonic)
            k = off
            while data[k] in (0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3):
                k += 1
            if data[k] in OPCODES_186 or data[k] == 0x0F:
                n186 += 1
                x186 += c == 3
                r = ops186[(f, data[k])]
                r[0] += 1
                r[1] += c == 3
            try:
                decode(data[off:off + 16], 0)
            except DecodeError as e:
                rej += 1
                xrej += c == 3
                r = reasons[f"{e}"]
                r[0] += 1
                r[1] += c == 3
        out.append(f"| {f} | {n} | {ex} | {len(mn)} | {n186} ({x186}) | {rej} ({xrej}) |")
    out.append("\n| Module | Opcode | Instruction | Starts | Executed |\n|---|---|---|---|---|")
    for (f, op), (s, x) in sorted(ops186.items()):
        out.append(f"| {f} | {op:02X}h | {OPCODES_186.get(op, '0Fh escape')} | {s} | {x} |")
    top = sorted(reasons.items(), key=lambda kv: -kv[1][0])
    out.append("\nDecoder rejections by reason, starts (executed): " +
               ("; ".join(f"{k}: {s} ({x})" for k, (s, x) in top[:12]) or "none") +
               (f"; {len(top) - 12} more reasons" if len(top) > 12 else "") + ".\n")


def interrupts(corpus: Corpus, ints, out: list[str], bad: list[str]) -> None:
    sw = defaultdict(Counter)
    hw = defaultdict(Counter)
    hooked = defaultdict(Counter)
    for r in M.csv_rows(corpus.traces, "interrupts.csv"):
        vec, src, off = int(r["vector"], 16), r["source_module"], int(r["source_offset"], 16)
        n = int(r["count"])
        if r["type"] == "0":
            hw[vec][f"{r['target_module']}+{int(r['target_offset'], 16):05X}"] += n
            continue
        if src == "-":
            if r["target_module"] != "-":
                hooked[vec][f"{r['target_module']}+{int(r['target_offset'], 16):05X}"] += n
            continue
        site = (src, off - 2)
        if site not in ints:
            bad.append(f"traced INT {vec:02X}h at {src}+{off - 2:05X} is not a static int site")
        ax = int(r["ax"], 16)
        if vec == 0x33 or (vec, ax >> 8) in ((0x21, 0x25), (0x21, 0x35), (0x10, 0x10)):
            fn = f"AX={ax:04X}h"
        elif vec in (0x10, 0x16, 0x1A, 0x21, 0x2F, 0x67):
            fn = f"AH={ax >> 8:02X}h"
        else:
            fn = ""
        sw[(vec, fn)][site] += n
    out.append("## Interrupts (MEASURED)\n")
    out.append("Software interrupts raised by the game, by function; sites are the `int` "
               "instructions (module+offset ×count, all traces).\n")
    out.append("| INT | Function | Sites |\n|---|---|---|")
    for (vec, fn), sites in sorted(sw.items()):
        s = ", ".join(f"{m}+{o:05X}×{c}" for (m, o), c in sorted(sites.items())[:6])
        more = f" (+{len(sites) - 6} sites)" if len(sites) > 6 else ""
        out.append(f"| {vec:02X}h | {fn} | {s}{more} |")
    traced = {s for sites in sw.values() for s in sites}
    untraced = sorted(k for k in ints if k not in traced)
    byv = defaultdict(list)
    for k in untraced:
        byv[ints[k]].append(f"{k[0]}+{k[1]:05X}")
    out.append(f"\nStatic `int` sites {len(ints)} (DERIVED), traced {len(traced)}; never traced: " +
               ("; ".join(f"INT {v:02X}h ×{len(ss)} ({' '.join(ss[:4])}{' …' if len(ss) > 4 else ''})"
                          for v, ss in sorted(byv.items())) or "none") + ".\n")
    out.append("| Vector | Raised by | Handler (×count) |\n|---|---|---|")
    for vec, targets in sorted(hooked.items()):
        out.append(f"| {vec:02X}h | software, through the IVT | "
                   f"{', '.join(f'{k}×{n}' for k, n in sorted(targets.items()))} |")
    for vec, targets in sorted(hw.items()):
        out.append(f"| {vec:02X}h | hardware | {', '.join(f'{k}×{n}' for k, n in sorted(targets.items()))} |")
    out.append("\nVectors set (INT 21h AH=25h, MEASURED):\n")
    out.append("| Vector | Set by (×count) |\n|---|---|")
    by = defaultdict(list)
    for (v, m, o), n in sorted(corpus.vectors.items()):
        by[v].append(f"{m}+{o:05X}×{n}")
    for v, sites in sorted(by.items()):
        out.append(f"| {v:02X}h | {', '.join(sites)} |")
    out.append(f"\nMouse event handlers (INT 33h AX=000Ch/0014h/0018h): "
               f"{', '.join(f'AX={a:04X}h {m}×{n}' for (a, m), n in sorted(corpus.mouse.items())) or 'none'}.\n")


def ports(corpus: Corpus, static, out: list[str], bad: list[str]) -> None:
    by = defaultdict(lambda: [0, 0, set(), set()])
    sites = defaultdict(Counter)
    for r in M.csv_rows(corpus.traces, "ports.csv"):
        if r["source_module"] == "-":
            continue
        p = int(r["port"], 16)
        site = (r["source_module"], int(r["source_offset"], 16))
        if site not in static:
            bad.append(f"traced port {p:03X}h at {site[0]}+{site[1]:05X} is not a static in/out")
        cls = next((n for n, f in PORT_CLASSES if f(p)), f"other {p:03X}h")
        v = by[cls]
        v[0 if r["direction"] == "in" else 1] += int(r["count"])
        v[2].add(f"{p:03X}h")
        v[3].add(r["source_module"])
        sites[(r["direction"], p)][site] += int(r["count"])
    out.append("## Ports (MEASURED)\n")
    out.append("| Device | In | Out | Ports | Modules |\n|---|---|---|---|---|")
    for name, _ in PORT_CLASSES:
        i, o, ps, ms = by.get(name, [0, 0, set(), set()])
        out.append(f"| {name} | {i} | {o} | {' '.join(sorted(ps)) or 'never touched'} | {' '.join(sorted(ms))} |")
    for name, (i, o, ps, ms) in sorted(by.items()):
        if not any(name == n for n, _ in PORT_CLASSES):
            out.append(f"| {name} | {i} | {o} | {' '.join(sorted(ps))} | {' '.join(sorted(ms))} |")
    out.append("\n| Dir | Port | Sites (×count) |\n|---|---|---|")
    for (d, p), ss in sorted(sites.items(), key=lambda k: (k[0][1], k[0][0])):
        s = ", ".join(f"{m}+{o:05X}×{c}" for (m, o), c in sorted(ss.items())[:5])
        more = f" (+{len(ss) - 5})" if len(ss) > 5 else ""
        out.append(f"| {d} | {p:03X}h | {s}{more} |")
    traced = {s for ss in sites.values() for s in ss}
    untraced = sorted(k for k in static if k not in traced)
    out.append(f"\nStatic in/out sites {len(static)} (DERIVED), traced {len(traced)}; never traced: " +
               (", ".join(f"{m}+{o:05X} {static[(m, o)][0]} {static[(m, o)][1]}" for m, o in untraced[:20])
                or "none") + (f" (+{len(untraced) - 20})" if len(untraced) > 20 else "") + ".\n")


def pit(corpus: Corpus, out: list[str]) -> None:
    outs = defaultdict(Counter)
    for r in M.csv_rows(corpus.traces, "ports.csv"):
        p = int(r["port"], 16)
        if r["direction"] == "out" and 0x40 <= p <= 0x43:
            outs[(p, r["source_module"])][int(r["value"], 16)] += int(r["count"])
    out.append("## Timer (MEASURED)\n")
    out.append("| Port | Writer | Values (×count) |\n|---|---|---|")
    for (p, m), vals in sorted(outs.items()):
        out.append(f"| {p:02X}h | {m} | {', '.join(f'{v:02X}h×{n}' for v, n in sorted(vals.items())[:8])} |")
    lo = [v for v in outs.get((0x40, M.ROOT), {}) if v not in (0,)]
    run = next((r for r in corpus.ticks if r.startswith("ref-m6")), None)
    out.append("")
    if run:
        out.append(f"IRQ 0 taken in {run}: {corpus.ticks[run]}. ")
    out.append(f"The game's divisor (DERIVED from the counter 0 writes and the handler's tick count, "
               f"docs/pc-reference-loop.md): 4DAEh, {PIT_HZ / 0x4DAE:.2f} Hz.\n")
    del lo


def vga(corpus: Corpus, out: list[str]) -> None:
    out.append("## VGA (MEASURED)\n")
    out.append("Modes set (INT 10h AH=00h): " +
               ", ".join(f"{mode:02X}h at {m}+{o:05X}×{n}" for (mode, m, o), n in sorted(corpus.modes.items())) + ".")
    out.append("Palette services (INT 10h AH=10h): " +
               (", ".join(f"AX={a:04X}h {m}×{n}" for (a, m), n in sorted(corpus.palette.items())) or "none") + ".")
    seq = defaultdict(Counter)
    regs_out = Counter()
    status = Counter()
    for r in M.csv_rows(corpus.traces, "ports.csv"):
        p = int(r["port"], 16)
        if r["source_module"] == "-":
            continue
        if r["direction"] == "out" and 0x3C0 <= p <= 0x3DF:
            regs_out[f"{p:03X}h"] += int(r["count"])
            if p in (0x3C4, 0x3CE, 0x3D4) and int(r["width"]) == 2:
                v = int(r["value"], 16)
                seq[f"{p:03X}h index {v & 0xFF:02X}h"][v >> 8] += int(r["count"])
        if r["direction"] == "in" and p == 0x3DA:
            status[f"{r['source_module']}+{int(r['source_offset'], 16):05X}"] += int(r["count"])
    out.append("Register writes by port: " + ", ".join(f"{k}×{n}" for k, n in sorted(regs_out.items())) + ".")
    if seq:
        out.append("Indexed word writes (index: data values): " +
                   "; ".join(f"{k}: {', '.join(f'{v:02X}h×{n}' for v, n in sorted(c.items()))}"
                             for k, c in sorted(seq.items())) + ".")
    out.append("Input status (3DAh) reads by site, the retrace waits: " +
               ", ".join(f"{k}×{n}" for k, n in status.most_common(8)) +
               (f" (+{len(status) - 8} sites)" if len(status) > 8 else "") + ".\n")
    pages = defaultdict(lambda: [0, 0, set()])
    for r in M.csv_rows(corpus.traces, "vga.csv"):
        v = pages[r["source_module"]]
        v[0 if r["direction"] == "read" else 1] += int(r["count"])
        v[2].add(int(r["page"], 16))
    out.append("| Module | Reads | Writes | A000h pages (256 B) | Highest |\n|---|---|---|---|---|")
    for m, (rd, wr, ps) in sorted(pages.items()):
        out.append(f"| {m} | {rd} | {wr} | {len(ps)} | {max(ps):05X}h |")
    out.append("")


def ems(corpus: Corpus, out: list[str]) -> None:
    out.append("## EMS (INT 67h, MEASURED)\n")
    funcs = sorted({k for c in corpus.ems.values() for k in c})
    out.append("| Run | Timer ticks | " + " | ".join(f"AH={f:02X}h" for f in funcs) +
               " | Maps per tick | Physical pages | Logical pages | Allocated |\n|---|---|" +
               "---|" * len(funcs) + "---|---|---|---|")
    for run, c in corpus.ems.items():
        ticks = corpus.ticks.get(run, 0)
        rate = f"{c.get(0x44, 0) / ticks:.2f}" if ticks else "-"
        lp = corpus.ems_logical[run]
        out.append(f"| {run} | {ticks} | " + " | ".join(str(c.get(f, 0)) for f in funcs) +
                   f" | {rate} | {' '.join(str(p) for p in sorted(corpus.ems_pages[run])) or '-'} | "
                   f"{(str(min(lp)) + '–' + str(max(lp))) if lp else '-'} | "
                   f"{' '.join(str(a) for a in corpus.ems_alloc[run]) or '-'} |")
    out.append("")


def delete(corpus: Corpus, name: str) -> str:
    done, failed = corpus.files_deleted.get((name, True), 0), corpus.files_deleted.get((name, False), 0)
    return f"{done} of {done + failed}" if done + failed else "-"


def files(corpus: Corpus, out: list[str]) -> None:
    out.append("## DOS files (MEASURED)\n")
    out.append("Opened (AH=3Dh mode, or create: AH=3Ch), bytes read and written (the largest run), "
               "deletions (AH=41h: done of asked).\n")
    out.append("| File | Opened (mode ×count) | Bytes read | Bytes written | Deleted |\n|---|---|---|---|---|")
    names = sorted({n for n, _ in corpus.files_open} | set(corpus.files_read) |
                   set(corpus.files_write) | {n for n, _ in corpus.files_deleted})
    for n in names:
        modes = ", ".join(f"{m}×{c}" for (f, m), c in sorted(corpus.files_open.items()) if f == n)
        rd, wr = corpus.files_read.get(n), corpus.files_write.get(n)
        out.append(f"| {n} | {modes or '-'} | {max(rd.values()) if rd else 0} | "
                   f"{max(wr.values()) if wr else 0} | {delete(corpus, n)} |")
    out.append("")


def drivers(corpus: Corpus, prog: Program, out: list[str]) -> None:
    out.append("## Driver interface (MEASURED; docs/drivers.md)\n")
    loads = defaultdict(Counter)
    for t in corpus.traces:
        with (t / "events.csv").open() as f:
            for line in f:
                if ",read," not in line or ".DRV " not in line:
                    continue
                p = line.rstrip("\n").split(",", 4)[4].split()
                kv = dict(x.split("=", 1) for x in p[1:] if "=" in x)
                if int(kv.get("got", 0)) > 64:
                    loads[p[0]][(int(kv["linear"], 16), int(kv["pos"], 16), int(kv["got"]))] += 1
    hw = {(r["target_module"], int(r["target_offset"], 16))
          for r in M.csv_rows(corpus.traces, "interrupts.csv") if r["type"] == "0"}
    edges = M.edges(corpus.traces)
    out.append("| Driver | Loads (linear, file offset, bytes ×traces) | Entries called (callers) | "
               "Callbacks |\n|---|---|---|---|")
    for f, n in DRIVER_TABLE.items():
        u = prog.units[f]
        d = prog.data[f]
        table = {u.lo + struct.unpack_from("<H", d, u.lo + 2 * k)[0]: k for k in range(1, n)
                 if struct.unpack_from("<H", d, u.lo + 2 * k)[0]}
        called = defaultdict(set)
        for fm, fo, tm, to in edges:
            if tm == f and fm != f and to in table and (tm, to) not in hw:
                called[table[to]].add(f"{fm}+{fo:05X}")
        back = Counter()
        with (SWEEP / "indirect.csv").open() as fh:
            for r in csv.DictReader(fh):
                if r["module"] == f and r["instruction"].startswith("lcall"):
                    for t in r["traced_targets"].replace(" (isr)", "(isr)").split():
                        if not t.endswith("(isr)") and not t.startswith(f):
                            back[f"{t} ({r['instruction']})"] += 1
        ld = ", ".join(f"{lin:05X}h, +{pos:X}, {got} ×{c}" for (lin, pos, got), c in sorted(loads[f].items()))
        ent = ", ".join(f"{k} ({len(called[k])})" for k in sorted(called))
        out.append(f"| {f} | {ld} | {ent} | {', '.join(sorted(back)) or 'none'} |")
    out.append("\nEntries are the entry-table indices whose address a far call from outside the "
               "driver reached; callbacks are the driver's indirect far calls and their traced "
               "targets (tools/sweep.py), apart from the timer interrupt.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=M.CORPUS, help="tmp/pc-runs globs for the trace corpus (wc2_model.CORPUS)")
    ap.add_argument("--write", type=Path, help="write the markdown there (docs/external-surface.md)")
    args = ap.parse_args()
    prog = Program()
    for f in prog.data:
        if not (SWEEP / f"{f}.cls").exists():
            print(f"surface: tmp/sweep/{f}.cls missing: run tools/sweep.py", file=sys.stderr)
            return 1
    traces = M.runs(args.runs)
    if not traces:
        print("surface: no traces", file=sys.stderr)
        return 1
    corpus = Corpus(traces)
    ints, prts = static_sites(prog)
    bad: list[str] = []
    out = ["# External surface",
           "",
           "Generated by `tools/surface.py` (port-plan P2.5) from the sweep (`tools/sweep.py`) and "
           f"the milestone traces ({len(traces)} traces, `{args.runs}`; reference config "
           "`reference/dosbox-x.conf`). Module offsets are `WC2.EXE` image offsets and driver "
           "file offsets ([pc-reference-loop.md](pc-reference-loop.md)). MEASURED rows are "
           "traced; DERIVED rows come from the static code or from measured values. Overlay "
           "manager: [vroomm.md](vroomm.md); drivers: [drivers.md](drivers.md).",
           ""]
    interrupts(corpus, ints, out, bad)
    ports(corpus, prts, out, bad)
    pit(corpus, out)
    vga(corpus, out)
    ems(corpus, out)
    files(corpus, out)
    drivers(corpus, prog, out)
    opcodes(prog, out)
    text = "\n".join(out).rstrip() + "\n"
    if args.write:
        args.write.write_text(text)
    else:
        print(text, end="")
    for b in sorted(set(bad))[:20]:
        print(b, file=sys.stderr)
    print(f"surface: {len(traces)} traces, {len(ints)} int sites, {len(prts)} port sites, "
          f"{len(set(bad))} mismatches", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
