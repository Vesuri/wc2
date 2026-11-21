#!/usr/bin/env python3
"""Flight frame time from a probe log (port-plan P1.5, docs/pc-reference-loop.md).

Run the game into flight with these probes, e.g.
  tools/pc_run.py RUN --probes WC2.EXE+7400:8=rect,WC2.EXE+10636:1=wait,WC2.EXE+10640:1=woke ...
then `tools/frame_time.py tmp/pc-runs/RUN/trace/probe.csv`.
- WC2.EXE+7400 hands a rectangle to the video driver; in flight the first call of
  each frame copies (A8h,A8h)-(A8h,ADh) (MEASURED: one per frame).
- WC2.EXE+10636..10640 is the frame limiter's wait: it spins until the timer
  handler (WC2.EXE+0FD10) has counted [D134h] up to the target that
  WC2.EXE+10642 set; flight frames last 4 ticks of 60 Hz (DERIVED from the
  interval, the same at 12000 and 24000 cycles).
Prints the frame interval and the time spent in the wait (median, 10th and 90th
percentile of emulated ms) and their difference, the frame's work. Interrupt
handlers that run during the wait count as idle.

--group NAME --at-least N: the frames by how many entries of probe NAME they hold
(N or more in one row), each with its interval and its own work (interval less
its waits). An interval over 1 s is the autopilot's skip, not a frame, and is
left out. For combat, SUPERTM.DRV+153E (entry 2: as many calls as entry 1 at +15F5,
MEASURED in the Nav 1 fight; one per scaled object drawn, INFERRED) counts them:
  tools/pc_run.py combat --launch "WC2 Origin -k" --key-hold 120000 \
    --keys "<m5's keys through the first autopilot>,WC2.EXE+fd10#600=backspace" \
    --probes ...,SUPERTM.DRV+153E:1=obj ...
  tools/frame_time.py tmp/pc-runs/combat/trace/probe.csv --group obj --at-least 8
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

FRAME_ARGS = "b3c6 00a8 00a8 00a8 00ad"  # driver table, x0, y0, x1, y1


def frames(probe: Path, name: str = "rect") -> list[float]:
    with probe.open() as f:
        return [float(r["ms"]) for r in csv.DictReader(f)
                if r["name"] == name and r["args"].startswith(FRAME_ARGS)]


def waits(probe: Path, after: float) -> list[float]:
    out, start = [], None
    with probe.open() as f:
        for r in csv.DictReader(f):
            t = float(r["ms"])
            if t < after:
                continue
            if r["name"] == "wait":
                start = t
            elif r["name"] == "woke" and start is not None:
                out.append(t - start)
                start = None
    return out


def stats(v: list[float]) -> tuple[float, float, float]:
    v = sorted(v)
    return statistics.median(v), v[len(v) // 10], v[9 * len(v) // 10]


def grouped(probe: Path, t: list[float], name: str, cap: int) -> int:
    with probe.open() as f:
        ev = sorted((float(r["ms"]), r["name"]) for r in csv.DictReader(f)
                    if r["name"] in ("wait", "woke", name))
    rows: dict[int, list[tuple[float, float]]] = {}
    j = 0
    for a, b in zip(t, t[1:]):
        if b - a > 1000:
            continue
        while j < len(ev) and ev[j][0] < a:
            j += 1
        k, idle, start, n = j, 0.0, None, 0
        while k < len(ev) and ev[k][0] < b:
            ms, what = ev[k]
            if what == "wait":
                start = ms
            elif what == "woke" and start is not None:
                idle, start = idle + ms - start, None
            elif what == name:
                n += 1
            k += 1
        rows.setdefault(min(n, cap), []).append((b - a, b - a - idle))
    if not rows:
        print(f"no frames with {name}")
        return 1
    for n in sorted(rows):
        r = rows[n]
        iv, wk = stats([x[0] for x in r]), stats([x[1] for x in r])
        print(f"{name} {n}{'+' if n == cap else ''}: {len(r)} frames, interval median {iv[0]:.1f} "
              f"(p90 {iv[2]:.1f}), work median {wk[0]:.1f} (p90 {wk[2]:.1f}, max {max(x[1] for x in r):.1f}) ms")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("probe", type=Path)
    ap.add_argument("--group", help="probe name counted per frame")
    ap.add_argument("--at-least", type=int, default=8, help="the top row: this many or more")
    args = ap.parse_args()
    t = frames(args.probe)
    if args.group and len(t) >= 11:
        return grouped(args.probe, t, args.group, args.at_least)
    if len(t) < 11:
        print(f"{len(t)} frames: too few to measure")
        return 1
    frame = stats([b - a for a, b in zip(t, t[1:])])
    print(f"frames {len(t)} over {(t[-1] - t[0]) / 1000:.1f} s: interval median {frame[0]:.1f} ms "
          f"(p10 {frame[1]:.1f}, p90 {frame[2]:.1f})")
    w = waits(args.probe, t[0])
    if len(w) < 11:
        print(f"{len(w)} limiter waits: no wait probe")
        return 0
    idle = stats(w)
    print(f"limiter waits {len(w)}: median {idle[0]:.1f} ms (p10 {idle[1]:.1f}, p90 {idle[2]:.1f}); "
          f"work per frame {frame[0] - idle[0]:.1f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
