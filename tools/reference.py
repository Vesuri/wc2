#!/usr/bin/env python3
"""Run every milestone in reference/milestones.csv twice and check its signal (gate 1).
`--table reference/coverage.csv` runs other scripts the same way; names select rows.

Each milestone is two independent tools/pc_run.py runs from a fresh root (ref-<name>-a,
ref-<name>-b), in parallel (--jobs). Snapshots (space-separated triggers, taken in
order after the key script) are named <name>-0, -1, ...; a run ends at the last.
Checks per milestone: both runs reach every snapshot; at the last, the listed modules
are resident and the BIOS video mode is the listed one; the listed files were opened
(`opened`: DOS opens that succeeded before the last snapshot) and the listed hardware
interrupt vectors were taken (`irqs`, hex: e.g. 0f, the Sound Blaster's IRQ 7 at the end
of a DMA block); consecutive snapshots
differ in RAM and VRAM (the scene advances); every snapshot of both runs passes the
image proof (tools/load_image.py); and every snapshot's RAM, VRAM and DAC are
byte-identical between the two runs. The hashes are also compared with the previous
invocation (tmp/reference-hashes.csv). The instruction count is reported only:
DOSBox-X interleaves host ticks with execution, so the instruction at which an
interrupt lands varies while guest state at the milestone does not.

The translator's poll points (build/gen/poll-points.csv) gate hardware interrupts
in the trace patch; they are passed only once `make gen` emits some (port-plan P2),
since an empty list would hold every interrupt. Adapted from Secret Weapons of
Luftwaffe (docs/upstream.md).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fixture_inputs

REPO = Path(__file__).resolve().parent.parent
HASHES = REPO / "tmp/reference-hashes.csv"
POLLS = REPO / "build/gen/poll-points.csv"  # make gen
PARTS = ("ram.bin", "vram.bin", "dac.bin")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def resident(snapshot: Path) -> set[str]:
    with (snapshot / "residency.csv").open() as f:
        return {r["module"] for r in csv.DictReader(f)}


def opened(trace: Path, until: int) -> set[str]:
    names = set()
    with (trace / "events.csv").open() as f:
        for line in f:
            p = line.rstrip("\n").split(",", 4)
            if len(p) == 5 and p[1] == "open" and int(p[0]) <= until and " ok=1 " in p[4]:
                names.add(p[4].split()[0])
    return names


def taken(trace: Path) -> set[int]:
    """Hardware interrupt vectors taken in the run (it ends at the last snapshot)."""
    with (trace / "interrupts.csv").open() as f:
        return {int(r["vector"], 16) for r in csv.DictReader(f) if r["type"] == "0"}


def polls() -> list[str]:
    if not POLLS.exists():
        return []
    with POLLS.open() as f:
        return ["--polls", str(POLLS)] if len(f.read().splitlines()) > 1 else []


def command(m: dict, run: str) -> list[str]:
    name = m["name"]
    triggers = m["snapshots"].split()
    names = [f"{name}-{i}" for i in range(len(triggers))]
    cmd = [sys.executable, str(REPO / "tools/pc_run.py"), run,
           "--time-limit", m["time_limit"],
           "--snapshots", ",".join(f"{n}@{t}" for n, t in zip(names, triggers)),
           "--exit-after", names[-1], "--keys", m["keys"].replace(";", ","), "--services"]
    cmd += polls()
    for path in fixture_inputs.missing_files(m.get("missing_files") or ""):
        cmd += ["--missing-file", path]
    if m.get("joystick") == "1":
        cmd += ["--joystick"]
    if m.get("rep_chunks") == "1":
        cmd += ["--rep-chunks"]
    if m.get("launch"):
        cmd += ["--launch", m["launch"]]
    if m.get("key_hold"):
        hold = int(m["key_hold"])
        if hold < 1:
            raise ValueError("key_hold must be a positive instruction count")
        cmd += ["--key-hold", str(hold)]
    return cmd


def check_run(m: dict, run: str) -> tuple[list[str], list[dict]]:
    """Problems of one run, and per snapshot: name, icount, hashes."""
    status = subprocess.run(command(m, run), stdout=subprocess.DEVNULL).returncode
    if status != 0:
        return [f"{run}: run status {status}"], []
    trace = REPO / f"tmp/pc-runs/{run}/trace"
    names = [f"{m['name']}-{i}" for i in range(len(m["snapshots"].split()))]
    snaps = [trace / f"snap-{n}" for n in names]
    problems = []
    last = snaps[-1]
    missing = set(m["resident"].split()) - resident(last)
    if missing:
        problems.append(f"{run}: not resident: {' '.join(sorted(missing))}")
    regs = dict(kv.split("=") for kv in (last / "regs.txt").read_text().split())
    if m["vga_mode"] and int(regs["vga_mode"], 16) != int(m["vga_mode"], 16):
        problems.append(f"{run}: vga mode {regs['vga_mode']}")
    unopened = set((m.get("opened") or "").split()) - opened(trace, int(regs["icount"]))
    if unopened:
        problems.append(f"{run}: not opened: {' '.join(sorted(unopened))}")
    absent = {int(v, 16) for v in (m.get("irqs") or "").split()} - taken(trace)
    if absent:
        problems.append(f"{run}: interrupts not taken: {' '.join(f'{v:02x}' for v in sorted(absent))}")
    for a, b in zip(snaps, snaps[1:]):
        for part in ("ram.bin", "vram.bin"):
            if digest(a / part) == digest(b / part):
                problems.append(f"{run}: {b.name} {part} did not advance")
    rows = []
    for s in snaps:
        if subprocess.run([sys.executable, str(REPO / "tools/load_image.py"), str(s)],
                          stdout=subprocess.DEVNULL).returncode:
            problems.append(f"{run}: {s.name} image proof")
        r = dict(kv.split("=") for kv in (s / "regs.txt").read_text().split())
        rows.append({"name": s.name[len("snap-"):], "icount": r["icount"],
                     **{p.split(".")[0]: digest(s / p) for p in PARTS}})
    return problems, rows


def milestone(m: dict) -> tuple[list[str], list[dict]]:
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.map(lambda run: check_run(m, run), (f"ref-{m['name']}-a", f"ref-{m['name']}-b"))
    problems = a[0] + b[0]
    if a[1] and b[1]:
        for x, y in zip(a[1], b[1]):
            for k in ("ram", "vram", "dac"):
                if x[k] != y[k]:
                    problems.append(f"{x['name']} {k} differs between runs")
    return problems, a[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="reference/milestones.csv")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2),
                    help="milestones in parallel (each runs two emulators)")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args()
    table = [m for m in csv.DictReader((REPO / args.table).open())
             if not args.names or m["name"] in args.names]
    previous = {}
    if HASHES.exists():
        previous = {r["name"]: r for r in csv.DictReader(HASHES.open())}
    failed = False
    results = []
    with ThreadPoolExecutor(max(1, args.jobs)) as pool:
        for m, (problems, rows) in zip(table, pool.map(milestone, table)):
            for row in rows:
                old = previous.get(row["name"])
                if old and any(old[k] != row[k] for k in ("ram", "vram", "dac")):
                    problems.append(f"{row['name']} differs from the previous invocation")
            failed |= bool(problems) or not rows
            results += rows
            last = rows[-1] if rows else {"icount": "", "ram": "", "vram": ""}
            print(f"{m['name']:18} {'FAIL ' + '; '.join(problems) if problems else 'ok'}  "
                  f"snapshots={len(rows)} icount={last['icount']} ram={last['ram']} vram={last['vram']}",
                  flush=True)
    merged = {**previous, **{r["name"]: r for r in results}}
    with HASHES.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "icount", "ram", "vram", "dac"])
        w.writeheader()
        w.writerows(merged.values())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
