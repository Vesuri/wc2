#!/usr/bin/env python3
"""Run the generated program with the runtime on Unicorn 68020 (gate 5):
build/host/wc2.elf from the WC2.EXE entry to a reference milestone, data files
read from the installed game directory (ref/WING2, read-only). Copied from
X-Wing's tests/host_run.py (commit 49b792b; it adapted Secret Weapons of the
Luftwaffe's) and adapted: WC2's reference runs and replay ports, VROOMM
dispatch by the stubs' word 10h, the IRQ monitor only with a footprint.

Checked against the host reference run of that milestone
(tmp/pc-runs/host-<milestone>, `tools/reference.py --host`: hardware interrupts
at the translator's poll points, the PIT and VGA status reads recorded):
- service log: every software INT the guest raises, in order, with the
  registers at entry and at return (the tracer's svc/svc_ret events);
- at the milestone label: guest registers and guest RAM (COMPARE ranges);
  dead stack is masked: bytes in the DEAD_STACK window below SS:SP at a
  service call, or at a hardware interrupt the handler footprint's stack depth
  and frame below it, that the guest did not write afterwards (DOSBox-X's own
  code, the interrupt frame's FLAGS word and the reference's IRQ0 handler on the
  interrupted stack leave other values there),
  and the FLAGS images of annotations/flags.csv PUSHFs until rewritten;
- every machine byte outside COMPARE (and the IRQ0 handler's private stack)
  that generated code read holds the reference value.
The BIOS ROM (F0000h..FFFFFh) is the reference machine's, a local fixture input from
the m0 snapshot at the WC2.EXE entry (reference_rom): SUPERTM.DRV's noise fill
(+74D2) samples bit 0 of ROM bytes at a pseudo-random F000:SI.
The keyboard intercept (WC2's INT 15h handler, from the runtime's BIOS INT 09h
model: rt_key_hook) runs as often with each AX as the reference's BIOS stub
called it (interrupts.csv, from F000:E98F); an interrupt the reference took
inside it (the runtime holds them there) fails.
Every read of port 3DAh answers the reference's next recorded value, and every
PIT latch the next two recorded port 40h reads (low, high), each read in the
same service-event interval (trace/replay-ports.csv), and all are used.
DOSBox-X restarts a REP at the end of its cycle slice, so an interrupt can land
inside one: a diagnostic image with REP hooks (rep_replay.py) replays the
reference's slices (trace/rep.csv) at each REP poll point, and all are used.
With --amiga DIR, the same checks run on the A1200 model's capture
(amiga/milestone.gdb.in: regs.txt, state.bin, ram.bin, dac.bin), masked by
this host run's dead-stack set, and the shown frame (plane0-7.bin, bytes per
row in regs.txt, colours.bin = LoadRGB32 table) decodes to the reference
framebuffer and DAC. --label prints a milestone's label for the fixture.
Exit 1 on any difference, a runtime stop or the time limit.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import gzip
import csv
import struct
import sys
import threading
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import uc as U  # noqa: E402
import rep_replay  # noqa: E402
import irq_monitor  # noqa: E402
from translator import emit, image  # noqa: E402

REPO = image.REPO
ELF = REPO / "build/host/wc2.elf"
MEM = 0x01000000          # flat map: code, data, stack, guest RAM
STACK_TOP = 0x00FF0000
BLOCK = 0x00400000        # src/platform/host/host.c HOST_BLOCK
GUEST_BYTES = 0x110000
TOP = BLOCK + GUEST_BYTES - 1   # rt_guest: guest linear L at TOP - L (reversed)
STATE = TOP + 1           # state block (translator/lower.py STATE_EQU)
G_IRQ = TOP + 9
G_DS = TOP + 1            # lower.py STATE_EQU: G_DS(a6)
G_ES = TOP + 5
# Key names of the reference key script (tracer KeyByName): scan << 8 | ASCII
# as the BIOS INT 09h handler stores them.
KEYS = {"enter": 0x1C0D, "esc": 0x011B, "space": 0x3920, "tab": 0x0F09, "backspace": 0x0E08,
        "up": 0x4800, "down": 0x5000, "left": 0x4B00, "right": 0x4D00,
        **{f"f{k}": (0x3A + k) << 8 for k in range(1, 11)},
        **{c: s << 8 | ord(c) for c, s in zip("qwertyuiopasdfghjklzxcvbnm",
                                             list(range(0x10, 0x1A)) + list(range(0x1E, 0x27))
                                             + list(range(0x2C, 0x33)))},
        **{str(k): (k + 1) << 8 | ord(str(k)) for k in range(1, 10)}, "0": 0x0B30,
        "minus": 0x0C2D, "equals": 0x0D3D, "insert": 0x5200, "delete": 0x5300}
GREY = {KEYS[k] for k in ("up", "down", "left", "right", "insert", "delete")}  # E0-prefixed (DOSBox KBD_up..)
# Modifier bits belong to scripted input, above the base BIOS key word.
KEY_MODIFIERS = {"shift": 1 << 16, "ctrl": 1 << 17, "alt": 1 << 18}


def key_code(name: str) -> int:
    parts = name.split("+")
    modifiers = 0
    for part in parts[:-1]:
        bit = KEY_MODIFIERS.get(part, 0)
        if not bit or modifiers & bit:
            raise ValueError(f"invalid key chord: {name}")
        modifiers |= bit
    if parts[-1] not in KEYS:
        raise ValueError(f"unknown key: {name}")
    return modifiers | KEYS[parts[-1]]


def key_events(key: int) -> tuple[int, ...]:
    if key & ~0x7ffff:
        raise ValueError(f"invalid scripted key: {key:x}")
    base = key & 0xffff
    scan = base >> 8
    modifiers = tuple(scan for bit, scan in ((1 << 16, 0x2a),
                      (1 << 17, 0x1d), (1 << 18, 0x38)) if key & bit)
    body = (0xe0, scan, 0xe0, scan | 0x80) if base in GREY else (scan, scan | 0x80)
    return modifiers + body + tuple(scan | 0x80 for scan in reversed(modifiers))


def key_bytes(key: int, repeats: int = 0) -> tuple[int, ...]:
    """The scan bytes DOSBox-X sends for a key held long enough for `repeats`
    typematic repeats: the makes, the key's own make again per repeat (E0 and
    the scan for a grey key; modifiers do not repeat), then the breaks."""
    ev = key_events(key)
    make, brk = ev[:len(ev) // 2], ev[len(ev) // 2:]
    body = make[-2:] if (key & 0xffff) in GREY else make[-1:]
    return make + body * repeats + brk


def typematic(trace: Path, keys: list) -> list[int]:
    """Per scripted key, the typematic repeats the reference sent: its IRQ 1s
    from key_down to key_up beyond the makes (events.csv); the breaks must be the
    IRQ 1s after the key_up, before the next key_down, and nothing else may differ."""
    rows, cur = [], None
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] == "key_down":
                cur = [0, 0, False]
                rows.append(cur)
            elif r["kind"] == "key_up":
                cur[2] = True
            elif r["kind"] == "irq" and r["detail"].split()[0] == "09":
                if cur is None:
                    raise ValueError("reference IRQ 1 before any key")
                cur[1 if cur[2] else 0] += 1
    codes = [k for _, k in keys if isinstance(k, int)]
    if len(codes) != len(rows):
        raise ValueError(f"{len(codes)} scripted keys, {len(rows)} in the reference")
    out = []
    for code, (held, after, _) in zip(codes, rows):
        ev = key_events(code)
        body = 2 if (code & 0xffff) in GREY else 1
        extra = held - len(ev) // 2
        if extra < 0 or extra % body or after != len(ev) // 2:
            raise ValueError(f"key {code:x}: {held} IRQ 1s held, {after} after: not makes, "
                             f"repeats and breaks")
        out.append(extra // body)
    return out


KEY_HOLD = 600_000  # tracer: x86 instructions from key down to key up
# Compared guest RAM: the DOS arena from the environment MCB to the top of
# conventional memory; below it are IVT/BIOS/DOS internals the runtime models
# only through services, above it video and BIOS ROM.
COMPARE = [(0x07C90, 0xA0000)]
# Chained mode 13h: guest A0000h+a is DOSBox-X vram[((a & ~3) << 2) | (a & 3)]
# (tools/snap_png.py); the whole 64 KiB window is compared with the DAC.
FRAME = (0xA0000, 0xB0000)
# The IRQ0 handler's private stack (runtime.h RT_IRQ_SS:RT_IRQ_SP down, I4): runtime
# state, no machine bytes; its depth is the footprint's (tests/irq_monitor.py checks).
IRQ_STACK = (0xB8000 - 0x200, 0xB8000)
REGS = ("ax", "cx", "dx", "bx", "sp", "bp", "si", "di")
DEAD_STACK = 0x60

TABLE = REPO / "reference/milestones.csv"
RUNS = REPO / "tmp/pc-runs"
ROM = (0xF0000, 0x100000)
POLLS = REPO / "build/gen/poll-points.csv"


def elf_load(path: Path, function_extents: dict | None = None):
    d = path.read_bytes()
    entry, phoff, shoff = struct.unpack_from(">III", d, 0x18)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from(">HHHHH", d, 0x2A)
    segs = []
    for k in range(phnum):
        typ, off, vaddr, _, filesz, memsz = struct.unpack_from(">IIIIII", d, phoff + k * phentsize)
        if typ == 1:
            segs.append((vaddr, d[off:off + filesz], memsz))
    secs = [struct.unpack_from(">IIIIIIIIII", d, shoff + k * shentsize) for k in range(shnum)]
    syms = {}
    for s in secs:
        if s[1] != 2:  # SHT_SYMTAB
            continue
        strtab = secs[s[6]]
        for k in range(s[5] // 16):
            name, value, size, info, _, shndx = struct.unpack_from(">IIIBBH", d, s[4] + k * 16)
            if name and shndx:
                a = strtab[4] + name
                symbol = d[a:d.index(b"\0", a)].decode()
                syms[symbol] = value
                if function_extents is not None and info & 15 == 2 and size:
                    function_extents[symbol] = (value, value + size)
    return entry, segs, syms


def call_returns(segs, function_extents: dict, target: int) -> set[int]:
    """The return addresses of the jsr/bsr calls to `target` in the image's
    functions (Capstone's 68020 decode of each function's extent)."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN | capstone.CS_MODE_M68K_020)
    out = set()
    for lo, hi in function_extents.values():
        code = next((data[lo - v:hi - v] for v, data, _ in segs if v <= lo and hi <= v + len(data)), None)
        for i in md.disasm(code or b"", lo):
            if i.mnemonic.split(".")[0] in ("jsr", "bsr") and i.op_str.split(".")[0] == f"${target:x}":
                out.add(i.address + i.size)
    return out


def events(trace: Path):
    if (trace / "events.csv.gz").exists():
        return gzip.open(trace / "events.csv.gz", "rt")
    return (trace / "events.csv").open()


def reference_services(trace: Path) -> list[tuple[str, dict]]:
    out = []
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                vec, *kv = r["detail"].split()
                regs = {k: int(v, 16) for k, v in (x.split("=") for x in kv)}
                regs["vector"] = int(vec, 16)
                regs["site"] = (r["module"], int(r["offset"], 16))
                out.append((r["kind"], regs))
    return out


IDLE = "rt_idle_poll"   # DOS's idle wait: the reference's irq rows at module "-" (rt_key_wait)


def idle_stacks(trace: Path) -> dict:
    """The reference's SS, SP and six stack words at each idle-wait interrupt,
    by its index among the irq rows (dosbox-x-wc2-idle-irq.patch)."""
    out, k = {}, 0
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] != "irq":
                continue
            if r["module"] == "-":
                p = r["detail"].split()
                assert len(p) == 10 and p[3].startswith("stack="), r
                ss, sp = (int(x, 16) for x in p[3][6:].split(":"))
                out[k] = (ss, sp, tuple(int(x, 16) for x in p[4:]))
            k += 1
    return out


def reference_inputs(trace: Path, *, exact_releases: bool = False) -> tuple[list, list]:
    """The reference's hardware interrupts as (service events so far, poll
    point label, its executions since the last service event, vector), and
    the service-event count at each key release. Exact releases additionally
    retain recorded ineligible visits to the next trigger in that interval.
    The default preserves the existing diagnostic Amiga replay input format."""
    irqs, releases, n = [], [], 0
    with events(trace) as f:
        for r in csv.DictReader(f):
            if r["kind"] in ("svc", "svc_ret"):
                n += 1
            elif r["kind"] == "irq":
                vec, svc, hits = r["detail"].split()[:3]
                assert int(svc[4:]) == n, r
                lab = IDLE if r["module"] == "-" else emit.label(r["module"], int(r["offset"], 16))
                irqs.append((n, lab, int(hits[5:]), int(vec, 16)))
            elif r["kind"] == "key_up":
                fields = r["detail"].split()
                release = n
                if exact_releases and len(fields) > 1:
                    if len(fields) != 2 or not fields[1].startswith("skip="):
                        raise ValueError(f"invalid key release: {r}")
                    skipped = int(fields[1][5:])
                    if skipped < 0:
                        raise ValueError(f"negative key release visits: {r}")
                    release = (n, skipped)
                releases.append(release)
    return irqs, releases


class KeyRelease:
    """Count trigger visits while held; IRQ replay remains independent.

    The recorder resets this count on key-down and each service event. For
    a snapshot, the release instruction itself is ineligible; for another
    key it is eligible. The recorded skip count already includes that order.
    Old captures retain their service-only behavior.
    """

    def __init__(self, release):
        self.service, self.skip = (release, None) if isinstance(release, int) else release
        self.interval, self.visits = None, 0

    def ready(self, service: int, target: bool) -> bool:
        if service != self.interval:
            self.interval, self.visits = service, 0
        if target:
            self.visits += 1
        if service != self.service:
            return service > self.service
        return self.skip is None or (target and self.visits > self.skip)


