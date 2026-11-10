"""Recursive descent over a scope of modules with the translator's own decoder.

Secret Weapons of Luftwaffe's descent, adapted to WC2's VROOMM overlays and drivers
(docs/vroomm.md, docs/drivers.md) with the unit and resolution rules of tools/sweep.py
(docs/upstream.md). `build()` covers image.SCOPE (68020 generation) unless given another
scope; the decoder and IR checks use image.X86_SCOPE.

Code ranges (tools/wc2_model.py `code_ranges`): the root (WC2.EXE+0..16B80h), each of
the 124 overlays (its code at its image offsets, relocated at load segment 0) and the
loaded entry of each driver. A root instruction runs with the highest root code
segment at or below it; an overlay with the paragraph of its image offset (its run-time
buffer segment is dynamic, port-plan P4.2), so IP 0 is its first byte; a driver with
CS 0 and IP 0 at its entry's first byte.

Seeds (all from annotations/ and the images, no traces): the MZ entry, every stub entry
(the overlay's entry k), `entries.csv` (the sweep's start-up table, far pointers, the
functions after a RETF, the driver entry tables, the interrupt handlers), `runtime.csv`,
and the switch and traced targets of `indirect.csv`. Follows fall-through and direct
near and far transfers; stops at returns and indirect jumps, and after a near call to a
routine of `noreturn.csv`. A far target in a stub segment at an entry (20h + 5k) is the
overlay's entry k (`stub_calls` keeps the stub cell it goes through, emit.py); in a root code segment, the root; anything else (no literal far
transfer in a driver; `jmp far FFFF:0000` in the root) is not followed. A start is
reached with one CS; a seed without one takes the CS its runtime.csv row names, else
its unit's (Unit.segment). Self-modified regions are not decoded statically (D16): flow into
one is recorded as an entry of the region, and the successors of each of its listed
forms are followed. Overlaps, flow outside its code range, undecodable bytes, two CS
values for one start and far targets at a stub offset that is no entry raise CfgError
(all of them, at the end).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import image
from .decode import DecodeError, Far, Insn, Rel, decode

M = image.M


class CfgError(Exception):
    pass


@dataclass
class Unit:
    name: str
    module: M.Module
    ranges: list                                                # M.CodeRange of the module
    root_segs: list[int]
    insns: dict[int, Insn] = field(default_factory=dict)
    cs: dict[int, int] = field(default_factory=dict)          # offset -> CS link paragraph
    manager_calls: dict[int, str] = field(default_factory=dict)  # SWOTL's PLINK calls: none
    smc_entries: dict[int, str] = field(default_factory=dict)  # region entry -> reason
    far_targets: dict[int, tuple[str, int]] = field(default_factory=dict)  # site -> (module, offset)
    stub_calls: dict[int, tuple[int, int]] = field(default_factory=dict)  # site -> (stub, entry k)
    seeds: dict[int, str] = field(default_factory=dict)

    @property
    def bases(self) -> list[int]:
        return sorted(set(self.root_segs if self.name == M.ROOT else []) |
                      {r.base for r in self.ranges if r.base is not None})

    def range_at(self, off: int):
        return next((r for r in self.ranges if r.has(off)), None)

    def segment(self, off: int) -> int:
        """CS of an entry seeded without one (module docstring)."""
        r = self.range_at(off)
        if r is None:
            raise CfgError(f"{self.name}+{off:05X}: outside every code range")
        if r.base is not None:
            return r.base
        return max(b for b in self.root_segs if b * 16 <= off)

    def ip_of(self, off: int) -> int:
        seg = self.cs[off] if off in self.cs else self.segment(off)
        return self.module.to_link(off) - seg * 16

    def off_of(self, seg: int, ip: int) -> int:
        return self.module.from_link(seg * 16 + ip)


def stub_entries() -> list[tuple[str, int, str, int]]:
    return [(M.ROOT, o.code + e, f"stub {o.stub >> 4:04X} entry {k}", o.code >> 4)
            for o in M.overlays() for k, e in enumerate(o.entries)]


def seeds(mods: dict[str, M.Module], scope=None) -> list[tuple[str, int, str]]:
    """Seeds without a CS (the dispatch rows of emit.py; build() adds the stub entries)."""
    scope = image.SCOPE if scope is None else scope
    out = [(M.ROOT, M.entry(), "MZ entry")]
    for r in image.rows("entries.csv"):
        out.append((r["module"], int(r["offset"], 16), r["reason"]))
    for r in image.rows("runtime.csv"):
        out.append((r["module"], int(r["offset"], 16), f"runtime {r['name']}"))
    for r in image.rows("indirect.csv"):
        site = f"{r['module']}+{r['offset']}"
        for col in ("switch_targets", "traced_targets"):
            for t in r[col].split():
                if t == "(isr)":
                    continue
                mod, off = t.split("+")
                out.append((mod, int(off, 16), f"{col[:-8]} {site}"))
    return [s for s in out if s[0] in scope]


class _Descent:
    def __init__(self, mods, scope):
        self.mods = mods
        ovls = M.overlays()
        ranges = M.code_ranges(ovls=ovls)
        segs = M.root_code_segs(M.image_file())
        self.units = {n: Unit(n, mods[n], [r for r in ranges if r.module == n], segs) for n in scope}
        self.stubs = {o.stub >> 4: o for o in ovls}
        self.root_segs = set(segs)
        self.smc = image.smc_regions()
        self.forms = image.smc_forms()
        self.noreturn = {(r["module"], int(r["offset"], 16)) for r in image.rows("noreturn.csv")}
        # runtime.csv rows name their CS (seg_ip): a routine below a later root code
        # segment (WC2.EXE+0FA58, 0F12:0938, a near target) runs with it
        self.known_cs: dict[tuple[str, int], int] = {}
        for r in image.rows("runtime.csv"):
            if r["module"] not in self.units or not r.get("seg_ip"):
                continue
            seg, ip = (int(x, 16) for x in r["seg_ip"].split(":"))
            off = int(r["offset"], 16)
            if seg * 16 + ip != mods[r["module"]].to_link(off):
                self.errors.append(f"{r['module']}+{off:05X}: runtime.csv seg_ip {r['seg_ip']} is not its offset")
            self.known_cs[(r["module"], off)] = seg
        self.work: list[tuple[str, int, str, int | None]] = []
        self.body: dict[str, dict[int, int]] = {n: {} for n in scope}  # byte -> start
        self.errors: list[str] = []

    def seed(self, mod, off, why, cs=None):
        if mod == M.ROOT and M.STUBS[0] <= off < M.STUBS[1]:
            # a traced transfer to a stub entry runs the overlay's entry (its far jump)
            o = self.stubs[max(k for k in self.stubs if k * 16 <= off)]
            k, rem = divmod(off - o.stub - 0x20, 5)
            if rem or not 0 <= k < len(o.entries):
                self.errors.append(f"{mod}+{off:05X}: seed in stub {o.stub >> 4:04X} is no entry ({why})")
                return
            off, cs, why = o.code + o.entries[k], o.code >> 4, f"stub {o.stub >> 4:04X} entry {k} ({why})"
        if mod in self.units:
            self.work.append((mod, off, why, cs))
            self.units[mod].seeds.setdefault(off, why)

    def region(self, mod, off):
        return next(((lo, hi) for lo, hi in self.smc.get(mod, ()) if lo <= off <= hi), None)

    def far(self, mod, at, f: Far):
        o = self.stubs.get(f.seg)
        if o is not None:
            k, rem = divmod(f.off - 0x20, 5)
            if rem or not 0 <= k < len(o.entries):
                raise CfgError(f"{mod}+{at:05X}: far target {f} in stub {f.seg:04X} is no entry")
            target, cs = (M.ROOT, o.code + o.entries[k]), o.code >> 4
            self.units[mod].stub_calls[at] = (o.stub, k)
        elif f.seg in self.root_segs and f.seg * 16 + f.off < M.ROOT_CODE_END:
            target, cs = (M.ROOT, f.seg * 16 + f.off), f.seg
        else:
            return
        self.units[mod].far_targets[at] = target
        self.seed(*target, f"far {mod}+{at:05X}", cs)

    def run(self):
        while self.work:
            try:
                self.flow(*self.work.pop())
            except CfgError as e:
                self.errors.append(str(e))

    def smc_entry(self, mod, off, why, cs):
        """Flow into a self-modified region: follow every listed form's successors."""
        u = self.units[mod]
        u.smc_entries.setdefault(off, why)
        lo, hi = self.region(mod, off)
        if off != lo:
            return
        for form in self.forms.get((mod, lo, hi), ()):
            if "ww" in form:
                continue
            seg = u.segment(off) if cs is None else cs
            n = decode(bytes.fromhex(form), u.module.to_link(off) - seg * 16)
            if lo + n.size != hi + 1:
                raise CfgError(f"{mod}+{off:05X}: form {form} does not fill its region")
            if n.op not in ("ret", "retf", "iret", "hlt", "jmp"):
                self.seed(mod, lo + n.size, f"after form {form} at {mod}+{off:05X}", seg)
            if n.operands and isinstance(n.operands[0], Rel):
                self.seed(mod, u.off_of(seg, n.operands[0].target), f"form {form} at {mod}+{off:05X}", seg)

    def flow(self, mod, off, why, cs):
        u = self.units[mod]
        data = u.module.data
        r = u.range_at(off)
        if r is None:
            raise CfgError(f"{mod}+{off:05X}: flow outside code ({why})")
        while True:
            if not r.has(off):
                raise CfgError(f"{mod}+{off:05X}: flow past the end of {r.name} ({why})")
            if off in u.insns:
                if cs is not None and u.cs[off] != cs:
                    raise CfgError(f"{mod}+{off:05X}: reached with CS {cs:04X} and {u.cs[off]:04X} ({why})")
                return
            if self.region(mod, off):
                self.smc_entry(mod, off, why, cs)
                return
            if off in self.body[mod]:
                raise CfgError(f"{mod}+{off:05X}: start inside {mod}+{self.body[mod][off]:05X} ({why})")
            if cs is None:
                cs = self.known_cs.get((mod, off))
            seg = cs = u.segment(off) if cs is None else cs
            ip = u.module.to_link(off) - seg * 16
            if not 0 <= ip < 0x10000:
                raise CfgError(f"{mod}+{off:05X}: outside CS {seg:04X} ({why})")
            try:
                n = decode(data, ip, off)
            except DecodeError as e:
                raise CfgError(f"{mod}+{off:05X}: {e} ({why})") from None
            if not r.has(off + n.size - 1):
                raise CfgError(f"{mod}+{off:05X}: instruction past the end of {r.name} ({why})")
            for k in range(off + 1, off + n.size):
                if k in u.insns or k in self.body[mod]:
                    raise CfgError(f"{mod}+{off:05X}: overlaps {mod}+{k:05X} ({why})")
                self.body[mod][k] = off
            u.insns[off], u.cs[off] = n, seg
            why = f"{mod}+{off:05X}"
            if n.op in ("ret", "retf", "iret", "hlt"):
                return
            if n.op in ("callf", "jmpf") and isinstance(n.operands[0], Far):
                self.far(mod, off, n.operands[0])
                if n.op == "jmpf":
                    return
            elif n.operands and isinstance(n.operands[0], Rel):
                t = u.off_of(seg, n.operands[0].target)
                if not r.has(t):
                    raise CfgError(f"{mod}+{off:05X}: near target {mod}+{t:05X} outside {r.name}")
                self.seed(mod, t, why, seg)
                if n.op == "jmp" or (n.op == "call" and (mod, t) in self.noreturn):
                    return
            elif n.op in ("jmp", "jmpf"):
                return
            off += n.size


def build(mods: dict[str, M.Module] | None = None, scope=None) -> dict[str, Unit]:
    scope = image.SCOPE if scope is None else scope
    if not scope:
        return {}  # WC2: no module generated before P4
    mods = mods or image.load()
    d = _Descent(mods, scope)
    cs, _ = M.mz(M.REF / M.ROOT)[2]
    d.seed(M.ROOT, M.entry(), "MZ entry", cs)
    for s in stub_entries():
        d.seed(*s)
    for s in seeds(mods, scope):
        d.seed(*s)
    d.run()
    if d.errors:
        raise CfgError("\n".join(sorted(set(d.errors))))
    return d.units
