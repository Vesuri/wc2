#!/usr/bin/env python3
"""Classify every CPU write into code-segment bytes (port-plan P2.4).

Adapted from Secret Weapons of Luftwaffe's tools/code_writes.py by way of X-Wing's
(docs/upstream.md), for WC2's VROOMM manager (docs/vroomm.md).
Writes come from the trace corpus: the tracer's code-writes.csv (every write into a
paragraph that has executed, with writer and linear address) and each snapshot's
writes.csv (last writer per byte since its load). Byte classes from tools/sweep.py
(tmp/sweep/*.cls).

The manager's writes are checked by linear address, since the buffer's contents move:
  move        WC2.EXE+F81F, the buffer compaction (rep movsw): into the buffer
  relocation  WC2.EXE+F567 (segment words) and +F5D0 (far pointers to stub entries):
              into the buffer
  header      WC2.EXE+F4CE, +F6DE, +F826: the stub back pointer in the paragraph before
              an overlay's code: into the buffer
  stub        WC2.EXE+F7B9..F7F2 (entry forms), +F840 (far-jump segments after a move):
              into a stub's entries, the two-form cells (sweep class 6)
  dos         a DOSBox callback (F000h): the DOS reads of overlay code into the buffer
Every other writer's bytes are mapped to the module offset they held when written (the
tracer's target_module/target_offset) and classified by the sweep:
  data        a byte that is not a decoded instruction (code-segment variables)
  self-modified  a byte of annotations/self-modifying.csv
A write by any other writer into a decoded instruction or a stub cell fails; so does a
manager write outside its region.
Output: tmp/sweep/code-writes.csv (module or region, class, writer, first, last, bytes)
and a summary. Exit 1 on any failure or if no trace has a manager write.
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from collections import defaultdict
from pathlib import Path

import wc2_model as M

MANAGER = {0xF81F: "move", 0xF567: "relocation", 0xF5D0: "relocation",
           0xF4CE: "header", 0xF6DE: "header", 0xF826: "header",
           0xF7B9: "stub", 0xF7BC: "stub", 0xF7BF: "stub", 0xF7EC: "stub", 0xF7EF: "stub",
           0xF7F2: "stub", 0xF840: "stub"}
STUBS = (0x173D0, 0x19760)  # image range of the stub segments (link 173Dh..1975h)
CODE = (1, 2, 3, 4)
STUB_CELL = 6


def smc_regions() -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = defaultdict(list)
    with (M.REPO / "annotations/self-modifying.csv").open() as f:
        for r in csv.DictReader(f):
            out[r["module"]].append((int(r["first"], 16), int(r["last"], 16)))
    return out


def buffer_range(trace: Path, image: bytes) -> tuple[int, int, int] | None:
    """(load segment, buffer start, end) linear: the start-up read of the first overlay
    (docs/vroomm.md) and the buffer size."""
    load = None
    with (trace / "events.csv").open() as f:
        for line in f:
            if ",arm," in line:
                load = int(line.split("load_seg=")[1].split()[0], 16)
                break
    first = min(M.overlays(), key=lambda o: o.stub)
    with (trace / "vroomm.csv").open() as f:
        for line in f:
            p = line.split(",")
            if len(p) > 5 and p[1] == "read" and f"image=0x{first.code:05x}" in p[5]:
                b4 = int(p[4], 16) // 16
                size = struct.unpack_from("<H", image, M.OVRBUFFER)[0]
                return load, (b4 - 1) * 16, (b4 + size) * 16
    return (load, 0, 0) if load is not None else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="ref-*", help="tmp/pc-runs glob for the trace corpus")
    args = ap.parse_args()
    traces = M.runs(args.runs)
    image = M.image_file()
    cls = {f.name[:-4]: f.read_bytes() for f in (M.REPO / "tmp/sweep").glob("*.cls")}
    if not cls:
        print("no tmp/sweep/*.cls: run tools/sweep.py first")
        return 1
    smc = smc_regions()
    bad: list[str] = []
    by_class: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    manager_writes = 0
    for t in traces:
        rng = buffer_range(t, image)
        if rng is None:
            bad.append(f"{t.parent.name}: no arm event")
            continue
        load, blo, bhi = rng
        slo, shi = load * 16 + STUBS[0], load * 16 + STUBS[1]
        residency = M.residency(t / "residency.csv")
        with (t / "code-writes.csv").open() as f:
            for r in csv.DictReader(f):
                a, width = int(r["target_linear"], 16), int(r["width"])
                wm, wo = r["writer_module"], int(r["writer_offset"], 16)
                writer = f"{wm}+{wo:05X}"
                for b in range(a, a + width):
                    in_buf = blo <= b < bhi
                    if wm == M.ROOT and wo in MANAGER:
                        kind = MANAGER[wo]
                        manager_writes += 1
                        ok = (slo <= b < shi) if kind == "stub" else in_buf
                        if kind == "stub" and ok:
                            off = b - load * 16
                            ok = cls[M.ROOT][off] == STUB_CELL
                        if not ok:
                            bad.append(f"{t.parent.name}: {writer} ({kind}) at {b:05x} outside its region")
                        by_class[("(linear)", kind, writer)].add(b)
                        continue
                    if wm == "-" and wo >= 0xF0000:
                        if not in_buf:
                            hit = M.locate(residency, b)
                            mod, off = hit if hit else ("(linear)", b)
                            k = cls.get(mod, b"")[off] if off < len(cls.get(mod, b"")) else 0
                            if k in CODE or k == STUB_CELL:
                                bad.append(f"{t.parent.name}: DOS write into code {mod}+{off:05X}")
                        by_class[("(linear)", "dos", "DOS")].add(b)
                        continue
                    if r.get("target_module") not in (None, "", "-"):
                        mod = r["target_module"]
                        off = int(r["target_offset"], 16) + b - a
                    elif in_buf:
                        bad.append(f"{t.parent.name}: {writer} writes the overlay buffer at {b:05x} "
                                   "with no module there")
                        continue
                    else:
                        hit = M.locate(residency, b)
                        if hit is None:
                            continue
                        mod, off = hit
                    c = cls.get(mod)
                    k = c[off] if c is not None and off < len(c) else 0
                    if any(lo <= off <= hi for lo, hi in smc.get(mod, ())):
                        kind = "self-modified"
                    elif k in CODE or k == STUB_CELL:
                        kind = "code"
                        bad.append(f"{t.parent.name}: {writer} writes {'a stub cell' if k == STUB_CELL else 'code'} "
                                   f"{mod}+{off:05X} outside annotations/self-modifying.csv")
                    else:
                        kind = "data"
                    by_class[(mod, kind, writer)].add(off)
    rows = []
    for (mod, kind, w), offs in sorted(by_class.items()):
        offs_l = sorted(offs)
        start = prev = offs_l[0]
        for o in offs_l[1:] + [None]:
            if o is not None and o == prev + 1:
                prev = o
                continue
            rows.append([mod, kind, w, f"0x{start:05x}", f"0x{prev:05x}", prev - start + 1])
            if o is not None:
                start = prev = o
    with (M.REPO / "tmp/sweep/code-writes.csv").open("w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["module", "class", "writer", "first", "last", "bytes"])
        cw.writerows(rows)
    total: dict[tuple[str, str], int] = defaultdict(int)
    writers: dict[tuple[str, str], set[str]] = defaultdict(set)
    for mod, kind, w, _, _, n in rows:
        total[(mod, kind)] += n
        writers[(mod, kind)].add(w)
    for (mod, kind), n in sorted(total.items()):
        ws = sorted(writers[(mod, kind)])
        shown = " ".join(ws[:5]) + (f" (+{len(ws) - 5})" if len(ws) > 5 else "")
        print(f"{mod:12} {kind:13} {n:7}  {shown}")
    if not manager_writes:
        bad.append("no manager write in any trace")
    for b in sorted(set(bad))[:20]:
        print(b)
    print(f"traces {len(traces)}: {'0 failures' if not bad else f'{len(set(bad))} FAILURES'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