def fnv(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


SABOTAGE = {
    "read": "first byte of each guest file read flipped",
    "ax": "AX of the tenth service result off by one",
    "psp": "one PSP byte changed at the guest entry",
    "dac": "one DAC gun off at each DAC change",
    "vram": "stores to video memory not marked (rt_vram_mark returns at once)",
    "far": "every dispatch row near-only (rt_dispatch_far must stop, R14e)",
    "retrace": "one VGA status read answered with bit 3 flipped",
    "irq-stack": "rt_irq_async runs the IRQ0 handler on the interrupted stack (private SS:SP not set, I4)",
    "irq-state": "rt_irq_async restores no state block after the handler (I4)",
    "irq-sentinel": "rt_irq_async expects another sentinel CS:IP than its frame holds (I4)",
    "irq-offset": "rt_irq_async starts the private stack at 7FFEh, not IRQ_SP (the relocated compare)",
    "keyon": "rt_out8 counts no AdLib key-on edge (its addq dropped)",
    "overlay": "the overlay stub table zeroed (machine.c overlay_row finds no overlay CS)",
    "pit": "the sixth PIT latch answered one above the fifth: a full period gone, STRAX's delay loop ends 5 latches early",
    "irq-footprint": "the monitor's footprint without the INT 08h handler's tick-count write row (I3)",
    "irq-sync": "the monitor's footprint without sync rows (I3)",
    "irq-bounds": "the monitor's irq-bounds.csv bounds one lower at their top (I3)",
    "sb-block": "the second DSP block's length one byte long (the block oracle)",
    "sb-irq": "an IRQ 7 posted with the first replayed interrupt, no DSP block playing",
    "dsp-status": "the model's 22Eh status reporting no data after the DSP reset",
    "key-hook": "rt_key_hook returns at once: the BIOS INT 09h model calls no INT 15h intercept",
    "hook-cf": "the intercept's return read with CF clear: the BIOS model takes no key",
    "int16-zf": "the first INT 16h AH=01h that finds a key reports none (ZF set)",
    "idle": "rt_idle returns at once: DOS's console wait takes no interrupt",
    "idle-stack": "the console wait's SP two bytes lower at its first rt_idle (RT_IDLE_DEPTH)",
    "ems-fast": "the EMS guard's table never refreshed (ems.c refresh returns at once)",
    "ems-cache": "the EMS guard caches never emptied (ems.c rt_ems_cache_clear returns at once)",
    "ems-cache-irq": "an interrupt's handler leaves its EMS guard caches (ems.c rt_ems_cache_restore returns at once)",
    "ems-irq": "an interrupt's handler leaves the EMS frame pages as it found them (ems.c rt_ems_irq_leave returns at once)",
    "ems-restore": "a restore row's POP DS copies nothing anywhere (ems.c rt_ems_restore_c returns at once)",
    "stall": "the code at R_0FA8F (a poll point m1 reaches) replaced by a 68k bra.s *: the guest "
             "spins with no service or interrupt (the run's watchdog, at 20 s)",
}
# Plants that are caught only by their own check (the first problem's text): a
# milestone without speech has no DSP block, one without keys no keyboard
# interrupt, so they are left out there. hook-cf's key never reaches the BIOS
# buffer: the first INT 16h that finds it in the reference finds none (the run
# stops at that service's return).
SABOTAGE_CATCH = {"sb-block": "SB blocks", "sb-irq": "IRQ 7 without a DSP block",
                  "dsp-status": "the model's 2a", "key-hook": "keyboard intercept",
                  "hook-cf": "svc_ret int 16", "int16-zf": "zf=", "pit": "PIT",
                  "idle": "console read with no key buffered", "idle-stack": "idle wait: stack",
                  "stall": "stalled: no service event"}
SPEECH = ("sb-block", "dsp-status")
KEYED = ("key-hook", "hook-cf", "int16-zf")
IDLED = ("idle", "idle-stack")     # a milestone whose reference waits in DOS's idle stub


def dos_file_stamp(stamp):
    t = time.localtime(stamp)
    return ((t.tm_hour & 31) << 11 | (t.tm_min & 63) << 5 | (t.tm_sec // 2 & 31),
            ((t.tm_year - 1980) & 127) << 9 | (t.tm_mon & 63) << 5 | (t.tm_mday & 31))


class MemFile:
    """An open file the guest writes: kept in memory, never on disk."""

    def __init__(self, data: bytearray):
        self.data, self.pos = data, 0
        self.modified = False
        self.dos_stamp = None

    def read(self, n: int) -> bytes:
        out = bytes(self.data[self.pos:self.pos + n])
        self.pos += len(out)
        return out

    def write(self, b: bytes) -> int:
        self.modified = True
        if not b:  # DOS write of 0 bytes: truncate here
            del self.data[self.pos:]
            return 0
        if self.pos > len(self.data):
            self.data.extend(bytes(self.pos - len(self.data)))
        self.data[self.pos:self.pos + len(b)] = b
        self.pos += len(b)
        return len(b)

    def seek(self, off: int, whence: int) -> int:
        self.pos = max(0, (0, self.pos, len(self.data))[whence] + off)
        return self.pos

    def close(self) -> None:
        pass


class DeadMask(set):
    """The masked dead-stack bytes, mirrored into a byte per guest byte that
    memwatch.c reads (a write to one goes to the Python hook)."""

    def __init__(self, arr: bytearray):
        super().__init__()
        self.arr = arr

    def add(self, a):
        super().add(a)
        self.arr[a] = 1

    def update(self, *spans):
        for span in spans:
            span = list(span)
            super().update(span)
            for a in span:
                self.arr[a] = 1

    def difference_update(self, *spans):
        for span in spans:
            span = list(span)
            super().difference_update(span)
            for a in span:
                self.arr[a] = 0

    def discard(self, a):
        super().discard(a)
        self.arr[a] = 0


def outside(stored: bytearray, inside: bytearray) -> list[int]:
    """Offsets set in stored and not in inside (both bytes of 0/1)."""
    if not int.from_bytes(stored, "little") & ~int.from_bytes(inside, "little"):
        return []
    return [o for o in range(len(stored)) if stored[o] and not inside[o]]


class Host:
    # class defaults for a bare host (tests/test_host_replay_visits.py)
    sabotage = None
    hooking = False     # inside rt_key_hook
    early = stalled = retrace_bad = display_miss = irq_lost = None
    stall = 300
    _masked = None

    def __init__(self, ref_root: Path, sabotage: str | None = None, elf: Path | None = None,
                 retrace: list | None = None, pit: list | None = None, dsp: dict | None = None):
        self.launch = ""
        self.key_queue: list[int] = []      # scan bytes not yet in rt_key_ring
        self.key_sent = self.key_posted = 0
        self.rom: bytes | None = None   # F0000h..FFFFFh before the first guest instruction
        self.root = ref_root
        self.file_clock = None
        self.calendar_date = None
        self.sabotage = sabotage
        functions = {}
        entry, segs, self.syms = elf_load(elf or ELF, functions)
        self.frame_writer = functions["push_frame"]
        e = self.e = U.Engine(U.ARCH_M68K, U.MODE_BIG_ENDIAN, U.CPU_M68K_M68020)
        e.map(0, MEM)
        for vaddr, data, memsz in segs:
            e.write(vaddr, data + bytes(memsz - len(data)))
        self.entry = entry
        self.files: dict[int, object] = {}
        self.allocations = {}
        self.free_spans = [(0x900000, 0x500000)]
        self.next_file = 1
        self.written: dict[str, bytearray] = {}  # files the guest wrote (game path -> bytes)
        self.file_stamps: dict[str, tuple[int, int]] = {}
        self.deleted: set[str] = set()
        self.log: list[str] = []
        self.console = b""             # plat_console: the game's DOS console output
        self.exit: int | None = None
        self.services: list[tuple[str, dict]] = ServiceLog()
        self.stopped_at: str | None = None
        self.early: str | None = None     # the problem that stopped the run (stop_early)
        self.stalled: str | None = None
        self.stall = 300                  # seconds without progress (run's watchdog)
        self.stubs = {self.syms[n]: n for n in ("plat_alloc", "plat_free", "plat_open", "plat_create", "plat_read", "plat_write",
                                                "plat_delete", "plat_seek",
                                                "plat_calendar_date", "plat_file_stamp", "plat_close", "plat_dir_names", "plat_file_info", "plat_timer_rate", "plat_pit_count", "plat_mouse", "plat_present", "plat_palette",
                                                "plat_service", "plat_vga_status", "plat_dsp_status", "plat_sb_block",
                                                "plat_log", "plat_console",
                                                "plat_sfx_cached", "plat_sfx_wanted", "plat_sfx_captured", "plat_exit")}
        # --sfx-capture: the effect captures (src/runtime/sfx.c), each with the
        # guest RAM at its hook; sfx_cap while one runs (out of the game's flow:
        # no trigger, poll, service, OPL, IRQ or memory check sees it)
        self.sfx_cap = False
        self.sfx_depth = 0                # the sound init's hook (HLE sfx_init) entered
        self.sfx_plant = "on"
        self.sfx_entry: tuple[bytes, int] | None = None
        self.sfx_captures: list[dict] = []
        # VGA status replay: (service events, value, reads) runs of trace/retrace.csv
        self.retrace = list(retrace or [])
        self.retrace_i = self.retrace_used = 0
        self.retrace_bad: str | None = None
        # PIT replay: (service events, value, reads) runs of port 40h reads
        self.pit = list(pit or [])
        self.pit_i = self.pit_used = self.pit_latches = self.pit_prev = 0
        # DSP status replay: per port (22Ch, 22Eh) its runs, next row, reads used of it
        self.dsp = {port: [list(runs), 0, 0] for port, runs in (dsp or {}).items()}
        self.dsp_reads = 0
        self.blocks: list[tuple[int, int, int]] = []   # plat_sb_block: linear, length, rate
        self.mouse_dx = self.mouse_dy = self.mouse_buttons = 0
        self.presents = 0
        # D9 display: every byte the guest stores to the frame is inside the
        # rectangles of the next present (the runtime's marks vs the stores)
        self.vram_written = bytearray(64000)
        self.display_miss: str | None = None
        # memwatch.c: the memory hooks in C, passing on only the accesses the
        # checks act on (the Python hooks below keep their own tests)
        self.machine = bytearray(GUEST_BYTES)
        for lo, hi in machine_ranges():
            self.machine[lo:hi] = b"\1" * (hi - lo)
        self.dead_bytes = bytearray(GUEST_BYTES)
        self.watch_lib = U.watch_lib()
        w = self.watch = U.Watch()
        self.watch_bufs = [(ctypes.c_char * len(b)).from_buffer(b)
                           for b in (self.machine, self.dead_bytes, self.vram_written)]
        w.top, w.size = TOP, GUEST_BYTES
        w.machine, w.dead, w.vram = (ctypes.addressof(b) for b in self.watch_bufs)
        w.mem_read = ctypes.cast(U.uc.uc_mem_read, ctypes.c_void_p).value
        w.dead_flags = -1
        w.rbits, w.wbits = irq_monitor.WRITTEN, irq_monitor.ACCESSED | irq_monitor.BUFFER
        self.watch_ptr = ctypes.addressof(w)
        e.write(self.syms["rt_present_due"], b"\1")  # a vertical blank is always due
        if sabotage == "vram":
            e.write(self.syms["rt_vram_mark"], b"\x4e\x75")  # rts
        if sabotage in ("irq-stack", "irq-state", "irq-sentinel", "irq-offset"):
            a = self.syms["rt_irq_async"]
            code = e.read(a, self.syms["rt_irq_async_back"] + 0x40 - a)
            if sabotage == "irq-stack":     # move.w #$b000,G_SS(a6); move.w #$8000,rt_r+8 -> nops
                k = code.index(bytes.fromhex("3d7cb0000003"))
                e.write(a + k, bytes.fromhex("4e71") * 3)
                k = code.index(bytes.fromhex("33fc8000"))
                e.write(a + k, bytes.fromhex("4e71") * 4)
            elif sabotage == "irq-offset":  # move.w #$8000,rt_r+8 -> #$7ffe
                k = code.index(bytes.fromhex("33fc8000"))
                e.write(a + k + 2, bytes.fromhex("7ffe"))
            elif sabotage == "irq-state":   # move.l (a0)+,d16(a6) x4 after the handler -> nops
                k = code.index(bytes.fromhex("2d580001"))
                e.write(a + k, bytes.fromhex("4e71") * 8)
            else:                           # move.l #$b0008000,d7 -> #$b0008002
                k = code.index(bytes.fromhex("2e3cb0008000"))
                e.write(a + k + 2, bytes.fromhex("b0008002"))
        if sabotage == "ems-fast":
            e.write(self.syms["refresh"], b"\x4e\x75")  # rts
        if sabotage == "ems-cache":
            e.write(self.syms["rt_ems_cache_clear"], b"\x4e\x75")  # rts
        if sabotage == "ems-cache-irq":
            e.write(self.syms["rt_ems_cache_restore"], b"\x4e\x75")  # rts
        if sabotage == "ems-irq":
            e.write(self.syms["rt_ems_irq_leave"], b"\x4e\x75")  # rts
        if sabotage == "ems-restore":
            e.write(self.syms["rt_ems_restore_c"], b"\x4e\x75")  # rts
        if sabotage == "key-hook":
            e.write(self.syms["rt_key_hook"], bytes.fromhex("4e75"))   # rts
        if sabotage == "idle":   # moveq #0,d0; rts
            e.write(self.syms["rt_idle"], bytes.fromhex("70004e75"))
        if sabotage == "idle-stack":
            planted = []

            @U.CODE_CB
            def idle_entry(h, addr, size, user):
                if not planted:
                    a = self.syms["rt_r"] + 8
                    sp = int.from_bytes(self.mem(a, 2), "big")
                    self.e.write(a, ((sp - 2) & 0xFFFF).to_bytes(2, "big"))
                    planted.append(sp)
            self.idle_entry = idle_entry     # kept alive for the hook
            e.hook_range(U.HOOK_CODE, idle_entry, self.syms["rt_idle"], self.syms["rt_idle"])
        if sabotage == "keyon":  # addq.b #1,(a0,d7.w) -> nop; nop
            a = self.syms["rt_out8"]
            code = e.read(a, 0x100)
            e.write(a + code.index(bytes.fromhex("52307000")), bytes.fromhex("4e714e71"))
        if sabotage == "overlay":
            n = int.from_bytes(e.read(self.syms["overlay_count"], 4), "big")
            e.write(self.syms["overlay_stubs"], bytes(2 * n))
        if sabotage == "far":
            rows = int.from_bytes(e.read(self.syms["dispatch_count"], 4), "big")
            for k in range(rows):
                e.write(self.syms["dispatch_table"] + 12 * k + 6, b"\0\0")

        # the frame exists in mode 13h only (memwatch.c watch_vram)
        e.hook_native(U.HOOK_MEM_WRITE, self.native("watch_vram"), self.watch_ptr,
                      TOP - 0xA0000 - 63999, TOP - 0xA0000)

        @U.CODE_CB
        def stub(h, addr, size, user):
            n = self.stubs.get(addr)
            if n:
                self.platform(n)

        e.hook_range(U.HOOK_CODE, stub, self.syms["host_stubs"], self.syms["host_stubs_end"])

        # a service returns when the runtime glue's rts goes back to the
        # address after its jsr rt_int (static hooks: Unicorn retranslates
        # on every hook change)
        @U.CODE_CB
        def ret_hit(h, addr, size, user):
            if self.pending and self.u32(self.r("a7")) == self.pending[-1]:
                self.pending.pop()
                if self.sabotage == "ax" and len(self.services) == 19:
                    self.e.reg_write(U.M68K["d0"], (self.r("d0") + 1) & 0xFFFF)
                if self.sabotage == "int16-zf" and self.pending_vec[-1] == 0x16 and not self.zf_planted \
                        and self.services[-1][1]["ax"] >> 8 == 0x01 and not self.state(16, 1) & 4:
                    self.e.write(TOP + 16, bytes([self.state(16, 1) | 4]))
                    self.zf_planted = True
                regs = self.guest_regs(self.pending_vec.pop())
                if self.irq_stack:
                    regs["irq"] = self.irq_stack[-1]
                self.services.append(("svc_ret", regs))
                self.in_service = bool(self.pending)

        for n in ("rt_exit", "rt_exit_guest"):
            e.hook_range(U.HOOK_CODE, ret_hit, self.syms[n], self.syms[n])
        self.pending: list = []
        self.pending_vec: list = []
        self.zf_planted = False

        # the keyboard intercept (rt_key_hook): AX at each run (the BIOS
        # stub's 4Fh, the scan code), the reference's INT 15h rows to compare
        self.key_hooks: Counter = Counter()
        self.hooking = False
        self.hook_runs = 0

        @U.CODE_CB
        def key_hook(h, addr, size, user):
            self.hooking = True
            self.hook_runs = sum(self.key_hooks.values())

        @U.CODE_CB
        def key_hook_ret(h, addr, size, user):
            # rt_key_hook returned to the BIOS model: the intercept must have run
            self.hooking = False
            if sum(self.key_hooks.values()) == self.hook_runs and not self.irq_lost:
                self.irq_lost = "keyboard intercept: the BIOS INT 09h model's INT 15h returned " \
                                "without running the guest handler"
                self.halted = True
                self.e.stop()

        @U.CODE_CB
        def key_hook_run(h, addr, size, user):
            if self.u32(self.r("a7")) == self.syms["rt_key_hook_back"]:
                self.key_hooks[self.r("d0") & 0xFFFF] += 1

        @U.CODE_CB
        def key_hook_back(h, addr, size, user):
            self.hooking = False
            if self.sabotage == "hook-cf":
                self.e.write(TOP + 16, bytes([self.state(16, 1) & ~1 & 0xFF]))

        e.hook_range(U.HOOK_CODE, key_hook, self.syms["rt_key_hook"], self.syms["rt_key_hook"])
        self.hook_rets = call_returns(segs, functions, self.syms["rt_key_hook"])
        if not self.hook_rets:
            raise SystemExit("host image: no call to rt_key_hook found")
        for ret in self.hook_rets:
            e.hook_range(U.HOOK_CODE, key_hook_ret, ret, ret)
        e.hook_range(U.HOOK_CODE, key_hook_run, self.syms["deliver_guest"], self.syms["deliver_guest"])
        e.hook_range(U.HOOK_CODE, key_hook_back, self.syms["rt_key_hook_back"], self.syms["rt_key_hook_back"])

        # a vector the guest owns (VROOMM's INT 3Fh): rt_int's service part ends
        # where its guest handler starts (deliver_int); that IRET may return
        # elsewhere (rt_ret_far_mismatch), never through rt_exit, so the handler
        # and what follows are guest code, not a service
        @U.CODE_CB
        def int_guest(h, addr, size, user):
            if self.pending and self.u32(self.r("a7")) == self.pending[-1]:
                self.pending.pop()
                self.pending_vec.pop()
                self.in_service = bool(self.pending)

        e.hook_range(U.HOOK_CODE, int_guest, self.syms["deliver_int"], self.syms["deliver_int"])

        # IRQ0's guest handler runs on the private stack (rt_irq_async, I4): the
        # interrupted SS:SP for the relocated service compare (compare_services)
        self.irq_stack: list[tuple[int, int]] = []

        @U.CODE_CB
        def irq_async(h, addr, size, user):
            g = self.guest_regs(0)
            self.irq_stack.append((g["ss"], g["sp"]))

        @U.CODE_CB
        def irq_async_back(h, addr, size, user):
            self.irq_stack.pop()

        e.hook_range(U.HOOK_CODE, irq_async, self.syms["rt_irq_async"], self.syms["rt_irq_async"])
        e.hook_range(U.HOOK_CODE, irq_async_back, self.syms["rt_irq_async_back"],
                     self.syms["rt_irq_async_back"])

        @U.CODE_CB
        def int_entry(h, addr, size, user):
            d6 = self.r("d6")
            regs = self.guest_regs(d6 & 0xFF)
            if self.irq_stack:
                regs["irq"] = self.irq_stack[-1]
            self.services.append(("svc", regs))
            self.in_service = True
            top = regs["ss"] * 16 + regs["sp"]
            self.masked.update(range(top - DEAD_STACK, top))
            self.pending.append(self.u32(self.r("a7")))
            self.pending_vec.append(d6 & 0xFF)

        a = self.syms["rt_int"]
        e.hook_range(U.HOOK_CODE, int_entry, a, a)

        # AdLib writes as the guest makes them (check_opl)
        self.opl: list[tuple[int, int]] = []
        self.opl_ports: list[tuple[int, int]] = []

        @U.CODE_CB
        def out8(h, addr, size, user):
            if self.sfx_cap:
                return
            port, v = self.r("d7") & 0xFFFF, self.r("d6") & 0xFF
            if port in (0x388, 0x389):
                self.opl_ports.append((port, v))
            if port == 0x389:
                reg = self.mem(self.syms["rt_opl_index"], 1)[0]
                self.opl.append((reg, v))

        a = self.syms["rt_out8"]
        e.hook_range(U.HOOK_CODE, out8, a, a)

        # Hardware interrupts: the reference's BIOS handlers (and the INT frame)
        # use the interrupted stack, ours run in C; the window below SS:SP is dead.
        # The reference's handlers push there down to the footprint's proved
        # depth below the frame (IRQ0's runs on the private stack here, I4).
        irq_dead = DEAD_STACK
        if irq_monitor.FOOTPRINT.exists():
            irq_dead = max(DEAD_STACK, irq_monitor.stack_depth() + 6)

        @U.CODE_CB
        def irq_entry(h, addr, size, user):
            if self.sfx_cap:
                return
            g = self.guest_regs(0)
            top = g["ss"] * 16 + g["sp"]
            self.masked.update(range(top - irq_dead, top))

        for n in ("rt_irq", "rt_bios_int08"):
            e.hook_range(U.HOOK_CODE, irq_entry, self.syms[n], self.syms[n])

        # I3: every guest access against the IRQ0 footprint (tests/irq_monitor.py)
        self.irq = irq_monitor.Monitor(self, GUEST_BYTES, sabotage=sabotage) \
            if irq_monitor.FOOTPRINT.exists() else NoMonitor()

        @U.CODE_CB
        def irq_deliver(h, addr, size, user):
            if not self.sfx_cap:
                self.irq.deliver()

        @U.CODE_CB
        def irq_back(h, addr, size, user):
            if not self.sfx_cap:
                self.irq.returned()

        e.hook_range(U.HOOK_CODE, irq_deliver, self.syms["deliver_guest"], self.syms["deliver_guest"])
        for n in ("rt_irq_async_back", "rt_irq_interrupt_back", "rt_irq_back", "rt_key_hook_back"):
            if n in self.syms:
                e.hook_range(U.HOOK_CODE, irq_back, self.syms[n], self.syms[n])

        # memory watch from the guest entry on (rt_start's own writes are not watched)
        self.in_service = False
        self.masked = set()
        self.machine_reads: dict[int, tuple[int, int]] = {}   # byte -> first reader (pc, services)

        @U.MEM_CB
        def write(h, kind, addr, size, value, user):
            if self.sfx_cap:
                return True
            # memory is reversed: the 68k value's byte k is the guest's byte lin + k
            self.irq.write(TOP - addr - size + 1, size, value & ((1 << 8 * size) - 1))    # I3
            span = range(TOP - addr - size + 1, TOP - addr + 1)
            if self.dead_flags is not None and self.dead_flags in span:
                self.masked.update(span)
                self.dead_flags = None
            elif (not self.in_service and self.masked
                  and not self.masked.isdisjoint(span)
                  and not self.frame_writer[0] <= self.r("pc") < self.frame_writer[1]):
                # The interrupt frame belongs to the runtime. Preserve only
                # the existing dead-stack mask; all other writes still clear it.
                self.masked.difference_update(span)
            return True

        # The FLAGS image of an annotations/flags.csv PUSHF is dead by that
        # annotation; its word below SS:SP is masked until the guest rewrites it.
        @U.CODE_CB
        def dead_pushf(h, addr, size, user):
            if self.sfx_cap:
                return
            g = self.guest_regs(0)
            self.dead_flags = g["ss"] * 16 + ((g["sp"] - 2) & 0xFFFF)

        self.dead_flags = None
        for r in image.rows("flags.csv"):
            lab = emit.label(r["module"], int(r["save"], 16))
            for a in {self.syms[x] for x in (lab, lab + "_bp") if x in self.syms}:  # R6 copy
                e.hook_range(U.HOOK_CODE, dead_pushf, a, a)

        machine = self.machine

        @U.MEM_CB
        def read(h, kind, addr, size, value, user):
            if self.sfx_cap:
                return True
            lin = TOP - addr - size + 1
            self.irq.read(lin, size)    # I3 (tests/irq_monitor.py)
            if (machine[lin] or machine[lin + size - 1]) and not self.in_service \
                    and self.code[0] <= self.r("pc") < self.code[1]:
                for b in range(lin, lin + size):
                    if machine[b] and b not in self.machine_reads:
                        self.machine_reads[b] = (self.r("pc"), len(self.services))
            return True

        @U.CODE_CB
        def guest_start(h, addr, size, user):
            if self.watching:
                return
            self.watching = True
            # The reference shell's launch with arguments (milestones.csv launch,
            # `WC2 Origin -k`): machine.c's PSP has none, so its command tail
            # and FCBs 1 and 2 are written here before the first guest instruction
            if self.rom:
                self.e.write(TOP - (ROM[1] - 1), self.rom[::-1])
            if self.launch:
                psp = (self.u32(self.syms["load_segment"]) - 0x10) * 16
                for off, data in psp_arguments(self.launch).items():
                    for k, b in enumerate(data):
                        self.e.write(TOP - psp - off - k, bytes([b]))
            if self.sabotage == "stall":     # before the code is translated
                self.e.write(self.syms["R_0FA8F"], b"\x60\xfe")
            if self.sabotage == "psp":
                a = TOP - (0x8120 + 0x5d)
                self.e.write(a, bytes([self.mem(a, 1)[0] ^ 0x20]))
            self.watch.read_cb = ctypes.cast(read, ctypes.c_void_p).value
            self.watch.write_cb = ctypes.cast(write, ctypes.c_void_p).value
            self.e.hooks += [read, write]
            self.e.hook_native(U.HOOK_MEM_WRITE, self.native("watch_write"), self.watch_ptr,
                               TOP - GUEST_BYTES + 1, TOP)
            self.e.hook_native(U.HOOK_MEM_READ, self.native("watch_read"), self.watch_ptr,
                               TOP - GUEST_BYTES + 1, TOP)

        # generated code: from the first guest label to program.s's data after
        # the modules (the runtime's own reads, e.g. the BIOS tick, are not the
        # guest's)
        tags = tuple(t + "_" for t in emit.TAG.values())
        self.code = (min(v for k, v in self.syms.items() if k.startswith(tags)),
                     self.syms["load_segment"])
        self.watching = False
        a = self.syms["rt_run_guest"]
        e.hook_range(U.HOOK_CODE, guest_start, a, a)

    def stop_early(self, why: str) -> None:
        """A problem the run cannot recover from: stop now, report after."""
        if self.early is None:
            self.early = why
        self.halted = True
        self.e.stop()

    def problem_now(self) -> str | None:
        """A problem the checks after the run will report (stop_early)."""
        mon = getattr(getattr(self, "irq", None), "problems", None)
        return self.services.bad or self.irq_lost or self.retrace_bad or self.display_miss or \
            (mon[0] if mon else None)

    def where(self, pc: int | None = None) -> str:
        """The generated label or runtime symbol at `pc` (default: the 68k pc)."""
        pc = self.r("pc") if pc is None else pc
        if not hasattr(self, "sym_sorted"):
            self.sym_sorted = sorted((a, n) for n, a in self.syms.items())
        k = max((i for i in range(len(self.sym_sorted)) if self.sym_sorted[i][0] <= pc), default=None)
        return f"{self.sym_sorted[k][1]}+{pc - self.sym_sorted[k][0]:x}" if k is not None else f"{pc:x}"

    def native(self, name: str) -> int:
        return ctypes.cast(getattr(self.watch_lib, name), ctypes.c_void_p).value

    @property
    def masked(self) -> set[int]:
        return self._masked

    @masked.setter
    def masked(self, bytes_: set[int]) -> None:
        """Any set assigned becomes the mirrored one (memwatch.c reads its bytes)."""
        if self._masked:
            self.dead_bytes[:] = bytes(len(self.dead_bytes))
        self._masked = DeadMask(self.dead_bytes)
        self._masked.update(bytes_)

    @property
    def dead_flags(self):
        return self._dead_flags

    @dead_flags.setter
    def dead_flags(self, lin):
        self._dead_flags = lin
        self.watch.dead_flags = -1 if lin is None else lin

    def watch_mask(self, mask: bytearray) -> None:
        """The IRQ monitor's mask (its layout), read by memwatch.c."""
        self.watch_mon = (ctypes.c_char * len(mask)).from_buffer(mask)
        self.watch.mon = ctypes.addressof(self.watch_mon)

    def watch_handler(self, inside: bool) -> None:
        """A delivered handler runs (every access to Python) or returned."""
        self.watch.all = int(inside)

    def r(self, name: str) -> int:
        return self.e.reg_read(U.M68K[name])

    def mem(self, a: int, n: int) -> bytes:
        return self.e.read(a, n)

    def gmem(self, a: int, n: int) -> bytes:
        """Guest bytes a..a+n-1 in guest order."""
        return self.e.read(TOP - a - n + 1, n)[::-1]

    def u32(self, a: int) -> int:
        return struct.unpack(">I", self.mem(a, 4))[0]

    def cstr(self, a: int) -> str:
        b = self.mem(a, 256)
        return b[:b.index(b"\0")].decode("latin-1")

    def state(self, off: int, n: int) -> int:
        return int.from_bytes(self.mem(TOP + off, n), "big")

    def guest_regs(self, vector: int) -> dict:
        regs = {n: self.r(r) & 0xFFFF for n, r in zip(REGS, ("d0", "d1", "d2", "d3", "d4", "d5",
                                                             "a4", "a5"))}
        regs["sp"] ^= 0x7FFF    # mirrored (translator/lower.py MIRROR)
        regs["bp"] ^= 0x7FFF
        regs.update(es=self.state(5, 2), ss=self.state(3, 2), ds=self.state(1, 2))
        ccr = self.state(16, 1)
        regs["cf"], regs["zf"] = ccr & 1, ccr >> 2 & 1
        regs["df"], regs["if"] = int(self.state(12, 1) != 0), int(self.state(11, 1) != 0)
        regs["vector"] = vector
        return regs

    def platform(self, n: str) -> None:
        sp = self.r("a7")
        args = struct.unpack(">IIII", self.mem(sp + 4, 16))
        res = 0
        if n in ("plat_open", "plat_dir_names", "plat_file_info", "plat_create", "plat_delete"):
            name = self.cstr(args[0])
            path = self.root
            for part in filter(None, name.split("/")):
                matches = [p for p in path.iterdir() if p.name.upper() == part] if path.is_dir() else []
                path = matches[0] if matches else self.root / "\0"
            on_disk = path.is_file() and name not in self.deleted
        if n == "plat_alloc":
            size = (args[0] + 3) & ~3
            for i, (address, length) in enumerate(self.free_spans):
                if length >= size:
                    self.allocations[address] = size
                    self.free_spans[i:i+1] = [(address+size, length-size)] if length > size else []
                    res = address
                    break
        elif n == "plat_free":
            address = args[0]
            size = self.allocations.pop(address)
            spans = sorted(self.free_spans + [(address, size)])
            self.free_spans = []
            for address, length in spans:
                if self.free_spans and sum(self.free_spans[-1]) == address:
                    previous, size = self.free_spans.pop()
                    self.free_spans.append((previous, size+length))
                else:
                    self.free_spans.append((address, length))
        elif n == "plat_dir_names":
            prefix = name + "/" if name else ""
            disk = {p.name for p in path.iterdir()
                    if p.is_file() and len(p.name) <= 12 and prefix + p.name.upper() not in self.deleted} \
                if path.is_dir() else set()
            disk.update(w[len(prefix):] for w in self.written
                        if w.startswith(prefix) and "/" not in w[len(prefix):])
            packed = b"".join(n.encode() + b"\0" for n in sorted(disk))
            fit = packed[:args[2]]
            fit = fit[:fit.rfind(b"\0") + 1]
            if fit:
                self.e.write(args[1], fit)
            res = len(packed)
        elif n == "plat_file_info":
            if name in self.written:
                self.e.write(args[1], struct.pack(">IHH", len(self.written[name]), *self.file_stamps[name]))
            elif on_disk:
                self.e.write(args[1], struct.pack(">IHH", path.stat().st_size, *dos_file_stamp(path.stat().st_mtime)))
            else:
                res = -1
        elif n == "plat_open":
            if args[1] and on_disk and name not in self.written:
                self.written[name] = bytearray(path.read_bytes())  # a copy: ref/ stays untouched
                self.file_stamps[name] = dos_file_stamp(path.stat().st_mtime)
            f = MemFile(self.written[name]) if name in self.written else \
                path.open("rb") if on_disk else None
            if f:
                self.files[self.next_file] = f
                res, self.next_file = self.next_file, self.next_file + 1
            else:
                res = -1
        elif n == "plat_create":
            self.written[name] = bytearray()
            self.file_stamps[name] = dos_file_stamp(self.file_clock if self.file_clock is not None else time.time())
            self.deleted.discard(name)
            self.files[self.next_file] = MemFile(self.written[name])
            res, self.next_file = self.next_file, self.next_file + 1
        elif n == "plat_delete":
            if name in self.written:
                del self.written[name]
            elif on_disk:
                self.deleted.add(name)
            else:
                res = -1
        elif n == "plat_read":
            f = self.files[args[0]]
            data = f.read(args[2])
            if self.sabotage == "read" and data and self.watching:
                data = bytes([data[0] ^ 0xFF]) + data[1:]
            self.e.write(args[1], data)
            res = len(data)
        elif n == "plat_write":
            f = self.files[args[0]]
            res = f.write(self.mem(args[1], args[2])) if isinstance(f, MemFile) else -1
        elif n == "plat_seek":
            f = self.files[args[0]]
            off = args[1] - (1 << 32) if args[1] & 0x80000000 else args[1]
            res = f.seek(off, args[2])
        elif n == "plat_calendar_date":
            calendar = time.localtime(time.time())
            res = self.calendar_date if self.calendar_date is not None else \
                calendar.tm_year << 16 | calendar.tm_mon << 8 | calendar.tm_mday
        elif n == "plat_file_stamp":
            f = self.files[args[0]]
            if not isinstance(f, MemFile):
                raise AssertionError('explicit timestamp on a read-only platform file')
            f.dos_stamp = (args[1], args[2])
        elif n == "plat_close":
            f = self.files.pop(args[0])
            if isinstance(f, MemFile) and f.modified:
                for name, data in self.written.items():
                    if data is f.data:
                        self.file_stamps[name] = f.dos_stamp or dos_file_stamp(self.file_clock if self.file_clock is not None else time.time())
            f.close()
        elif n == "plat_mouse":
            self.e.write(args[0], struct.pack(">i", self.mouse_dx))
            self.e.write(args[1], struct.pack(">i", 0 if self.sabotage == "mouse-motion" else self.mouse_dy))
            self.mouse_dx = self.mouse_dy = 0
            res = self.mouse_buttons & (3 if self.sabotage == "mouse-buttons" else 7)
        elif n == "plat_present":
            self.presents += 1
            shown = bytearray(64000)
            for k in range(args[2]):
                x0, y0, x1, y1 = struct.unpack(">4H", self.mem(args[1] + 8 * k, 8))
                for y in range(y0, y1):
                    shown[y * 320 + x0:y * 320 + x1] = b"\1" * (x1 - x0)
            miss = outside(self.vram_written, shown)
            if miss and not self.display_miss:
                self.display_miss = f"present {self.presents}: {len(miss)} stored pixels outside " \
                    f"its rectangles, first x={miss[0] % 320} y={miss[0] // 320}"
            ctypes.memset(self.watch_bufs[2], 0, 64000)
            self.e.write(self.syms["rt_present_due"], b"\1")
        elif n == "plat_palette":
            if self.sabotage == "dac":
                self.e.write(args[0] + 300, bytes([self.mem(args[0] + 300, 1)[0] ^ 1]))
        elif n == "plat_vga_status":
            res = self.vga_status()
        elif n == "plat_dsp_status":
            res = self.dsp_status(args[0], args[1])
        elif n == "plat_sb_block":
            length = args[1] + (self.sabotage == "sb-block" and len(self.blocks) == 1)
            self.blocks.append((args[0], length, args[2]))
        elif n == "plat_pit_count":
            if args[0] != 0:
                self.retrace_bad = self.retrace_bad or f"PIT latch of channel {args[0]}"
            lo, hi = self.pit_read(), self.pit_read()
            self.pit_latches += 1
            res = hi << 8 | lo
            # STRAX.DRV's OPL delay (+0714h) sums the counter's fall from latch to
            # latch until CX ticks pass, so only the latch that ends it counts; the
            # sixth is mid-loop (latches 4-11 wait 37h ticks, open-work 14): one
            # above the fifth reads as 4DADh ticks, the loop ends there
            if self.sabotage == "pit" and self.pit_latches == 6:
                res = self.pit_prev + 1
            self.pit_prev = res
        elif n == "plat_log":
            self.log.append(self.cstr(args[0]))
            print(self.log[-1])
        elif n == "plat_console":
            self.console += self.mem(args[0], args[1])
        elif n == "plat_sfx_cached":            # no cache on the host: every run captures
            res = 0
        elif n == "plat_sfx_wanted":
            res = 1
        elif n == "plat_sfx_captured":
            if self.sfx_plant == "restore":     # a DGROUP byte the restore missed:
                ds = self.sfx_entry[1]          # the capture's slot 31 flags
                a = TOP - (ds * 16 + 0xa54c + 14 * 31)
                self.e.write(a, bytes([self.mem(a, 1)[0] ^ 0x80]))
            if self.sfx_plant == "starts":      # a start counted inside the capture
                self.e.write(self.syms["rt_sfx_starts"] + 1, b"\1")
            self.sfx_captures.append(self.sfx_state())
        elif n == "plat_exit":
            self.exit = args[0]
            self.halted = True
            self.e.stop()
        self.e.reg_write(U.M68K["d0"], res & 0xFFFFFFFF)

    def sfx_enable(self, plant: str = "on") -> None:
        """Turn the effect capture on (rt_sfx_prerender_on) and mark its window,
        keeping the guest RAM and DS at its hook."""
        self.e.write(self.syms["rt_sfx_prerender_on"], b"\1")
        self.sfx_plant = plant

        @U.CODE_CB
        def cap(h, addr, size, user):
            if addr == self.syms["rt_hle_sfx_init"]:
                self.sfx_depth += 1
                if self.sfx_depth == 1:
                    self.sfx_entry = (self.e.read(TOP - GUEST_BYTES + 1, GUEST_BYTES)[::-1], self.state(1, 2))
            else:
                self.sfx_depth -= 1
            self.sfx_cap = self.sfx_depth > 0

        for n in ("rt_hle_sfx_init", "rt_hle_sfx_init_done"):
            self.e.hook_range(U.HOOK_CODE, cap, self.syms[n], self.syms[n])

    def sfx_state(self) -> dict:
        """At plat_sfx_captured: the capture (runtime.h rt_sfx_*), the guest RAM
        (linear, restored) and the RAM and DS at the hook."""
        ids = 56                                    # runtime.h RT_SFX_IDS
        words = lambda n: struct.unpack(f">{ids}H", self.mem(self.syms[n], 2 * ids))
        first, writes, ticks = words("rt_sfx_first"), words("rt_sfx_writes"), words("rt_sfx_ticks")
        total = max((f + w for f, w in zip(first, writes)), default=0)
        raw = self.mem(self.syms["rt_sfx_capture"], 4 * total)
        cap = [struct.unpack_from(">HBB", raw, 4 * k) for k in range(total)]
        ram, ds = self.sfx_entry
        return {"ids": {i: (cap[first[i]:first[i] + writes[i]], ticks[i]) for i in range(ids)},
                "opl": bytes(self.mem(self.syms["rt_sfx_opl"], 256)), "ram": bytes(ram), "ds": ds,
                "starts": bytes(self.mem(self.syms["rt_sfx_starts"], ids)),
                "after": bytes(self.e.read(TOP - GUEST_BYTES + 1, GUEST_BYTES)[::-1])}

    def vga_status(self) -> int:
        """The reference's next 3DAh value, read in the same service interval."""
        n = len(self.services)
        while self.retrace_i < len(self.retrace) and self.retrace_used == self.retrace[self.retrace_i][2]:
            self.retrace_i, self.retrace_used = self.retrace_i + 1, 0
        if self.retrace_i == len(self.retrace):
            self.retrace_bad = self.retrace_bad or f"VGA status read after the reference's last (service events {n})"
            return 0
        svc, value, _ = self.retrace[self.retrace_i]
        if svc != n:
            self.retrace_bad = self.retrace_bad or \
                f"VGA status read #{sum(r[2] for r in self.retrace[:self.retrace_i]) + self.retrace_used} " \
                f"at service event {n}, the reference's at {svc}"
        self.retrace_used += 1
        if self.sabotage == "retrace" and self.retrace_i == len(self.retrace) // 2 and self.retrace_used == 1:
            value ^= 8
        return value

    def dsp_status(self, port: int, model: int) -> int:
        """The reference's next read of DSP status port 22Ch or 22Eh, in the same
        service interval. It may differ from the model's answer only by the
        device's timing: 22Ch busy (bit 7 set), 22Eh data not yet there (bit 7 clear)."""
        n = len(self.services)
        if port not in self.dsp:
            self.retrace_bad = self.retrace_bad or f"DSP status {port:X}h read: none in the reference"
            return model
        runs, i, used = self.dsp[port]
        while i < len(runs) and used == runs[i][2]:
            i, used = i + 1, 0
        self.dsp[port][1:] = i, used + 1
        self.dsp_reads += 1
        if i == len(runs):
            self.retrace_bad = self.retrace_bad or \
                f"DSP status {port:X}h read after the reference's last (service events {n})"
            return model
        svc, value, _ = runs[i]
        if self.sabotage == "dsp-status" and port == 0x22E and model == 0xAA:
            model = 0x2A     # the model's 22Eh reporting no data after the reset
        timing = value == (model | 0x80 if port == 0x22C else model & 0x7F)
        if svc != n or (value != model and not timing):
            self.retrace_bad = self.retrace_bad or \
                f"DSP status {port:X}h read {self.dsp_reads} at service event {n}: the reference's " \
                f"{value:02x} at {svc}, the model's {model:02x}"
        return value

    def dsp_left(self) -> int:
        return sum(sum(r[2] for r in runs[i:]) - used for runs, i, used in self.dsp.values())

    def retrace_left(self) -> int:
        return sum(r[2] for r in self.retrace[self.retrace_i:]) - self.retrace_used

    def pit_read(self) -> int:
        """The reference's next port 40h value, read in the same service interval."""
        n = len(self.services)
        while self.pit_i < len(self.pit) and self.pit_used == self.pit[self.pit_i][2]:
            self.pit_i, self.pit_used = self.pit_i + 1, 0
        if self.pit_i == len(self.pit):
            self.retrace_bad = self.retrace_bad or f"PIT read after the reference's last (service events {n})"
            return 0
        svc, value, _ = self.pit[self.pit_i]
        if svc != n:
            self.retrace_bad = self.retrace_bad or \
                f"PIT read #{sum(r[2] for r in self.pit[:self.pit_i]) + self.pit_used} " \
                f"at service event {n}, the reference's at {svc}"
        self.pit_used += 1
        return value

    def pit_left(self) -> int:
        return sum(r[2] for r in self.pit[self.pit_i:]) - self.pit_used

    def post(self, vector: int) -> None:
        tail = self.mem(self.syms["rt_irq_tail"], 1)[0]
        self.e.write(self.syms["rt_irq_ring"] + tail % 32, bytes([vector]))
        self.e.write(self.syms["rt_irq_tail"], bytes([(tail + 1) & 0xFF]))
        self.e.write(self.syms["rt_irq_pending"], b"\1")  # RT_RAISE_IRQ
        self.e.write(G_IRQ, b"\1")

    def guest_vector(self, vector: int) -> bool:
        """machine.c guest_vector: the IVT entry points into the program's memory,
        from its PSP to the top of DOS memory."""
        off, seg = struct.unpack("<HH", self.gmem(vector * 4, 4))
        psp = int.from_bytes(self.mem(self.syms["load_segment"], 4), "big") - 0x10
        return psp * 16 <= seg * 16 + off < 0x9FFF * 16

    def press(self, key: int, repeats: int = 0) -> None:
        """Queue the key's scan bytes (key_bytes: makes, typematic repeats,
        breaks) for runtime.h rt_key_ring, as many as it has room for now (key_fill);
        DOSBox posts one IRQ 1 per byte, and the runtime's BIOS INT 09h model
        stores the word at the make interrupt."""
        self.key_queue += key_bytes(key, repeats)
        self.key_fill()

    def key_fill(self) -> None:
        """Queued scan bytes into rt_key_ring while it has room (input.c key_head)."""
        while self.key_queue:
            tail = self.mem(self.syms["rt_key_tail"], 1)[0]
            if (tail - self.mem(self.syms["key_head"], 1)[0]) & 0xFF >= 16:
                return
            self.e.write(self.syms["rt_key_ring"] + 2 * (tail % 16), struct.pack(">H", self.key_queue.pop(0)))
            self.e.write(self.syms["rt_key_tail"], bytes([(tail + 1) & 0xFF]))
            self.key_sent += 1

    def run(self, script: dict | None, timeout: int) -> None:
        """Run to the script's last snapshot trigger (None: until a stop).
        Hardware interrupts replay the reference's (script["irqs"]): posted at
        the same visit of the same poll point after the same service event;
        key release eligibility uses recorded trigger visits when available."""
        steps = [(t, k) for t, k in script["keys"]] + [(t, None) for t in script["snapshots"]] \
            if script else []
        releases = list(script["releases"]) if script else []
        repeats = list(script.get("repeats", [])) if script else []
        self.irqs = list(script["irqs"]) if script else []
        idle = script.get("idle", {}) if script else {}
        self.step, self.hits, self.release = 0, 0, None
        self.irq_i, self.visit_n, self.visits, self.groups = 0, None, {}, {}
        self.irq_lost: str | None = None
        makes = 0
        rep = script.get("rep") if script else None
        rep_labels = set(rep.labels) if rep else set()
        # an instruction's label and its guarded copy's (R6) are one guest instruction
        at = {lab: {self.syms[x] for x in (lab, lab + "_bp") if x in self.syms}
              for lab in {t[0] for t, _ in steps} | {lab for _, lab, _, _ in self.irqs} | rep_labels}
        canon = {a: lab for lab, addrs in at.items() for a in addrs}

        @U.CODE_CB
        def hit(h, addr, size, user):
            if self.step == len(steps) or self.sfx_cap:
                return
            (lab, _, n), key = steps[self.step]
            if self.release is not None:
                if not self.release.ready(len(self.services), addr in at[lab]):
                    return
                self.release = None
            if addr not in at[lab]:
                return
            self.hits += 1
            if self.hits < n:
                return
            self.step, self.hits = self.step + 1, 0
            if isinstance(key, str):
                if key.startswith('j'):
                    return  # Device effects come from recorded gameport accesses.
                amount = int(key[2:])
                if key[1] == "x":
                    self.mouse_dx += amount
                elif key[1] == "y":
                    self.mouse_dy += amount
                else:
                    self.mouse_buttons = amount
            elif key is not None:
                self.press(key, repeats.pop(0) if repeats else 0)
                self.release = KeyRelease(releases.pop(0))
            elif self.step == len(steps):
                self.stopped_at = lab
                self.halted = True
                self.e.stop()

        @U.CODE_CB
        def poll(h, addr, size, user):
            try:
                replay(addr)
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        def replay(addr):
            if self.posted_at and self.r("a7") >= self.posted_at[2]:
                self.posted_at = None   # a later poll, not one nested in the handlers
            if self.irq_i == len(self.irqs) or self.sfx_cap:
                return
            n = len(self.services)
            if n != self.visit_n:  # executions of each poll point since the service event
                self.visit_n, self.visits = n, {}
            here = canon[addr]
            svc, lab, hits, _ = self.irqs[self.irq_i]
            if n > svc and not self.irq_lost:
                self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                                f"not reached (service events {n})"
            if n != svc or here != lab or self.visits.get(here, 0) != hits:
                return
            if here == IDLE:
                # the wait's stack is the reference's (input.c RT_IDLE_DEPTH)
                ss, sp, words = idle[self.irq_i]
                g = self.guest_regs(0)
                got = (g["ss"], g["sp"], tuple(int.from_bytes(self.gmem(g["ss"] * 16 + g["sp"] + 2 * i, 2),
                                                              "little") for i in range(6)))
                if got != (ss, sp, words) and not self.irq_lost:
                    self.irq_lost = f"reference irq #{self.irq_i} in DOS's idle wait: stack " \
                                    f"{got[0]:04x}:{got[1]:04x} {' '.join(f'{w:04x}' for w in got[2])}, " \
                                    f"the reference's {ss:04x}:{sp:04x} {' '.join(f'{w:04x}' for w in words)}"
            post_group(self.r("a7"))

        def post_group(a7):
            """Post the next interrupt of the reference's (svc, label, hits) group;
            for the BIOS's handlers (instant) the whole group. One the guest
            handles, the reference took the next of its group only after the IRET
            back to the same poll point (rt_irq_back at this stack depth)."""
            nonlocal makes
            key = self.irqs[self.irq_i][:3]
            self.posted_at = (key[1], len(self.services), a7)     # for done()
            if self.hooking and not self.irq_lost:
                # the runtime holds interrupts while the keyboard intercept runs
                # (rt_irq0_running): the reference took this one inside it
                self.irq_lost = f"reference irq #{self.irq_i} at {key[1]} inside the keyboard " \
                                f"intercept (held to its IRET here)"
            if self.sabotage == "sb-irq" and self.irq_i == 0:
                self.post(0x0F)
            while self.irq_i < len(self.irqs) and self.irqs[self.irq_i][:3] == key:
                vector = self.irqs[self.irq_i][3]
                guest = self.guest_vector(vector)
                if vector == 9:
                    self.key_fill()
                    self.key_posted += 1
                    if self.key_posted > self.key_sent and not self.irq_lost:
                        self.irq_lost = f"reference irq #{self.irq_i} (IRQ 1) with no scripted scan byte"
                    makes += 1
                    vector = 9 if makes % 2 else 0x89  # make, then the key's break
                self.post(vector)
                self.irq_i += 1
                if guest:
                    self.groups[a7 - 12] = key  # a7 at rt_irq_back: jsr rt_irq, movem d6-d7
                    self.posted_at = None       # back() resumes it, not done()
                    return

        @U.CODE_CB
        def back(h, addr, size, user):
            if self.sfx_cap:
                return
            try:
                stack = self.r("a7")
                key = self.groups.pop(stack, None)
                if key and self.irq_i < len(self.irqs):
                    n = len(self.services)
                    if n != self.visit_n:
                        self.visit_n, self.visits = n, {}
                    # IRET returns before the instruction. Handler visits or
                    # services may make a new count eligible at this point.
                    resume = (n, key[1], self.visits.get(key[1], 0))
                    if self.irqs[self.irq_i][:3] == resume:
                        post_group(stack + 12)
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        @U.CODE_CB
        def done(h, addr, size, user):
            if self.sfx_cap:
                return
            # rt_irq_done: the posted interrupts ran BIOS handlers only. A service
            # the keyboard intercept made inside them (INT 16h, WC2.EXE+0FEA5)
            # starts a new interval, and the reference took the next interrupt at
            # the IRET back to the poll point (visit 0): post it and poll again
            # (rt_irq with the poll's return address and d6/d7, as from the poll).
            # Only the exit of the poll's own rt_irq call: the intercept's drain
            # loop (+0FEA3..+0FEAD) polls too, inside it (a7 deeper)
            try:
                at = self.posted_at
                if at is None or self.r("a7") + 4 != at[2]:
                    return
                self.posted_at = None
                if self.irq_i == len(self.irqs) or len(self.services) == at[1]:
                    return
                n = len(self.services)
                if n != self.visit_n:
                    self.visit_n, self.visits = n, {}
                if self.irqs[self.irq_i][:3] == (n, at[0], self.visits.get(at[0], 0)):
                    post_group(self.r("a7") + 4)    # a7 at the poll: before jsr rt_irq
                    self.e.reg_write(U.M68K["pc"], self.syms["rt_irq"])
            except Exception as e:  # ctypes drops exceptions raised in hooks
                self.irq_lost = f"interrupt replay: {e!r}"
                self.halted = True
                self.e.stop()

        self.posted_at = None
        if "rt_irq_done" in self.syms:
            self.e.hook_range(U.HOOK_CODE, done, self.syms["rt_irq_done"], self.syms["rt_irq_done"])

        # The poll entry precedes interrupt delivery; _np is the actual
        # instruction continuation, including returns from guarded copies.
        continuations = {}
        for lab in {r[1] for r in self.irqs if r[1] != IDLE} | rep_labels:
            for name in (lab + "_np", lab + "_bp_np"):
                if name in self.syms:
                    continuations[self.syms[name]] = lab
            if lab + "_np" not in self.syms:
                raise ValueError(f"missing replay execution continuation: {lab}")

        @U.CODE_CB
        def executed(h, addr, size, user):
            if self.sfx_cap:
                return
            n = len(self.services)
            if n != self.visit_n:
                self.visit_n, self.visits = n, {}
            here = continuations[addr]
            self.visits[here] = self.visits.get(here, 0) + 1

        for a in continuations:
            self.e.hook_range(U.HOOK_CODE, executed, a, a)

        if rep is not None:
            @U.CODE_CB
            def rep_checkpoint(h, addr, size, user):
                if self.sfx_cap:            # the capture's driver code: no interrupt cuts it
                    self.e.write(self.r("a7") + 4, struct.pack(">I", 0))
                    return
                try:
                    sp = self.r("a7")
                    point, done = struct.unpack(">II", self.mem(sp + 4, 8))
                    lab = rep.labels[point]
                    regs = tuple(self.r(r) & 0xffff for r in ("d1", "a4", "a5"))
                    resumed = rep.checkpoint(point, regs, len(self.services),
                                             self.visits.get(lab, 0), done)
                    self.e.write(sp + 4, struct.pack(">I", int(resumed)))
                except Exception as error:
                    self.irq_lost = f"REP replay: {error}"
                    self.e.stop()
            a = self.syms["rt_replay_rep"]
            self.e.hook_range(U.HOOK_CODE, rep_checkpoint, a, a)

        # static hooks (Unicorn retranslates on every hook change)
        for a in {a for t, _ in steps for a in at[t[0]]}:
            self.e.hook_range(U.HOOK_CODE, hit, a, a)
        for a in {a for _, lab, _, _ in self.irqs for a in at[lab]}:
            self.e.hook_range(U.HOOK_CODE, poll, a, a)
        self.e.hook_range(U.HOOK_CODE, back, self.syms["rt_irq_back"], self.syms["rt_irq_back"])
        self.e.reg_write(U.M68K["sr"], 0x2700)
        self.e.reg_write(U.M68K["a7"], STACK_TOP)
        self.halted = False
        # watchdog: a problem the checks will report stops the run at once, and so
        # does a stall (no service event and no replayed interrupt for self.stall s)
        done = threading.Event()

        def watchdog():
            last, since = None, time.monotonic()
            while not done.wait(1.0):
                why = self.problem_now()
                if why:
                    self.early = self.early or why
                    self.e.stop()
                    return
                now = (len(self.services), self.irq_i)
                if now != last:
                    last, since = now, time.monotonic()
                elif time.monotonic() - since > self.stall:
                    self.stalled = f"stalled: no service event or replayed interrupt for {self.stall} s " \
                                   f"(service events {now[0]}, interrupts replayed {now[1]})"
                    self.e.stop()
                    return

        guard = threading.Thread(target=watchdog, daemon=True)
        guard.start()
        try:
            err = self.e.start(self.entry, 0xFFFFFFFF, timeout_us=timeout * 1_000_000)
        finally:
            done.set()
            guard.join()
        if self.stalled:
            self.stalled += f" at {self.where()}"
        if err:
            print(f"unicorn error {U.uc.uc_strerror(err).decode()} pc={self.r('pc'):x}")
            self.exit = -1
        if self.irq_i < len(self.irqs) and self.irqs[self.irq_i][0] < len(self.services) \
                and not self.irq_lost:
            svc, lab, hits, _ = self.irqs[self.irq_i]
            self.irq_lost = f"reference irq #{self.irq_i} at {lab} svc={svc} hits={hits} " \
                            f"not reached (service events {len(self.services)})"


def psp_arguments(launch: str) -> dict[int, bytes]:
    """PSP bytes by offset for a shell command line `WC2 ARGS`: the command
    tail at 80h (length, the text after the program name, CR) and FCBs 1 and 2
    at 5Ch and 6Ch as COMMAND.COM fills them (INT 21h AH=29h: drive 0, the name
    upper-cased and blank-padded). MEASURED for `WC2 Origin -k` (host-m5's
    snapshot: tail 0A " Origin -k" 0D, FCBs ORIGIN and -K); names with a drive,
    an extension or wildcards are not modelled."""
    prog, _, tail = launch.partition(" ")
    if prog.upper() != "WC2":
        raise ValueError(f"launch of {prog}: the host runs WC2.EXE")
    text = (" " + tail).encode("ascii") if tail else b""
    if len(text) > 126:
        raise ValueError("command tail longer than 126 bytes")
    out = {0x80: bytes([len(text)]) + text + b"\r"}
    words = tail.split()
    for k, off in enumerate((0x5C, 0x6C)):
        name = words[k].upper() if k < len(words) else ""
        if len(name) > 8 or any(c in name for c in ":.*?"):
            raise ValueError(f"FCB argument {name!r} not modelled")
        out[off] = b"\0" + name.ljust(11).encode("ascii")
    return out


def trigger(spec: str) -> tuple[str, int, int]:
    """MODULE+HEX[#N] -> (label, offset, N)."""
    at, _, n = spec.partition("#")
    mod, off = at.split("+")
    off = off.removeprefix("0x")
    return emit.label(mod, int(off, 16)), int(off, 16), int(n or 1)


def milestone_script(name: str) -> dict:
    """reference/milestones.csv row: the run stops at the last snapshot trigger;
    keys (those of `after`, then its own: tools/reference.py) are pressed in order,
    each counted from the previous key's release (the tracer's rules); the frame
    is compared at vga_mode 13; speech: the reference took IRQ 7 (irqs 0f)."""
    rows = {r["name"]: r for r in csv.DictReader(TABLE.open())}
    r = rows[name]
    keys = []
    for k in filter(None, r["keys"].split(";")):
        # a per-key hold (KEY*N) is the recorder's: the release replays from the
        # reference's key_up event (KeyRelease), whatever the hold
        k, _, hold = k.partition("*")
        if hold and not (hold.isdigit() and int(hold) > 0):
            raise SystemExit(f"{name}: invalid per-key hold *{hold}")
        spec, _, key = k.rpartition("=")
        keys.append((trigger(spec), key if key.startswith(("mx", "my", "mb")) else key_code(key)))
    return {"keys": keys, "snapshots": [trigger(t) for t in r["snapshots"].split()],
            "launch": r["launch"].partition(" ")[2] and r["launch"],
            "frame": r["vga_mode"] == "13", "speech": "0f" in r["irqs"].split()}


def reference_hooks(trace: Path) -> Counter:
    """AX at each INT 15h the reference BIOS's INT 09h made (interrupts.csv: from
    F000:E98F's stub, DOSBox-X CB_IRQ1) into a guest handler."""
    out: Counter = Counter()
    with (trace / "interrupts.csv").open() as f:
        for r in csv.DictReader(f):
            if r["vector"] == "0x15" and r["source_module"] == "-" and r["source_offset"] == "0xfe98f" \
                    and r["target_module"] != "-":
                out[int(r["ax"], 16)] += int(r["count"])
    return out


def reference_rom() -> bytes:
    """The reference machine's BIOS ROM: the m0 snapshot's F0000h..FFFFFh (the
    WC2.EXE entry; byte-identical in every reference snapshot, m0 to m6: MEASURED)."""
    ram = RUNS / "ref-m0-a/trace/snap-m0-0/ram.bin"
    if not ram.exists():
        raise SystemExit("no m0 reference for the BIOS ROM: python3 tools/reference.py m0")
    return ram.read_bytes()[ROM[0]:ROM[1]]


def host_reference(milestone: str) -> Path:
    """The host reference run's trace (tools/reference.py --host)."""
    run = RUNS / f"host-{milestone}"
    if not (run / "trace").is_dir():
        raise SystemExit(f"no host reference for {milestone}: python3 tools/reference.py --host {milestone}")
    return run / "trace"


def reference_blocks(trace: Path) -> tuple[list[tuple[int, int, int]], list[float]]:
    """The Sound Blaster blocks the reference's DSP and DMA writes start
    (trace/sound.csv, `pc_run.py --opl`; decoded here independently of ports.c):
    (linear, length, rate) per 14h command, and per block that the reference ended
    (the handler's next 22Eh acknowledge read) the time from its last length byte
    to that read minus length / rate, in ms."""
    blocks, late = [], []
    flip, addr, count, page, tc, command, args, start = 0, 0, 0, 0, 0, None, [], None
    with (trace / "sound.csv").open() as f:
        for r in csv.DictReader(f):
            port, v, ms = int(r["port"], 16), int(r["value"], 16), float(r["ms"])
            if r["direction"] == "in":
                if port == 0x22E and start is not None:
                    late.append(ms - start[0] - 1000 * start[1])
                    start = None
                continue
            if port in (0x02, 0x03):
                old = addr if port == 0x02 else count
                new = (old & 0xFF) | v << 8 if flip else (old & 0xFF00) | v
                addr, count = (new, count) if port == 0x02 else (addr, new)
                flip ^= 1
            elif port == 0x0C:
                flip = 0
            elif port == 0x83:
                page = v
            elif port == 0x22C and command is not None:
                args.append(v)
                if command == 0x40:
                    tc, command = v, None
                elif len(args) == 2:
                    length, rate = (args[0] | args[1] << 8) + 1, 1000000 // (256 - tc)
                    blocks.append((page << 16 | addr, length, rate))
                    start, command = (ms, length / rate), None
            elif port == 0x22C and v in (0x40, 0x14):
                command, args = v, []
    return blocks, late


def port_runs(trace: Path, ports: tuple[int, ...]) -> list[tuple[int, int, int]]:
    """(service events, value, reads) runs of the module reads of `ports`
    (trace/replay-ports.csv, `pc_run.py --replay-ports`)."""
    with (trace / "replay-ports.csv").open() as f:
        return [(int(r["service"]), int(r["value"], 16), int(r["count"])) for r in csv.DictReader(f)
                if int(r["port"], 16) in ports]


class NoMonitor:
    """No IRQ0 footprint (gen.IRQ_PROOF off, open-work 9): interrupts are taken
    at poll points only, so no handler runs inside main code's accesses."""

    def deliver(self): pass
    def returned(self): pass
    def read(self, lin, size): pass
    def write(self, lin, size, value=None): pass

    def finish(self, path) -> list[str]:
        print("irq monitor: no footprint (IRQ_PROOF off): not run")
        return []


def machine_ranges() -> list[tuple[int, int]]:
    """Guest memory outside COMPARE."""
    out, at = [], 0
    for lo, hi in sorted(COMPARE + [FRAME, IRQ_STACK]):
        out.append((at, lo))
        at = hi
    return [(lo, hi) for lo, hi in out + [(at, GUEST_BYTES)] if lo < hi]


IRQ_SS, IRQ_SP = 0xB000, 0x8000   # runtime.h RT_IRQ_SS, RT_IRQ_SP (I4)


def relocated(g: dict) -> tuple[dict, list[str]]:
    """A service inside IRQ0's handler (owner decision 2026-11-10, docs/design.md):
    ours runs on the private stack IRQ_SS:IRQ_SP, the reference on the interrupted
    SS:SP. SS must be IRQ_SS and stands for the interrupted SS; SP, and BP while it
    points into the private stack (SP <= BP <= IRQ_SP), are their offsets below
    IRQ_SP applied to the interrupted SP. Every other register compares as is."""
    if "irq" not in g:
        return g, []
    if g["ss"] != IRQ_SS:
        return g, [f"ss={g['ss']:04x} in IRQ0's handler, not the private stack {IRQ_SS:04x}"]
    ss, sp = g["irq"]
    r = dict(g, ss=ss, sp=(g["sp"] - IRQ_SP + sp) & 0xFFFF)
    if g["sp"] <= g["bp"] <= IRQ_SP:
        r["bp"] = (g["bp"] - IRQ_SP + sp) & 0xFFFF
    return r, []


def undefined_flags() -> dict:
    """annotations/undefined-flags.csv: (module, INT offset) -> {register: bits}
    of a FLAGS image an undefined flag reached (translation lesson 39)."""
    out: dict = {}
    for r in image.rows("undefined-flags.csv"):
        out.setdefault((r["module"], int(r["offset"], 16)), {})[r["register"]] = int(r["mask"], 16)
    return out


class ServiceCheck:
    """One service event at a time against the reference's (compare_services).
    CF/ZF: services read no flags, so the state block may hold dead ones at
    entry; at return they are checked where the reference service changed them
    or where they agreed at entry. Services in IRQ0's handler: relocated().
    A register bit of `masks` (undefined_flags()) is not compared at that INT
    and its return; each difference it hid goes to `applied`."""

    KEYS = REGS + ("es", "ss", "ds", "vector")

    def __init__(self, masks: dict | None = None, applied: list | None = None):
        self.masks = undefined_flags() if masks is None else masks
        self.applied = applied
        self.entry: list = []

    def add(self, k: int, got, want) -> str | None:
        (gk, g), (wk, w) = got, want
        g, diff = relocated(g)
        if gk == "svc":
            mask = self.masks.get(w.get("site"), {})
        else:
            mask = self.masks.get(self.entry[-1][1].get("site"), {}) if self.entry else {}
        for n in self.KEYS:
            m = mask.get(n, 0)
            if (g[n] ^ w[n]) & ~m & 0xFFFF:
                diff.append(f"{n}={g[n]:04x}/{w[n]:04x}")
            elif g[n] != w[n] and self.applied is not None:
                self.applied.append((k, n, g[n], w[n]))
        flags = w["flags"]
        if gk == "svc":
            self.entry.append((g, w))
        else:
            ge, we = self.entry.pop() if self.entry else (g, w)
        for n, bit in (("cf", 0x1), ("zf", 0x40), ("if", 0x200), ("df", 0x400)):
            ref = int(bool(flags & bit))
            if n in ("cf", "zf"):
                if gk == "svc":
                    continue
                if int(bool(we["flags"] & bit)) == ref and ge[n] != ref:
                    continue
            if g[n] != ref:
                diff.append(f"{n}={g[n]}/{ref}")
        if gk != wk or diff:
            return f"service #{k} {wk} int {w['vector']:02x} ax={w['ax']:04x}: {' '.join(diff) or gk}"
        return None


def compare_services(got, want, masks: dict | None = None, applied: list | None = None) -> list[str]:
    """The service log against the reference's (ServiceCheck), and its length."""
    check = ServiceCheck(masks, applied)
    for k, (g, w) in enumerate(zip(got, want)):
        bad = check.add(k, g, w)
        if bad:
            return [bad]
    if len(got) != len(want):
        return [f"service count {len(got)} vs reference {len(want)}"]
    return []


class ServiceLog(list):
    """The host's service events; with the reference's, each is compared as it
    is logged (ServiceCheck) and the first difference, or an event past the
    reference's last, stops the run (Host.stop_early). The full comparison after
    the run (compare_services) reports it."""

    def __init__(self, host=None, want=None):
        super().__init__()
        self.host, self.want = host, want
        self.check = ServiceCheck() if want is not None else None
        self.bad: str | None = None

    def append(self, item) -> None:
        super().append(item)
        if self.check is None or self.bad:
            return
        k = len(self) - 1
        if k >= len(self.want):
            self.bad = f"service event #{k} past the reference's {len(self.want)}"
        else:
            self.bad = self.check.add(k, item, self.want[k])
        if self.bad:
            self.host.stop_early(self.bad)


def compare_ram(ram: bytes, ref: bytes, residency: Path, masked: set[int]) -> list[str]:
    rows = image.M.residency(residency)
    bad, total = [], 0
    for lo, hi in COMPARE:
        k = lo
        while k < hi:
            if ram[k] == ref[k] or k in masked:
                k += 1
                continue
            j = k
            while j < hi and (ram[j] != ref[j] or j + 1 < hi and ram[j + 1] != ref[j + 1]):
                j += 1
            total += j - k
            where = image.M.locate(rows, k)
            owner = f"{where[0]}+{where[1]:05X}" if where else "-"
            if len(bad) < 40:
                bad.append(f"ram {k:05X}..{j:05X} ({owner}): ours {ram[k:min(j, k + 12)].hex()} "
                           f"ref {ref[k:min(j, k + 12)].hex()}")
            k = j
    if total:
        bad.append(f"{total} bytes differ")
    return bad


def compare_frame(ram: bytes, dac: bytes, snap: Path, size: int = FRAME[1] - FRAME[0]) -> list[str]:
    planes = (snap / "vram.bin").read_bytes()
    lo = FRAME[0]
    ref = bytes(planes[((a & ~3) << 2) | (a & 3)] for a in range(size))
    bad = [a for a in range(size) if ram[lo + a] != ref[a]]
    out = [f"frame: {len(bad)} bytes differ, first at A000:{bad[0]:04X} ours "
           f"{ram[lo + bad[0]]:02x} reference {ref[bad[0]]:02x}"] if bad else []
    want = (snap / "dac.bin").read_bytes()
    bad = [k for k in range(256) if dac[k * 3:k * 3 + 3] != want[k * 3:k * 3 + 3]]
    if bad:
        k = bad[0]
        out.append(f"DAC: {len(bad)} entries differ, first {k:02x} ours {dac[k * 3:k * 3 + 3].hex()} "
                   f"reference {want[k * 3:k * 3 + 3].hex()}")
    return out


def compare_shown(capture: Path, bytes_per_row: int, snap: Path) -> list[str]:
    """The Amiga screen: 8 bitplanes, plane k = bit k of the pixel; colours =
    LoadRGB32 (count << 16, first 0), 32-bit guns whose top 6 bits are the DAC."""
    if not bytes_per_row:
        return ["amiga: no screen shown"]
    planes = [(capture / f"plane{k}.bin").read_bytes() for k in range(8)]
    lo, hi = FRAME
    shown = bytearray(320 * 200)
    for y in range(200):
        for xb in range(40):
            bits = [p[y * bytes_per_row + xb] for p in planes]
            for b in range(8):
                shown[y * 320 + xb * 8 + b] = sum(((bits[k] >> (7 - b)) & 1) << k for k in range(8))
    words = struct.unpack(f">{1 + 768 + 1}I", (capture / "colours.bin").read_bytes())
    dac = bytearray(w >> 26 for w in words[1:769])
    out = []
    if words[0] != 256 << 16:
        out.append(f"amiga: LoadRGB32 header {words[0]:08x}")
    dac = bytes(dac)
    ram = bytes(lo) + bytes(shown) + bytes(hi - lo - len(shown))
    out += [f"amiga shown: {p}" for p in compare_frame(ram, dac, snap, len(shown))]
    return out


# The emulator's own picture: a one-field trace screenshot of the native FS-UAE
# (tests/amiga_replay.py), 754x576 with the 320x200 screen at 2x2 from (74, 60)
# (DIWSTRT $3881). Composed planes and sprite words cannot show what the
# chipset does with them (a fetch window that took the sprites' DMA slots).
VIDEO_SIZE, VIDEO_ORIGIN = (754, 576), (74, 60)


def compare_video(png: Path, snap: Path) -> list[str]:
    """Every screen pixel of the real video against the DOSBox frame's colour
    (6-bit DAC guns as g << 2 | g >> 4), exactly."""
    from PIL import Image
    picture = Image.open(png).convert("RGB")
    if picture.size != VIDEO_SIZE:
        return [f"video: screenshot size {picture.size}, expected {VIDEO_SIZE}"]
    px = picture.load()
    planes = (snap / "vram.bin").read_bytes()
    dac = (snap / "dac.bin").read_bytes()
    rgb = [tuple(g << 2 | g >> 4 for g in dac[3 * k:3 * k + 3]) for k in range(256)]
    ox, oy = VIDEO_ORIGIN
    bad = []
    for a in range(320 * 200):
        x, y = a % 320, a // 320
        want = rgb[planes[((a & ~3) << 2) | (a & 3)]]
        if any(px[ox + 2 * x + i, oy + 2 * y + j] != want for i in (0, 1) for j in (0, 1)):
            bad.append(a)
    if not bad:
        return []
    a = bad[0]
    return [f"video: {len(bad)} of 64000 pixels differ from the DOSBox frame, first x={a % 320} "
            f"y={a // 320} shown {px[ox + 2 * (a % 320), oy + 2 * (a // 320)]}"]


def check_capture(tag, regs, state, ram, dac, ref_regs, ref, snap, h, irq=None) -> list[str]:
    """Registers (state block: segments), RAM, framebuffer and DAC (dac None:
    not compared) of one capture vs the snapshot. irq: the interrupted SS:SP
    when the capture is inside IRQ0's handler (relocated(), design D8)."""
    problems = []
    seg = {"es": state[4:6], "ss": state[2:4], "ds": state[0:2]}  # G_ES +5, G_SS +3, G_DS +1
    regs = dict(regs, **{n: int.from_bytes(v, "big") for n, v in seg.items()})
    if irq is not None:
        regs, problems = relocated(dict(regs, irq=irq))
        problems = [f"{tag}: {p}" for p in problems]
    for n in REGS + ("es", "ss", "ds"):
        if regs[n] != int(ref_regs[n], 16):
            problems.append(f"{tag}: register {n} {regs[n]:04x} reference {ref_regs[n]}")
    dead = sum(ram[a] != ref[a] for a in h.masked if a < len(ref))
    print(f"{tag}: dead stack {len(h.masked)} bytes masked, {dead} of them differ")
    problems += [f"{tag}: {p}" for p in compare_ram(ram, ref, snap / "residency.csv",
                                                     h.masked)]
    if dac is not None:
        problems += [f"{tag}: {p}" for p in compare_frame(ram, dac, snap)]
    reads = sorted(a for a in h.machine_reads if a < len(ref) and ram[a] != ref[a])
    print(f"{tag}: machine bytes read by the guest {len(h.machine_reads)}, {len(reads)} differ")
    print(f"{tag}: EMS mapping changed over an interrupt's handler "
          f"{int.from_bytes(h.mem(h.syms['rt_ems_irq_remaps'], 4), 'big')} times (ems.c rt_ems_irq_leave)")
    for a in reads[:20]:
        pc, n = h.machine_reads[a]
        problems.append(f"{tag}: machine byte {a:05X} read by the guest: ours {ram[a]:02x} "
                        f"reference {ref[a]:02x}, first at {h.where(pc)} after service {n}")
    return problems


# --sfx-capture plants (each must fail the check; tests/host_run.py --sfx-capture NAME):
# "restore" leaves a DGROUP byte changed after the capture; "tick", "value" and "end"
# alter the first captured id after it ran; "starts" counts a start inside it.
SFX_SABOTAGE = ("restore", "tick", "value", "end", "starts")


def sfx_problems(h: "Host", plant: str) -> list[str]:
    """Every capture (src/runtime/sfx.c) against tools/sfx_capture.py: STRAX.DRV and
    the game's effect code under Unicorn x86 from the guest RAM at the hook (the
    sound init's return); and the guest RAM after the capture equal to the RAM at
    the hook."""
    import sfx_capture as X
    if not h.sfx_captures:
        return ["effect capture: the sound init's hook (WC2.EXE+13771) was not reached"]
    problems = []
    for n, c in enumerate(h.sfx_captures):
        if c["after"] != c["ram"]:
            diff = [a for a in range(len(c["ram"])) if c["ram"][a] != c["after"][a]]
            problems.append(f"effect capture {n}: {len(diff)} guest bytes not restored, first "
                            f"{diff[0]:05x}: {c['ram'][diff[0]]:02x} -> {c['after'][diff[0]]:02x}")
        if n == 0 and any(c["starts"]):
            problems.append(f"effect capture 0: starts counted at the sound init: "
                            f"{[i for i, k in enumerate(c['starts']) if k]} (the capture's starts counted)")
        opl0, want = X.capture(c["ram"], c["ds"])
        got = dict(c["ids"])
        if plant in ("tick", "value", "end"):
            sid = next(i for i in sorted(want) if want[i][0])
            w, end = got[sid]
            t, r, v = w[0]
            got[sid] = ([(t + (plant == "tick"), r, v ^ (plant == "value"))] + w[1:], end + (plant == "end"))
        for sid in range(len(got)):
            ours, ours_end = got[sid]
            writes, end = want.get(sid, ([], 0))
            if ours_end != end or ours != writes:
                k = next((k for k, (a, b) in enumerate(zip(ours, writes)) if a != b), min(len(ours), len(writes)))
                problems.append(f"effect capture {n} id {sid}: end tick {ours_end}, {len(ours)} writes; "
                                f"the original's {end}, {len(writes)}; first difference at write {k}: "
                                f"{ours[k] if k < len(ours) else '-'} vs {writes[k] if k < len(writes) else '-'}")
        if c["opl"] != opl0:
            problems.append(f"effect capture {n}: start registers differ from the oracle's")
        print(f"effect capture {n}: {len(want)} ids, {sum(len(w) for w, _ in got.values())} writes, "
              f"{sum(1 for i in want if not got[i][1])} without an end", flush=True)
    return problems


def main(argv=None) -> int:
    global TABLE
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", default="m1")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds of emulation before failing")
    ap.add_argument("--stale-polls", action="store_true",
                    help="diagnostic: run on a reference recorded with other poll points (never passes)")
    ap.add_argument("--stall", type=int, default=300,
                    help="seconds without a service event or replayed interrupt before failing")
    ap.add_argument("--amiga", type=Path, help="also check this A1200-model capture")
    ap.add_argument("--label", action="store_true", help="print the milestone's label and exit")
    ap.add_argument("--sabotage", action="store_true",
                    help="each planted runtime fault (SABOTAGE) must fail the check")
    ap.add_argument("--plants", help="with --sabotage: only these (comma-separated)")
    ap.add_argument("--table", type=Path, default=TABLE,
                    help="the milestone table (tools/reference.py --table; a diagnostic one in tmp/)")
    ap.add_argument("--sfx-capture", nargs="?", const="on", choices=("on",) + SFX_SABOTAGE,
                    help="turn the effect capture on (src/runtime/sfx.c) and compare every capture "
                         "with tools/sfx_capture.py; a plant name must fail")
    args = ap.parse_args(argv)
    TABLE = args.table.resolve()
    if args.label:
        print(milestone_script(args.milestone)["snapshots"][-1][0])
        return 0
    if args.sabotage:
        missed = []
        names = args.plants.split(",") if args.plants else list(SABOTAGE)
        for name in names:
            what = SABOTAGE[name]
            if not args.plants and name in SPEECH and not milestone_script(args.milestone)["speech"]:
                continue
            if not args.plants and name in KEYED and not any(
                    isinstance(k, int) for _, k in milestone_script(args.milestone)["keys"]):
                continue
            if not args.plants and name in IDLED and not idle_stacks(host_reference(args.milestone)):
                continue
            problems = check(args.milestone, args.timeout, None, name, stall=args.stall)
            catch = SABOTAGE_CATCH.get(name, "")
            hit = [p for p in problems if catch in p]
            print(f"sabotage {name:12} ({what}): {len(problems)} problems, first: "
                  f"{hit[0] if hit else problems[0] if problems else '-'}", flush=True)
            if not hit:
                missed.append(name)
        print("not caught: " + ", ".join(missed) if missed else "all sabotages caught")
        return 1 if missed else 0
    problems = check(args.milestone, args.timeout, args.amiga, None, stall=args.stall,
                     stale_polls=args.stale_polls, sfx=args.sfx_capture)
    for p in problems:
        print(p)
    if args.sfx_capture in SFX_SABOTAGE:
        print(f"effect capture plant {args.sfx_capture}: {'caught' if problems else 'MISSED'}")
        return 0 if problems else 1
    print(f"host run to {args.milestone}: {'ok' if not problems else 'FAIL'}")
    return 1 if problems else 0


def overlay_problems(sabotage: str | None = None) -> list[str]:
    """machine.c rt_lookup finds overlay code at the CS its stub's word 10h holds
    (the manager's residency record): for each overlay alone at a buffer CS,
    every entry of its rows must return its row; at a CS no stub holds, none."""
    h, problems = Host(image.M.REF, sabotage), []
    ret = h.syms["plat_exit"]  # stop address, never executed
    h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
    n = h.u32(h.syms["dispatch_count"])
    craw = Host(image.M.REF).mem(h.syms["dispatch_table"], 12 * n)  # unplanted
    count = h.u32(h.syms["overlay_count"])
    stubs = struct.unpack(f">{count}H", Host(image.M.REF).mem(h.syms["overlay_stubs"], 2 * count))
    rows: dict[int, list[tuple[int, int]]] = {}
    for j in range(n):
        cs, ip, overlay, _far, code = struct.unpack_from(">HHHHI", craw, 12 * j)
        if overlay:
            rows.setdefault(overlay, []).append((ip, code))
    if not rows:
        return ["overlay probe: no overlay rows"]
    buffer = 0x6000

    def lookup(cs, ip):
        h.e.write(STACK_TOP - 16, ret.to_bytes(4, "big") + cs.to_bytes(4, "big")
                  + ip.to_bytes(4, "big") + (0).to_bytes(4, "big"))
        h.e.reg_write(U.M68K["sr"], 0x2700)
        h.e.reg_write(U.M68K["a7"], STACK_TOP - 16)
        h.e.start(h.syms["rt_lookup"], ret, timeout_us=1_000_000)
        return h.r("d0") if h.r("pc") == ret else None

    for k, stub in enumerate(stubs):
        for other in stubs:
            h.e.write(TOP - (other * 16 + 0x10) - 1, (buffer if other == stub else 0).to_bytes(2, "little")[::-1])
        for ip, code in rows.get(k + 1, ()):
            got = lookup(buffer, ip)
            if got != code:
                problems.append(f"rt_lookup {buffer:04x}:{ip:04x} with overlay {k + 1} (stub "
                                f"{stub:04x}) at {buffer:04x}: {got if got is None else hex(got)}, "
                                f"want {code:x}")
                break
        if len(problems) > 5:
            break
    return problems


def rearm_problems() -> list[str]:
    """runtime.h poll-point contract on the C path the replay never reaches (it
    posts only where the reference took the interrupt, so with IF set):
    rt_set_flags_word with IF set re-arms G_IRQ from rt_irq_pending."""
    h, problems = Host(image.M.REF), []
    ret = h.syms["plat_exit"]  # stop address, never executed
    h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
    for flags in (0x0002, 0x0202):
        for pending in (0, 1):
            h.e.write(G_IRQ, b"\0")
            h.e.write(h.syms["rt_irq_pending"], bytes([pending]))
            h.e.write(STACK_TOP - 8, ret.to_bytes(4, "big") + flags.to_bytes(4, "big"))
            h.e.reg_write(U.M68K["sr"], 0x2700)  # first: it selects which a7
            h.e.reg_write(U.M68K["a7"], STACK_TOP - 8)
            h.e.start(h.syms["rt_set_flags_word"], ret, timeout_us=1_000_000)
            got, want = h.mem(G_IRQ, 1)[0], int(bool(flags & 0x200) and pending)
            if h.r("pc") != ret or got != want:
                problems.append(f"rt_set_flags_word({flags:04x}) with rt_irq_pending {pending}: "
                                f"G_IRQ {got}, want {want} (pc={h.r('pc'):x})")
    return problems


def check_opl(h, trace: Path, counts: bool = True) -> list[str]:
    """The host's AdLib writes, per port and value, are the reference's
    (ports.csv of the same run); rt_opl and rt_opl_keyon hold the registers and
    key-on edges (B0-B8 bit 5 rising) of the host's write sequence."""
    want: dict[tuple[int, int], int] = {}
    for r in csv.DictReader((trace / "ports.csv").open()):
        if r["direction"] == "out" and r["port"] in ("0x0388", "0x0389"):
            k = (int(r["port"], 16), int(r["value"], 16))
            want[k] = want.get(k, 0) + int(r["count"])
    got: dict[tuple[int, int], int] = {}
    for port, v in h.opl_ports:
        got[(port, v)] = got.get((port, v), 0) + 1
    data = sum(n for (p, _), n in want.items() if p == 0x389)
    print(f"OPL: {len(h.opl)} writes, {data} in the reference")
    if counts and got != want:
        diff = sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k))
        return [f"OPL: {len(diff)} port/value counts differ, first {diff[0][0]:x}={diff[0][1]:02x}: "
                f"{got.get(diff[0], 0)} vs {want.get(diff[0], 0)}"]
    regs, edges = bytearray(256), bytearray(9)
    for reg, v in h.opl:
        if 0xB0 <= reg <= 0xB8 and v & 0x20 and not regs[reg] & 0x20:
            edges[reg - 0xB0] = (edges[reg - 0xB0] + 1) & 0xFF
        regs[reg] = v
    problems = []
    if h.mem(h.syms["rt_opl"], 256) != bytes(regs):
        problems.append("OPL: rt_opl differs from the writes")
    if h.mem(h.syms["rt_opl_keyon"], 9) != bytes(edges):
        problems.append(f"OPL: rt_opl_keyon {list(h.mem(h.syms['rt_opl_keyon'], 9))}, "
                        f"key-on edges {list(edges)}")
    print(f"OPL: key-on edges per channel {list(edges)}")
    return problems


