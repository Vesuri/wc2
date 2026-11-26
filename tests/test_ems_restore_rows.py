"""annotations/ems-ds.csv restore rows (translator/emit.py ems_restore_problem):
each row passes; the check rejects, as controls found in the program itself, an
instruction that is no POP DS, a POP DS whose run reads DS before its exit, and
one whose run transfers before it (each control must exist and be rejected)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
from translator import cfg, image  # noqa: E402
from translator.emit import ems_restore_problem  # noqa: E402


def pop_ds(i) -> bool:
    return i.op == "pop" and getattr(i.operands[0], "name", None) == "ds"


def main() -> int:
    units = cfg.build()
    rows = [(r["module"], int(r["first"], 16)) for r in image.rows("ems-ds.csv") if r["kind"] == "restore"]
    problems = [f"{m}+{o:05X}: {p}" for m, o in rows if (p := ems_restore_problem(units[m], o))]
    controls = {"is no POP DS": None, "accesses DS": None, "transfers": None}
    m, o = rows[0]
    controls["is no POP DS"] = (m, o + 1, ems_restore_problem(units[m], o + 1))
    for mod, u in units.items():
        for off, i in sorted(u.insns.items()):
            if not pop_ds(i) or (mod, off) in rows:
                continue
            p = ems_restore_problem(u, off)
            for kind in ("accesses DS", "transfers"):
                if controls[kind] is None and p and p.startswith(kind):
                    controls[kind] = (mod, off, p)
    for kind, c in controls.items():
        if c is None:
            problems.append(f"control '{kind}': no such POP DS in the program")
        elif not c[2] or not c[2].startswith(kind):
            problems.append(f"control '{kind}' {c[0]}+{c[1]:05X} not rejected as such: {c[2]}")
        else:
            print(f"control {kind}: {c[0]}+{c[1]:05X} rejected ({c[2]})")
    for p in problems:
        print(p)
    print(f"ems-ds.csv restore rows: {len(rows)}, {len(problems)} problems")
    return 1 if problems or not rows else 0


if __name__ == "__main__":
    sys.exit(main())
