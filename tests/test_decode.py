#!/usr/bin/env python3
"""Decoder cross-check against Capstone (plan step 3.2).

1. Every instruction the translator decodes (translator/cfg.py from
   annotations/, over image.X86_SCOPE) matches Capstone in length, mnemonic and operands.
2. The decoded starts are the sweep's (tools/sweep.py, tmp/sweep/<module>.cls, from
   `make map`), outside the self-modified regions: no start more, none fewer.
3. Every traced executed instruction start is a decoded start; inside
   annotations/self-modifying.csv the executed starts are decoded from the
   run-time bytes of a snapshot instead (the static bytes are rewritten), and in a VROOMM
   stub's cells (docs/vroomm.md) both of the cell's forms are decoded: `INT 3Fh` and,
   for an entry, `JMP FAR` to the overlay's entry.
4. Opcode space: every first byte with random ModRM/tail bytes either raises
   DecodeError (outside the supported 8086 set) or matches Capstone.
Exit 1 on any mismatch; prints counts (zero comparisons fail).
"""

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import capstone
from capstone import x86

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from translator import cfg, image  # noqa: E402
from translator.decode import CC, DecodeError, Far, Imm, Insn, Mem, Reg, Rel, decode  # noqa: E402

CS_NAME = {"cdq": "cwd", "cwde": "cbw", "lcall": "callf", "ljmp": "jmpf", "xlatb": "xlat",
           "iret": "iret", "salc": None}
# 186+/286 opcodes outside the forms of translator/decode.py (pusha/popa, bound, ins/outs,
# 0Fh), FPU escapes, WAIT, LOCK, INT1, SALC: not in the swept code.
UNSUPPORTED = {0x0F, *range(0x60, 0x68), 0x6C, 0x6D, 0x6E, 0x6F, 0x9B, 0xD6, *range(0xD8, 0xE0),
               0xF0, 0xF1}
STRING = {"movs", "cmps", "stos", "lods", "scas"}
MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_16)
MD.detail = True


def capstone_form(i):
    mn = i.mnemonic.removeprefix("notrack ")  # Capstone's CET name for a 3Eh prefix
    rep = None
    for p in ("rep ", "repe ", "repne "):
        if mn.startswith(p):
            rep, mn = p.strip(), mn[len(p):]
    mn = CS_NAME.get(mn, mn)
    if mn and mn[:-1] in STRING and mn[-1] in "bw":
        mn = mn[:-1]
    if mn and mn.startswith("j") and mn[1:] in CC:
        mn = "jcc:" + mn[1:]
    ops = []
    for o in i.operands:
        if o.type == x86.X86_OP_REG:
            ops.append(("reg", i.reg_name(o.reg)))
        elif o.type == x86.X86_OP_IMM:
            ops.append(("imm", o.imm & 0xFFFF))
        elif o.type == x86.X86_OP_MEM:
            m = o.mem
            ops.append(("mem", o.size, i.reg_name(m.segment) if m.segment else None,
                        i.reg_name(m.base) if m.base else None,
                        i.reg_name(m.index) if m.index else None, m.disp & 0xFFFF))
    return i.size, mn, rep, ops


def own_form(n: Insn):
    mn = f"jcc:{n.cc}" if n.op == "jcc" else n.op
    ops = []
    if n.op in STRING:
        return n.size, mn, n.rep, None, n.seg
    for o in n.operands:
        if isinstance(o, Reg):
            ops.append(("reg", o.name))
        elif isinstance(o, Imm):
            ops.append(("imm", o.value & 0xFFFF))
        elif isinstance(o, Rel):
            ops.append(("imm", o.target))
        elif isinstance(o, Far):
            ops += [("imm", o.seg), ("imm", o.off)]
        elif isinstance(o, Mem):
            ops.append(("mem", o.width // 8, o.seg if o.override else None, o.base, o.index,
                        o.disp))
    return n.size, mn, n.rep, ops, None


def compare(code: bytes, ip: int, n: Insn) -> str | None:
    c = next(MD.disasm(code[:16], ip), None)
    if c is None:
        return "capstone cannot decode"
    size, mn, rep, ops = capstone_form(c)
    osize, omn, orep, oops, oseg = own_form(n)
    if (size, mn) != (osize, omn):
        return f"capstone {c.mnemonic} {c.op_str} ({size}) vs {n} ({osize})"
    if omn in STRING:
        if (rep or None) != orep and not (omn in ("movs", "stos", "lods") and rep and orep):
            return f"rep {rep} vs {orep}"
        segs = [o[2] for o in ops if o[0] == "mem" and o[3] == "si"]
        if segs and segs[0] != oseg and not (segs[0] == "ds" and oseg is None):
            return f"string segment {segs[0]} vs {oseg}"
        return None
    if mn in ("in", "out", "int"):  # capstone keeps imm port/vector as 8-bit
        ops = [(t[0], t[1] & 0xFF) if t[0] == "imm" else t for t in ops]
    if mn == "enter":  # capstone sign-extends the level byte
        ops = [ops[0], (ops[1][0], ops[1][1] & 0xFF)]
    if mn in ("les", "lds"):  # capstone sizes the m16:16 operand as the register
        ops = [t[:1] + (4,) + t[2:] if t[0] == "mem" else t for t in ops]
    # Capstone names a default segment only when the prefix is present.
    if ops != oops:
        return f"capstone {c.mnemonic} {c.op_str} {ops} vs {n} {oops}"
    return None