def reference_clocks(trace):
    """Use recorded external inputs; old captures retain their unpinned clocks."""
    with events(trace) as f:
        arm = next(csv.DictReader(f))
    assert arm['kind'] == 'arm', arm
    detail = dict(kv.split('=', 1) for kv in arm['detail'].split())
    calendar = None
    if 'dos_date' in detail:
        y, m, d = map(int, detail['dos_date'].split('-'))
        calendar = y << 16 | m << 8 | d
    source = trace.parent / 'clock-inputs.json'
    clock = None
    if source.exists():
        fields = json.loads(source.read_text())
        assert fields['basis'] == 'local calendar'
        clock = time.mktime(time.strptime(fields['host_file_clock'], '%Y-%m-%dT%H:%M:%S'))
    return calendar, clock


EMS_FRAME, EMS_PAGE = 0xE0000, 0x4000
EMS_STORE, EMS_STORE_PAGES = STATE + 16, 64   # ems.c store(): RT_STATE_BYTES, RT_EMS_STORE_PAGES
IRQ0_HANDLER = 0x17F50000                     # CS:IP of INT 08h's handler on m4-m6 (irq monitor)


def host_ems_pages(h) -> dict:
    """The EMS model's frame pages not yet copied in (ems.c: rt_ems_live 0), as
    their mapped store pages show them, guest order."""
    mapped = struct.unpack(">4H", h.mem(h.syms["rt_ems_mapped"], 8))
    live = h.mem(h.syms["rt_ems_live"], 4)
    # ems.c store(): slot s at RT_EMS_STORE_PAGES (64) - s pages after the state block
    return {k: h.mem(EMS_STORE + (EMS_STORE_PAGES - mapped[k]) * EMS_PAGE, EMS_PAGE)[::-1]
            for k in range(4) if mapped[k] and not live[k]}


