"""IRQ footprint monitor (docs/irq-plan.md I3) for tests/host_run.py. Copied from
Secret Weapons of the Luftwaffe and adapted to WC2's handlers (translator/irq.py
HANDLERS: INT 08h at WC2.EXE+0FD10 and +148E0, INT 0Fh at +06F3F, INT 15h at +0FD93).

Checks every guest memory access of a host run against I2's footprint
(build/gen/irq-footprint.csv):
- inside a delivered handler (deliver_guest from rt_irq_async or
  rt_irq_interrupt to its back label), which starts on the private stack
  (runtime.h RT_IRQ_SS:RT_IRQ_SP below its frame), every access, generated or
  runtime, lies in the footprint for its kind: a fixed class (four hex digits: a
  load-relative link paragraph, the drivers' at emit.DRIVER_SEG; `abs:XXXX` an
  absolute paragraph), a runtime class (`[C:a-b]`: segments the words at C:a..b
  hold, as the handler entered or as it stored them since), or the handler's
  stack from the frame down by the proved depth (K);
- the irq-bounds.csv variables hold their bounds at every handler entry and
  return (the proof assumed them: I3 checks);
- in main code, an access that meets a fixed class of the footprint (a read of a
  handler-written byte, a write of a handler-accessed byte) comes from a sync
  instruction whose row covers the address, runs with guest IF clear, or from a
  runtime service (recorded: the services that must mask the tick, I6); any
  other generated or runtime access fails;
- runtime-class buffers in conventional memory (music, effects, speech data the
  handler reads through a pointer): a generated main write of a byte between the
  handler's first and last read of that byte fails (buffer_races); a write after
  the last read (a reload of bytes already played) is no race. The EMS page frame
  is left out of that rule: its bytes change page with every map (INT 67h, a
  service), so a linear byte is no buffer identity; frame reads are counted. The
  frame bytes ems.c's `copy` moves inside a handler (a page shown at its first
  access or segment load, a write-back at a page map: the frame keeps showing
  its mapped page's bytes) are the EMS model's, counted, not footprint accesses.
The Sound Blaster's IRQ 7 (INT 0Fh, ports.c's DSP blocks) is delivered at a poll
point from rt_irq on the interrupted stack, as the reference takes it; so is the
keyboard intercept (INT 15h AH=4Fh, from the BIOS INT 09h model: rt_key_hook to
rt_key_hook_back). Their handler runs are checked as IRQ0's, the stack window
from their frame. The record counts deliveries per handler entry.
Records the sync sites hit, IF-clear accesses, services and buffers in
tmp/test/irq-monitor-<run>.json.
"""
from __future__ import annotations

import bisect
import csv
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FOOTPRINT = REPO / "build/gen/irq-footprint.csv"
EMS_FRAME = (0xE0000, 0xF0000)     # src/runtime/ems.c EMS_FRAME
WRITTEN, ACCESSED, READ_OK, WRITE_OK, POINTER, BOUNDED, BUFFER = 1, 2, 4, 8, 16, 32, 64
LIMIT = 20
# Runtime code that runs as an interrupt handler, not main code: the BIOS tick
# (IRQ0 while IVT 08h is the BIOS's, and the end of the handler's chain) and the
# BIOS INT 09h's key (input.c rt_keyboard_irq, bios_key, add_key: after the INT
# 15h intercept); a compiler clone (add_key.part.0) counts as its function
INTERRUPT_SIDE = {"bios_tick", "rt_keyboard_irq", "bios_key", "add_key"}
PRIVATE_STACK = (0xB000, 0x8000 - 6)   # runtime.h RT_IRQ_SS:RT_IRQ_SP, frame pushed
DROP = "mem,1976,0xd130,w"    # WC2.EXE+0FD70..+0FD7C: the tick counts, every INT 08h run
RUNTIME = re.compile(r"\[([0-9A-F]{4}|abs:[0-9A-F]{4}):([0-9A-F]{4})-([0-9A-F]{4})\]")


def buffer_races(reads: dict[int, list], writes) -> list[str]:
    """Generated main writes of a buffer byte between the handler's first and last
    read of that byte. reads: linear -> [first tick, last tick, class]; writes:
    (linear, size, who, generated, tick). A write after a byte's last read (a
    reload of bytes already played) is no race."""
    out = []
    for lin, size, who, generated, tick in writes:
        for a in range(lin, lin + size):
            r = reads.get(a)
            if generated and r and r[0] <= tick <= r[1]:
                out.append(f"irq monitor: main write of {a:05X} into {r[2]}'s buffer "
                           f"at {who} (tick {tick}, byte read in ticks {r[0]}-{r[1]})")
                break
    return out


