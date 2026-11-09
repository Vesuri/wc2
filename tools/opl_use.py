#!/usr/bin/env python3
"""OPL channel use from a trace's opl.csv (tools/pc_run.py --opl; port-plan P1.5, D6).

Counts the melodic channels whose key-on bit (B0h-B8h bit 5) is set, at most at once
and ever, and lists the values written to BDh (bit 5: rhythm mode). A key-on bit
that stays set after a note's release counts as in use, so the maximum is an upper bound.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("opl", type=Path, help="tmp/pc-runs/<run>/trace/opl.csv")
    args = ap.parse_args()
    on = [False] * 9
    keyed, bd = set(), set()
    most = writes = 0
    last = 0.0
    with args.opl.open() as f:
        for r in csv.DictReader(f):
            reg, value = int(r["reg"], 16), int(r["value"], 16)
            writes += 1
            last = float(r["ms"])
            if 0xB0 <= reg <= 0xB8:
                on[reg - 0xB0] = bool(value & 0x20)
                if value & 0x20:
                    keyed.add(reg - 0xB0)
            elif reg == 0xBD:
                bd.add(value)
            most = max(most, sum(on))
    if not writes:
        print("no OPL writes")
        return 1
    print(f"writes {writes} over {last / 1000:.0f} s; channels keyed {sorted(keyed)}; "
          f"at most {most} at once; BDh values {' '.join(f'{v:02X}h' for v in sorted(bd)) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