def ems_guard_problems(elf: Path | None, sabotage: str | None = None) -> list[str]:
    """The EMS guard's routing on the run's own image (rt_entry.s EMS_GUARD,
    ems.c guard and refresh), where the m68k differential stubs it: frame
    pages mapped by the real INT 67h, then rt_ems_es and rt_ems_ds with ES or
    DS E030h. A range across two frame pages (DI 3C00h, 140h bytes: a REP row)
    runs on the store when they map consecutive store pages (one displacement,
    ems.c store), and otherwise takes the C path with its byte count, so both
    pages are copied in and the base is plain; a range within one page runs on
    its store page; with the pages live (DS E000h's load, rt_ems_seg) on the
    frame. From X-Wing 5f720a2. Then the one-entry caches (X-Wing 4c50051):
    another access within the page hits (the same base), a remap empties them
    (the new page's base), and over IRQ0's handler, which fills them with its
    own segment, they come back as they were."""
    problems = []
    plain = TOP - 0x7FFF - 0xE0300
    frame0 = TOP - (EMS_FRAME + EMS_PAGE) + 1
    for name, slot in (("rt_ems_es", G_ES), ("rt_ems_ds", G_DS)):
        for d7, d6, order, want_live, expose in (
                (0x3C00, 0x140, (0, 1), (0, 0), False), (0x3C00, 0x140, (1, 0), (1, 1), False),
                (0x0100, 0x140, (1, 0), (0, 0), False), (0x0100, 0x140, (1, 0), (1, 1), True)):
            h = Host(image.M.REF, sabotage, elf=elf)
            ret = h.syms["plat_exit"]  # stop address, never executed
            h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
            rr = h.syms["rt_r"]        # runtime.h struct rt_regs: ax, cx, dx, bx

            def call(fn, d6=0, d7=0):
                h.e.reg_write(U.M68K["sr"], 0x2700)  # first: it selects which a7
                h.e.reg_write(U.M68K["a7"], STACK_TOP - 8)
                h.e.write(STACK_TOP - 8, ret.to_bytes(4, "big"))
                h.e.reg_write(U.M68K["a6"], TOP)
                h.e.reg_write(U.M68K["d6"], d6)
                h.e.reg_write(U.M68K["d7"], d7)
                h.e.start(h.syms[fn], ret, timeout_us=1_000_000)
                return h.r("pc") == ret

            def int67(ax, bx=0, dx=0):
                h.e.write(rr, ax.to_bytes(2, "big") + bytes(2) + dx.to_bytes(2, "big") + bx.to_bytes(2, "big"))
                ok = call("rt_int67")
                return ok, int.from_bytes(h.mem(rr + 4, 2), "big")

            ok, handle = int67(0x4300, bx=4)
            for phys in (0, 1):
                ok = ok and int67(0x4400 | phys, bx=order[phys], dx=handle)[0]
            if expose:
                h.e.write(G_DS, (0xE000).to_bytes(2, "big"))
                ok = ok and call("rt_ems_seg")
                h.e.write(G_DS, (0x1000).to_bytes(2, "big"))
            h.e.write(slot, (0xE030).to_bytes(2, "big"))
            ok = ok and call(name, d6, d7)
            a = h.r({"rt_ems_es": "a1", "rt_ems_ds": "a3"}[name])
            live = tuple(h.mem(h.syms["rt_ems_live"], 2))
            store = EMS_STORE + (EMS_STORE_PAGES - int.from_bytes(h.mem(h.syms["rt_ems_mapped"], 2), "big")) * EMS_PAGE
            want_a = plain if want_live[0] else plain + store - frame0
            if not ok or live != want_live or a != want_a:
                problems.append(f"EMS guard {name} d7={d7:04x} d6={d6:x} pages {order}"
                                f"{' page 0 live' if expose else ''}: frame pages live {live}, "
                                f"want {want_live}; base {a:x}, want {want_a:x} (pc={h.r('pc'):x})")
            if d7 != 0x0100 or expose:
                continue
            for remap, (cd7, cd6) in ((False, (0x3B00, 0x100)), (True, (0x0100, 0x140))):
                if remap:
                    ok = int67(0x4400, bx=order[1], dx=handle)[0]
                ok = ok and call(name, cd6, cd7)
                a = h.r({"rt_ems_es": "a1", "rt_ems_ds": "a3"}[name])
                live = tuple(h.mem(h.syms["rt_ems_live"], 2))
                store = EMS_STORE + (EMS_STORE_PAGES - int.from_bytes(h.mem(h.syms["rt_ems_mapped"], 2),
                                                                      "big")) * EMS_PAGE
                want_a = plain if live[0] else plain + store - frame0
                if not ok or a != want_a:
                    problems.append(f"EMS guard cache {name} d7={cd7:04x} d6={cd6:x} "
                                    f"{'after a remap' if remap else 'hit'}: base {a:x}, want {want_a:x} "
                                    f"(pc={h.r('pc'):x})")
            caches = h.syms["rt_ems_cache_es"], h.syms["rt_ems_cache_ds"]
            held = [h.mem(c, 12) for c in caches]
            h.e.write(TOP - 0x23, IRQ0_HANDLER.to_bytes(4, "big"))   # IVT 08h, as ems_irq_problems
            ok = call("rt_irq0_enter") and h.mem(h.syms["rt_irq0_running"], 1) == b"\1"
            h.e.write(slot, (0xE430).to_bytes(2, "big"))
            ok = ok and call(name, 0x40, 0x0100) and call("rt_irq0_leave")
            h.e.write(slot, (0xE030).to_bytes(2, "big"))
            back = [h.mem(c, 12) for c in caches]
            if not ok or back != held or not any(any(b) for b in held):
                problems.append(f"EMS guard cache {name} around IRQ0's handler: {[b.hex() for b in back]}, "
                                f"want {[b.hex() for b in held]} (pc={h.r('pc'):x})")
    return problems


