#!/usr/bin/env python3
"""Review of the indirect sites the traces never ran (port-plan P6.4, gate 6;
X-Wing 33d685a's review, generated here): writes docs/indirect-coverage.md.

Inputs: annotations/indirect.csv (make map), the dispatch table of
build/gen/program.s (make gen), the milestone runs' snapshots (tmp/pc-runs/ref-*-a,
snap-*/ram.bin: linear memory; m0's, the MZ entry, is left out) and the trace corpus (wc2_model.CORPUS).

A site whose operand is a constant address (`[disp]`, DS = DGROUP for the root and
overlays and the manager's data 16B8h in the overlay manager, `cs:[disp]` the site's CS) is resolved in every snapshot: the far or near
pointer there and whether the dispatch table has a row for it (rt_lookup finds the
target; without one the site stops loudly). A snapshot value is not execution
evidence and not a proof against a later write. Control: the same resolution on the
executed constant-address sites, whose traced targets must be among the snapshot
targets or the site's pointer must vary (reported). A site's routine counts as run
when the `push bp; mov bp, sp` before it is an executed instruction start (INFERRED,
as X-Wing: a nested frame or a routine without that prologue is counted by its
enclosing one).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import wc2_model as M  # noqa: E402
from translator import image  # noqa: E402
from translator.emit import DRIVER_SEG, TAG  # noqa: E402

LOADSEG = 0x0824     # the milestones' load segment (docs/drivers.md)
DGROUP = 0x1976      # the root data's link segment (wc2_model OVRBUFFER)
MANAGER = (0xF120, 0xFA58)  # the overlay manager's code (0F12:xxxx), DS = its data 16B8h (docs/vroomm.md)
DRIVER_BASE = {"TM.DRV": 0x0C, "SUPERTM.DRV": 0x0C, "STRAX.DRV": 0x04DD}  # module offset of IP 0
OUT = M.REPO / "docs/indirect-coverage.md"
PROGRAM = M.REPO / "build/gen/program.s"


def dispatch() -> set[tuple[int, int]]:
    """(CS - LOADSEG, IP) of every dispatch row."""
    rows, text = set(), PROGRAM.read_text()
    for m in re.finditer(r"dc\.w\tLOADSEG\+(\$?[0-9a-fA-F]+),(\$?[0-9a-fA-F]+),", text):
        seg, ip = (int(v[1:], 16) if v.startswith("$") else int(v) for v in m.groups())
        rows.add((seg, ip))
    if not rows:
        raise SystemExit(f"{PROGRAM}: no dispatch rows (make gen)")
    return rows


def snapshots() -> list[tuple[str, bytes]]:
    """The milestone snapshots after start-up: m0's is the MZ entry, before the game
    initializes its data."""
    out = [(p.name, (p / "ram.bin").read_bytes())
           for p in sorted(M.RUNS.glob("ref-*-a/trace/snap-*"))
           if (p / "ram.bin").exists() and not p.name.startswith("snap-m0-")]
    if not out:
        raise SystemExit("no snapshots in tmp/pc-runs/ref-*-a (tools/reference.py)")
    return out


class Site:
    def __init__(self, r: dict):
        self.module, self.offset = r["module"], int(r["offset"], 16)
        self.insn, self.executed = r["instruction"], r["executed"] == "1"
        self.table = r["switch_targets"].split()
        self.traced = r["traced_targets"].split()
        self.far = self.insn.split()[0] in ("lcall", "ljmp")
        m = re.search(r"(?:(\w\w):)?\[\s*(0x[0-9a-f]+)\s*\]", self.insn)
        seg = m.group(1) or "ds" if m else None
        self.const = (seg, int(m.group(2), 16)) if seg in ("ds", "cs") else None

    @property
    def name(self) -> str:
        return f"{self.module}+{self.offset:05X}"


def code_segment(site: Site, segs: list[int], ovls: list) -> tuple[int, int] | None:
    """(CS - LOADSEG, the module offset of IP 0) of the site's code."""
    if site.module in DRIVER_SEG:
        return DRIVER_SEG[site.module], DRIVER_BASE[site.module]
    for o in ovls:
        if o.code <= site.offset < o.code + o.size:
            return None   # overlay code runs at its buffer segment: near pointers only by IP
    seg = max((s for s in segs if s * 16 <= site.offset), default=0)
    return seg, seg * 16


