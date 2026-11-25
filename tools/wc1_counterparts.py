#!/usr/bin/env python3
"""PC WC1 counterparts of WC2.EXE routines named by image offset (open-work 8, 30).

  wc1_counterparts.py [--funcs tmp/compare/funcs.csv] [--exe ref/WING2/WC2.EXE] NAME...

NAME is `WC2.EXE+x` (or x, hex), the profile's naming: an image offset, the root's load
image, then the FBOV area at file offset minus the MZ header (docs/vroomm.md). Each is
placed in `make compare`'s WC2 function (tools/wc_compare.py, `R:seg:off` for the root,
`O:stub+off` for an overlay, its code bytes) and printed with that function's WC1 match:
kind (identical bytes, exact: the same normalised code, fuzzy), similarity and the WC1
function; below 0.70 (the unrelated control's band) no counterpart. Driver
files (TM.DRV, SUPERTM.DRV, STRAX.DRV) are not in the comparison: docs/drivers.md.
"""
import argparse
import bisect
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import bc_exe  # noqa: E402

BAND = 0.70     # docs/wc1-wc2-comparison.md: below it, no counterpart (the control's band)


def places(exe: Path) -> list[tuple[int, int, str]]:
    """(image offset, end, unit format) per overlay."""
    x = bc_exe.load(exe)
    out = []
    for o in x.overlays:
        base = x.fbov + 16 + o.file_off - x.header
        out.append((base, base + o.code_size, f"O:{o.stub_off // 16:04X}+{{:04X}}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="+")
    ap.add_argument("--funcs", type=Path, default=ROOT / "tmp/compare/funcs.csv")
    ap.add_argument("--exe", type=Path, default=ROOT / "ref/WING2/WC2.EXE")
    args = ap.parse_args()
    rows = list(csv.DictReader(args.funcs.open()))
    overlays = places(args.exe)
    # resident functions: R:seg:off at image offset seg*16+off
    starts = []
    for r in rows:
        kind, rest = r["b_func"].split(":", 1)
        if kind == "R":
            seg, off = rest.split(":")
            starts.append((int(seg, 16) * 16 + int(off, 16), r))
        else:
            stub, off = rest.split("+")
            base = next((b for b, _, f in overlays if f.startswith(f"O:{stub}")), None)
            if base is None:
                sys.exit(f"{r['b_func']}: no overlay with stub {stub}")
            starts.append((base + int(off, 16), r))
    starts.sort(key=lambda t: t[0])
    at = [a for a, _ in starts]
    for name in args.names:
        v = int(name.split("+")[-1], 16)
        i = bisect.bisect_right(at, v) - 1
        if i < 0 or v >= at[i] + int(starts[i][1]["b_size"]):
            print(f"{name}: in no compared function (data in code, or outside the split)")
            continue
        a, r = starts[i]
        where = f" at +{v - a:X}" if v != a else ""
        if not r["a_func"] or float(r["ratio"] or 0) < BAND:
            best = f", best {r['ratio']} {r['a_func']}" if r["a_func"] else ""
            print(f"{name}: {r['b_func']}{where} ({r['b_size']} B, {r['b_insns']} insns): "
                  f"no WC1 counterpart{best}")
        else:
            print(f"{name}: {r['b_func']}{where} ({r['b_size']} B, {r['b_insns']} insns): {r['kind']} "
                  f"{r['ratio']} WC1 {r['a_func']} ({r['a_size']} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