def ems_irq_problems(elf: Path | None, sabotage: str | None = None) -> list[str]:
    """The EMS frame pages over an interrupt's handler (ems.c rt_ems_irq_enter,
    rt_ems_irq_leave), which production runs at any instruction, also between a
    guard and its access (lockstep delivers at poll points only, so it cannot
    see this): on the run's own image, a page mapped by the real INT 67h, then
    rt_irq0_enter, the handler's own DS at the frame (rt_ems_seg copies the page
    in) and a write there, the interrupted state back and rt_irq0_leave. With
    the interrupted DS at E030h in listed code (rt_ems_ds: the base on the store
    page) the page is in the store again with the handler's byte; with DS at
    E030h outside listed code (rt_ems_seg: live) the handler remaps the page
    away and back with its DS elsewhere, and the page is live again. Then a
    restore row's POP DS (rt_ems_restore, annotations/ems-ds.csv) with the
    interrupted DS at E030h in listed code: inside the handler it copies
    nothing and the page is in the store after the return; outside a handler,
    or inside one with another DS (E010h), it copies the page in."""
    problems = []
    plain = TOP - 0x7FFF - 0xE0300
    frame0 = TOP - (EMS_FRAME + EMS_PAGE) + 1
    for listed in (True, False):
        h = Host(image.M.REF, sabotage, elf=elf)
        ret = h.syms["plat_exit"]  # stop address, never executed
        h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
        rr = h.syms["rt_r"]        # runtime.h struct rt_regs: ax, cx, dx, bx

        def call(fn, d6=0, d7=0):
            h.e.reg_write(U.M68K["sr"], 0x2700)  # first: it selects which a7
            h.e.reg_write(U.M68K["a7"], STACK_TOP - 8)
            h.e.write(STACK_TOP - 8, ret.to_bytes(4, "big"))
            h.e.reg_write(U.M68K["a6"], TOP)
            h.e.reg_write(U.M68K["d6"], d6)
            h.e.reg_write(U.M68K["d7"], d7)
            h.e.start(h.syms[fn], ret, timeout_us=1_000_000)
            return h.r("pc") == ret

        def int67(ax, bx=0, dx=0):
            h.e.write(rr, ax.to_bytes(2, "big") + bytes(2) + dx.to_bytes(2, "big") + bx.to_bytes(2, "big"))
            ok = call("rt_int67")
            return ok, int.from_bytes(h.mem(rr + 4, 2), "big")

        def ds(seg):
            h.e.write(G_DS, seg.to_bytes(2, "big"))

        def live():
            return h.mem(h.syms["rt_ems_live"], 1)[0]

        ok, handle = int67(0x4300, bx=2)
        ok = ok and int67(0x4400, bx=0, dx=handle)[0]
        store = EMS_STORE + (EMS_STORE_PAGES - int.from_bytes(h.mem(h.syms["rt_ems_mapped"], 2), "big")) * EMS_PAGE
        ds(0xE030)
        if listed:
            ok = ok and call("rt_ems_ds", 0x40, 0x0100)
            base = h.r("a3")
            ok = ok and base == plain + store - frame0 and not live()
        else:
            ok = ok and call("rt_ems_seg") and live()
        before = live()
        # IVT 08h (guest 20h..23h: IP, CS) a handler the dispatcher knows; guest bytes
        # run down from TOP, so CS then IP big-endian end at guest 20h
        h.e.write(TOP - 0x23, IRQ0_HANDLER.to_bytes(4, "big"))
        ok = ok and call("rt_irq0_enter") and h.mem(h.syms["rt_irq0_running"], 1) == b"\1"
        if listed:
            ds(0xE000)
            ok = ok and call("rt_ems_seg") and live()
            h.e.write(frame0 + EMS_PAGE - 1 - 0x0400, b"\x5a")   # guest E000:0400
        else:
            ds(0x1000)
            ok = ok and int67(0x4400, bx=1, dx=handle)[0] and int67(0x4400, bx=0, dx=handle)[0] and not live()
        ds(0xE030)
        ok = ok and call("rt_irq0_leave")
        byte = h.mem(store + EMS_PAGE - 1 - 0x0400, 1)
        if not ok or live() != before or (listed and byte != b"\x5a"):
            problems.append(f"EMS over an interrupt's handler ({'listed' if listed else 'unlisted'} DS E030h): "
                            f"frame page live {live()}, want {before}; store byte {byte.hex()} "
                            f"(pc={h.r('pc'):x})")
    for held, seg in ((True, 0xE030), (False, 0xE030), (True, 0xE010)):
        h = Host(image.M.REF, sabotage, elf=elf)
        ret = h.syms["plat_exit"]
        h.e.write(h.syms["rt_guest"], TOP.to_bytes(4, "big"))
        rr = h.syms["rt_r"]

        def call(fn, d6=0, d7=0):
            h.e.reg_write(U.M68K["sr"], 0x2700)
            h.e.reg_write(U.M68K["a7"], STACK_TOP - 8)
            h.e.write(STACK_TOP - 8, ret.to_bytes(4, "big"))
            h.e.reg_write(U.M68K["a6"], TOP)
            h.e.reg_write(U.M68K["d6"], d6)
            h.e.reg_write(U.M68K["d7"], d7)
            h.e.start(h.syms[fn], ret, timeout_us=1_000_000)
            return h.r("pc") == ret

        def int67(ax, bx=0, dx=0):
            h.e.write(rr, ax.to_bytes(2, "big") + bytes(2) + dx.to_bytes(2, "big") + bx.to_bytes(2, "big"))
            ok = call("rt_int67")
            return ok, int.from_bytes(h.mem(rr + 4, 2), "big")

        def ds(v):
            h.e.write(G_DS, v.to_bytes(2, "big"))

        def live():
            return h.mem(h.syms["rt_ems_live"], 1)[0]

        ok, handle = int67(0x4300, bx=2)
        ok = ok and int67(0x4400, bx=0, dx=handle)[0]
        ds(0xE030)
        ok = ok and call("rt_ems_ds", 0x40, 0x0100) and not live()
        h.e.write(TOP - 0x23, IRQ0_HANDLER.to_bytes(4, "big"))
        if held:
            ok = ok and call("rt_irq0_enter")
            ds(0x1000)
        ds(seg)
        ok = ok and call("rt_ems_restore")
        want = 0 if held and seg == 0xE030 else 1
        got = live()
        if held:
            ok = ok and call("rt_irq0_leave")
        after = live()
        if not ok or got != want or held and after != 0:
            problems.append(f"EMS restore of DS {seg:04x} {'inside' if held else 'outside'} an interrupt's "
                            f"handler: frame page live {got}, want {want}; after the return {after} "
                            f"(pc={h.r('pc'):x})")
    return problems