def main() -> int:
    mods = image.load()
    code = cfg.build(mods, image.X86_SCOPE)
    bad, counts, seen = [], Counter(), Counter()
    for name, unit in code.items():
        data = mods[name].data
        for off, n in unit.insns.items():
            why = compare(data[off:off + 16], n.ip, n)
            counts["static"] += 1
            seen[n.op] += 1
            if why:
                bad.append(f"{name}+{off:05X}: {why}")
    # The sweep's starts (Capstone's descent, gate 2) against the translator's.
    smc = image.smc_regions()
    for name, unit in code.items():
        path = image.REPO / "tmp/sweep" / f"{name}.cls"
        if not path.exists():
            bad.append(f"{name}: no {path.relative_to(image.REPO)}: run make map")
            continue
        sweep = {o for o, c in enumerate(path.read_bytes()) if c in (1, 3)
                 and not any(lo <= o <= hi for lo, hi in smc.get(name, ()))}
        for o in sorted(sweep - set(unit.insns))[:10]:
            bad.append(f"{name}+{o:05X}: a sweep start the translator does not decode")
        for o in sorted(set(unit.insns) - sweep)[:10]:
            bad.append(f"{name}+{o:05X}: a decoded start the sweep does not reach")
        counts["sweep starts"] += len(sweep & set(unit.insns))
    # Executed starts: decoded statically, or (self-modified region) from a
    # snapshot: the first holding the region, else one of a run that executed
    # the start (snapshots are taken at run end; the cell layout differs per run).
    traces = image.M.runs()
    executed = image.M.executed(traces)
    runtime = image.runtime_bytes(traces, image.X86_SCOPE)
    cells = {}  # stub cell -> its forms (the overlay's buffer segment stands in as 1234h)
    for o in image.M.overlays():
        cells[o.stub] = [bytes.fromhex("cd3f")]
        for k, e in enumerate(o.entries):
            cells[o.stub + 0x20 + 5 * k] = [bytes.fromhex("cd3f") + e.to_bytes(2, "little") + b"\0",
                                            b"\xea" + e.to_bytes(2, "little") + b"\x34\x12"]
    own = {t: (image.runtime_bytes([t], image.X86_SCOPE), image.M.executed([t])) for t in traces}
    for name, starts in executed.items():
        if name not in code:
            continue
        for off in sorted(starts):
            if any(lo <= off <= hi for lo, hi in smc.get(name, ())):
                if name not in runtime:
                    bad.append(f"{name}: no snapshot holds the self-modified region")
                    break
                held = [runtime[name]] + [rt[name] for rt, ex in own.values()
                                          if name in rt and off in ex.get(name, ())]
                problems = []
                for rt in held:
                    try:
                        n = decode(rt, code[name].ip_of(off), off)
                    except DecodeError as e:
                        problems.append(str(e))
                        continue
                    why = compare(rt[off:off + 16], n.ip, n)
                    if not why:
                        break
                    problems.append(why)
                else:
                    bad.append(f"{name}+{off:05X} (run time): {problems[0]}")
                    continue
                counts["self-modified executed"] += 1
            elif off in code[name].insns:
                counts["executed"] += 1
            elif name == image.M.ROOT and off in cells:
                for raw in cells[off]:
                    why = compare(raw, 0, decode(raw, 0))
                    if why:
                        bad.append(f"{name}+{off:05X} (stub cell {raw.hex()}): {why}")
                counts["stub cells executed"] += 1
            else:
                bad.append(f"{name}+{off:05X}: executed start not decoded")
    # Opcode space.
    rng = random.Random(3)
    for first in range(256):
        for _ in range(64):
            tail = bytes(rng.randrange(256) for _ in range(7))
            raw = bytes([first]) + tail
            try:
                n = decode(raw, 0x1000)
            except DecodeError as e:
                counts["space rejected"] += 1
                op = str(e).removeprefix("opcode ")
                if op != str(e) and int(op, 16) not in UNSUPPORTED:
                    bad.append(f"opcode {raw.hex()}: rejected but in the 8086 set")
                continue
            why = compare(raw, 0x1000, n)
            counts["space"] += 1
            if why:
                bad.append(f"opcode {raw.hex()}: {why}")
    for k, v in counts.items():
        print(f"{k:24} {v}")
    print("forms:", " ".join(f"{k}={v}" for k, v in sorted(seen.items())))
    for b in bad[:30]:
        print(b)
    if bad:
        print(f"{len(bad)} mismatches")
    need = ("static", "sweep starts", "executed", "self-modified executed", "space")
    return 1 if bad or not all(counts[k] for k in need) else 0


if __name__ == "__main__":
    sys.exit(main())
