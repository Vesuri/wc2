#!/usr/bin/env python3
"""The Amiga image's code by source (docs/feasibility.md "Code size").

Reads the linked ELF's symbol table (objdump -t) and gives each .text byte to the
symbol at or below it: the translator's labels name their module (R_ WC2.EXE,
STM_ SUPERTM.DRV, TM_ TM.DRV, SX_ STRAX.DRV, each followed by a hex address or
by rm and a number); every other symbol is the runtime and platform layer. Usage: tools/code_size.py amiga/out/Wc2.elf
"""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULES = (("R_", "WC2.EXE"), ("STM_", "SUPERTM.DRV"), ("TM_", "TM.DRV"), ("SX_", "STRAX.DRV"))
SYMBOL = re.compile(r"^([0-9a-f]{8}) .{7} \.text\t[0-9a-f]{8} (\S+)$")
SECTION = re.compile(r"^\s*\d+ \.text\s+([0-9a-f]+)\s+([0-9a-f]+)")


def source(name: str) -> str:
    for prefix, module in MODULES:
        if re.match(prefix + r"(rm)?[0-9A-Fa-f]", name):
            return module
    return "runtime and platform"


def objdump(elf: Path, flag: str) -> str:
    cmd = f'. "{REPO}/amiga/env.sh" >/dev/null 2>&1; m68k-amiga-elf-objdump {flag} "{elf}"'
    return subprocess.run(["bash", "-c", cmd], check=True, capture_output=True, text=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("elf", type=Path)
    args = ap.parse_args()
    end = None
    for line in objdump(args.elf, "-h").splitlines():
        m = SECTION.match(line)
        if m:
            end = int(m.group(1), 16) + int(m.group(2), 16)
    syms = sorted((int(m.group(1), 16), m.group(2)) for m in
                  (SYMBOL.match(l) for l in objdump(args.elf, "-t").splitlines()) if m)
    if end is None or not syms:
        print("no .text section or symbols")
        return 1
    size = collections.Counter()
    for (addr, name), nxt in zip(syms, [a for a, _ in syms[1:]] + [end]):
        size[source(name)] += nxt - addr
    size["runtime and platform"] += syms[0][0]
    print(f".text {end:,} bytes")
    for k, v in size.most_common():
        print(f"  {k:<22} {v:>10,}  {100 * v / end:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