def resolve(site: Site, ram: bytes, cs: tuple[int, int] | None) -> tuple[int, int] | None:
    """(CS - LOADSEG, IP) the site's pointer holds in this snapshot."""
    seg, disp = site.const
    if seg == "ds":
        data = M.MGR_DATA >> 4 if MANAGER[0] <= site.offset < MANAGER[1] else DGROUP
        base = (LOADSEG + data) * 16 if site.module == M.ROOT else None
    elif seg == "cs" and cs is not None:
        base = (LOADSEG + cs[0]) * 16
    else:
        base = None
    if base is None:
        return None
    lin = base + disp
    ip = ram[lin] | ram[lin + 1] << 8
    if site.far:
        return (ram[lin + 2] | ram[lin + 3] << 8) - LOADSEG, ip
    return (cs[0], ip) if cs is not None else None


def describe(t: tuple[int, int], ovls: list) -> str:
    seg, ip = t
    if seg < 0:
        return f"{seg + LOADSEG:04X}:{ip:04X}"
    for name, s in DRIVER_SEG.items():
        if seg == s:
            return f"{name}+{ip + DRIVER_BASE[name]:05X}"
    lin = seg * 16 + ip
    for o in ovls:
        if o.stub <= lin < o.stub + 0x20 + 5 * len(o.entries):
            k = (lin - o.stub - 0x20) // 5
            return f"stub {o.stub >> 4:04X} entry {k}" if lin >= o.stub + 0x20 else f"stub {o.stub >> 4:04X} header"
    if lin >= IMAGE_SIZE[0]:
        return f"{seg + LOADSEG:04X}:{ip:04X} (outside the program)"
    return f"{M.ROOT}+{lin:05X}"


def routine_ran(site: Site, data: bytes, executed: dict[str, set[int]]) -> bool | None:
    starts = executed.get(site.module, set())
    k = data.rfind(b"\x55\x8b\xec", max(0, site.offset - 0x4000), site.offset)
    return None if k < 0 else k in starts


