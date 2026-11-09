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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("probe", type=Path)
    args = ap.parse_args()
    t = frames(args.probe)
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
