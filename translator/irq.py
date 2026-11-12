"""IRQ handler footprint proof (docs/irq-plan.md I2): gen time, generated code unchanged.

Handlers: every one WC2 installs (HANDLERS: INT 08h at WC2.EXE+0FD10 and its temporary
+148E0, INT 0Fh at +06F3F), each an abstract interpretation of the lifted IR
(translator/sem.py) over its CFG; one footprint for the set (merge). Values: constants,
unsigned and signed ranges, byte pairs (`b`: a known byte under another), the
interrupted registers (whole or halves), entry SP plus a displacement, segment
classes, words loaded through a displacement (typed by it). Contexts: a call enters
its target with the input as markers; CTX_LIMIT exact inputs per function, then one
joined context per DS classes and constant argument words; a function calling itself
nests SELF_DEPTH deep, deeper is recursion (an error). States per context and
instruction are partitioned by SP, BP and DS (and the counter of a leaf loop counted
below UNROLL, which runs unrolled), joined within a partition, widened at loop heads
to the compare constants nearby (thresholds) after WIDEN changes. Branches narrow
both compared operands (registers, stack slots, memory facts, the slot a register
was just loaded from; constants or bounded values). REP MOVS/STOS is one access over
the bytes any count in CX moves. Segment classes: a load-relative link paragraph
(four hex digits; the drivers' at emit.DRIVER_SEG), `abs:XXXX` an absolute paragraph
(the BIOS tick the BIOS chain runs, rt_bios_int08; segment 0, the EMS resolver's
null result, is left out: a runtime row, I3 fails any handler access there), a
runtime class `[C:a-b]` (segments the words at C:a..b hold: the EMS frame segment,
buffers; I3 places them at run time), `K` (the interrupted stack). Loads inside an
annotations/irq-bounds.csv variable or byte table take its bound; a handler store
outside it is an error, one that may break it a runtime row (I3 checks every bound
at handler entry and return); accesses of a class with an extent row (`*`) are
clamped to it. INT 67h AH=44h/47h/48h is the runtime's EMS service (runtime rows).
Proved, else Violation: no interrupted register, flag or stack word is read but
to save it (a push or its copy), every exit (IRET, or the chain to the BIOS
handler with the frame in place) has every register, SP and the frame as on entry,
no DF read, every port in PORTS, no other software interrupt, no recursion, no
indirect transfer but traced far calls and the BIOS chain. A possible divide
fault is listed (runtime row).

Main code: a forward analysis over emit.Program's graph from the MZ entry with the
DOS state; the handler entries are not main code. States are kept per context
(function entry, entry DS, entry SS): a call enters its targets' contexts, a return
site joins the caller's stack and BP with the callee context's state at its returns
(DS and the rest), so a function entered with several DS values is classified once
per value. State: segment registers, the general registers as constants (byte
halves too), the stack since the function entry (push/pop, `mov bp,sp`/`mov sp,bp`,
SP adjustments), IF and the STI shadow, and code-segment words stored on the path
(`mov cs:[x],ds` ... `mov ds,cs:[x]`; killed by stores that may overlap them, an
indexed writer by its self-modifying.csv region, else all). Unresolved transfers
reach their traced targets (indirect.csv); an untraced call keeps DS (Borland C; I3's
monitor checks); INT 21h AH=4Ch ends a path. annotations/irq-ds.csv declares
entries that return the caller's DS where the analysis cannot see it. Constant-
address word stores give memory slots (resolved by iteration). Each access of a reached instruction is masked (IF = 0
or STI shadow in every context: no delivery before it), disjoint (known address
outside the footprint), sync (may meet it: a read of a handler-written byte, a
write of a handler-accessed byte, a handler port; an indexed access whose
displacement lies in a footprint interval of its segment) or monitored (segment or
offset unknown, or not reached; host runs check them, I3; annotations/irq-sync.csv
declares the ones they found meeting it: sync for the declared span); the worst
context counts. Runtime classes are only located at run time (I3). A sync access to a
handler-written byte must lower to one 68k instruction that touches memory, or to
straight-line code the emitter runs under rt_irq_hold (Proof.held, irq-hold.csv), and
no compute row may contain a sync access, else Violation; main writes of bounded
variables are checked by I3 at every handler entry.
Output build/gen/irq-footprint.csv: kind (mem, port, if, hook, runtime, exit, extent,
stack, sync), class, first, last, access, where.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from . import image
from .decode import Far, Imm, Mem, Reg
from .ir import FLAG_KINDS, T, mask
from .lower import CC_READS, LOADSEG
from .sem import lift

M = image.M
# Ports the handlers may touch (MEASURED in the traces, external-surface.md): the PIC
# EOI, STRAX's OPL writes and its delay loop's PIT counter reads, and the IRQ 7
# handler's Sound Blaster DSP and DMA channel 1 programming
PORTS = {0x20: "PIC EOI", 0x40: "PIT counter 0", 0x43: "PIT control", 0x388: "OPL index",
         0x389: "OPL data", 0x22A: "SB DSP read", 0x22C: "SB DSP write", 0x22E: "SB DSP status",
         0x02: "DMA address 1", 0x03: "DMA count 1", 0x0A: "DMA mask", 0x0B: "DMA mode",
         0x0C: "DMA flip-flop", 0x83: "DMA page 1"}
NULL_CLASS = "abs:0000"   # EMS resolver's failure result 0000:0000 (WC2.EXE+15831 paths)
BIOS_TICK = ("abs:0040", 0x6C, 0x70)  # rt_bios_int08: tick dword, midnight byte (0040:006C)
BIOS_ENTRY = ("-", 0xFFEA5)          # indirect.csv target of the chain (F000:FEA5)
# The hardware interrupt handlers WC2 installs (external-surface.md, MEASURED: the
# vectors set through INT 21h AH=25h and the handlers the traces entered) -> vector
HANDLERS = {("WC2.EXE", 0x0FD10): 0x08, ("WC2.EXE", 0x148E0): 0x08, ("WC2.EXE", 0x06F3F): 0x0F}
# entries.csv "interrupt handler" rows no hardware interrupt enters
EMS_HANDLER = {0x44: "map a page", 0x47: "save the page map", 0x48: "restore the page map"}
NOT_HARDWARE = {("WC2.EXE", 0x0FD93): "INT 15h AH=4Fh keyboard intercept, called by the BIOS "
                                      "INT 09h handler (not by input.c's yet: port-plan P6)"}
SIGNATURES = 64                      # signatures per context and instruction before joining
WIDEN = 6                            # joins that change a loop head's state before widening (4x elsewhere)
STATES = 400_000                     # handler states (context, instruction, signature) at most
WINDOW = 0x40                        # caller stack bytes above a callee's return address it sees
TH_SPAN = 0x200                      # bytes around a loop head whose compare constants bound widening
SELF_DEPTH = 3                       # nested contexts of a function calling itself
CTX_LIMIT = 8                        # exact input contexts per function before one joined one
REGS = ("ax", "bx", "cx", "dx", "si", "di", "bp", "sp", "cs", "ds", "es", "ss", "flagsx")
HALF = {"al": ("ax", 0), "ah": ("ax", 1), "bl": ("bx", 0), "bh": ("bx", 1),
        "cl": ("cx", 0), "ch": ("cx", 1), "dl": ("dx", 0), "dh": ("dx", 1)}
FLAGS = ("CF", "PF", "AF", "ZF", "SF", "TF", "IF", "DF", "OF")
X = ("x",)
TAINT = ("e", "h", "p", "x")


class Violation(Exception):
    pass


def bounds() -> dict[tuple[str, int, int], tuple[int, int, int]]:
    """(class, first, width) -> (lo, hi, last): every element at first..last (a
    variable, or `first-last` a byte table) holds lo..hi; a load that lies inside
    takes the bound."""
    out = {}
    for r in image.rows("irq-bounds.csv"):
        if r["variable"] == "*":
            continue
        first, _, last = r["variable"].partition("-")
        w = int(r["width"])
        if last and w != 8:
            raise Violation(f"irq-bounds.csv: table {r['class']}:{r['variable']} of {w}-bit elements")
        out[(r["class"], int(first, 16), w)] = (int(r["lo"], 16), int(r["hi"], 16),
                                               int(last or first, 16))
    return out


def bound_of(rows, cls, a, b, w):
    """The irq-bounds.csv bound (lo, hi) of a w-bit load of cls bytes a..b, else None."""
    for (bc, first, bw), (lo, hi, last) in rows.items():
        if bc == cls and bw == w and first <= a and b <= last + w // 8 - 1 and \
                (w == 8 or a == first):
            return lo, hi
    return None


def extents() -> dict[str, tuple[int, int]]:
    """class -> (lo, hi): the offsets every handler access of the class lies in (variable
    `*`); a wider access range is clamped and listed (extent rows; I3 checks)."""
    return {r["class"]: (int(r["lo"], 16), int(r["hi"], 16))
            for r in image.rows("irq-bounds.csv") if r["variable"] == "*"}


def declared_sync() -> dict[tuple[str, int], list[tuple[str, int, int, str]]]:
    """(module, offset) -> [(class, first, last, access)]: monitored accesses that the
    host runs found meeting the footprint (irq-sync.csv, I3); sync for that span."""
    out = defaultdict(list)
    for r in image.rows("irq-sync.csv"):
        out[(r["module"], int(r["offset"], 16))].append(
            (r["class"], int(r["first"], 16), int(r["last"], 16), r["access"]))
    return dict(out)


# Runtime classes: a segment register loaded from a handler-visible word of class
# C at offsets a..b (an indexed word: every offset its address may take) is the
# class "[C:a-b]": the paragraphs those words hold when the access runs. I3's
# monitor takes them at each handler entry and adds the words the handler stores
# there while it runs. An index range wider than RUNTIME_SPAN is an error (an
# unbounded index).
RUNTIME_SPAN = 0x400


def runtime_class(cls, a, b) -> str:
    return f"[{cls}:{a:04X}-{b:04X}]"


def runtime_words(name):
    """(class, a, b) of a runtime class name, else None."""
    m = re.fullmatch(r"\[([0-9A-F]{4}|abs:[0-9A-F]{4}):([0-9A-F]{4})-([0-9A-F]{4})\]", name)
    return (m.group(1), int(m.group(2), 16), int(m.group(3), 16)) if m else None


# Memory facts: a cmp/test of a non-stack memory operand keeps the value it read
# (narrowed by the branch after it) as a state slot keyed by the operand's form, so
# compiled code's reload of a tested field sees the bound. A store through the
# fact's own form sets it; it dies when a register of its address changes, at a
# non-stack store that may meet it (any but one through the same address registers
# to other bytes), at calls, and at INT 67h unless its segment is a module class.
FACT = 1 << 32
_FACTS: dict = {}
FACT_REGS: dict = {}
FACT_FORM: dict = {}


def fact_key(m) -> int:
    form = (m.seg, m.base, m.index, m.disp, m.width)
    if form not in _FACTS:
        _FACTS[form] = FACT + len(_FACTS)
        FACT_REGS[_FACTS[form]] = {r for r in (m.seg, m.base, m.index) if r}
        FACT_FORM[_FACTS[form]] = form
    return _FACTS[form]


SWAP = {"e": "e", "ne": "ne", "b": "a", "a": "b", "be": "ae", "ae": "be",
        "l": "g", "g": "l", "le": "ge", "ge": "le"}


def bound(x, w, cc, y):
    """x bounded by `x cc y` (y a constant or a range): the new value, None (no
    bound), or False (infeasible)."""
    half = 1 << (w - 1)
    clo, chi = srng(y, w)
    if cc in ("l", "ge", "le", "g"):        # on the signed interval
        lo, hi = signed(*srng(x, w), w) or (-half, half - 1)
        got = signed(clo, chi, w)
        if got is None:
            return None
        clo, chi = got
    else:
        lo, hi = srng(x, w)
        if lo < 0 and cc in ("e", "ne"):
            clo, chi = signed(clo, chi, w) or (clo, chi)
        elif lo < 0:
            lo, hi = rng(x, w)
        if clo < 0 and lo >= 0:
            clo, chi = rng(y, w)
    if cc in ("b", "l"):
        hi = min(hi, chi - 1)
    elif cc in ("be", "le"):
        hi = min(hi, chi)
    elif cc in ("a", "g"):
        lo = max(lo, clo + 1)
    elif cc in ("ae", "ge"):
        lo = max(lo, clo)
    elif cc == "e":
        lo, hi = max(lo, clo), min(hi, chi)
    elif cc == "ne" and clo == chi:
        lo, hi = lo + (lo == clo), hi - (hi == clo)
    else:
        return None
    if lo > hi:
        return False
    return mk(lo, hi, w)


def self_depth(ctx) -> int:
    """How many nested self-call contexts ctx is in."""
    d = 0
    while isinstance(ctx[1], tuple) and ctx[1][0] == "self":
        d, ctx = d + 1, ctx[1][1]
    return d


def code_class(prog, n) -> str:
    """The class of a static code segment: its link paragraph (load-relative; a
    driver's at its emit.DRIVER_SEG)."""
    from .emit import DRIVER_SEG
    u = prog.units[n[0]]
    return f"{u.cs[n[1]] + DRIVER_SEG.get(n[0], 0):04X}"


def handler_entries() -> dict[tuple[str, int], int]:
    """HANDLERS, checked against entries.csv: every "interrupt handler" row is a
    hardware handler or in NOT_HARDWARE."""
    rows = {(r["module"], int(r["offset"], 16)) for r in image.rows("entries.csv")
            if r["reason"] == "interrupt handler"}
    if rows != set(HANDLERS) | set(NOT_HARDWARE):
        raise Violation(f"entries.csv interrupt handlers {sorted(rows)} are not HANDLERS and NOT_HARDWARE")
    return dict(HANDLERS)


def traced_far(prog, n) -> list:
    """The traced targets of an indirect far transfer (indirect.csv), an interrupt
    handler the trace entered through it ("(isr)", a call of the previous handler)
    included; the BIOS tick as BIOS_ENTRY."""
    out = []
    for r in image.rows("indirect.csv"):
        if (r["module"], int(r["offset"], 16)) == n:
            for t in r["traced_targets"].split():
                if t != "(isr)":
                    mod, off = t.split("+")
                    out.append((mod, int(off, 16)))
    return list(dict.fromkeys(out))


# -- abstract values -----------------------------------------------------------
def pointer_targets(mod, text) -> list:
    """The traced targets of every far transfer in mod through the same fixed
    pointer (indirect.csv's instruction text): what that variable held."""
    out = []
    for r in image.rows("indirect.csv"):
        if r["module"] == mod and r["instruction"] == text:
            for t in r["traced_targets"].split():
                if t != "(isr)":
                    m, off = t.split("+")
                    out.append((m, int(off, 16)))
    return list(dict.fromkeys(out))


def raw(v):
    """A value without its input marker: ('in', r, v) is v, the callee's input
    register r (Handler.call), kept through copies so a return can give the
    caller its own value back."""
    return v[2] if v[0] == "in" else v


def rng(v, w):
    """Unsigned (lo, hi) of a handler-defined value, else None."""
    v = raw(v)
    k = v[0]
    if k == "c":
        return v[1] & mask(w), v[1] & mask(w)
    if k == "r":
        return (v[1], v[2]) if 0 <= v[1] and v[2] <= mask(w) else (0, mask(w))
    if k in ("l", "s", "sd"):
        return 0, mask(w)
    if k == "b" and w == 16:
        lo, hi = rng(v[1], 8), rng(v[2], 8)
        return lo[0] | hi[0] << 8, lo[1] | hi[1] << 8
    if k == "b":
        return 0, mask(w)
    return None


def srng(v, w):
    """(lo, hi) as a signed interval when the value is one (a range ("r", lo, hi)
    with lo < 0: -1..N and the like), else as rng."""
    v = raw(v)
    if v[0] == "r" and v[1] < 0 and v[2] <= mask(w):
        return v[1], v[2]
    return rng(v, w)


def signed(lo, hi, w):
    """An unsigned or signed interval as a signed one, else None (it crosses 8000h)."""
    half = 1 << (w - 1)
    if lo < 0 or hi < half:
        return lo, hi
    if lo >= half:
        return lo - 2 * half, hi - 2 * half
    return None


def mk(lo, hi, w):
    """A range of w-bit values: unsigned, or signed (lo < 0) when it holds
    values on both sides of zero; else every value. Wrapped sums fold back."""
    full = 1 << w
    if lo >= full:
        lo, hi = lo - full, hi - full
    elif hi >= full > lo and lo - full >= -(full >> 1) and hi - full < full >> 1:
        lo, hi = lo - full, hi - full
    if lo < 0 and lo >= -(full >> 1) and hi < 0:
        lo, hi = lo + full, hi + full
    if lo < -(full >> 1) or hi > mask(w) or (lo < 0 and hi >= full >> 1):
        return ("r", 0, mask(w))
    return ("c", lo & mask(w)) if lo == hi else ("r", lo, hi)


def hull(x, y, w):
    """The smaller of the unsigned and the signed hull of two intervals."""
    u = (min(x[0], y[0]), max(x[1], y[1])) if x[0] >= 0 and y[0] >= 0 else None
    sx, sy = signed(*x, w), signed(*y, w)
    s_ = (min(sx[0], sy[0]), max(sx[1], sy[1])) if sx and sy else None
    if u is None and s_ is None:
        return ("r", 0, mask(w))
    if u is None or (s_ is not None and s_[1] - s_[0] < u[1] - u[0]):
        return mk(*s_, w)
    return mk(*u, w)


def split(v, k):
    v = raw(v)
    t = v[0]
    if t == "c":
        return ("c", v[1] >> 8 * k & 0xFF)
    if t == "r" and v[1] < 0:
        return ("r", 0, 0xFF)
    if t == "r":
        return mk(v[1] >> 8 * k if k else v[1], v[2] >> 8 * k if k else v[2], 8) if k or v[2] < 256 \
            else ("r", 0, 0xFF)
    if t == "e":
        return ("h", v[1], k)
    if t in ("p", "b"):
        return v[1 + k]
    if t in ("l", "s", "sd"):
        return ("r", 0, 0xFF)
    return X


def combine(lo, hi):
    lo, hi = raw(lo), raw(hi)
    if lo[0] == "c" and hi[0] == "c":
        return ("c", lo[1] | hi[1] << 8)
    if lo[0] == "h" and hi[0] == "h" and lo[1] == hi[1] and (lo[2], hi[2]) == (0, 1):
        return ("e", lo[1])
    if lo[0] in TAINT or hi[0] in TAINT:
        return ("p", lo, hi)
    a, b = rng(lo, 8), rng(hi, 8)
    if b[0] != b[1] and a != (0, 0xFF):     # not one interval: the bytes apart
        return ("b", mk(*a, 8), mk(*b, 8))
    return mk(a[0] | b[0] << 8, a[1] | b[1] << 8, 16)


def join8(a, b):
    a, b = raw(a), raw(b)
    if a == b:
        return a
    if a[0] in TAINT or b[0] in TAINT:
        return X
    return hull(srng(a, 8), srng(b, 8), 8)


def join_flag(x, y):
    """Flag values; None (the interrupted flag) absorbs."""
    return x if x == y else None if x is None or y is None else ("r", 0, 1)


def join(a, b):
    """Values on two paths: interrupted state on either stays X (reading it
    fails); handler values of different kinds join to the full range."""
    if a == b:
        return a
    if a[0] == "in" and b[0] == "in" and a[1] == b[1]:
        return ("in", a[1], join(a[2], b[2]))
    a, b = raw(a), raw(b)
    if a == b:
        return a
    if a[0] == "w" and b[0] == "w":     # FLAGS images (Handler.flags_value)
        return ("w", tuple(join_flag(x, y) for x, y in zip(a[1], b[1])), join(a[2], b[2]))
    if a[0] == "l" == b[0] and len(a) == len(b) == 5 and a[1] == b[1]:
        return ("l", a[1], None, min(a[3], b[3]), max(a[4], b[4]))   # a word of either
    # a loaded word with a segment or a constant (FFFFh: none): as its runtime class
    # (as a number any word either way)
    if a[0] == "l" and len(a) == 5 and b[0] in ("s", "sd", "c") and not a[1].startswith("["):
        a = ("s", frozenset({runtime_class(a[1], a[3], a[4])}))
    if b[0] == "l" and len(b) == 5 and a[0] in ("s", "sd", "c") and not b[1].startswith("["):
        b = ("s", frozenset({runtime_class(b[1], b[3], b[4])}))
    if a[0] in ("s", "sd") and b[0] == "c":    # a segment or a constant (FFFFh: none)
        a, b = b, a
    if a[0] == "c" and b[0] in ("s", "sd"):
        a = ("s", frozenset({abs_class(a[1])}))
    if a[0] in ("s", "sd") and b[0] in ("s", "sd"):
        return seg_join(a, b)
    if a[0] in ("e", "p", "b") or b[0] in ("e", "p", "b"):
        return combine(join8(split(a, 0), split(b, 0)), join8(split(a, 1), split(b, 1)))
    if a[0] in TAINT or b[0] in TAINT:
        return X
    x, y = srng(a, 16), srng(b, 16)
    if x is None or y is None or a[0] in ("sp", "s", "sd") or b[0] in ("sp", "s", "sd"):
        return ("r", 0, 0xFFFF)     # stack addresses, segments, markers: a handler word
    return hull(x, y, 16)


def abs_class(para) -> str:
    """The class of a constant paragraph."""
    return f"abs:{para & 0xFFFF:04X}"


def paras(v):
    """A segment value's paragraph displacement from its classes' bases."""
    return (v[2], v[3]) if v[0] == "sd" else (0, 0)


def seg_of(classes, lo, hi):
    """Segment classes displaced by lo..hi paragraphs ('sd'), or plain ('s')."""
    return ("s", classes) if (lo, hi) == (0, 0) else ("sd", classes, lo, hi)


def seg_key(v):
    """What a joined context keeps of a segment register: its classes."""
    v = raw(v)
    return v[1] if v[0] in ("s", "sd") else v[0]


def seg_join(a, b):
    (alo, ahi), (blo, bhi) = paras(a), paras(b)
    return seg_of(a[1] | b[1], min(alo, blo), max(ahi, bhi))


def widen(o, v, th=()):
    """v widened from o: a range bound that grew goes to the next threshold (th:
    the compare constants near a loop head), a byte's end (FFh), the end of the
    signed positive half, then the end."""
    if v[0] == "in":
        return ("in", v[1], widen(o[2] if o and o[0] == "in" else None, v[2], th))
    if v[0] == "sd":
        return ("sd", v[1], v[2], 0xFFFF)
    if v[0] == "b":     # a byte that changed: all its values
        was = o if o is not None and o[0] == "b" else (None, None, None)
        return combine(*(v[1 + k] if was[1 + k] == v[1 + k] else ("r", 0, 0xFF) for k in (0, 1)))
    if v[0] != "r":
        return v
    old = srng(o, 16) if o is not None else None
    if old is None:
        return ("r", 0, 0xFFFF)
    if v[1] < 0:        # signed: the old interval as signed too
        old = signed(*old, 16)
        if old is None:
            return ("r", 0, 0xFFFF)
    lo = old[0] if v[1] >= old[0] else \
        max((t for t in set(th) | {0, -1} if t <= v[1]), default=-0x8000)
    hi = old[1] if v[2] <= old[1] else \
        min(t for t in set(th) | {0xFF, 0x7FFF, 0xFFFF} if t >= v[2])
    return mk(lo, hi, 16)


@dataclass
class Footprint:
    mem: dict = field(default_factory=lambda: defaultdict(set))   # (cls, lo, hi, 'r'|'w') -> sites
    ports: dict = field(default_factory=lambda: defaultdict(set))
    ifs: dict = field(default_factory=lambda: defaultdict(set))   # value -> sites
    hooks: dict = field(default_factory=lambda: defaultdict(set))
    exits: dict = field(default_factory=lambda: defaultdict(set))
    runtime: dict = field(default_factory=lambda: defaultdict(set))
    clamped: dict = field(default_factory=lambda: defaultdict(set))   # class -> sites (extents)
    pointers: dict = field(default_factory=lambda: defaultdict(set))  # (cls, var) -> far targets
    depth: int = 0
    nodes: set = field(default_factory=set)
    errors: list = field(default_factory=list)

def site(n) -> str:
    return f"{n[0]}+{n[1]:05X}"


# -- handler interpretation ----------------------------------------------------
class _Path:
    """One state while interpreting an instruction's ops."""

    def __init__(self, regs, flags, slots):
        self.regs, self.flags, self.slots = dict(regs), dict(flags), dict(slots)
        self.t = {}

    def freeze(self):
        return (tuple(self.regs[r] for r in REGS), tuple(self.flags.get(f) for f in FLAGS),
                tuple(sorted(self.slots.items())))


def thaw(st):
    regs, flags, slots = st
    return _Path(dict(zip(REGS, regs)), {f: v for f, v in zip(FLAGS, flags) if v is not None},
                 dict(slots))


def join_states(a, b):
    regs = tuple(join(x, y) for x, y in zip(a[0], b[0]))
    flags = tuple(join_flag(x, y) for x, y in zip(a[1], b[1]))
    sa, sb = dict(a[2]), dict(b[2])
    slots = tuple((d, (wa, join(va, sb[d][1]))) for d, (wa, va) in a[2]
                  if d in sb and sb[d][0] == wa)
    # a caller's word unchanged on one path, absent on the other (callers of a
    # joined context differ): still the caller's on return, unreadable here
    one = [(d, sa.get(d) or sb[d]) for d in sorted(sa.keys() ^ sb.keys())]
    slots += tuple((d, (w, ("in", v[1], X))) for d, (w, v) in one
                   if v[0] == "in" and not isinstance(v[1], str))
    slots = tuple(sorted(slots))
    return regs, flags, slots


SIG = tuple(REGS.index(r) for r in ("sp", "bp", "ds"))
UNROLL = 0x10                        # leaf loops counted to below this run unrolled


def signature(s):
    """States join only with states of equal stack addresses and segments (numbers
    join to ranges; Handler.narrow bounds them at the branches)."""
    regs = tuple(raw(s[0][k]) if raw(s[0][k])[0] in ("s", "sp") else
                 ("sd", raw(s[0][k])[1]) if raw(s[0][k])[0] == "sd" else raw(s[0][k])[0] for k in SIG)
    return regs


def widen_state(old, new, th=()):
    """Widen the values that grew."""
    slots = dict(old[2])

    def was(d, w):
        got = slots.get(d)
        return got[1] if got is not None and got[0] == w else None

    return (tuple(v if v == o else widen(o, v, th) for o, v in zip(old[0], new[0])), new[1],
            tuple((d, (w, v if slots.get(d) == (w, v) else widen(was(d, w), v, th)))
                  for d, (w, v) in new[2]))


class Handler:
    def __init__(self, prog, entry):
        self.prog = prog
        self.entry = entry
        self.code_cls = code_class(prog, entry)
        self.bounds = bounds()
        self.extents = extents()
        self.fp = Footprint()
        self.far = {}
        self._th = {}

    def err(self, n, msg):
        self.fp.errors.append(f"{site(n)}: {msg}")

    def cs_value(self, n):
        return ("s", frozenset({code_class(self.prog, n)}))

    def para_class(self, n, para):
        mod = self.prog.units[n[0]].module
        if mod.link_lo <= para * 16 < mod.link_hi:
            return ("s", frozenset({f"{para:04X}"}))
        self.err(n, f"relocated segment {para:04X} outside {n[0]}")
        return X

    # -- contexts: one per function entry and input state -------------------------
    # A call enters its target with SP and the stack slots rebased to the callee's
    # entry (0: the return address, as RET markers) and only the WINDOW bytes above
    # it visible; calls with equal inputs share the callee's analysis. A return
    # rebases the callee's exit state into each caller that entered with it.
    def run(self) -> Footprint:
        regs = {r: ("e", r) for r in REGS}
        regs["cs"] = ("s", frozenset({self.code_cls}))
        regs["sp"] = ("sp", 0)
        flags = {"IF": ("c", 0), "TF": ("c", 0)}   # the others: the interrupted ones (absent)
        slots = {0: (16, ("e", "ip")), 2: (16, ("e", "cs")), 4: (16, ("e", "fl"))}
        start = _Path(regs, flags, slots).freeze()
        root = (self.entry, "root")
        self.states: dict = {}
        self.changes: Counter = Counter()
        self.done: dict = defaultdict(set)
        self.work, self.queued = [], set()
        self.conts: dict = defaultdict(set)     # ctx -> {(caller ctx, return node, d, caller state)}
        self.exits: dict = defaultdict(set)     # ctx -> {exit state (callee-relative)}
        self.edges: dict = defaultdict(set)     # ctx -> {(callee ctx, d)}
        self.local: Counter = Counter()         # ctx -> bytes below its entry it writes
        self.writes: dict = defaultdict(set)    # ctx -> stack bytes at or above its entry it may write
        self.grown: set = set()                 # contexts whose writes grew: their returns re-run
        self.count = 0
        self.inputs: Counter = Counter()        # function entry -> exact input contexts
        self.add(root, self.entry, start)
        while self.work:
            key = self.work.pop()
            self.queued.discard(key)
            ctx, n = key
            for st in [s for s in self.states[key].values() if s not in self.done[key]]:
                self.done[key].add(st)
                self.ctx = ctx
                for nctx, nn, ns in self.step(ctx, n, st):
                    self.add(nctx, nn, ns)
            while self.grown:
                g = self.grown.pop()
                for c in list(self.conts[g]):
                    for r in list(self.exits[g]):
                        self.add(*self.back(c, r, g))
        self.fp.depth = self.depth(root, set())
        return self.fp

    def add(self, ctx, n, ns):
        k2 = (ctx, n)
        have = self.states.setdefault(k2, {})
        sig = signature(ns)
        for k in self.unrolled(n):      # a counted leaf loop: one state per count
            v = raw(ns[0][k])
            sig += (v if v[0] == "c" else None,)
        if len(have) >= SIGNATURES and sig not in have:
            sig = None      # too many: one joined state
            if None not in have:
                base = ns
                for v in have.values():
                    base = join_states(base, v)
                have.clear()
                have[None] = base
        old = have.get(sig)
        if old is not None:
            new = join_states(old, ns)
            if new == old:
                return
            self.changes[(k2, sig)] += 1
            head = n in self.heads()
            if self.changes[(k2, sig)] > (WIDEN if head else 4 * WIDEN):
                new = widen_state(old, new, self.thresholds(n) if head else ())
            ns = new
        else:
            self.count += 1
            if self.count > STATES:
                hot = Counter(k[1] for k in self.states).most_common(5)
                raise Violation(f"{site(self.entry)}: more than {STATES} handler states "
                                f"(most contexts: {[(site(x), c) for x, c in hot]})")
        have[sig] = ns
        if k2 not in self.queued:
            self.queued.add(k2)
            self.work.append(k2)

    def unrolled(self, n):
        """The counter registers of the leaf loops n lies in: a backward jcc right
        after `cmp R,imm` (imm below UNROLL) with no call, interrupt or indirect jump
        between its target and it. States there are kept apart per constant
        counter (the loop runs unrolled, so an index moving with the counter stays
        exact); a counter that is no constant joins as before."""
        if not hasattr(self, "_unroll"):
            self._unroll = defaultdict(tuple)
            for m, ss in self.prog.succ.items():
                i = self.prog.node_insn(m)
                if i.op != "jcc":
                    continue
                for h in ss:
                    if not (isinstance(h, tuple) and h[0] == m[0] and h[1] <= m[1]):
                        continue
                    u = self.prog.units[m[0]]
                    body = [o for o in u.insns if h[1] <= o <= m[1]]
                    j = self.prog.node_insn(self._prev[m]) if self.preds_ok(m) else None
                    if j is None or j.op != "cmp" or not isinstance(j.operands[0], Reg) or \
                            j.operands[0].name not in ("si", "di", "cx", "bx") or \
                            not isinstance(j.operands[1], Imm) or \
                            not 0 < j.operands[1].value & 0xFFFF <= UNROLL:
                        continue
                    if any(u.insns[o].op in ("call", "callf", "int", "jmpf") or
                           u.insns[o].op == "jmp" and isinstance(u.insns[o].operands[0], (Mem, Reg))
                           for o in body):
                        continue
                    k = REGS.index(j.operands[0].name)
                    for o in body:
                        if k not in self._unroll[(m[0], o)]:
                            self._unroll[(m[0], o)] += (k,)
        return self._unroll.get(n, ())

    def heads(self):
        """Loop heads (backward jump targets): widened first, so a branch in the body
        bounds the body before the body widens."""
        if not hasattr(self, "_heads"):
            self._heads = {t for m, ss in self.prog.succ.items() for t in ss
                           if isinstance(t, tuple) and t[0] == m[0] and t[1] <= m[1]}
        return self._heads

    def thresholds(self, n):
        """Widening thresholds at loop head n: the constants (and one less) its
        neighbourhood's compares test, the bounds of the irq-bounds.csv variables they
        test, and 7FFFh, ascending."""
        if n not in self._th:
            u = self.prog.units[n[0]]
            out = set()
            for off in range(max(0, n[1] - TH_SPAN), n[1] + TH_SPAN):
                i = u.insns.get(off)
                if i is None or i.op != "cmp":
                    continue
                b = i.operands[1]
                if isinstance(b, Imm):
                    c = b.value & mask(b.width)
                    out |= {c, c - 1} - {-1}
                elif isinstance(b, Mem) and not (b.base or b.index):
                    for (cls, var, w), (lo, hi, last) in self.bounds.items():   # a bounded variable
                        if var <= b.disp <= last and w == b.width:
                            out |= {lo, hi, hi - 1} - {-1}
            self._th[n] = sorted(out | {0x7FFF})
        return self._th[n]

    def depth(self, ctx, path) -> int:
        if ctx in path:
            self.err(ctx[0], "recursion")
            return 0
        d = self.local[ctx]
        for callee, at in self.edges[ctx]:
            d = max(d, -at + self.depth(callee, path | {ctx}))
        return d

    @staticmethod
    def rebase(v, d):
        return ("sp", v[1] - d) if v[0] == "sp" else v

    def call(self, ctx, n, q, target, fall, far):
        """Enter target from q (the return address pushed): its context's input.
        Registers but SP and CS enter as input markers (raw); a function with
        CTX_LIMIT exact inputs takes the next ones in one joined context per
        DS classes and constant argument words (STRAX.DRV+0103E's command: a join
        across commands reaches command 79h's channel table with another command's
        channel). A function calling itself enters a nested context per calling site
        and context, SELF_DEPTH deep (STRAX.DRV+0103E: command 79h on channel 10 resets
        channels 11..26, three levels); deeper is a cycle (recursion, an error)."""
        sp = q.regs["sp"]
        if sp[0] != "sp":
            self.err(n, f"call with SP {sp}")
            return []
        d = sp[1]
        regs = {r: ("in", r, self.rebase(raw(v), d)) for r, v in q.regs.items()}
        regs["sp"] = ("sp", 0)
        regs["cs"] = self.cs_value(target)
        slots = {k - d: (w, self.rebase(raw(v), d)) for k, (w, v) in q.slots.items()
                 if 0 <= k - d < WINDOW}
        self.preds_ok(n)
        before = self._prev.get(n)
        j = self.prog.node_insn(before) if before else None
        borland = not far and j is not None and j.op == "push" and j.operands[0] == Reg("cs") \
            and slots.get(2) == (16, self.cs_value(n))      # push cs; call near
        slots = {k: (w, ("in", ("slot", k), v)) for k, (w, v) in slots.items()}
        slots[0] = (16, ("ret", "ip"))
        if far or borland:
            slots[2] = (16, ("ret", "cs"))
        entry = _Path(regs, q.flags, slots).freeze()
        callee = (target, entry)
        if ctx[0] == target and self_depth(ctx) < SELF_DEPTH:
            callee = (target, ("self", ctx, n))    # a call of itself: nested, per context and site
        elif callee not in self.conts and self.inputs[target] >= CTX_LIMIT:
            consts = tuple((k, raw(v[1])) for k, v in sorted(slots.items())
                           if k >= (4 if far or borland else 2) and raw(v[1])[0] == "c")
            callee = (target, ("joined", seg_key(regs["ds"])) + ((consts,) if consts else ()))
        elif callee not in self.conts:
            self.inputs[target] += 1
        cont = (ctx, fall, d, q.freeze())
        self.edges[ctx].add((callee, d))
        out = [(callee, target, entry)]
        if cont not in self.conts[callee]:
            self.conts[callee].add(cont)
            out += [self.back(cont, r, callee) for r in self.exits[callee]]
        return out

    def wrote(self, ctx, offsets):
        """Stack bytes a context writes; those at or above its entry are its caller's."""
        new = {k for k in offsets if k >= 0} - self.writes[ctx]
        if new and ctx[1] != "root":
            self.writes[ctx] |= new
            self.grown.add(ctx)

    def back(self, cont, r, callee):
        """The caller's state after a return with callee exit state r: input
        markers give the caller's own values back; a window word the callee
        never writes is the caller's."""
        cctx, fall, d, cst = cont
        c = thaw(cst)
        e = thaw(r)
        self.wrote(cctx, {k + d for k in self.writes[callee]})

        def up(v):
            if v[0] == "in" and isinstance(v[1], str):
                return c.regs[v[1]]
            if v[0] == "in":
                got = c.slots.get(d + v[1][1])
                return got[1] if got is not None else X
            return ("sp", v[1] + d) if v[0] == "sp" else v

        regs = {k: up(v) for k, v in e.regs.items()}
        slots = {k: s for k, s in c.slots.items() if d + WINDOW <= k < FACT}
        top = e.regs["sp"][1]
        for k, (w, v) in e.slots.items():
            if 0 <= k < WINDOW and k >= top:
                if v[0] == "in" and not isinstance(v[1], str) and d + v[1][1] not in c.slots:
                    continue    # a word this caller never had (another caller's): still absent
                slots[k + d] = (w, up(v))
        written = self.writes[callee]
        for k, s in c.slots.items():
            if d + top <= k < d + WINDOW and k not in slots and \
                    not any(b in written for b in range(k - d, k - d + s[0] // 8)):
                slots[k] = s
        p = _Path(regs, e.flags, slots)
        return (cctx, fall, p.freeze())

    def returned(self, ctx, n, p, words):
        """A RET, RETF or IRET in a called context: the markers checked, SP past
        them (words: the return address and flags words popped, the RET imm)."""
        if ctx[1] == "root":
            self.err(n, "return with an empty call stack")
            return []
        exit_ = p.freeze()
        if exit_ not in self.exits[ctx]:
            self.exits[ctx].add(exit_)
            return [self.back(c, exit_, ctx) for c in self.conts[ctx]]
        return []

    # one instruction from one state: [(ctx, node, state)]
    def step(self, ctx, n, st):
        prog = self.prog
        mod, off = n
        u = prog.units[mod]
        i = u.insns.get(off)
        if i is None:
            self.err(n, "flow outside decoded code")
            return []
        if any(o.code <= off < o.code + o.size for o in self.overlays(mod)):
            self.err(n, "overlay code (dynamic CS) in the handler")
            return []
        self.fp.nodes.add(n)
        if n in prog.hle:
            self.fp.hooks[prog.hle[n][1]].add(site(n))
        fall = (mod, off + i.size)
        p = thaw(st)
        p.regs["cs"] = self.cs_value(n)
        self.disp = None
        if i.op == "pushf":
            return self.pushf(ctx, n, p, fall)
        if i.op == "popf":
            return self.popf(ctx, n, p, fall)
        if i.op == "iret":
            return self.iret(ctx, n, p)
        if i.op in ("jmpf", "callf") and isinstance(i.operands[0], Mem):
            return self.indirect_far(ctx, n, i, p, fall)
        out = []
        for q, ex in self.ops(n, i, p, u):
            kind = ex[0]
            if i.op == "jcc" and kind in ("fall", "jump") and not self.narrow(n, i, q, kind == "jump"):
                continue    # the compared value cannot take this edge
            if kind == "fall":
                out.append((ctx, fall, q.freeze()))
            elif kind == "jump":
                t = ex[1]
                if isinstance(t, int):
                    ip = t
                elif t[0] == "c":
                    ip = t[1]
                else:
                    self.err(n, "indirect jump")
                    continue
                out.append((ctx, (mod, u.off_of(u.cs[off], ip)), q.freeze()))
            elif kind in ("call", "callf"):
                if kind == "call":
                    t = ex[1]
                    if not isinstance(t, int):
                        self.err(n, "indirect call")
                        continue
                    target = (mod, u.off_of(u.cs[off], t))
                elif off in u.far_targets:
                    target = u.far_targets[off]
                else:
                    self.err(n, "far call outside the scope")
                    continue
                out += self.call(ctx, n, q, target, fall, kind == "callf")
            elif kind == "jumpf" and off in u.far_targets:
                out.append((ctx, u.far_targets[off], q.freeze()))
            elif kind == "int" and ex[1] == 0x67:
                out += self.ems(ctx, n, q, fall)
            elif kind == "fault":
                self.fp.runtime[f"fault {ex[1]:02X}h (divide error: guest INT 00h at interrupt level)"].add(site(n))
            elif kind in ("ret", "retf"):
                want = [("ret", "ip")] + ([("ret", "cs")] if kind == "retf" else [])
                if list(ex[1:][::-1]) != want:
                    self.err(n, f"{kind} to {ex[1:]}, not the caller's return address")
                    continue
                out += self.returned(ctx, n, q, 0)
            else:
                self.err(n, f"{kind} in the handler")
        return out

    def ems(self, ctx, n, q, fall):
        """INT 67h in the handler: the runtime's EMS service (rt_int67) for the
        functions EMS_HANDLER; AH comes back as the status, the other registers and
        the flags as they were; memory facts but those in a module class die (it
        maps frame pages)."""
        ah = raw(split(q.regs["ax"], 1))
        if ah[0] != "c" or ah[1] not in EMS_HANDLER:
            self.err(n, f"INT 67h AH={ah} in the handler (allowed: {sorted(EMS_HANDLER)})")
            return []
        self.fp.runtime[f"rt_int67 AH={ah[1]:02X}h ({EMS_HANDLER[ah[1]]})"].add(site(n))
        q.regs["ax"] = combine(split(q.regs["ax"], 0), ("r", 0, 0xFF))
        for k in [k for k in q.slots if k >= FACT]:
            seg = raw(q.regs[FACT_FORM[k][0]])
            if seg[0] == "s" and all(re.fullmatch(r"[0-9A-F]{4}", c) for c in seg[1]):
                continue    # a module class: never in the page frame
            del q.slots[k]
        return [(ctx, fall, q.freeze())]

    # -- branch narrowing ---------------------------------------------------------
    NEG = {"e": "ne", "ne": "e", "b": "ae", "ae": "b", "be": "a", "a": "be",
           "l": "ge", "ge": "l", "le": "g", "g": "le"}

    def preds_ok(self, n):
        """n is entered only by falling through from the instruction before it."""
        if not hasattr(self, "_jumped"):
            self._jumped = set()
            for m, ss in self.prog.succ.items():
                f = (m[0], m[1] + self.prog.node_insn(m).size)
                self._jumped |= {t for t in ss if isinstance(t, tuple) and t != f}
            self._jumped |= set(self.prog.dispatch)
            self._prev = {}
            for mod, u in self.prog.units.items():
                for off, i in u.insns.items():
                    self._prev[(mod, off + i.size)] = (mod, off)
        return n not in self._jumped and n in self._prev

    def location(self, q, o):
        """A register or a stack slot (ss:[bp+d], BP a stack address) the state holds."""
        if isinstance(o, Reg) and (o.name in GPR or o.name in HALF):
            return ("reg", o.name)
        if isinstance(o, Mem) and o.seg == "ss" and o.base == "bp" and not o.index \
                and raw(q.regs["bp"])[0] == "sp" and o.width in (8, 16):
            return ("slot", raw(q.regs["bp"])[1] + o.disp - (0x10000 if o.disp >= 0x8000 else 0), o.width)
        if isinstance(o, Mem) and o.seg != "ss" and o.width in (8, 16) and fact_key(o) in q.slots:
            return ("slot", fact_key(o), o.width)
        return None

    def loc_get(self, q, loc):
        if loc[0] == "reg":
            return raw(self.get(q, loc[1])), 8 if loc[1] in HALF else 16
        got = q.slots.get(loc[1])
        return (None if got is None or got[0] != loc[2] else raw(got[1])), loc[2]

    def loc_put(self, n, q, loc, v):
        if loc[0] == "reg":
            old = q.regs[HALF[loc[1]][0] if loc[1] in HALF else loc[1]]
            if loc[1] not in HALF and old[0] == "in":
                v = ("in", old[1], v)       # still the input register, now bounded
            self.put(n, q, loc[1], v)
        else:
            old = q.slots.get(loc[1])
            if old is not None and old[1][0] == "in":
                v = ("in", old[1][1], v)    # still the caller's word, now bounded
            q.slots[loc[1]] = (loc[2], v)

    def narrow(self, n, i, q, taken) -> bool:
        """After `cmp A,B` / `test R,R` / `or R,R` right before this jcc: bound A (a
        register, stack slot or memory fact) by B (a constant or a bounded value) on
        this edge; False: infeasible."""
        if not self.preds_ok(n):
            return True
        j = self.prog.node_insn(self._prev[n])
        cc = i.cc if taken else self.NEG.get(i.cc)
        if cc is None:
            return True
        if j.op in ("test", "or", "and") and j.operands[0] == j.operands[1] and \
                cc in ("e", "ne", "l", "ge", "le", "g", "s", "ns"):
            a, b = j.operands[0], Imm(0, j.operands[0].width)    # the value against 0
            cc = {"s": "l", "ns": "ge"}.get(cc, cc)
        elif j.op == "cmp":
            a, b = j.operands
        else:
            return True
        la = self.location(q, a)
        x, w = self.loc_get(q, la) if la else (None, a.width if hasattr(a, "width") else 16)
        if x is not None and x[0] in ("s", "sd") and isinstance(b, Imm) and cc in ("e", "ne"):
            const = abs_class(b.value)      # a segment against a constant: its abs class
            if cc == "e":
                if const not in x[1]:
                    return False
                self.loc_put(n, q, la, ("c", b.value & 0xFFFF))
                return True
            rest = x[1] - {const}
            if not rest:
                return False
            self.loc_put(n, q, la, (x[0], rest) + x[2:])
            return True
        if isinstance(b, Imm):
            lb, y = None, ("c", b.value & mask(w))
        else:
            lb = self.location(q, b)
            y = self.loc_get(q, lb)[0] if lb else self.bounded_operand(q, b)
        num = ("c", "r")
        if x is None or y is None or x[0] not in num or y[0] not in num:
            return True
        got = bound(x, w, cc, y)
        if got is False:
            return False
        if got is not None:
            self.loc_put(n, q, la, got)
            src = self.loaded_from(self._prev[n], q, a) if la[0] == "reg" else None
            if src is not None:     # the slot the register was just loaded from, too
                got2 = bound(self.loc_get(q, src)[0] or x, w, cc, y)
                if got2 is False:
                    return False
                if got2 is not None:
                    self.loc_put(n, q, src, got2)
        if lb is not None:                  # B too, by the reversed condition
            got = bound(y, w, SWAP[cc], x)
            if got is False:
                return False
            if got is not None:
                self.loc_put(n, q, lb, got)
        return True

    def bounded_operand(self, q, o):
        """A constant-address memory operand's irq-bounds.csv bound, else None."""
        if not (isinstance(o, Mem) and o.seg != "ss" and not o.base and not o.index):
            return None
        seg = raw(q.regs[o.seg])
        if seg[0] != "s" or len(seg[1]) != 1:
            return None
        got = bound_of(self.bounds, next(iter(seg[1])), o.disp, o.disp + o.width // 8 - 1, o.width)
        return mk(*got, o.width) if got else None

    def loaded_from(self, at, q, a):
        """The stack slot location register a was loaded from by the instruction
        before node `at` (`mov a,[bp+d]`), if that is how `at` is entered."""
        if not self.preds_ok(at):
            return None
        i = self.prog.node_insn(self._prev[at])
        if i.op != "mov" or i.operands[0] != a:
            return None
        loc = self.location(q, i.operands[1])
        return loc if loc is not None and loc[0] == "slot" and loc[1] < FACT and \
            loc[2] == a.width else None

    def overlays(self, mod):
        if mod != M.ROOT:
            return []
        if not hasattr(self, "_ovls"):
            self._ovls = M.overlays()
        return self._ovls

    def transparent(self, n, p, sp):
        for r in REGS:
            want = ("sp", sp) if r == "sp" else ("s", frozenset({self.code_cls})) if r == "cs" \
                else ("e", r)
            if r == "cs":
                continue    # IRET and the chain take CS from the frame
            if p.regs[r] != want:
                self.err(n, f"{r} is {p.regs[r]} at the exit, not as interrupted")

    # -- the FLAGS image: PUSHF, POPF, IRET ---------------------------------------
    def flags_value(self, p):
        """The FLAGS register as a stack word: ('w', per-flag values; None: the
        interrupted flag), flagsx as interrupted unless the handler wrote it."""
        return ("w", tuple(p.flags.get(f) for f in FLAGS), p.regs["flagsx"])

    def set_flags(self, n, p, word):
        if word is None or word[0] != "w":
            self.err(n, f"pops FLAGS from {word}, not a FLAGS image the handler pushed")
            return False
        p.flags = {f: v for f, v in zip(FLAGS, word[1]) if v is not None}
        p.regs["flagsx"] = word[2]
        return True

    def pop_word(self, n, p, k=0):
        sp = p.regs["sp"]
        if sp[0] != "sp":
            self.err(n, f"pops through SP {sp}")
            return None
        got = p.slots.get(sp[1] + 2 * k)
        if got is None or got[0] != 16:
            self.err(n, f"reads the stack at SP{sp[1] + 2 * k:+d} (interrupted or unwritten)")
            return None
        return raw(got[1])

    def pushf(self, ctx, n, p, fall):
        sp = p.regs["sp"]
        if sp[0] != "sp":
            self.err(n, f"pushes through SP {sp}")
            return []
        p.regs["sp"] = ("sp", sp[1] - 2)
        self.access(n, p, p.regs["ss"], p.regs["sp"], 16, "w", self.flags_value(p))
        return [(ctx, fall, p.freeze())]

    def popf(self, ctx, n, p, fall):
        word = self.pop_word(n, p)
        if word is None or not self.set_flags(n, p, word):
            return []
        p.regs["sp"] = ("sp", p.regs["sp"][1] + 2)
        return [(ctx, fall, p.freeze())]

    def iret(self, ctx, n, p):
        """IRET: out of the handler with the interrupt frame (the root context), or
        back from a handler called as `pushf; callf` (the frame that call pushed)."""
        if ctx[1] == "root":
            for d, name in ((0, "ip"), (2, "cs"), (4, "fl")):
                sp = p.regs["sp"]
                if sp[0] != "sp" or p.slots.get(sp[1] + d) != (16, ("e", name)):
                    self.err(n, f"IRET pops {p.slots.get(sp[1] + d) if sp[0] == 'sp' else sp}, not the frame's {name}")
                    return []
            p.regs["sp"] = ("sp", p.regs["sp"][1] + 6)
            self.transparent(n, p, 6)
            self.fp.exits["iret"].add(site(n))
            return []
        ip, cs, word = (self.pop_word(n, p, k) for k in range(3))
        if (ip, cs) != (("ret", "ip"), ("ret", "cs")):
            self.err(n, f"IRET to {cs}:{ip}, not the caller's return address")
            return []
        if not self.set_flags(n, p, word):
            return []
        p.regs["sp"] = ("sp", p.regs["sp"][1] + 6)
        return self.returned(ctx, n, p, 0)

    # -- far transfers through memory --------------------------------------------
    def indirect_far(self, ctx, n, i, p, fall):
        """`jmpf`/`callf` through a pointer: its traced targets (indirect.csv); the
        BIOS tick (F000:FEA5) runs rt_bios_int08, which IRETs on this stack."""
        m = i.operands[0]
        u = self.prog.units[n[0]]
        out = []
        for q, ex in self.ops(n, i, p, u):     # reads the pointer, pushes CS:IP for callf
            if ex[0] not in ("jumpf", "callf"):
                self.err(n, f"{ex[0]} at a far transfer")
                continue
            targets = traced_far(self.prog, n)
            ds = raw(p.regs["ds"])
            if not targets and m.base is None and m.index is None and m.seg == "ds" \
                    and ds[0] == "s" and len(ds[1]) == 1:
                # an untraced site through a fixed pointer: the targets traced through
                # that pointer elsewhere; the monitor checks it at handler entry
                text = next(r["instruction"] for r in image.rows("indirect.csv")
                            if (r["module"], int(r["offset"], 16)) == n)
                targets = pointer_targets(n[0], text)
                self.fp.pointers[(next(iter(ds[1])), m.disp)].update(targets)
            if not targets:
                self.err(n, f"far {i.op} through {m} with no traced target (DS {ds})")
                continue
            for t in targets:
                r = _Path(q.regs, q.flags, q.slots)
                if t == BIOS_ENTRY:
                    if i.op == "callf":
                        self.err(n, "far call of the BIOS tick")
                        continue
                    out += self.bios_tick(ctx, n, r)
                elif t[0] in self.prog.units and t[1] in self.prog.units[t[0]].insns:
                    out += self.call(ctx, n, r, t, fall, True) if i.op == "callf" else [(ctx, t, r.freeze())]
                else:
                    self.err(n, f"far {i.op} target {t} outside the program")
        return out

    def bios_tick(self, ctx, n, p):
        cls, lo, hi = BIOS_TICK
        self.fp.mem[(cls, lo, hi, "r")].add("rt_bios_int08")
        self.fp.mem[(cls, lo, hi, "w")].add("rt_bios_int08")
        self.fp.runtime["rt_bios_int08 (BIOS tick, IRET)"].add(site(n))
        if ctx[1] == "root":
            self.fp.exits["BIOS chain"].add(site(n))
        return self.iret(ctx, n, p)

    def ptr_seg(self, n, p, r):
        return p.regs[r]

    # -- memory --------------------------------------------------------------
    def access(self, n, p, seg, off, w, kind, val=None):
        size = w // 8
        seg, off = raw(seg), raw(off)
        if seg == ("e", "ss"):
            if off[0] != "sp":
                self.err(n, f"stack access at {off}")
                return X
            d = off[1]
            if kind == "w":
                self.local[self.ctx] = max(self.local[self.ctx], -d)
                self.wrote(self.ctx, range(d, d + size))
                for k in (d - 1, d, d + 1):     # a word slot a byte write meets: two bytes
                    got = p.slots.get(k)
                    if got and got[0] == 16 and w == 8 and k <= d <= k + 1:
                        p.slots[k], p.slots[k + 1] = (8, split(got[1], 0)), (8, split(got[1], 1))
                for k in range(d - 1, d + size):
                    if k in p.slots and k != d and k + p.slots[k][0] // 8 > d:
                        del p.slots[k]
                for k in list(p.slots):
                    if d < k < d + size:
                        del p.slots[k]
                p.slots[d] = (w, val)
                return None
            return self.stack_read(n, p, d, w)
        if seg[0] not in ("s", "sd"):
            self.err(n, f"segment {seg}")
            return X
        val = None if val is None else raw(val)
        key = fact_key(self.mem_op) if self.mem_op is not None and self.mem_op.width == w else None
        if kind == "w":
            st = self.mem_op
            for k in [k for k in p.slots if k >= FACT]:
                f = FACT_FORM[k]
                if k == key and val is not None and val[0] not in TAINT:
                    p.slots[k] = (w, val)   # a store through the fact's own form: its value
                    continue
                if st is not None and (st.seg, st.base, st.index) == f[:3] and \
                        (st.disp + st.width // 8 <= f[3] or f[3] + f[4] // 8 <= st.disp):
                    continue    # the same address registers, other bytes: no alias
                del p.slots[k]
        r = srng(off, 16)
        if r is None:
            self.err(n, f"offset {off} from interrupted state")
            return X
        lo, hi = r[0], r[1] + size - 1
        plo, phi = paras(seg)
        if lo < 0:      # a signed interval: the top of the segment and its bottom
            pieces = ((lo + 0x10000, 0xFFFF), (0, hi)) if hi >= 0 else ((lo + 0x10000, hi + 0x10000),)
        else:
            pieces = ((lo, min(hi, 0xFFFF)), (0, hi - 0x10000)) if hi > 0xFFFF else ((lo, hi),)
        pieces = tuple((16 * plo + a, 16 * phi + b) for a, b in pieces)    # from the class base
        out = None
        for cls in sorted(seg[1]):
            if cls == NULL_CLASS:   # a failed pointer's segment 0: not in the footprint
                if kind == "w":
                    self.err(n, "stores through segment 0 (a null far pointer)")
                else:
                    self.fp.runtime["read through segment 0, a null far pointer (I3 fails it)"].add(site(n))
                continue
            for a, b in pieces:
                if cls in self.extents and not (self.extents[cls][0] <= a and b <= self.extents[cls][1]):
                    self.fp.clamped[cls].add(site(n))
                    a, b = max(a, self.extents[cls][0]), min(b, self.extents[cls][1])
                if b >= a:
                    self.fp.mem[(cls, a, b, kind)].add(site(n))
            var = self.disp if self.disp is not None else lo
            a, b = min(x for x, _ in pieces), max(y for _, y in pieces)
            if kind == "w":
                if val is not None and val[0] in TAINT + ("sp",):
                    self.err(n, f"stores {val} (interrupted state) to {cls}")
                for (bc, bv, bw), (blo, bhi, last) in self.bounds.items():
                    if bc == cls and bv <= b and a <= last + bw // 8 - 1:
                        exact_ = bound_of({(bc, bv, bw): (blo, bhi, last)}, cls, a, b, w) is not None
                        got = rng(val, bw) if val is not None and exact_ else None
                        if got is not None and blo <= got[0] and got[1] <= bhi:
                            continue
                        if got is not None and (got[1] < blo or bhi < got[0]):
                            self.err(n, f"stores {val} into bounded {cls}:{bv:04X} ({blo:#x}..{bhi:#x})")
                        else:   # may meet it: I3 checks the variable after the store
                            self.fp.runtime[f"bounded {cls}:{bv:04X} store (I3 checks)"].add(site(n))
                continue
            got = ("l", cls, var, a, b) if w == 16 else ("l", cls, var)
            got_b = bound_of(self.bounds, cls, a, b, w)
            if got_b is not None:
                got = mk(*got_b, w)
            out = got if out is None else join(out, got)
        if key is not None and kind == "r":
            if key in p.slots and p.slots[key][0] == w:
                return p.slots[key][1]
            if self.cur_op in ("cmp", "test"):
                p.slots[key] = (w, out)
        return out

    def stack_read(self, n, p, d, w):
        """A stack word or byte: as written, a byte of a word, or a word of two bytes."""
        got = p.slots.get(d)
        if got is not None and got[0] == w:
            return got[1]
        if w == 8:
            for k, half in ((d, 0), (d - 1, 1)):
                got = p.slots.get(k)
                if got is not None and got[0] == 16:
                    return split(got[1], half)
        elif w == 16:
            lo, hi = p.slots.get(d), p.slots.get(d + 1)
            if lo is not None and hi is not None and lo[0] == hi[0] == 8:
                return combine(lo[1], hi[1])
        self.err(n, f"reads the stack at SP{d:+d} (interrupted or unwritten)")
        return X

    def seg_value(self, n, v):
        """A value written to a segment register."""
        v = raw(v)
        if v[0] in ("s", "sd", "e"):
            return v
        if v[0] == "c":
            return ("s", frozenset({abs_class(v[1])}))
        if v[0] == "l" and len(v) == 5:
            cls, a, b = v[1], v[3], v[4]
            if cls.startswith("["):
                self.err(n, f"segment register from a word of runtime class {cls}")
                return X
            if b - a > RUNTIME_SPAN:
                self.err(n, f"segment register from {cls}:{a:04X}..{b:04X} (index unbounded)")
                return X
            return ("s", frozenset({runtime_class(cls, a, b)}))
        self.err(n, f"segment register from {v}")
        return X

    # -- IR ------------------------------------------------------------------
    def rep_string(self, n, i, p):
        """REP MOVS / REP STOS as one access per operand over the bytes any count
        in CX's range moves (the lifted loop would run once per element), SI/DI
        advanced by it and CX 0; None: not one of these."""
        if i.rep != "rep" or i.op not in ("movs", "stos"):
            return None
        step = i.width // 8
        cx, df = rng(p.regs["cx"], 16), raw(p.flags.get("DF", X))
        if cx is None or df[0] != "c":
            self.err(n, f"rep {i.op} with CX {p.regs['cx']}, DF {df}")
            return []
        self.mem_op, self.disp, self.cur_op = None, None, i.op

        def span(r):
            got = srng(p.regs[r], 16)
            if got is None or got[0] < 0:
                self.err(n, f"rep {i.op} with {r.upper()} {p.regs[r]}")
                return None
            lo, hi = got
            lo, hi = (lo, hi + step * (cx[1] - 1)) if not df[1] else (lo - step * (cx[1] - 1), hi)
            return ("r", lo, hi) if 0 <= lo and hi + step - 1 <= 0xFFFF else ("r", 0, 0xFFFF - step + 1)

        def advance(r):
            lo, hi = srng(p.regs[r], 16)
            d = (step * cx[0], step * cx[1]) if not df[1] else (-step * cx[1], -step * cx[0])
            p.regs[r] = mk(lo + d[0], hi + d[1], 16)

        val = ("r", 0, mask(i.width))
        if cx[1] > 0:
            if i.op == "movs":
                src = span("si")
                if src is None:
                    return []
                val = self.access(n, p, p.regs[i.seg or "ds"], src, i.width, "r")
            else:
                val = raw(p.regs["ax"]) if i.width == 16 else split(p.regs["ax"], 0)
            dst = span("di")
            if dst is None:
                return []
            self.access(n, p, p.regs["es"], dst, i.width, "w", val)
            if i.op == "movs":
                advance("si")
            advance("di")
        p.regs["cx"] = ("c", 0)
        return [(p, ("fall",))]

    def ops(self, n, i, p, u):
        """Interpret the lifted ops of i on path p: [(path, exit)]."""
        done = self.rep_string(n, i, p)
        if done is not None:
            return done
        ops = lift(i)
        labels = {o.args[0]: k for k, o in enumerate(ops) if o.op == "label"}
        fix = {f - n[1] for f in u.module.fixups if n[1] <= f < n[1] + i.size}
        reloc = None
        if fix:
            if i.op == "mov" and isinstance(i.operands[0], Reg) and isinstance(i.operands[1], Imm) \
                    and fix == {i.size - 2}:
                reloc = self.para_class(n, i.operands[1].value)
            elif not (i.op in ("callf", "jmpf") and isinstance(i.operands[0], Far)):
                self.err(n, "relocated operand")
                return []
        self.zero = i.op in ("xor", "sub") and isinstance(i.operands[0], Reg) and \
            i.operands[0] == i.operands[1]
        if self.zero:
            reloc = "zero"
        self.same = i.op in ("or", "and") and isinstance(i.operands[0], Reg) and \
            i.operands[0] == i.operands[1]      # or/and r, r: r itself
        mems = [o for o in i.operands if isinstance(o, Mem)]
        self.disp = mems[0].disp if len(mems) == 1 and i.op not in ("les", "lds") else None
        self.mem_op = mems[0] if len(mems) == 1 and i.op not in ("les", "lds") and \
            mems[0].seg != "ss" else None
        self.cur_op = i.op
        out, pending = [], [(0, p)]
        guard = 0
        while pending:
            k, q = pending.pop()
            while k < len(ops):
                guard += 1
                if guard > 10000:
                    self.err(n, "op budget")
                    return out
                o = ops[k]
                k += 1
                op, a = o.op, o.args
                if op == "label":
                    continue
                if op == "goto":
                    k = labels[a[0]]
                    continue
                if op == "br":
                    c = raw(self.val(q, a[0], 1))
                    if c[0] == "c":
                        if c[1]:
                            k = labels[a[1]]
                        continue
                    if c[0] in TAINT:
                        self.err(n, "branch on interrupted state")
                    alt = _Path(q.regs, q.flags, q.slots)
                    alt.t = dict(q.t)
                    pending.append((labels[a[1]], alt))
                    continue
                if o.dst is not None:
                    q.t[o.dst.n] = self.value(n, q, o, reloc)
                    continue
                ex = self.effect(n, q, o, reloc)
                if ex is not None:
                    out.append((q, ex))
                    break
            else:
                out.append((q, ("fall",)))
        return out

    def val(self, q, a, w):
        if isinstance(a, T):
            return q.t[a.n]
        return ("c", a & mask(w))

    def get(self, q, r):
        if r in HALF:
            reg, k = HALF[r]
            return split(q.regs[reg], k)
        return q.regs[r]

    def put(self, n, q, r, v):
        if r in HALF:
            reg, k = HALF[r]
            v8 = split(v, 0) if v[0] not in ("h", "c", "r") else v
            if v[0] == "c":
                v8 = ("c", v[1] & 0xFF)
            parts = [split(q.regs[reg], 0), split(q.regs[reg], 1)]
            parts[k] = v8
            q.regs[reg] = combine(*parts)
        elif r in ("ds", "es", "ss") and v[0] == "in" and v[1] == r:
            # the callee's input restored (pop ds): the caller's own on return
            inner = v[2]
            q.regs[r] = v if inner[0] in TAINT + ("e",) else ("in", r, self.seg_value(n, inner))
        elif r in ("ds", "es", "ss"):
            q.regs[r] = self.seg_value(n, v)
        else:
            q.regs[r] = v
        full = HALF[r][0] if r in HALF else r
        for k in [k for k in q.slots if k >= FACT and full in FACT_REGS[k]]:
            del q.slots[k]

    def value(self, n, q, o, reloc):
        op, a, w = o.op, o.args, o.dst.w
        if op == "const":
            return ("c", a[0] & mask(w))
        if op == "get":
            return self.get(q, a[0])
        if op == "flag":
            v = q.flags.get(a[0])
            if v is None:
                self.err(n, f"reads {a[0]} before the handler sets it")
                return X
            return v
        if op == "load":
            return self.access(n, q, self.val(q, a[0], 16), self.val(q, a[1], 16), w, "r")
        if op == "in":
            self.port(n, self.val(q, a[0], 16), "r")
            return ("r", 0, mask(w))
        if op == "cond":
            return self.cond(n, q, a[0])
        vals = [self.val(q, x, w if op not in ("zext", "sext", "trunc", "shl", "shr", "sar", "rol",
                                                 "ror", "eq", "ne", "ltu", "lts", "select")
                         else (x.w if isinstance(x, T) else w)) for x in a]
        vals = [raw(v) for v in vals]
        if op == "select":
            c = vals[0]
            if c[0] == "c":
                return vals[1] if c[1] else vals[2]
            if c[0] in TAINT:
                self.err(n, "select on interrupted state")
            return join(vals[1], vals[2])
        if op in ("xor", "sub") and reloc == "zero":
            return ("c", 0)     # xor/sub r, r: the result does not depend on r
        if op in ("zext", "trunc"):
            src = vals[0]
            if src[0] in ("e", "h", "p"):
                if op == "zext" or src[0] == "h":
                    self.err(n, f"{op} of interrupted {src}")
                    return X
            if op == "trunc" and w == 8 and src[0] in ("e", "p"):
                self.err(n, f"truncates interrupted {src}")
                return X
            if op == "trunc" and w == 8 and src[0] == "b":
                return src[1]           # the low byte as it is
        for v in vals:
            if v[0] in TAINT:
                if op in ("zext", "trunc", "sext") or v[0] != "sp":
                    self.err(n, f"{op} reads interrupted {v}")
                    return X
        if any(v[0] == "sp" for v in vals):
            if op in ("add", "sub") and len(vals) == 2 and vals[0][0] == "sp" and vals[1][0] == "c":
                d = vals[1][1] if op == "add" else -vals[1][1]
                d = (d + 0x8000) % 0x10000 - 0x8000
                return ("sp", vals[0][1] + d)
            self.err(n, f"{op} on SP")
            return X
        v0 = raw(vals[0])
        if op in ("add", "sub") and w == 16 and v0[0] == "l" and len(v0) == 5 and \
                not v0[1].startswith("[") and v0[4] - v0[3] <= RUNTIME_SPAN and raw(vals[1])[0] in ("c", "r"):
            # a loaded word stepped by paragraphs (a segment walk): as its runtime class;
            # as a number it stays any word
            vals = [("s", frozenset({runtime_class(v0[1], v0[3], v0[4])})), vals[1]]
        if op in ("add", "sub") and w == 16 and raw(vals[0])[0] in ("s", "sd") and \
                raw(vals[1])[0] in ("c", "r"):
            vals = [raw(v) for v in vals]
            (plo, phi), (c, d) = paras(vals[0]), rng(vals[1], 16)
            lo, hi = (plo + c, phi + d) if op == "add" else (plo - d, phi - c)
            hi = min(hi, 0xFFFF)    # a megabyte above the base covers every paragraph
            if lo >= 0:
                return seg_of(vals[0][1], lo, hi)     # a paragraph step from the class base
            return ("r", 0, 0xFFFF)     # below the base (cmp against a constant): a number
        for v in vals:
            if rng(v, 16) is None:
                self.err(n, f"{op} reads {v}")
                return X
        if op in ("or", "and") and self.same:
            return vals[0]      # or/and r, r leaves r as it is (a signed -1..N too)
        return arith(op, w, vals, [x.w if isinstance(x, T) else w for x in a])

    def cond(self, n, q, cc):
        need = CC_READS[cc]
        f = {}
        for name in need:
            v = q.flags.get(name)
            if v is None:
                self.err(n, f"reads {name} before the handler sets it")
                return X
            f[name] = v
        if any(v[0] != "c" for v in f.values()):
            return ("r", 0, 1)
        g = {k: v[1] for k, v in f.items()}
        r = {"o": lambda: g["OF"], "b": lambda: g["CF"], "e": lambda: g["ZF"],
             "be": lambda: g["CF"] | g["ZF"], "s": lambda: g["SF"], "p": lambda: g["PF"],
             "l": lambda: g["SF"] ^ g["OF"], "le": lambda: g["ZF"] | (g["SF"] ^ g["OF"])}
        base = cc[1:] if cc.startswith("n") and cc not in ("ne",) and cc[1:] in r else cc
        if cc == "ne":
            return ("c", 1 - g["ZF"])
        if cc in ("ae", "a", "ge", "g"):
            inv = {"ae": "b", "a": "be", "ge": "l", "g": "le"}[cc]
            return ("c", 1 - r[inv]())
        if cc in r:
            return ("c", r[cc]())
        return ("c", 1 - r[base]())

    def port(self, n, v, kind):
        v = raw(v)
        if v[0] != "c" or v[1] not in PORTS:
            self.err(n, f"port {v} not in PORTS")
            return
        self.fp.ports[(v[1], kind)].add(site(n))

    def effect(self, n, q, o, reloc=None):
        op, a = o.op, o.args
        if op == "put":
            if reloc not in (None, "zero") and isinstance(a[1], int):
                self.put(n, q, a[0], reloc)
                return None
            self.put(n, q, a[0], self.val(q, a[1], 8 if a[0] in HALF else 16))
            return None
        if op == "setflag":
            v = raw(self.val(q, a[1], 1))
            if v[0] in TAINT:
                self.err(n, f"sets {a[0]} from interrupted state")
                v = ("r", 0, 1)
            if a[0] == "IF":
                self.fp.ifs[v[1] if v[0] == "c" else "?"].add(site(n))
            q.flags[a[0]] = v
            return None
        if op == "store":
            w = a[3]
            self.access(n, q, self.val(q, a[0], 16), self.val(q, a[1], 16), w, "w",
                        self.val(q, a[2], w))
            return None
        if op == "out":
            port = self.val(q, a[0], 16)
            self.port(n, port, "w")
            self.fp.runtime["rt_out8" if port == ("c", 0x388) or port == ("c", 0x389)
                            else "rt_out8 (PIC: no effect)"].add(site(n))
            v = raw(self.val(q, a[1], 8))
            if v[0] in TAINT:
                self.err(n, f"writes interrupted {v} to a port")
            return None
        if op == "flags":
            self.flags(n, q, a)
            return None
        if op == "bcd":
            self.err(n, "BCD in the handler")
            return None
        return (op,) + tuple(raw(self.val(q, x, 16)) if isinstance(x, T) else x for x in a)

    def flags(self, n, q, a):
        kind, w = a[0], a[1]
        vals = [raw(self.val(q, x, w if not isinstance(x, T) else x.w)) for x in a[2:]]
        if self.zero:
            vals = [("c", 0)] * 3
        elif any(v[0] in TAINT for v in vals):
            self.err(n, f"{kind} flags from interrupted state {[v for v in vals if v[0] in TAINT][0]}")
        elif any(v[0] == "sp" for v in vals):     # e.g. sub sp,n: flags of the interrupted SP
            for f in set(FLAG_KINDS[kind][0]) | set(FLAG_KINDS[kind][1]):
                q.flags.pop(f, None)
            return
        d, undef = FLAG_KINDS[kind]
        unknown = ("r", 0, 1)
        for f in set(d) | set(undef):
            q.flags[f] = unknown
        x, y, r = (rng(v, w) if v[0] not in TAINT + ("sp",) else None for v in vals[:3])
        if r is None:
            return
        top = 1 << (w - 1)
        if r[0] == r[1]:
            q.flags["ZF"] = ("c", int(r[0] == 0)) if "ZF" in d else q.flags["ZF"]
            if "SF" in d:
                q.flags["SF"] = ("c", int(bool(r[0] & top)))
        elif r[0] > 0 and "ZF" in d:
            q.flags["ZF"] = ("c", 0)
        if kind == "logic":
            q.flags["CF"] = q.flags["OF"] = ("c", 0)
        elif kind == "sub" and x is not None and y is not None:
            if x[1] < y[0]:
                q.flags["CF"] = ("c", 1)
            elif x[0] >= y[1]:
                q.flags["CF"] = ("c", 0)
            if x[0] == x[1] and y[0] == y[1]:
                a_, b_, r_ = x[0], y[0], (x[0] - y[0]) & mask(w)
                q.flags["OF"] = ("c", int(bool((a_ ^ b_) & (a_ ^ r_) & top)))
        elif kind == "add" and x is not None and y is not None:
            if x[1] + y[1] <= mask(w):
                q.flags["CF"] = ("c", 0)
            elif x[0] + y[0] > mask(w):
                q.flags["CF"] = ("c", 1)


def arith(op, w, vals, widths):
    """Constants exactly, ranges conservatively."""
    rs = [rng(v, ww) for v, ww in zip(vals, widths)]
    m = mask(w)
    if all(r[0] == r[1] for r in rs):
        xs = [r[0] for r in rs]
        try:
            return ("c", exact(op, w, xs, widths) & m)
        except KeyError:
            return ("r", 0, m)
    ss = [srng(v, ww) for v, ww in zip(vals, widths)]   # signed where a value is
    (a, b), rest = rs[0], rs[1:]
    (sa, sb), srest = ss[0], ss[1:]
    if op in ("zext",):
        return mk(a, b, w)
    if op == "sext":
        got = signed(sa, sb, widths[0])
        return mk(*got, w) if got else ("r", 0, m)
    if op == "trunc":
        if sa < 0 and sb < 1 << (w - 1):
            return mk(sa, sb, w)
        return mk(a, b, w) if b <= m else ("r", 0, m)
    if op == "add":
        c, d = srest[0]
        return mk(sa + c, sb + d, w)
    if op == "sub":
        c, d = srest[0]
        return mk(sa - d, sb - c, w)
    if op == "shl" and rest[0][0] == rest[0][1]:
        return mk(sa << rest[0][0], sb << rest[0][0], w)
    if op == "shr" and rest[0][0] == rest[0][1]:
        return mk(a >> rest[0][0], b >> rest[0][0], w)
    if op in ("srem", "urem") and rest[0][0] == rest[0][1] and rest[0][0]:
        k = abs(sgn(rest[0][0], widths[1])) if op == "srem" else rest[0][0]
        return mk(-(k - 1) if op == "srem" else 0, k - 1, w)    # |rem| < |divisor|
    if op == "and":
        return mk(0, min(b, rest[0][1]), w)
    if op in ("or", "xor"):
        hi = max(b, rest[0][1])
        return mk(0, (1 << hi.bit_length()) - 1, w)
    if op == "mul":
        c, d = srest[0]
        ps = (sa * c, sa * d, sb * c, sb * d)
        return mk(min(ps), max(ps), w)
    if op in ("eq", "ne"):
        c, d = rest[0]
        if b < c or d < a:
            return ("c", int(op == "ne"))
        return ("r", 0, 1)
    if op == "ltu":
        c, d = rest[0]
        if b < c:
            return ("c", 1)
        if a >= d:
            return ("c", 0)
        return ("r", 0, 1)
    return ("r", 0, m)


def sgn(v, w):
    return v - (1 << w) if v >> (w - 1) & 1 else v


def exact(op, w, xs, widths):
    a = xs[0]
    b = xs[1] if len(xs) > 1 else 0
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "and":
        return a & b
    if op == "or":
        return a | b
    if op == "xor":
        return a ^ b
    if op == "not":
        return ~a
    if op == "neg":
        return -a
    if op == "mul":
        return a * b
    if op == "shl":
        return a << b if b < w else 0
    if op == "shr":
        return a >> b if b < w else 0
    if op == "sar":
        return sgn(a, widths[0]) >> min(b, w)
    if op == "zext":
        return a
    if op == "sext":
        return sgn(a, widths[0])
    if op == "trunc":
        return a
    if op == "eq":
        return int(a == b)
    if op == "ne":
        return int(a != b)
    if op == "ltu":
        return int(a < b)
    if op == "lts":
        return int(sgn(a, widths[0]) < sgn(b, widths[1]))
    if op in ("udiv", "urem") and b:
        return a // b if op == "udiv" else a % b
    raise KeyError(op)


# -- main code -----------------------------------------------------------------
GPR = ("ax", "bx", "cx", "dx", "si", "di", "bp")
SEGS = ("es", "ds", "ss")
STACK_CAP = 48
READS_DST = {"cmp", "test", "push", "call", "callf", "jmp", "jmpf"}
WRITES_AX = {"mul", "imul", "div", "idiv", "cbw", "lahf", "xlat", "in", "lods", "aaa", "aas",
             "daa", "das", "aam", "aad"}


@dataclass(frozen=True)
class MState:
    regs: tuple          # GPR values: int (16-bit) | ('m', depth) | ('b', lo, hi) | None
    segs: tuple          # es, ds, ss: runtime paragraph | None
    depth: int | None    # words pushed since the function entry
    tail: tuple          # known top of the stack (last = top)
    iflag: int | None
    shadow: bool
    cs_mem: tuple = ()   # ((module, first, last), value) of code-segment words stored on this path


def mjoin(a: MState | None, b: MState) -> MState:
    if a is None:
        return b
    if a == b:
        return a
    regs = tuple(x if x == y else None for x, y in zip(a.regs, b.regs))
    segs = tuple(x if x == y else None for x, y in zip(a.segs, b.segs))
    depth = a.depth if a.depth == b.depth else None
    n = min(len(a.tail), len(b.tail)) if depth is not None else 0
    tail = tuple(x if x == y else None for x, y in zip(a.tail[len(a.tail) - n:], b.tail[len(b.tail) - n:]))
    return MState(regs, segs, depth, tail, a.iflag if a.iflag == b.iflag else None,
                  a.shadow and b.shadow, tuple(x for x in a.cs_mem if x in b.cs_mem))


class Main:
    """Segment registers, IF and memory slots of main code (module docstring)."""

    def __init__(self, prog, handlers):
        self.prog = prog
        self.handlers = set(handlers)
        self.fixups = {n: set(u.module.fixups) for n, u in prog.units.items()}
        self.slots: dict[int, int | None] = {}
        self.stores: dict[int, int | None] = {}
        self.state: dict = {}
        self.rets_to = defaultdict(set)
        for r, sites in prog.ret_of.items():
            for s in sites:
                self.rets_to[s].add(r)
        self.rows = sorted(e for e in prog.dispatch if e in prog.succ and e not in self.handlers)
        self.smc = {}
        for r in image.rows("self-modifying.csv"):
            for w in r["writers"].replace("/", " ").split():
                self.smc[(r["module"], int(w[1:], 16))] = (r["module"], int(r["first"], 16),
                                                          int(r["last"], 16))

    # -- one instruction ---------------------------------------------------------
    def site_after(self, n):
        u = self.prog.units[n[0]]
        i = u.insns[n[1]]
        return (n[0], n[1] + i.size + (2 if n[1] in u.manager_calls else 0))

    @staticmethod
    def terminates(i, st: MState) -> bool:
        """INT 21h AH=4Ch (exit) does not return."""
        ax = st.regs[0]
        hi = ax >> 8 if isinstance(ax, int) else ax[2] if isinstance(ax, tuple) and ax[0] == "b" else None
        return i.op == "int" and i.operands[0].value == 0x21 and hi == 0x4C

    def cs_key(self, n, m: Mem):
        """A code-segment word: (module, first, last) module offsets; an indexed writer
        its self-modifying.csv region, else '*'."""
        u = self.prog.units[n[0]]
        if m.base or m.index:
            return self.smc.get(n, "*")
        off = u.off_of(u.cs[n[1]], m.disp)
        return (n[0], off, off + 1)

    def cs_write(self, n):
        """The code-segment word n writes through a CS override, else None."""
        i = self.prog.node_insn(n)
        dst = i.operands[0] if i.operands else None
        if isinstance(dst, Mem) and dst.seg == "cs" and i.op not in READS_DST:
            return self.cs_key(n, dst)
        return None

    @staticmethod
    def kill(cs_mem, keys):
        """cs_mem without the words keys overlap ('*': all)."""
        if "*" in keys:
            return ()
        return tuple(x for x in cs_mem if not any(
            m == x[0][0] and lo <= x[0][2] and x[0][1] <= hi for m, lo, hi in keys))

    def mem_lin(self, st: MState, m: Mem):
        seg = st.segs[SEGS.index(m.seg)] if m.seg in SEGS else None
        if not isinstance(seg, int) or m.base or m.index:
            return None
        return seg * 16 + m.disp

    def value(self, n, i, st: MState, o):
        if isinstance(o, Reg):
            if o.name in GPR:
                v = st.regs[GPR.index(o.name)]
                return v if not isinstance(v, tuple) else None
            if o.name in SEGS:
                return st.segs[SEGS.index(o.name)]
            if o.name == "cs":
                return LOADSEG + self.prog.units[n[0]].cs[n[1]]
            return None
        if isinstance(o, Imm):
            v = o.value
            if o.width == 16 and n[1] + i.size - 2 in self.fixups[n[0]]:
                v = (v + LOADSEG) & 0xFFFF
            return v
        if isinstance(o, Mem):
            if o.seg == "cs" and not (o.base or o.index) and o.width == 16:
                saved = dict(st.cs_mem)
                if self.cs_key(n, o) in saved:
                    return saved[self.cs_key(n, o)]
            lin = self.mem_lin(st, o)
            return self.slots.get(lin) if lin is not None and o.width == 16 else None
        return None

    def transfer(self, n, st: MState, record: bool = False) -> MState:
        """The state after n (calls and returns: before their transfer)."""
        u = self.prog.units[n[0]]
        i = u.insns[n[1]]
        op, ops = i.op, i.operands
        regs, segs = list(st.regs), list(st.segs)
        depth, tail = st.depth, list(st.tail)
        iflag, shadow = st.iflag, False
        cs_mem = st.cs_mem

        def setr(r, v):
            nonlocal depth, tail
            if r in GPR:
                regs[GPR.index(r)] = v
            elif r in SEGS:
                segs[SEGS.index(r)] = v
            elif r == "sp":
                depth, tail = None, []
            elif r in HALF:
                full, k = HALF[r]
                old = regs[GPR.index(full)]
                b = ([old & 0xFF, old >> 8] if isinstance(old, int) else
                     list(old[1:]) if isinstance(old, tuple) and old[0] == "b" else [None, None])
                b[k] = v if isinstance(v, int) else None
                regs[GPR.index(full)] = (b[0] | b[1] << 8 if None not in b else
                                         None if b == [None, None] else ("b", *b))

        def push(v):
            nonlocal depth
            tail.append(v)
            if len(tail) > STACK_CAP:
                del tail[0]
            depth = None if depth is None else depth + 1

        def pop():
            nonlocal depth
            depth = None if depth is None else depth - 1
            return tail.pop() if tail else None

        dst = ops[0] if ops else None
        key = self.cs_write(n)
        if key is not None:
            cs_mem = self.kill(cs_mem, {key})
            if op == "mov" and key != "*" and not (dst.base or dst.index) and dst.width == 16:
                v = self.value(n, i, st, ops[1])
                if v is not None:
                    cs_mem = tuple(sorted(cs_mem + ((key, v),)))
        if op == "mov" and isinstance(dst, Reg):
            src = ops[1]
            if dst.name == "sp" and src == Reg("bp") and isinstance(regs[6], tuple):
                d = regs[6][1]
                if depth is not None and d <= depth:
                    tail = tail[:max(len(tail) - (depth - d), 0)]
                    depth = d
                else:
                    depth, tail = None, []
            elif dst.name == "bp" and src == Reg("sp"):
                regs[6] = ("m", depth) if depth is not None else None
            elif isinstance(src, Reg) and src.name in GPR and dst.name in GPR:
                setr(dst.name, st.regs[GPR.index(src.name)])
            else:
                setr(dst.name, self.value(n, i, st, src))
        elif op == "mov" and isinstance(dst, Mem):
            lin = self.mem_lin(st, dst)
            if record and lin is not None and dst.width == 16:
                v = self.value(n, i, st, ops[1])
                v = v if isinstance(v, int) else None
                self.stores[lin] = v if self.stores.get(lin, v) == v else None
        elif op in ("xor", "sub") and isinstance(dst, Reg) and ops[1] == dst:
            setr(dst.name, 0)
        elif op == "push":
            push(self.value(n, i, st, dst) if dst != Reg("sp") else None)
        elif op == "pop":
            v = pop()
            if isinstance(dst, Reg):
                setr(dst.name, v)
        elif op == "pushf":
            push(None)
        elif op == "popf":
            pop()
            iflag = None
        elif op in ("les", "lds"):
            setr(dst.name, None)
            lin = self.mem_lin(st, ops[1])
            setr("es" if op == "les" else "ds", self.slots.get(lin + 2) if lin is not None else None)
        elif op == "xchg" and all(isinstance(o, Reg) and o.name in GPR for o in ops):
            a, b = (GPR.index(o.name) for o in ops)
            regs[a], regs[b] = st.regs[b], st.regs[a]
        elif op in ("add", "sub") and dst == Reg("sp") and isinstance(ops[1], Imm):
            v = sgn(ops[1].value & 0xFFFF, 16)
            words = v // 2 if op == "add" else -v // 2
            if v % 2 or abs(words) > 0x400:
                depth, tail = None, []
            elif words > 0:
                for _ in range(words):
                    pop()
            else:
                for _ in range(-words):
                    push(None)
        elif op == "cli":
            iflag = 0
        elif op == "sti":
            iflag, shadow = 1, True
        elif op == "int":
            for r in ("ax", "bx", "cx", "dx", "si", "di", "es"):
                setr(r, None)
        elif op in ("call", "callf", "ret", "retf", "iret", "jmp", "jmpf", "jcc", "jcxz", "cmp",
                    "test", "out", "nop", "clc", "stc", "cmc", "cld", "std", "hlt"):
            pass
        else:
            if op in WRITES_AX:
                setr("ax", None)
            if op in ("mul", "imul", "div", "idiv", "cwd") or op in ("mul", "imul") and i.width == 16:
                setr("dx", None)
            if op in ("movs", "cmps", "stos", "lods", "scas"):
                setr("si", None)
                setr("di", None)
                if i.rep:
                    setr("cx", None)
            if op in ("loop", "loope", "loopne"):
                setr("cx", None)
            if op == "lea" or op in ("in", "xlat", "lahf", "cbw", "cwd"):
                pass
            for o in (ops if op == "xchg" else ops[:1]):
                if isinstance(o, Reg):
                    setr(o.name, None)
        return MState(tuple(regs), tuple(segs), depth, tuple(tail), iflag, shadow, cs_mem)

    def call_entry(self, n, new: MState) -> MState:
        """The callee's entry state (return address pushed: depth 0 below it)."""
        i = self.prog.node_insn(n)
        push = (LOADSEG + self.prog.units[n[0]].cs[n[1]], None) if i.op == "callf" else (None,)
        return MState(new.regs, new.segs, 0, (new.tail + push)[-STACK_CAP:], new.iflag, False,
                      new.cs_mem)

    def ret_words(self, rets) -> int | None:
        def imm(i):     # RET imm; a jump-return (jump-returns.csv) pops no more
            return i.operands[0].value // 2 if i.op in ("ret", "retf") and i.operands else 0

        words = {imm(self.prog.node_insn(r)) for r in rets}
        return words.pop() if len(words) == 1 else None

    def after(self, caller: MState, callee: MState | None, words: int | None, ds) -> MState:
        """State at a return site: the caller's stack, BP and SS, DS from the callees'
        summaries (ds_after), the callee's other registers."""
        depth, tail = caller.depth, list(caller.tail)
        if words is None:
            depth, tail = None, []
        for _ in range(words or 0):
            depth = None if depth is None else depth - 1
            if tail:
                tail.pop()
        if callee is None:
            regs = tuple(caller.regs[k] if g == "bp" else None for k, g in enumerate(GPR))
            segs = (None, ds, caller.segs[2])
            iflag = None
        else:
            regs = tuple(caller.regs[k] if g == "bp" else callee.regs[k] for k, g in enumerate(GPR))
            segs = (callee.segs[0], ds, caller.segs[2])
            iflag = callee.iflag
        return MState(regs, segs, depth, tuple(tail), iflag, False,
                      () if callee is None else callee.cs_mem)

    # -- whole program -------------------------------------------------------------
    def targets(self, n):
        """Successors; an unresolved transfer reaches its traced targets (indirect.csv;
        others are not reached: monitored), None for a self-modified walk."""
        out = []
        for t in self.prog.succ.get(n, []):
            if t == "unknown":
                sw, tr = self.prog.indirect.get(n, ([], []))
                found = [x for x in sw + tr if x in self.prog.succ and x not in self.handlers]
                out += found or [None]
            elif t == "smc":
                out.append(None)
            elif isinstance(t, tuple):
                out.append(t)
        return out

    def run(self):
        """States per context (function entry, entry DS, entry SS): a call enters its
        targets' contexts; a return site joins the caller's stack and BP with the
        callee context's state at its returns. Iterated until the memory slots (word
        stores of constant addresses) are stable."""
        prog = self.prog
        self.declared = {(r["module"], int(r["offset"], 16)) for r in image.rows("irq-ds.csv")}
        root = (M.ROOT, M.entry())
        psp = LOADSEG - 0x10
        start = MState((None,) * len(GPR), (psp, psp, None), 0, (), 1, False)
        for _ in range(8):
            before = dict(self.slots)
            self.state, self.stores = {}, {}
            self.rets, self.callers = {}, defaultdict(set)
            first = ((root, psp, None), root)
            self.state[first] = start
            work, queued = [first], {first}
            while work:
                key = work.pop()
                queued.discard(key)
                for k, s in self.step(key[0], key[1], self.state[key]):
                    new = mjoin(self.state.get(k), s) if s is not None else self.state[k]
                    if new != self.state.get(k) or s is None:
                        self.state[k] = new
                        if k not in queued:
                            queued.add(k)
                            work.append(k)
            self.slots = self.stores
            if self.slots == before:
                break
        else:
            raise Violation("main-code slots did not converge")
        called = {c[0] for c in self.rets} | {c[0] for c in self.callers}
        for d in self.declared - called:
            raise Violation(f"irq-ds.csv: {site(d)} is no called entry")
        self.at = defaultdict(list)
        for (ctx, n), st in self.state.items():
            self.at[n].append(st)
        return self

    def states(self, n) -> list:
        return self.at.get(n, [])

    def step(self, ctx, n, st: MState):
        """(key, state) successors; state None re-runs a key (a callee's returns grew)."""
        prog = self.prog
        i = prog.node_insn(n)
        new = self.transfer(n, st, record=True)
        out = []
        if self.terminates(i, st):
            return out
        if i.op in ("call", "callf"):
            entry = self.call_entry(n, new)
            site = self.site_after(n)
            words = self.ret_words(self.rets_to.get(site, ()))
            for t in self.targets(n):
                if t is None:   # never traced: MS C keeps DS (I3 checks the accesses)
                    if site in prog.succ:
                        out.append(((ctx, site), self.after(st, None, words, st.segs[1])))
                    continue
                if t in self.handlers:
                    continue
                c = (t, entry.segs[1], entry.segs[2])
                out.append(((c, t), entry))
                self.callers[c].add((ctx, n))
                r = self.rets.get(c)
                if r is not None and site in prog.succ:
                    ds = st.segs[1] if t in self.declared else r.segs[1]
                    out.append(((ctx, site), self.after(st, r, words, ds)))
            return out
        if prog.is_ret(n):
            r = mjoin(self.rets.get(ctx), st)
            if r != self.rets.get(ctx):
                self.rets[ctx] = r
                out += [((cc, c), None) for cc, c in self.callers[ctx]]
            return out
        for t in self.targets(n):
            if t is not None and t not in self.handlers:
                out.append(((ctx, t), new))
        return out


# -- classification --------------------------------------------------------------
MEMLINE = re.compile(r"\((?:[^()]*,)?a[0-3](?:[,)])")
FLOWLINE = re.compile(r"^\S+:|^\s*(?:b[a-z]{2}|bra|bsr|jmp|jsr|db[a-z]{1,2}|rt[sde]|trap\w*|ifd|endif)\b")
STACKLINE = re.compile(r"\((?:[^()]*,)?a2(?:[,)])")    # the guest stack (SS base)


def hold_span(lines: list[str]) -> int | None:
    """Lines of a sync access's lowering the emitter brackets with rt_irq_hold:
    all of them when straight-line with more than one memory line; with control
    flow, the straight-line prefix to its last memory line when it holds more
    than one and every memory line after it touches only the guest stack (a far
    call's pointer loads, then its return frame); else None (atomic as it is, or
    not holdable)."""
    mem = [k for k, x in enumerate(lines) if MEMLINE.search(x) and not x.strip().startswith("lea")]
    flow = [k for k, x in enumerate(lines) if FLOWLINE.search(x)]
    if len(mem) <= 1:
        return None
    if not flow:
        return len(lines)
    head = [k for k in mem if k < flow[0]]
    if len(head) > 1 and all(STACKLINE.search(lines[k]) and not MEMLINE.search(
            STACKLINE.sub("", lines[k])) for k in mem if k > head[-1]):
        return head[-1] + 1
    return None


def accesses(i):
    """(memory operand or None for the stack/string side, 'r'|'w'|'rw') of i."""
    from .lower import mem_dests
    out = []
    dests = mem_dests(i)
    for o in i.operands:
        if isinstance(o, Mem) and i.op != "lea":
            if o in dests:
                kind = "w" if i.op in ("mov", "pop") else "rw"
            else:
                kind = "r"
            out.append((o, kind))
    return out


RANK = ("sync", "monitored", "disjoint")


def merge(fps) -> Footprint:
    """One footprint for the handler set (I3 checks every handler against it)."""
    out = Footprint()
    for fp in fps:
        for name in ("mem", "ports", "ifs", "hooks", "exits", "runtime", "clamped", "pointers"):
            for k, v in getattr(fp, name).items():
                getattr(out, name)[k] |= v
        out.depth = max(out.depth, fp.depth)
        out.nodes |= fp.nodes
        out.errors += fp.errors
    return out


class Proof:
    def __init__(self, prog, compute_rows=None):
        self.prog = prog
        self.entries = handler_entries()
        self.handlers = [Handler(prog, e) for e in sorted(self.entries)]
        self.handler = self.handlers[0]
        self.fps = {h.entry: h.run() for h in self.handlers}
        self.fp = merge(self.fps.values())
        self.main = Main(prog, self.entries).run()
        self.compute_rows = prog.compute_rows if compute_rows is None else compute_rows
        self.errors = list(self.fp.errors)
        self.classify()

    def lin_class(self):
        """Footprint class -> runtime paragraph (None: located at run time)."""
        out = {"BDA": 0x40}
        for (cls, *_rest) in self.fp.mem:
            if re.fullmatch(r"[0-9A-F]{4}", cls):
                out[cls] = int(cls, 16) + LOADSEG
            elif cls.startswith("abs:"):
                out[cls] = int(cls[4:], 16)
        return out

    def classify(self):
        paras = self.lin_class()
        self.paras = paras
        written, accessed = [], []
        for (cls, lo, hi, kind) in self.fp.mem:
            para = paras.get(cls)
            if para is None:
                continue
            span = (para * 16 + lo, para * 16 + hi, cls, lo)
            accessed.append(span)
            if kind == "w":
                written.append(span)
        self.written, self.accessed = written, accessed
        self.counts = Counter()
        self.sync = set()
        declared = declared_sync()
        prog = self.prog
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                states = self.main.states(n)
                if n in self.fp.nodes and not states:
                    continue
                acc = accesses(i)
                port = i.op in ("in", "out")
                if n in declared and (not states or not acc and not port):
                    # monitored (unreached, or a string instruction's implicit access):
                    # a declared row makes it sync for its span
                    for cls, lo, hi, kind in declared.pop(n):
                        para = paras.get(cls)
                        w_hit = para is not None and self.meets(para * 16 + lo, para * 16 + hi, written)
                        self.sync.add((n, cls, lo, hi, kind, bool(w_hit)))
                    self.counts["sync (declared, monitored)"] += 1
                    continue
                if not acc and not port:
                    continue
                if not states:
                    self.counts["monitored (not reached)"] += 1
                    continue
                live = [st for st in states if not (st.iflag == 0 or st.shadow)]
                if not live:
                    self.counts["masked (IF = 0)"] += 1
                    continue
                found = {self.classify_insn(n, i, st, acc) for st in live}
                if n in declared:
                    if "monitored" not in found:
                        self.errors.append(f"irq-sync.csv: {site(n)} is no monitored access ({found})")
                    for cls, lo, hi, kind in declared.pop(n):
                        para = paras.get(cls)
                        w_hit = para is not None and self.meets(para * 16 + lo, para * 16 + hi, written)
                        self.sync.add((n, cls, lo, hi, kind, bool(w_hit)))
                    found = {"sync"}
                self.counts[min(found, key=RANK.index)] += 1
        for n in declared:
            self.errors.append(f"irq-sync.csv: {site(n)} is not reached")
        self.check_atomic()
        self.check_rows()
        self.check_bounds()

    def meets(self, lo, hi, spans):
        return [s for s in spans if s[0] <= hi and lo <= s[1]]

    def classify_insn(self, n, i, st, acc):
        out = "disjoint"
        if i.op in ("in", "out"):
            p = i.operands[1 if i.op == "in" else 0]
            port = p.value if isinstance(p, Imm) else st.regs[GPR.index("dx")] if p == Reg("dx") else None
            if not isinstance(port, int):
                out = "monitored"
            elif port in PORTS:
                self.sync.add((n, "port", port, port, "w" if i.op == "out" else "r", False))
                return "sync"
        for m, kind in acc:
            seg = st.segs[SEGS.index(m.seg)] if m.seg in SEGS else LOADSEG + self.prog.units[n[0]].cs[n[1]]
            if seg is None:
                out = "monitored"
                continue
            size = m.width // 8 if m.width != 32 else 4
            if m.base or m.index:
                # indexed: sync when its displacement lies in a footprint span; the
                # row covers the spans it may reach (I3 checks the address)
                at = seg * 16 + m.disp
                hits = [s for s in self.accessed if s[0] <= at <= s[1]]
                if not hits:
                    out = "monitored" if out != "sync" else out
                    continue
                w_hit = [s for s in self.written if s[0] <= at <= s[1]]
                if ("r" in kind and w_hit) or "w" in kind:
                    for s in hits if "w" in kind else w_hit:
                        self.sync.add((n, s[2], s[3], s[3] + s[1] - s[0], kind, bool(w_hit)))
                    return "sync"
                continue
            lo, hi = seg * 16 + m.disp, seg * 16 + m.disp + size - 1
            w_hit = self.meets(lo, hi, self.written)
            a_hit = self.meets(lo, hi, self.accessed)
            if ("r" in kind and w_hit) or ("w" in kind and a_hit):
                cls = (w_hit or a_hit)[0]
                self.sync.add((n, cls[2], lo - (cls[0] - cls[3]), hi - (cls[0] - cls[3]), kind,
                                  bool(w_hit)))
                return "sync"
        return out

    def check_atomic(self):
        """A sync access to a handler-written byte lowers to one memory-touching 68k
        line, or to code whose memory lines but stack pushes the emitter brackets with
        rt_irq_hold (held, hold_span: the tick waits across them, as an x86
        instruction is never interrupted: LES of a far pointer, ADC to memory, a far
        call through memory); any other lowering fails."""
        from .lower import lower
        prog = self.prog
        self.held = set()
        for n, cls, lo, hi, kind, written in self.sync:
            if not written or cls == "port":
                continue
            i = prog.node_insn(n)
            try:
                lines = lower(i, prog.ctx(n[0], n[1], Counter())).out
            except Exception as e:  # noqa: BLE001 - reported, not hidden
                self.errors.append(f"{site(n)}: lowering for the atomicity check failed: {e}")
                continue
            mem = [x for x in lines if MEMLINE.search(x) and not x.strip().startswith("lea")]
            if hold_span(lines) is not None:
                self.held.add(n)
            elif len(mem) != 1:
                self.errors.append(f"{site(n)}: {i} meets handler-written {cls}:{lo:04X}..{hi:04X} "
                                   f"in {len(mem)} 68k memory accesses ({'; '.join(m.strip() for m in mem)})")

    def check_bounds(self):
        """Main-code writes of a bounded G variable (irq-bounds.csv): an immediate within
        the bound, or the restore of a frame copy taken in the same module
        (mov r,[v]; mov [bp+d],r ... mov r,[bp+d]; mov [v],r). Other classes are
        SPAZ-private; I3 monitors every handler access."""
        from .lower import mem_dests
        g = self.paras.get("G")
        rows = {var: (w, lo, hi) for (cls, var, w), (lo, hi, _) in bounds().items() if cls == "G"}
        if not rows or g is None:
            return
        prog = self.prog
        prev = {}
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                prev[(mod, off + i.size)] = (mod, off)

        def is_g(n, m):
            return m.seg in SEGS and any(st.segs[SEGS.index(m.seg)] == g for st in self.main.states(n))

        def plain(m, var):
            return isinstance(m, Mem) and not (m.base or m.index) and m.disp == var

        def frame(m):
            return isinstance(m, Mem) and m.seg == "ss" and m.base == "bp" and not m.index

        copies = set()
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                p = prev.get(n)
                if i.op == "mov" and frame(i.operands[0]) and isinstance(i.operands[1], Reg) and p:
                    j = prog.node_insn(p)
                    src = j.operands[1] if j.op == "mov" else None
                    if isinstance(src, Mem) and j.operands[0] == i.operands[1] and src.disp in rows \
                            and plain(src, src.disp) and is_g(p, src):
                        copies.add((mod, j.operands[1].disp, i.operands[0].disp, i.operands[1].name))
        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                for m in mem_dests(i):
                    var = next((v for v in rows if isinstance(m, Mem) and not (m.base or m.index)
                                and v <= m.disp + m.width // 8 - 1 and m.disp <= v + rows[v][0] // 8 - 1), None)
                    if var is None or not is_g(n, m):
                        continue
                    w, lo, hi = rows[var]
                    src = i.operands[1] if len(i.operands) > 1 else None
                    ok = i.op == "mov" and m.disp == var and m.width == w
                    if ok and isinstance(src, Imm):
                        ok = lo <= src.value <= hi
                    elif ok and isinstance(src, Reg) and n in prev:
                        j = prog.node_insn(prev[n])
                        ok = (j.op == "mov" and j.operands[0] == src and frame(j.operands[1])
                              and (mod, var, j.operands[1].disp, src.name) in copies)
                    else:
                        ok = False
                    if not ok:
                        self.errors.append(f"{site(n)}: {i} writes G:{var:04X} outside its irq-bounds.csv "
                                           f"bound {lo:#x}..{hi:#x} (immediate or frame-copy restore)")

    def check_rows(self):
        """No compute row's range or proved body (callees included) holds a sync access;
        a row with exits: its proved body (the exit stretches stay generated)."""
        syncs = {n for n, *_ in self.sync}
        bodies = getattr(self.prog, "compute_bodies", {})
        for row in sorted(self.compute_rows):
            resume = self.prog.hle.get(row, ((None, None), None))[0]
            mod, first = row
            u = self.prog.units[mod]
            end = self.prog.compute_end.get(row)
            last = max(o for o in u.insns if o < resume[1]) if resume[1] else first
            hi = max(last, end or 0)
            nodes = {(mod, off) for off in u.insns if first <= off <= hi}
            if row in bodies and row in getattr(self.prog, "compute_exits", {}):
                # exits and re-entries: the stretches between them run generated
                nodes = set(bodies[row].body)
            elif row in bodies:
                nodes |= bodies[row].body
            for n in sorted(nodes & syncs):
                self.errors.append(f"compute row {site(row)} contains sync access {site(n)}")

    def sync_points(self) -> dict:
        """I8 sync points, (module, offset) -> kind: where tests and the reference
        deliver posted interrupts, before the instruction. `access`: a sync access;
        `int`: a software interrupt (a service); `clear`: CLI, POPF or IRET (IF may
        go 1→0: a tick due before it is taken there, as without polling, not after the
        masked accesses that follow); `if`: the instruction after an IF 0→1, i.e.
        after POPF or after STI's shadow (a RET there: its return sites).
        Accesses and interrupts that only run with IF = 0 never deliver; reached
        or not, every other one counts (I3 checks what the analysis missed)."""
        prog = self.prog
        out = {n: "access" for n, *_ in self.sync}

        def live(n):
            states = self.main.states(n)
            return not states or any(not (st.iflag == 0 or st.shadow) for st in states)

        def after(n):
            ss = [s for s in prog.succ.get(n, ()) if isinstance(s, tuple) and s in prog.succ]
            if prog.is_ret(n):
                ss += sorted(prog.ret_of.get(n, ()))
            return ss

        for mod, u in prog.units.items():
            for off, i in u.insns.items():
                n = (mod, off)
                if (n in self.fp.nodes and not self.main.states(n)) or n not in prog.succ:
                    continue
                if i.op == "int" and live(n):
                    out.setdefault(n, "int")
                if i.op in ("cli", "popf", "iret") and live(n):
                    out.setdefault(n, "clear")
                if i.op in ("sti", "popf"):
                    states = self.main.states(n)
                    if states and all(st.iflag == 1 for st in states):
                        continue
                    for m in after(n) if i.op == "popf" else [x for s in after(n) for x in after(s)]:
                        out[m] = "if"   # checked in every build: wins over the other kinds
        return out

    def raise_errors(self):
        if self.errors:
            raise Violation("IRQ0 footprint:\n" + "\n".join(sorted(set(self.errors))[:60]))

    def rows(self) -> list[str]:
        out = []
        fp = self.fp

        def merged(cls, kind):
            spans = sorted((lo, hi, sites) for (c, lo, hi, k), sites in fp.mem.items()
                           if c == cls and k == kind)
            acc = []
            for lo, hi, sites in spans:
                if acc and lo <= acc[-1][1] + 1:
                    acc[-1] = (acc[-1][0], max(acc[-1][1], hi), acc[-1][2] | sites)
                else:
                    acc.append((lo, hi, set(sites)))
            return acc

        for cls in sorted({c for c, *_ in fp.mem}):
            for kind in ("r", "w"):
                for lo, hi, sites in merged(cls, kind):
                    out.append(f"mem,{cls},0x{lo:04x},0x{hi:04x},{kind},{' '.join(sorted(sites))}")
        for (port, kind), sites in sorted(fp.ports.items()):
            out.append(f"port,{PORTS[port].split(' ')[0]},0x{port:03x},0x{port:03x},{kind},{' '.join(sorted(sites))}")
        out.append(f"stack,K,-0x{fp.depth:x},-0x1,rw,{' '.join(site(e) for e in sorted(self.entries))}")
        for v, sites in sorted(fp.ifs.items(), key=str):
            out.append(f"if,,{v},{v},w,{' '.join(sorted(sites))}")
        for name, sites in sorted(fp.hooks.items()):
            out.append(f"hook,{name},,,,{' '.join(sorted(sites))}")
        for name, sites in sorted(fp.runtime.items()):
            out.append(f"runtime,{name},,,,{' '.join(sorted(sites))}")
        for name, sites in sorted(fp.exits.items()):
            out.append(f"exit,{name},,,,{' '.join(sorted(sites))}")
        for cls, sites in sorted(fp.clamped.items()):
            lo, hi = self.handler.extents[cls]
            out.append(f"extent,{cls},0x{lo:04x},0x{hi:04x},rw,{' '.join(sorted(sites))}")
        for n, cls, lo, hi, kind, written in sorted(self.sync):
            out.append(f"sync,{cls},0x{lo:04x},0x{hi:04x},{kind},{site(n)}")
        return out

    def summary(self) -> str:
        c = self.counts
        return ("irq footprint: handler " + f"{len(self.fp.nodes)} instructions, stack {self.fp.depth} bytes; "
                + "main accesses " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))


def prove(prog) -> Proof:
    p = Proof(prog)
    p.raise_errors()
    return p