IMAGE_SIZE = [0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows = dispatch()
    snaps = snapshots()
    ovls = M.overlays()
    segs = M.root_code_segs(M.image_file())
    traces = M.runs()
    executed = M.executed(traces)
    data = {n: M.module_path(n).read_bytes() if n != M.ROOT else M.image_file() for n in TAG}
    sites = [Site(r) for r in image.rows("indirect.csv")]
    IMAGE_SIZE[0] = len(data[M.ROOT])

    def targets(s: Site) -> list[tuple[int, int] | None]:
        return [resolve(s, ram, code_segment(s, segs, ovls)) for _, ram in snaps]

    # control: executed constant-address sites, traced targets against snapshot values
    agree = vary = miss = outside = 0
    misses = []
    outside_slots = set()
    for s in sites:
        if not s.executed or s.table or not s.const or s.module != M.ROOT:
            continue
        got = {describe(t, ovls) for t in targets(s) if t}
        hits = [t for t in targets(s) if t and t in rows]
        if len(got) > 1:
            vary += 1
        elif hits:
            agree += 1
        elif got and all("outside the program" in g for g in got):
            outside += 1
            outside_slots.add((s.const, frozenset(got)))
        else:
            miss += 1
            misses.append(f"{s.name} {sorted(got)}")

    never = [s for s in sites if not s.executed]
    tables = [s for s in never if s.table]
    ptrs = [s for s in never if not s.table]
    lines = [
        "# Indirect coverage",
        "",
        "Generated by `tools/indirect_review.py` (port-plan P6.4, gate 6; X-Wing `33d685a`'s "
        "review). Inputs: `annotations/indirect.csv` (`make map`), the dispatch table "
        "(`build/gen/program.s`, `make gen`), the milestone snapshots "
        f"({', '.join(n for n, _ in snaps)}) and {len(traces)} traces.",
        "",
        f"{len(sites)} indirect sites, {len(sites) - len(never)} executed in the traces and "
        f"{len(never)} not: {len(tables)} with a proved switch table and {len(ptrs)} through a "
        "pointer. Every unexecuted site keeps its guard: a proved table's index outside it "
        "stops at a named stop, any other site dispatches through `rt_lookup`, which stops "
        "on a target with no dispatch row. No site is marked executed and none is "
        "excluded (an exclusion is an owner decision; there are none). A snapshot value is "
        "not execution evidence and not a proof against a later write (DERIVED from the "
        "snapshots).",
        "",
        f"Method control (MEASURED): of the executed constant-address root sites, {agree} hold "
        f"one pointer in every snapshot and it has a dispatch row, {vary} hold different "
        f"pointers in different snapshots, {outside} hold a saved vector outside the program "
        f"(the BIOS's; host lockstep runs these sites), {miss} hold one pointer without a row"
        + (f" ({'; '.join(misses)})" if misses else "") + ".",
        "",
        "\"Routine\" says whether the `push bp; mov bp, sp` before the site is an executed "
        "instruction start (INFERRED, as X-Wing); `—` where none precedes it.",
        "",
        "## Proved switch tables",
        "",
        "Every target of the table is translated; an index outside it stops.",
        "",
        "| Site | Instruction | Targets | Routine |",
        "|---|---|---|---|",
    ]
    yes = {True: "ran", False: "never ran", None: "—"}
    for s in tables:
        lines.append(f"| {s.name} | `{s.insn}` | {len(s.table)} | "
                     f"{yes[routine_ran(s, data[s.module], executed)]} |")
    groups: dict[str, list[str]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for s in ptrs:
        ran = yes[routine_ran(s, data[s.module], executed)]
        if not s.const:
            key = "computed"
            groups[key].append(f"| {s.name} | `{s.insn}` | — | — | {ran} |")
            counts[key] += 1
            continue
        ts = targets(s)
        vals = sorted({(describe(t, ovls) if t else "unresolved") + ("" if t in rows else " ✗")
                       for t in ts})
        ok = all(t is not None and t in rows for t in ts)
        null = all(t is not None and t[1] == 0 and t[0] in (-LOADSEG, 0) for t in ts)
        out = all(t is not None and "outside the program" in describe(t, ovls) for t in ts)
        key = "row" if ok else "null" if null else "vector" if out else "norow"
        counts[key] += 1
        groups[key].append(f"| {s.name} | `{s.insn}` | {', '.join(vals)} | "
                           f"{'yes' if ok else 'no'} | {ran} |")
    titles = {
        "row": "Constant slot, a dispatch row in every snapshot",
        "null": "Constant slot, null in every snapshot",
        "norow": "Constant slot, no dispatch row in some snapshot",
        "computed": "Computed address",
        "vector": "Constant slot, a saved vector outside the program",
    }
    notes = {
        "row": "If reached with the value the snapshots hold, the target is translated.",
        "null": "Not installed on the m0–m6 routes; reaching it as it stands is a call "
                "through 0000:0000, which `rt_lookup` stops.",
        "norow": "✗ marks a value without a dispatch row: reached with it, `rt_lookup` "
                 "stops, so these are the paths to translate when a route reaches them. "
                 "Where the routine sets DS itself (start-up, interrupt hooks) the DGROUP "
                 "slot may not be the one read (INFERRED; the control above).",
        "computed": "A register, memory-indexed or ES-relative operand; no snapshot value "
                    "is defined.",
        "vector": "A chain to the vector the game saved (the BIOS's in the reference); "
                  "the executed sites that read the same slot run in host lockstep.",
    }
    for key in ("row", "norow", "vector", "null", "computed"):
        if not groups[key]:
            continue
        lines += ["", f"## {titles[key]} ({counts[key]})", "", notes[key], "",
                  "| Site | Instruction | Snapshot targets | Row | Routine |", "|---|---|---|---|---|"]
        lines += groups[key]
    args.out.write_text("\n".join(lines) + "\n")
    print(f"{args.out}: {len(never)} unexecuted ({len(tables)} tables, "
          f"{dict(counts)}); control: {agree} agree, {vary} vary, {miss} miss")
    return 0


if __name__ == "__main__":
    sys.exit(main())