def stack_depth(footprint: Path = FOOTPRINT) -> int:
    """The handlers' proved stack depth below the frame (the footprint's stack row)."""
    for r in csv.DictReader(footprint.open()):
        if r["kind"] == "stack":
            return -int(r["first"], 16)
    raise ValueError(f"{footprint}: no stack row")


def bound_rows():
    """irq-bounds.csv rows but extents: (class, first, last, width, lo, hi)."""
    from translator import irq
    return [(cls, first, last, w, lo, hi) for (cls, first, w), (lo, hi, last) in irq.bounds().items()]


class Monitor:
    def __init__(self, host, size: int, footprint: Path = FOOTPRINT, sabotage: str | None = None):
        """sabotage (host_run SABOTAGE, the monitor must then fail): irq-footprint
        leaves out the handler's tick-count write row (DROP), irq-sync every sync
        row, irq-bounds narrows each bound by one at its top."""
        from translator import emit
        self.h = host
        self.size = size
        self.mem, self.runtime_rows, self.sync = [], [], defaultdict(list)
        self.depth = None
        self.dropped = None
        for r in csv.DictReader(footprint.open()):
            if r["kind"] == "mem":
                row = (r["class"], int(r["first"], 16), int(r["last"], 16), r["access"])
                if sabotage == "irq-footprint" and DROP == f"mem,{r['class']},{r['first']},{r['access']}":
                    self.dropped = row
                    continue
                if RUNTIME.fullmatch(r["class"]):
                    self.runtime_rows.append(row)
                else:
                    self.mem.append(row)
            elif r["kind"] == "stack":
                self.depth = -int(r["first"], 16)
            elif r["kind"] == "sync" and r["class"] != "port" and sabotage != "irq-sync":
                mod, off = r["where"].split("+")
                self.sync[(mod, int(off, 16))].append(
                    (r["class"], int(r["first"], 16), int(r["last"], 16)))
        if self.depth is None:
            raise ValueError(f"{footprint}: no stack row")
        if sabotage == "irq-footprint" and self.dropped is None:
            raise ValueError(f"{footprint}: no row {DROP} to drop")
        self.bounds = [(c, f, last, w, lo, hi - (sabotage == "irq-bounds" and hi > lo))
                       for c, f, last, w, lo, hi in bound_rows()]
        tags = {t: m for m, t in emit.TAG.items()}
        pat = re.compile(r"^(%s)_([0-9A-F]{5})(_bp)?$" % "|".join(tags))
        labels = sorted((a, (tags[m.group(1)], int(m.group(2), 16)))
                        for n, a in host.syms.items() if (m := pat.match(n)))
        self.label_at = [a for a, _ in labels]
        self.label_node = [n for _, n in labels]
        named = sorted((a, n) for n, a in host.syms.items())
        self.sym_at = [a for a, _ in named]
        self.sym_name = [n for _, n in named]
        self.backs = {host.syms[n] for n in ("rt_irq_async_back", "rt_irq_interrupt_back")
                      if n in host.syms}   # the second: I6 builds
        self.poll_back = host.syms["rt_irq_back"]   # rt_irq's other guest handlers
        self.hook_back = host.syms["rt_key_hook_back"]  # the keyboard intercept
        self.loadseg = None
        self.mask = None
        self.intervals = {"r": ([], []), "w": ([], [])}   # runtime classes: starts, (end, class)
        self.entry_segs: dict = {}
        self.in_handler = False
        self.k = (0, -1)
        self.tick = 0
        self.entries = Counter()
        self.found = Counter()
        self.masked = Counter()
        self.services = Counter()
        self.runtime_reads = Counter()
        self.frame_reads = 0
        self.frame_service = 0     # frame bytes ems.c's copy moved inside a handler
        self.buffer_reads: dict[int, list] = {}  # linear -> [first tick, last tick, class]
        self.buffer_span = (1, 0)
        self.buffer_writes: list[tuple[int, int, str, bool, int]] = []
        self.checked_bounds = 0
        self.pending_place = False
        self.seg_cache: dict = {}
        self.place_key = None
        self.problems: list[str] = []
        self.failed: set[str] = set()

    # -- layout --------------------------------------------------------------
    def para(self, cls: str):
        if re.fullmatch(r"[0-9A-F]{4}", cls):
            return int(cls, 16) + self.loadseg
        if cls.startswith("abs:"):
            return int(cls[4:], 16)
        return None

    def word(self, lin: int) -> int:
        return int.from_bytes(self.h.gmem(lin, 2), "little")

    def layout(self):
        """The fixed classes' mask, the runtime classes' pointer words and the
        bounded variables (static: every fixed class is at a fixed paragraph)."""
        self.loadseg = self.h.u32(self.h.syms["load_segment"]) & 0xFFFF
        mask = bytearray(self.size)
        for cls, lo, hi, access in self.mem:
            p = self.para(cls)
            bits = (WRITTEN | ACCESSED | WRITE_OK) if access == "w" else (ACCESSED | READ_OK)
            for a in range(p * 16 + lo, min(p * 16 + hi + 1, len(mask))):
                mask[a] |= bits
        self.pointer_words = []
        for cls, *_ in self.runtime_rows:
            c, a, b = RUNTIME.fullmatch(cls).groups()
            lin = self.para(c) * 16 + int(a, 16)
            end = self.para(c) * 16 + int(b, 16)
            self.pointer_words.append((cls, lin, end))
            for x in range(lin, end + 1):
                mask[x] |= POINTER
        self.bounded = []
        for cls, first, last, w, lo, hi in self.bounds:
            p = self.para(cls)
            if p is None:
                continue
            a, b = p * 16 + first, p * 16 + last + w // 8 - 1
            self.bounded.append((cls, first, w, lo, hi, p * 16, a, b))
            for x in range(a, b + 1):
                mask[x] |= BOUNDED
        self.mask = mask
        if hasattr(self.h, "watch_mask"):
            self.h.watch_mask(mask)     # memwatch.c

    def segments(self) -> dict[str, set[int]]:
        """Runtime class -> the segment values its words hold now."""
        out = {}
        for cls, lin, end in self.pointer_words:
            raw = self.h.gmem(lin, end - lin + 1)
            got = self.seg_cache.get(cls)
            if got is None or got[0] != raw:    # the words rarely change: one set per value
                got = self.seg_cache[cls] = (raw, {int.from_bytes(raw[k:k + 2], "little")
                                                   for k in range(len(raw) - 1)})
            out[cls] = got[1]
        return out

    def place(self):
        """The runtime classes' intervals from the entry's and the current words."""
        now = self.segments()
        key = tuple(id(v) for v in self.entry_segs.values()) + tuple(id(v) for v in now.values())
        if key == self.place_key:       # the same sets (segments' cache): the same intervals
            return
        self.place_key = key
        spans = {"r": [], "w": []}
        for cls, lo, hi, access in self.runtime_rows:
            for v in self.entry_segs.get(cls, set()) | now.get(cls, set()):
                spans[access].append((v * 16 + lo, v * 16 + hi, cls))
        for access in ("r", "w"):
            got = sorted(spans[access])
            merged = []
            for a, b, cls in got:
                if merged and a <= merged[-1][1] + 1:
                    if b > merged[-1][1]:
                        merged[-1] = (merged[-1][0], b, merged[-1][2])
                else:
                    merged.append((a, b, cls))
            self.intervals[access] = ([a for a, _, _ in merged], [(b, c) for _, b, c in merged])

    def runtime_class(self, a: int, access: str):
        starts, ends = self.intervals[access]
        k = bisect.bisect_right(starts, a) - 1
        return ends[k][1] if k >= 0 and a <= ends[k][0] else None

    def check_bounds(self, when: str):
        for cls, first, w, lo, hi, base, a, b in self.bounded:
            raw = self.h.gmem(a, b - a + 1)
            for k in range(0, len(raw), w // 8):
                v = int.from_bytes(raw[k:k + w // 8], "little")
                self.checked_bounds += 1
                if not lo <= v <= hi:
                    self.fail(f"irq-bounds.csv {cls}:{a - base + k:04X} holds {v:#x} at handler "
                              f"{when}, outside {lo:#x}..{hi:#x} (tick {self.tick})")

    # -- sites -----------------------------------------------------------------
    def node(self, pc: int):
        k = bisect.bisect_right(self.label_at, pc) - 1
        return self.label_node[k] if k >= 0 else None

    def symbol(self, pc: int) -> str:
        k = bisect.bisect_right(self.sym_at, pc) - 1
        return self.sym_name[k] if k >= 0 else f"{pc:x}"

    @staticmethod
    def site(n) -> str:
        return f"{n[0]}+{n[1]:05X}"

    def where(self) -> str:
        pc = self.h.r("pc")
        return self.site(self.node(pc)) if self.h.code[0] <= pc < self.h.code[1] else self.symbol(pc)

    def fail(self, text: str):
        """Each distinct problem once (a site in a loop repeats it; a main access per
        site and class, its first address shown), LIMIT of them."""
        text = f"irq monitor: {text}"
        key = re.sub(r" \(tick \d+[^)]*\)", "", text)
        key = re.sub(r"of [0-9A-F]{5} \(([^:)]*)(:[0-9A-F]{4})?\)", r"(\1)", key)
        if key not in self.failed and len(self.problems) < LIMIT:
            self.failed.add(key)
            self.problems.append(text)

    # -- events from host_run -------------------------------------------------
    def deliver(self) -> bool:
        """deliver_guest reached: a handler delivery when it returns to
        rt_irq_async_back (sync) or rt_irq_interrupt_back (async, I6)."""
        back = self.h.u32(self.h.r("a7"))
        cs, ip = (int.from_bytes(self.h.mem(self.h.syms[n], 2), "big")
                  for n in ("rt_deliver_cs", "rt_deliver_ip"))
        # IRQ 7 from rt_irq: the frame on the interrupted stack (IVT 0Fh's handler)
        sb = back == self.poll_back and self.h.gmem(0x0F * 4, 4) == struct.pack("<HH", ip, cs) or \
            back == self.hook_back and self.h.gmem(0x15 * 4, 4) == struct.pack("<HH", ip, cs)
        if back not in self.backs and not sb:
            return False
        if self.mask is None:
            self.layout()
        if self.in_handler:
            self.fail(f"handler {cs:04X}:{ip:04X} entered inside a handler (tick {self.tick})")
        g = self.h.guest_regs(8)
        if not sb and (g["ss"], g["sp"]) != PRIVATE_STACK:
            self.fail(f"handler entered on {g['ss']:04X}:{g['sp']:04X}, not the private stack "
                      f"(tick {self.tick})")
        top = g["ss"] * 16 + g["sp"]
        self.k = (top - self.depth, top + 5)
        self.entries[f"{cs:04X}:{ip:04X}"] += 1
        self.check_bounds("entry")
        self.entry_segs = self.segments()
        self.place()
        self.in_handler = True
        if hasattr(self.h, "watch_handler"):
            self.h.watch_handler(True)     # memwatch.c: every access
        return True

    def returned(self):
        if self.in_handler:
            self.in_handler = False
            if hasattr(self.h, "watch_handler"):
                self.h.watch_handler(False)
            self.check_bounds("return")
            self.tick += 1

    def read(self, lin: int, size: int):
        m = self.mask
        if m is None:
            return
        if self.in_handler:
            return self.handler_access(False, lin, size)
        if m[lin] & WRITTEN or m[lin + size - 1] & WRITTEN or size == 4 and (m[lin + 1] | m[lin + 2]) & WRITTEN:
            self.main_access(False, lin, size)

    def write(self, lin: int, size: int):
        m = self.mask
        if m is None:
            return
        if self.in_handler:
            return self.handler_access(True, lin, size)
        if m[lin] & ACCESSED or m[lin + size - 1] & ACCESSED or \
                size == 4 and (m[lin + 1] | m[lin + 2]) & ACCESSED or \
                self.buffer_span[0] <= lin + size - 1 and lin <= self.buffer_span[1]:
            self.main_access(True, lin, size)

    def handler_access(self, write: bool, lin: int, size: int):
        if self.pending_place:      # a pointer word stored since (hooks run before the store)
            self.place()
            self.pending_place = False
        need = WRITE_OK if write else READ_OK
        kind = "w" if write else "r"
        stored_pointer = False
        for a in range(lin, lin + size):
            bits = self.mask[a]
            if write and bits & POINTER:
                stored_pointer = True
            if self.k[0] <= a <= self.k[1] or bits & need:
                continue
            cls = self.runtime_class(a, kind)
            if cls is not None:
                if not write:
                    self.runtime_reads[cls] += 1
                    if EMS_FRAME[0] <= a < EMS_FRAME[1]:
                        self.frame_reads += 1
                    else:
                        r = self.buffer_reads.setdefault(a, [self.tick, self.tick, cls])
                        r[1] = self.tick
                        self.mask[a] |= BUFFER      # memwatch.c passes main writes of it
                        lo, hi = self.buffer_span
                        self.buffer_span = (a, a) if lo > hi else (min(lo, a), max(hi, a))
                continue
            if EMS_FRAME[0] <= a < EMS_FRAME[1] and self.symbol(self.h.r("pc")) == "copy":
                self.frame_service += 1     # ems.c's page copy: the frame shows its mapped page
                continue
            self.fail(f"handler {'write' if write else 'read'} of {a:05X} outside the footprint "
                      f"at {self.where()} (tick {self.tick})")
            return
        if stored_pointer:
            self.pending_place = True

    def main_access(self, write: bool, lin: int, size: int):
        bits = 0
        for a in range(lin, lin + size):
            bits |= self.mask[a]
        hit = bits & (ACCESSED if write else WRITTEN)
        buffer = write and self.buffer_span[0] <= lin + size - 1 and lin <= self.buffer_span[1] and \
            any(a in self.buffer_reads for a in range(lin, lin + size))
        if not hit and not buffer:
            return
        pc = self.h.r("pc")
        generated = self.h.code[0] <= pc < self.h.code[1]
        if self.h.in_service:
            who = f"service {self.h.pending_vec[-1]:02X}h" if self.h.pending_vec else "service"
        elif generated:
            who = self.site(self.node(pc))
        else:
            who = self.symbol(pc)
        if buffer:
            self.buffer_writes.append((lin, size, who, generated and not self.h.in_service, self.tick))
        if not hit:
            return
        if self.h.in_service or (not generated and who.split(".")[0] in INTERRUPT_SIDE):
            self.services[f"{who} {self.cls_of(lin)}"] += 1
        elif not generated:
            self.fail(f"runtime {'write' if write else 'read'} of {lin:05X} meets the footprint "
                      f"at {who}")
        elif self.h.state(11, 1) == 0:
            self.masked[who] += 1
        elif self.covered(self.node(pc), lin, size):
            self.found[who] += 1
        else:
            self.fail(f"main {'write' if write else 'read'} of {lin:05X} ({self.cls_of(lin)}) meets "
                      f"the footprint at {who}, not a sync access for it")

    def cls_of(self, lin: int) -> str:
        for cls, lo, hi, _ in self.mem:
            p = self.para(cls)
            if p * 16 + lo <= lin <= p * 16 + hi:
                return f"{cls}:{lin - p * 16:04X}"
        return f"{lin:05X}"

    def covered(self, node, lin: int, size: int) -> bool:
        for cls, lo, hi in self.sync.get(node, ()):
            p = self.para(cls)
            if p is not None and p * 16 + lo <= lin and lin + size - 1 <= p * 16 + hi:
                return True
        return False

    # -- result ----------------------------------------------------------------
    def finish(self, out: Path | None) -> list[str]:
        problems = list(self.problems) + buffer_races(self.buffer_reads, self.buffer_writes)
        if not self.entries:
            problems.append("irq monitor: no handler delivery (nothing checked)")
        record = dict(ticks=self.tick, handler_entries=dict(self.entries),
                      dropped_row=self.dropped and list(self.dropped),
                      bound_checks=self.checked_bounds,
                      sync_sites=dict(sorted(self.found.items())),
                      if_clear=dict(sorted(self.masked.items())),
                      services=dict(sorted(self.services.items())),
                      runtime_class_reads=dict(sorted(self.runtime_reads.items())),
                      frame_reads=self.frame_reads, frame_service=self.frame_service,
                      buffer_bytes=len(self.buffer_reads),
                      service_buffer_writes=sorted({w for _, _, w, g, _ in self.buffer_writes if not g}))
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, indent=1) + "\n")
        print(f"irq monitor: {self.tick} handler runs ({', '.join(f'{k} {v}' for k, v in sorted(self.entries.items()))}), "
              f"{len(self.found)} sync sites hit, {sum(self.masked.values())} IF-clear and "
              f"{sum(self.services.values())} service accesses, {self.checked_bounds} bound checks, "
              f"{len(self.buffer_reads)} buffer bytes, {self.frame_reads} frame reads, "
              f"{self.frame_service} frame bytes copied by the EMS model, "
              f"{len(problems)} problems")
        return problems
