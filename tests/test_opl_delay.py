"""STRAX.DRV's OPL write delay (annotations/hle.csv opl_delay, D18): the
original x86 is the oracle.

The loop (STRAX.DRV+0714..0746, 0000:0237) latches PIT channel 0, reads the
count twice and sums the elapsed counts until CX. rt_hle_opl_delay, with
rt_opl_delay_skip, leaves the state of one iteration that saw CX counts, rounded
up to even (mode 3 steps by two), pass. Per CX: the original bytes run under
Unicorn x86 to the resume (+0744, before its pops) with the PIT reads of such
an iteration (the first count that number plus 2 above the second, 2, whose
high byte is AL), against the service on the run's own host image (DX, SI, AX,
CX; BX and SI are popped at the resume, the flags are dead there: the
generated resume reads none). Without rt_opl_delay_skip, and above CX 4DACh
(one iteration cannot pass it), the service answers EQ with every register
kept. Plants (--sabotage): each must fail."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
import uc as U  # noqa: E402
import host_run as H  # noqa: E402
from translator import image  # noqa: E402

MODULE, FIRST, RESUME, END = "STRAX.DRV", 0x714, 0x744, 0x747
IP0 = 0x0237                    # FIRST in the module's CS
CS, SS, SP, RET = 0x2000, 0x3000, 0xFFF0, 0x0100
CXS = (0x0A, 0x37, 0, 1, 2, 0x4DAC, 0x4DAD, 0xFFFF)
ONE = 0x4DAC                    # the largest CX one iteration passes (divisor 4DAEh)
# rt_entry.s rt_hle_opl_delay's instructions a plant removes (big-endian words)
PLANTS = {"rounding": bytes.fromhex("0242fffe"),   # andi.w #$fffe,d2
          "al": bytes.fromhex("4200"),             # clr.b d0
          "bound": None}                           # bhi.s .eq (found by its opcode)


def original(cx: int, ax: int, dx: int, bx: int, si: int) -> dict:
    """The original loop under Unicorn x86 to the resume."""
    code = image.load()[MODULE].data[FIRST:END]
    d = (cx + 1) & ~1
    counts = [d + 2, 2]                 # the latches: first, then each iteration's
    latched, reads = [], []
    e = U.Engine(U.ARCH_X86, U.MODE_16)
    e.map(0, 0x110000)
    e.write(CS * 16 + IP0, code)
    e.write(SS * 16 + SP, RET.to_bytes(2, "little"))   # the near call's return

    @U.OUT_CB
    def out(h, port, size, value, user):
        if port == 0x43 and value & 0xFF == 0x06:       # channel 0 latch
            v = counts[min(len(latched), len(counts) - 1)]
            latched.append(v)
            reads.extend((v & 0xFF, v >> 8))

    @U.IN_CB
    def inp(h, port, size, user):
        assert port == 0x40 and reads, f"in {port:x} without a latch"
        return reads.pop(0)

    e.hook(U.HOOK_INSN, out, U.X86_INS_OUT)
    e.hook(U.HOOK_INSN, inp, U.X86_INS_IN)
    for r, v in (("ax", ax), ("cx", cx), ("dx", dx), ("bx", bx), ("si", si), ("sp", SP), ("cs", CS),
                 ("ss", SS), ("ds", 0x4000)):
        e.reg_write(U.X86[r], v)
    stop = CS * 16 + IP0 + RESUME - FIRST
    err = e.start(CS * 16 + IP0, stop, count=10_000)
    ip = e.reg_read(U.X86["ip"])
    assert not err and ip == IP0 + RESUME - FIRST, f"x86 stopped at {ip:04x} (err {err})"
    return {r: e.reg_read(U.X86[r]) & 0xFFFF for r in ("ax", "cx", "dx", "si")} | {"latches": len(latched)}


def native(h, cx: int, ax: int, dx: int, bx: int, si: int, skip: int) -> tuple[bool, dict]:
    """rt_hle_opl_delay on the run's image: (NE, the guest registers after it)."""
    # jsr rt_hle_opl_delay; sne d7 (the hook's bne: the SR Unicorn reports holds
    # no current CCR), then the stop address
    t = H.STACK_TOP - 0x100
    h.e.write(t, bytes.fromhex("4eb9") + h.syms["rt_hle_opl_delay"].to_bytes(4, "big") + bytes.fromhex("56c7"))
    ret = t + 8
    h.e.write(h.syms["rt_opl_delay_skip"], bytes([skip]))
    h.e.reg_write(U.M68K["sr"], 0x2700)
    h.e.reg_write(U.M68K["a7"], H.STACK_TOP - 8)
    h.e.reg_write(U.M68K["a6"], H.TOP)
    h.e.reg_write(U.M68K["d7"], 0)
    for r, v in (("d0", 0xABCD0000 | ax), ("d1", 0x12340000 | cx), ("d2", 0x56780000 | dx),
                 ("d3", 0x9ABC0000 | bx), ("a4", si)):
        h.e.reg_write(U.M68K[r], v)
    h.e.start(t, ret, timeout_us=1_000_000)
    assert h.r("pc") == ret, f"rt_hle_opl_delay did not return (pc={h.r('pc'):x})"
    ne = h.r("d7") & 0xFF == 0xFF
    return ne, {"ax": h.r("d0") & 0xFFFF, "cx": h.r("d1") & 0xFFFF, "dx": h.r("d2") & 0xFFFF,
                "bx": h.r("d3") & 0xFFFF, "si": h.r("a4") & 0xFFFF}


