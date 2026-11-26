"""Port calls by port and generated caller in a milestone's meter window (speed-plan §1, P7.6).

  port_calls.py MILESTONE OUT.txt

The host lockstep check of the milestone (tools/cost_meter.py windowed), with hooks at
rt_port_in and rt_port_out (the C path: port, width and the generated return address
on the stack below rt_in8/rt_out8's saves) and at rt_in8 and rt_out8 (every call, the
asm fast paths included), counted inside the meter's window."""
import sys, struct, bisect
from collections import Counter
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tests"), str(REPO / "tools"), str(REPO)]
import cost_meter
from host_run import U

ms, out = sys.argv[1], Path(sys.argv[2])
st = {"open": False, "frames": 0}
cnt, fast = Counter(), Counter()
keep = []

def attach(h):
    names = sorted((a, n) for n, a in h.syms.items())
    at = [a for a, _ in names]
    def sym(a):
        i = bisect.bisect_right(at, a) - 1
        return names[i][1] if i >= 0 else "?"
    def pin(e, a, s, u):
        if st["open"]:
            sp = h.r("a7")
            port, width = struct.unpack(">II", h.mem(sp + 4, 8))
            cnt[("in", port & 0xffff, width, sym(h.u32(sp + 24)))] += 1
    def pout(e, a, s, u):
        if st["open"]:
            sp = h.r("a7")
            port, value, width = struct.unpack(">III", h.mem(sp + 4, 12))
            cnt[("out", port & 0xffff, width, sym(h.u32(sp + 28)))] += 1
    def o8(e, a, s, u):
        if st["open"]:
            fast[("out8", h.r("d7") & 0xffff)] += 1
    def i8(e, a, s, u):
        if st["open"]:
            fast[("in8", h.r("d7") & 0xffff)] += 1
    def frame(e, a, s, u):
        if st["open"]:
            st["frames"] += 1
    for name, f in (("rt_port_in", pin), ("rt_port_out", pout), ("rt_out8", o8), ("rt_in8", i8), ("R_0813C", frame)):
        cb = U.CODE_CB(f)
        keep.append(cb)
        h.e.hook_range(U.HOOK_CODE, cb, h.syms[name], h.syms[name])

def gate(inside):
    st["open"] = inside

h, _, problems, secs = cost_meter.windowed(ms, 7200, attach, gate)
with out.open("w") as f:
    print(ms, "frames", st["frames"], "C calls", sum(cnt.values()), "problems", problems[:3], "s", secs, file=f)
    byport = Counter()
    for (d, p, w, c), v in cnt.items():
        byport[(d, p, w)] += v
    print("by port:", file=f)
    for k, v in byport.most_common():
        print(f"  {v:9d} {k[0]} {k[1]:04x} w{k[2]}", file=f)
    print("rt_out8/rt_in8 entries by port (fast paths included):", file=f)
    for k, v in fast.most_common():
        print(f"  {v:9d} {k[0]} {k[1]:04x}", file=f)
    print("by caller (top 40):", file=f)
    for k, v in cnt.most_common(40):
        print(f"  {v:9d} {k[0]} {k[1]:04x} w{k[2]} {k[3]}", file=f)
print(out.read_text()[:4000])
sys.exit(1 if problems else 0)
