#!/usr/bin/env python3
"""Check the VROOMM overlay manager model (docs/vroomm.md) against traced runs (port-plan P2.1).

The model is the manager's own algorithm, read from WC2.EXE+F120..FA5A, run on the
trace's INT 3Fh traps in order:
- start-up: the overlays in segment-record order are laid out in the buffer by their file
  offsets while they fit, and read in one pass;
- a trap on a stub whose overlay is still in the buffer (its entries were reset to INT 3Fh)
  gives it probation 1 and re-patches its entries; otherwise the queue is made room for
  from its head (probation 0: evicted; else probation - 1 and moved to the allocation
  point, then queued again), wrapping by moving every resident overlay to the top of the
  buffer when the space to the end is short; the overlay is read at the allocation point,
  queued at the tail and its entries patched to far jumps;
- then the oldest overlays (probation 0) have their entries reset to INT 3Fh until the
  free space and theirs reach a quarter of the buffer.

Checks per trace (vroomm.csv from the trace patch):
- the start-up read and every trap's reads are the predicted file ranges at the
  predicted buffer addresses, and every buffer move is the predicted one;
- each trap ends in the overlay at the predicted address: the entry's code offset, or
  for a return trap the saved return offset (stub word 2);
- after each trap, every stub's state (buffer segment, flags, probation, queue link,
  entry form and far-jump segment) as rebuilt from the traced stub writes equals the
  model's;
- at each snapshot taken outside a trap, the manager's allocation point and queue head
  and every stub in the snapshot RAM equal the model's, the eviction hook is the RET and
  every stub's loader is the file reader (no EMS cache).
Exit 1 on any violation, if a trace that started the manager has no trap, or if no trace
started it (m0 ends at the MZ entry, before the manager). `--sabotage RULE` also runs a broken
model (second-chance: probation ignored; wrap: no compaction, the head is evicted instead;
sweep: no probation sweep; position: loads one paragraph higher) on every trace where the
honest model applied that rule, and exits 1 unless there is one and each such trace then
fails: the control that the checks see each rule.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import wc2_model as M

SABOTAGE = ("second-chance", "wrap", "sweep", "position")
SAVE_HOOK = 0x0938      # manager data word 10h: the eviction hook, a RET at WC2.EXE+FA58
FILE_LOADER = 0x04B8    # stub word 18h: the loader, WC2.EXE+F5D8 (reads the file)


class Stub:
    def __init__(self, o: M.Overlay, load: int):
        self.o = o
        self.seg = load + o.stub // 16     # runtime stub segment
        self.buf = 0                        # buffer segment of the code, 0 when not in memory
        self.flags = 0                      # bit 2: called while trapped in the buffer
        self.prob = 0                       # probation
        self.trapped = True                 # entries are INT 3Fh (else far jumps)
        self.link = 0                       # word 1Ch: the next in the queue (kept when evicted)


class Manager:
    """WC2's VROOMM manager (docs/vroomm.md); paragraph arithmetic is 16-bit."""

    def __init__(self, ovls: list[M.Overlay], load: int, image: bytes, sabotage: str = ""):
        self.load, self.sabotage = load, sabotage
        self.stubs = {o.stub: Stub(o, load) for o in ovls}
        self.order = [self.stubs[o.stub] for o in sorted(ovls, key=lambda o: o.stub)]
        size = struct.unpack_from("<H", image, M.OVRBUFFER)[0]
        aa = max(o.need for o in ovls) + 2
        self.size = size if aa < size else 2 * aa        # WC2.EXE+FA16
        self.queue: list[Stub] = []
        self.b4 = self.b6 = self.b0 = self.quarter = 0
        self.actions: list[tuple] = []
        self.used = dict.fromkeys(SABOTAGE, 0)  # how often each sabotaged rule decided

    # --- the routines, by their WC2.EXE offsets ---
    def start(self, b4: int) -> None:
        """F42D: lay out the overlays from the first in record order while they fit."""
        self.b4, self.b6 = b4, b4 + self.size
        self.quarter = (self.b6 - self.b4) >> 2
        si, placed = self.b4, []
        for cur, nxt in zip(self.order, self.order[1:]):
            end = si + (nxt.o.code - cur.o.code) // 16
            if end > self.b6:
                break
            cur.buf = si
            placed.append(cur)
            si = end
        self.b0 = si
        if placed:
            self.actions.append(("read", self.b4 * 16, placed[0].o.code, (si - self.b4) * 16))
        for s, nxt in zip(placed, placed[1:] + [None]):
            s.trapped = False
            s.link = nxt.seg if nxt else 0
            self.queue.append(s)

    def free(self) -> tuple[int, bool]:
        """F897: paragraphs from the allocation point to the queue head, or to the end."""
        if self.queue and self.queue[0].buf >= self.b0:
            return self.queue[0].buf - self.b0, False
        return (self.b6 - self.b0) & 0xFFFF, True

    def move(self, s: Stub) -> None:
        """F7F6: move the code to the allocation point."""
        words = (s.o.size + 1) >> 1
        self.actions.append(("move", self.b0 * 16, s.buf * 16, 2 * words))
        s.buf = self.b0

    def queue_tail(self, s: Stub) -> None:
        """F847."""
        self.b0 = (self.b0 + s.o.paras) & 0xFFFF
        if self.queue:
            self.queue[-1].link = s.seg
        s.link = 0
        self.queue.append(s)

    def trap_entries(self, s: Stub) -> None:
        """F7C3: entries back to INT 3Fh (and the frames that return into it to the stub)."""
        s.trapped = True

    def wrap(self) -> None:
        """F749: every resident overlay to the top of the buffer, in queue order."""
        self.used["wrap"] += 1
        order, self.queue = self.queue, []
        self.b0 = self.b6
        for s in reversed(order):
            s.link = self.queue[0].seg if self.queue else 0
            self.queue.insert(0, s)
            self.b0 = (self.b0 - s.o.paras) & 0xFFFF
            self.move(s)
        self.b0 = self.b4

    def make_room(self, need: int) -> None:
        """F66C."""
        while True:
            free, to_end = self.free()
            if need <= free:
                return
            if to_end:
                if self.sabotage == "wrap":
                    self.b0 = self.b4
                else:
                    self.wrap()
            head = self.queue.pop(0)
            if head.prob == 0 or self.sabotage == "second-chance":
                self.trap_entries(head)
                head.buf = 0
            else:
                self.used["second-chance"] += 1
                head.prob -= 1
                self.move(head)
                self.queue_tail(head)

    def trap(self, s: Stub) -> None:
        """F6B6, from the INT 3Fh handler at F606."""
        if s.buf:
            s.prob = 1
            s.flags |= 4
        else:
            self.used["position"] += 1
            self.make_room(s.o.need)
            s.buf = self.b0 + (1 if self.sabotage == "position" else 0)
            self.actions.append(("read", s.buf * 16, s.o.code, s.o.size + 2 * len(s.o.relocs)))
            self.queue_tail(s)
        s.trapped = False
        if self.sabotage == "sweep":
            return
        free, _ = self.free()
        for cur in self.queue[:-1]:
            if free >= self.quarter:
                break
            if cur.prob == 0:
                self.used["sweep"] += 1
                self.trap_entries(cur)
                free = (free + cur.o.paras) & 0xFFFF
            # a stub on probation adds nothing and is passed over

    # --- comparison ---
    def stub_state(self, s: Stub) -> tuple:
        return (s.buf, s.flags, s.prob, s.link, 0xCD if s.trapped else 0xEA,
                None if s.trapped else s.buf)