def plant(h, name: str) -> None:
    a, n = h.syms["rt_hle_opl_delay"], 0x40
    code = h.e.read(a, n)
    if name == "bound":
        k = next(k for k in range(0, n, 2) if code[k] == 0x62)      # bhi.s
        h.e.write(a + k, bytes.fromhex("4e71"))
        return
    k = code.find(PLANTS[name])
    assert k >= 0 and k % 2 == 0, name
    h.e.write(a + k, bytes.fromhex("4e71") * (len(PLANTS[name]) // 2))


def problems(sabotage: str | None = None) -> list[str]:
    h = H.Host(image.M.REF)
    if sabotage:
        plant(h, sabotage)
    out = []
    ax, dx, bx, si = 0x7F55, 0x1234, 0x0BAD, 0x0F0F
    for cx in CXS:
        regs = dict(ax=ax, dx=dx, bx=bx, si=si)
        ne, got = native(h, cx, **regs, skip=0)
        if ne or got != dict(regs, cx=cx):
            out.append(f"cx={cx:04x} without rt_opl_delay_skip: NE {ne}, {got}")
        ne, got = native(h, cx, **regs, skip=1)
        if cx > ONE:
            if ne or got != dict(regs, cx=cx):
                out.append(f"cx={cx:04x}: NE {ne} (want EQ, registers kept), {got}")
            continue
        want = original(cx, **regs)
        if want["latches"] != 2:
            out.append(f"cx={cx:04x}: the original took {want['latches'] - 1} iterations, not one")
        if not ne:
            out.append(f"cx={cx:04x}: EQ, want NE")
        for r in ("ax", "cx", "dx", "si"):
            if got[r] != want[r]:
                out.append(f"cx={cx:04x}: {r} {got[r]:04x}, the original {want[r]:04x}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sabotage", action="store_true", help="each plant must fail the check")
    args = ap.parse_args()
    found = problems()
    for p in found:
        print(p)
    print(f"opl_delay: {len(CXS)} counts, {len(found)} problems")
    if found:
        return 1
    if args.sabotage:
        missed = [name for name in PLANTS if not problems(name)]
        for name in PLANTS:
            print(f"plant {name}: {'MISSED' if name in missed else 'caught'}")
        return 1 if missed else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