def frame_view(ram: bytes, pages: dict) -> bytes:
    """Guest RAM as the guest sees it: frame pages not copied in show their store page."""
    ram = bytearray(ram)
    for k, page in pages.items():
        ram[EMS_FRAME + k * EMS_PAGE:EMS_FRAME + (k + 1) * EMS_PAGE] = page
    return bytes(ram)


def check(milestone: str, timeout: int, amiga: Path | None, sabotage: str | None,
          trace: Path | None = None, elf: Path | None = None, stall: int = 300,
          stale_polls: bool = False, sfx: str | None = None) -> list[str]:
    script = milestone_script(milestone)
    frame = script["frame"]
    trace = trace or host_reference(milestone)
    snap = trace / f"snap-{milestone}-{len(script['snapshots']) - 1}"  # where the run stops
    # REP slices (rep_replay.py): a diagnostic image with REP hooks replays the
    # reference's decoder slices, so an interrupt inside a REP lands where it did
    chunks = rep_replay.read(trace, required=True)
    rep = rep_replay.Replay(chunks)
    script["rep"] = rep
    elf = elf or rep_replay.host_image(rep.labels)
    h = Host(image.M.REF, sabotage, elf=elf,
             retrace=port_runs(trace, (0x3DA,)), pit=port_runs(trace, (0x40,)),
             dsp={port: port_runs(trace, (port,)) for port in (0x22C, 0x22E)})
    h.calendar_date, h.file_clock = reference_clocks(trace)
    h.launch = script["launch"]
    h.rom = reference_rom()
    label = script["snapshots"][-1][0]
    script["irqs"], script["releases"] = reference_inputs(trace, exact_releases=True)
    script["repeats"] = typematic(trace, script["keys"])
    script["idle"] = idle_stacks(trace)
    summary = dict(kv.split("=", 1) for kv in (trace / "summary.txt").read_text().split())
    problems = rearm_problems() + overlay_problems(sabotage) + ems_guard_problems(elf, sabotage) + ems_irq_problems(elf, sabotage)
    stale = int(summary.get("polls", "0"), 16) != fnv(POLLS.read_bytes())
    if stale and not stale_polls:
        problems.append("reference recorded with other poll points: rerun tools/reference.py --host")
    if problems:        # the lockstep would prove nothing: report them without running
        return problems
    if stale:
        # --stale-polls: new poll points only add places the reference took no
        # interrupt, so a run still finds the next problems (collect the
        # annotations for one re-recording); it can never pass
        problems.append("diagnostic only: the reference has other poll points (--stale-polls)")
    want = reference_services(trace)
    h.services = ServiceLog(h, want)
    h.stall = 20 if sabotage == "stall" else stall
    if sfx:
        h.sfx_enable(sfx)
    t0 = time.monotonic()
    h.run(script, timeout)
    print(f"host run: {time.monotonic() - t0:.0f} s")
    if sfx:
        problems += sfx_problems(h, sfx)
    w = h.watch
    print(f"memory watch: {w.seen[0]} reads, {w.seen[1]} writes; {w.passed[0]} and {w.passed[1]} "
          f"passed to the Python hooks")
    if h.stalled:
        problems.append(h.stalled)
    elif h.early:
        print(f"stopped early: {h.early}")
    try:
        rep.complete()
    except ValueError as error:
        problems.append(str(error))
    if h.irq_lost:
        problems.append(h.irq_lost)
    if h.retrace_bad:
        problems.append(h.retrace_bad)
    if h.stopped_at == label and h.retrace_left():
        problems.append(f"VGA status: {h.retrace_left()} reference reads not made")
    if h.stopped_at == label and h.pit_left():
        problems.append(f"PIT: {h.pit_left()} reference reads not made")
    if h.stopped_at == label and h.dsp_left():
        problems.append(f"DSP status: {h.dsp_left()} reference reads not made")
    want_blocks, late = reference_blocks(trace)
    done = want_blocks if h.stopped_at == label else want_blocks[:len(h.blocks)]
    if h.blocks != done:
        k = next((k for k, (a, b) in enumerate(zip(h.blocks, done)) if a != b), min(len(h.blocks), len(done)))
        problems.append(f"SB blocks: {len(h.blocks)} started, the reference {len(done)}; first difference "
                        f"#{k}: {h.blocks[k:k + 1]} vs {done[k:k + 1]}")
    print(f"SB blocks: {len(h.blocks)} started, {len(want_blocks)} in the reference" +
          (f"; reference IRQ 7 acknowledged {min(late):+.1f}..{max(late):+.1f} ms from length/rate"
           if late else ""))
    want_hooks = reference_hooks(trace)
    if h.stopped_at == label and h.key_hooks != want_hooks or \
            h.stopped_at != label and h.key_hooks - want_hooks:
        diff = sorted(set(h.key_hooks) ^ set(want_hooks) | {a for a in h.key_hooks if h.key_hooks[a] != want_hooks[a]})
        problems.append(f"keyboard intercept: {sum(h.key_hooks.values())} runs, the reference "
                        f"{sum(want_hooks.values())}; first AX {diff[0]:04x}: {h.key_hooks[diff[0]]} vs "
                        f"{want_hooks[diff[0]]}")
    # cut short: each reference keyboard interrupt ran the intercept once (m4:
    # 14 IRQ 1, 14 INT 15h), so each one replayed here must have, but the last
    # posted (its BIOS model may not have run when the run stopped)
    kb = [i for i in script["irqs"][:h.irq_i] if i[3] == 9]
    if h.stopped_at != label and sum(want_hooks.values()) == sum(i[3] == 9 for i in script["irqs"]) \
            and sum(h.key_hooks.values()) < len(kb) - 1:
        problems.append(f"keyboard intercept: {sum(h.key_hooks.values())} runs for {len(kb)} replayed "
                        f"keyboard interrupts (the reference runs it for each)")
    print(f"keyboard intercept: {sum(h.key_hooks.values())} runs, {sum(want_hooks.values())} in the reference")
    if h.display_miss:
        problems.append(h.display_miss)
    problems += h.irq.finish(REPO / "tmp/test" / f"irq-monitor-{milestone}{'-' + sabotage if sabotage else ''}.json")
    if h.stopped_at == label:
        problems += check_opl(h, trace)
    marked = bytearray(64000)  # stored since the last present: still marked (rt_vram_rows)
    rows = h.mem(h.syms["rt_vram_rows"], 800)
    for y in range(200):
        lo, hi = struct.unpack_from(">2H", rows, 4 * y)
        marked[y * 320 + lo:y * 320 + hi] = b"\1" * max(0, hi - lo)
    unmarked = outside(h.vram_written, marked)
    if unmarked:
        problems.append(f"{len(unmarked)} pixels stored since the last present and not marked, "
                        f"first x={unmarked[0] % 320} y={unmarked[0] // 320}")
    print(f"frame presents: {h.presents}")
    print(f"hardware interrupts: {h.irq_i} replayed, {len(script['irqs'])} in the reference")
    print(f"VGA status reads: {sum(r[2] for r in h.retrace)} in the reference")
    print(f"PIT latches: {h.pit_latches}, reads {sum(r[2] for r in h.pit)} in the reference")
    if h.stopped_at != label:
        problems.append(f"milestone label {label} not reached (exit {h.exit}, pc={h.r('pc'):x}"
                        f"{', ' + h.log[-1] if h.log else ''})")
    applied: list = []
    problems += compare_services(h.services, want if h.stopped_at == label else want[:len(h.services)],
                                 applied=applied)
    print(f"services: {len(h.services)} run, {len(want)} in the reference; "
          f"{len(applied)} register differences masked (annotations/undefined-flags.csv)")
    if h.stopped_at == label:
        ref_regs = dict(kv.split("=") for kv in (snap / "regs.txt").read_text().split())
        ref = (snap / "ram.bin").read_bytes()
        g = h.guest_regs(0)
        problems += check_capture("host", g, h.mem(STATE, 16), frame_view(h.gmem(0, 0x100000), host_ems_pages(h)),
                                  h.mem(h.syms["rt_dac"], 768) if frame else None,
                                  ref_regs, ref, snap, h, h.irq_stack[-1] if h.irq_stack else None)
        if amiga:
            regs = dict(kv.split("=") for kv in (amiga / "regs.txt").read_text().split())
            ga = {n: int(regs[n], 16) for n in REGS}
            if frame:
                problems += compare_shown(amiga, int(regs["bpr"]), snap)
            problems += check_capture("amiga", ga, (amiga / "state.bin").read_bytes(),
                                      frame_view((amiga / "ram.bin").read_bytes()[::-1],  # reversed
                                                 {k: (amiga / f"ems-page{k}.bin").read_bytes()[::-1]
                                                  for k in range(4) if (amiga / f"ems-page{k}.bin").exists()}),
                                      (amiga / "dac.bin").read_bytes() if frame else None,
                                      ref_regs, ref, snap, h, amiga_irq(amiga))
    return problems


def amiga_irq(capture: Path) -> tuple[int, int] | None:
    """The interrupted SS:SP of a capture inside IRQ0's handler (irq.bin:
    rt_irq0_running, then rt_irq_saved: state block, rt_r), else None."""
    data = (capture / "irq.bin").read_bytes()
    if not data[0]:
        return None
    saved = data[1:]
    return int.from_bytes(saved[2:4], "big"), int.from_bytes(saved[16 + 8:16 + 10], "big")


if __name__ == "__main__":
    sys.exit(main())