def traced_state(raw: bytearray, n: int) -> tuple:
    """The same fields from a stub's bytes (header + n entries)."""
    buf, = struct.unpack_from("<H", raw, 0x10)
    nxt, = struct.unpack_from("<H", raw, 0x1C)
    form = raw[0x20]
    jseg = struct.unpack_from("<H", raw, 0x23)[0] if form == 0xEA else None
    return (buf, raw[0x1A] & 0xF7, raw[0x1B], nxt, form, jseg)


def merged(rows: list[tuple]) -> list[tuple]:
    """Contiguous reads joined (the manager reads in chunks of up to FFF0h bytes)."""
    out: list[tuple] = []
    for r in rows:
        if r[0] == "read" and out and out[-1][0] == "read" and \
                out[-1][1] + out[-1][3] == r[1] and out[-1][2] + out[-1][3] == r[2]:
            out[-1] = ("read", out[-1][1], out[-1][2], out[-1][3] + r[3])
        else:
            out.append(r)
    return out


def rows(trace: Path):
    with (trace / "vroomm.csv").open() as f:
        next(f)
        for line in f:
            icount, kind, stub, entry, linear, detail = line.rstrip("\n").split(",", 5)
            yield int(icount), kind, int(stub, 16), int(entry, 16), int(linear, 16), \
                dict(x.split("=", 1) for x in detail.split() if "=" in x), detail


def snapshots(trace: Path) -> list[tuple[int, Path]]:
    out = []
    for snap in trace.glob("snap-*"):
        regs = (snap / "regs.txt").read_text().split()
        icount = int(next(x for x in regs if x.startswith("icount=")).split("=")[1])
        out.append((icount, snap))
    return sorted(out)


def check(trace: Path, ovls: list[M.Overlay], image: bytes, sabotage: str = "") -> tuple[list[str], dict]:
    load = None
    with (trace / "events.csv").open() as f:
        for line in f:
            if ",arm," in line:
                load = int(line.split("load_seg=")[1].split()[0], 16)
                break
    if load is None:
        return [f"{trace.parent.name}: no arm event"], {}
    m = Manager(ovls, load, image, sabotage)
    raw = {o.stub: bytearray(image[o.stub:o.stub + 32 + 5 * len(o.entries)]) for o in ovls}
    bad: list[str] = []
    stats = {"traps": 0, "return_traps": 0, "reads": 0, "moves": 0, "snapshots": 0}
    snaps = snapshots(trace)
    first = min(ovls, key=lambda o: o.stub)
    started = False
    in_trap = None          # (stub, entry, icount)
    got: list[tuple] = []
    run = trace.parent.name

    def where(icount):
        return f"{run}@{icount}"

    def compare_actions(icount, what):
        want, have = merged(m.actions), merged(got)
        if want != have:
            bad.append(f"{where(icount)} {what}: want {fmt(want)} got {fmt(have)}")
        m.actions.clear()
        got.clear()

    def compare_stubs(icount, what):
        for o in ovls:
            s = m.stubs[o.stub]
            if m.stub_state(s) != traced_state(raw[o.stub], len(o.entries)):
                bad.append(f"{where(icount)} {what}: stub {o.stub:05x} model {m.stub_state(s)} "
                           f"traced {traced_state(raw[o.stub], len(o.entries))}")
                return

    def compare_snapshot(icount, snap):
        ram = (snap / "ram.bin").read_bytes()
        ds = (load + M.MGR_DATA // 16) * 16
        b0, = struct.unpack_from("<H", ram, ds + 0xB0)
        head, = struct.unpack_from("<H", ram, ds + 0xBC)
        want_head = m.queue[0].seg if m.queue else 0
        save_hook, = struct.unpack_from("<H", ram, ds + 0x10)
        loaders = {struct.unpack_from("<H", ram, load * 16 + o.stub + 0x18)[0] for o in ovls}
        if save_hook != SAVE_HOOK or loaders != {FILE_LOADER}:
            bad.append(f"{where(icount)} snapshot {snap.name}: save hook {save_hook:04x}, loaders "
                       f"{sorted(loaders)}: not the file loader alone (EMS cache?)")
        if (b0, head) != (m.b0, want_head):
            bad.append(f"{where(icount)} snapshot {snap.name}: b0/head {b0:04x}/{head:04x}, "
                       f"model {m.b0:04x}/{want_head:04x}")
        for o in ovls:
            a = (load * 16) + o.stub
            r = bytearray(ram[a:a + 32 + 5 * len(o.entries)])
            if m.stub_state(m.stubs[o.stub]) != traced_state(r, len(o.entries)):
                bad.append(f"{where(icount)} snapshot {snap.name}: stub {o.stub:05x} RAM "
                           f"{traced_state(r, len(o.entries))} model {m.stub_state(m.stubs[o.stub])}")
                return
        stats["snapshots"] += 1

    for icount, kind, stub, entry, linear, kv, detail in rows(trace):
        while snaps and snaps[0][0] < icount:
            ic, snap = snaps.pop(0)
            if started and in_trap is None:
                compare_snapshot(ic, snap)
        if kind == "stub_write":
            w = int(detail.split()[0][1:])
            v = int(kv["v"], 16)
            if stub in raw and entry + w <= len(raw[stub]):
                raw[stub][entry:entry + w] = v.to_bytes(w, "little")
        elif kind == "read":
            img = int(kv["image"], 16)
            if not started:
                if img == first.code:
                    m.start(linear // 16)
                    started = True
                    got.append(("read", linear, img, int(kv["got"])))
                continue
            got.append(("read", linear, img, int(kv["got"])))
            stats["reads"] += 1
        elif kind == "move":
            got.append(("move", linear, int(kv["from"], 16), int(kv["bytes"])))
            stats["moves"] += 1
        elif kind in ("trap", "trap_unknown"):
            if not started:
                bad.append(f"{where(icount)} trap before the start-up read")
                break
            if in_trap is None and got:
                compare_actions(icount, "start-up")
                compare_stubs(icount, "start-up")
            if kind == "trap_unknown" or stub not in m.stubs:
                bad.append(f"{where(icount)} INT 3Fh outside a stub: {detail}")
                continue
            if in_trap is not None:
                bad.append(f"{where(icount)} trap inside the trap at {in_trap[2]}")
            s = m.stubs[stub]
            in_trap = (s, entry, icount)
            stats["traps"] += 1
            stats["return_traps"] += entry == 2
            m.trap(s)
        elif kind == "enter":
            if in_trap is None:
                continue
            s, ent, ic = in_trap
            in_trap = None
            compare_actions(ic, f"trap {s.o.stub:05x}+{ent:02x}")
            if ent == 2:
                off, = struct.unpack_from("<H", raw[s.o.stub], 2)
            else:
                k = (ent - 0x22) // 5
                off = s.o.entries[k] if (ent - 0x22) % 5 == 0 and k < len(s.o.entries) else -1
            want = s.buf * 16 + off
            if linear != want:
                bad.append(f"{where(ic)} trap {s.o.stub:05x}+{ent:02x} entered {linear:05x}, "
                           f"model {want:05x} ({detail})")
            compare_stubs(ic, f"after trap {s.o.stub:05x}+{ent:02x}")
        if len(bad) > 20:
            break
    for ic, snap in snaps:
        if started and in_trap is None:
            compare_snapshot(ic, snap)
    if not started:
        stats["before_start"] = 1         # m0: the snapshot is the MZ entry
    elif not stats["traps"]:
        bad.append(f"{run}: no trap traced")
    stats.update({f"rule {k}": v for k, v in m.used.items()})
    return bad, stats


def fmt(acts: list[tuple]) -> str:
    return " ".join(f"{a[0]}({a[1]:05x},{a[2]:05x},{a[3]})" for a in acts[:6]) + \
        (f" +{len(acts) - 6}" if len(acts) > 6 else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="ref-*", help="tmp/pc-runs glob (default: the milestones)")
    ap.add_argument("--sabotage", choices=SABOTAGE, help="run a broken model; every trace must fail")
    args = ap.parse_args()
    traces = M.runs(args.runs)
    if not traces:
        print(f"no traces match {args.runs}")
        return 1
    ovls = M.overlays()
    image = M.image_file()
    total = {}
    failed = exercised = missed = 0
    for t in traces:
        bad, stats = check(t, ovls, image)
        for k, v in stats.items():
            total[k] = total.get(k, 0) + v
        if bad:
            failed += 1
            print("\n".join(bad[:10]))
        if args.sabotage and stats.get(f"rule {args.sabotage}"):
            exercised += 1
            if not check(t, ovls, image, args.sabotage)[0]:
                missed += 1
                print(f"{t.parent.name}: sabotage {args.sabotage} not caught")
    print(f"traces {len(traces)}, " + ", ".join(f"{k} {v}" for k, v in total.items()) +
          f", failing {failed}")
    if args.sabotage:
        ok = not failed and exercised and not missed and len(traces) > total.get("before_start", 0)
        print(f"sabotage {args.sabotage}: caught in {exercised - missed} of the {exercised} traces "
              f"where the rule decides; {'ok' if ok else 'NOT OK'}")
        return 0 if ok else 1
    checked = len(traces) - total.get("before_start", 0)
    print("0 violations" if not failed and checked else "VIOLATIONS")
    return 1 if failed or not checked else 0


if __name__ == "__main__":
    sys.exit(main())
