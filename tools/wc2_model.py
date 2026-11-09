"""Shared static model of Wing Commander II: modules, link layout, traces.

Adapted from Secret Weapons of Luftwaffe's tools/swotl_model.py (docs/upstream.md). The
generic parts (Module, MZ reader, trace readers) are SWOTL's. Port-plan P1.4 proves the
image (WC2.EXE, its VROOMM overlays and drivers, from tools/bc_exe.py) with the loader
model below. The scope stays empty until P2 brings modules; until then the translator
has no module to translate and the differentials run on their synthetic corpora only.

Module address = module offset: root = MZ load-image offset. Link linear address =
link segment * 16 + offset, before relocation by the load segment.
"""

from __future__ import annotations

import csv
import struct
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REF = REPO / "ref/WING2"
RUNS = REPO / "tmp/pc-runs"
ROOT = "WC2.EXE"
OVL_TABLE = 0  # SWOTL's PLINK table; WC2's VROOMM model replaces it (P2.1, P4.2)
MANAGER = (None, None)  # SWOTL's PLINK manager entry; no WC2 equivalent
SCOPE: list[str] = []  # P2 (P1.4 proves the loader model only)
OUT_OF_SCOPE: list[str] = []


@dataclass
class Module:
    name: str
    data: bytes                 # file bytes (root: load image), unrelocated
    code_start: int             # module offset of the first code byte
    link_seg: int               # link segment of code_start
    fixups: list[int] = field(default_factory=list)  # module offsets of segment words
    index: int = -1             # overlay index
    end_seg: int = 0
    flags: int = 0
    paras: int = 0

    @property
    def link_lo(self) -> int:
        return self.link_seg * 16

    @property
    def link_hi(self) -> int:
        return self.link_lo + len(self.data) - self.code_start

    def to_link(self, off: int) -> int:
        return self.link_lo + off - self.code_start

    def from_link(self, linear: int) -> int:
        return linear - self.link_lo + self.code_start


def mz(path: Path) -> tuple[bytes, list[tuple[int, int]], tuple[int, int]]:
    data = path.read_bytes()
    last, pages, nrel, hdr = struct.unpack_from("<HHHH", data, 2)
    size = pages * 512 - (512 - last if last else 0) - hdr * 16
    ip, cs = struct.unpack_from("<HH", data, 0x14)
    relo = struct.unpack_from("<H", data, 0x18)[0]
    rels = [struct.unpack_from("<HH", data, relo + 4 * i) for i in range(nrel)]
    return data[hdr * 16: hdr * 16 + size], rels, (cs, ip)








def link_owners(mods: dict[str, Module], linear: int) -> list[str]:
    """Modules whose link range contains a link linear address."""
    return [m.name for m in mods.values() if m.link_lo <= linear < m.link_hi]


def runs(pattern: str = "ref-*") -> list[Path]:
    return sorted(p / "trace" for p in RUNS.glob(pattern) if (p / "trace/summary.txt").exists())


def executed(traces: list[Path]) -> dict[str, set[int]]:
    """Union of executed instruction starts per module."""
    out: dict[str, set[int]] = {}
    for t in traces:
        for f in t.glob("executed-*.bin"):
            name = f.name[len("executed-"):-len(".bin")]
            s = out.setdefault(name, set())
            s.update(i for i, b in enumerate(f.read_bytes()) if b)
    return out


def edges(traces: list[Path]) -> set[tuple[str, int, str, int]]:
    out = set()
    for t in traces:
        with (t / "edges.csv").open() as f:
            for r in csv.DictReader(f):
                out.add((r["from_module"], int(r["from_offset"], 16),
                         r["to_module"], int(r["to_offset"], 16)))
    return out


def csv_rows(traces: list[Path], name: str) -> list[dict]:
    rows = []
    for t in traces:
        p = t / name
        if p.exists():
            with p.open() as f:
                for r in csv.DictReader(f):
                    r["_run"] = t.parent.name
                    rows.append(r)
    return rows


def residency(path: Path) -> list[tuple[int, int, str, int]]:
    """(first linear, end linear, module, module offset of first) rows."""
    with path.open() as f:
        return [(int(r["first_para"], 16) * 16, (int(r["last_para"], 16) + 1) * 16, r["module"],
                 int(r["module_offset"], 16)) for r in csv.DictReader(f)]


def locate(rows: list[tuple[int, int, str, int]], linear: int) -> tuple[str, int] | None:
    for lo, hi, mod, off in rows:
        if lo <= linear < hi:
            return mod, off + linear - lo
    return None


def cpu_writes(traces: list[Path]) -> dict[str, dict[int, set[str]]]:
    """Module offset -> writer sites, from snapshot writes.csv (last writer since load)
    and code-writes.csv (writes into executed paragraphs, mapped by exit residency)."""
    out: dict[str, dict[int, set[str]]] = {}

    def add(rows, lo, hi, writer):
        for a in range(lo, hi + 1):
            hit = locate(rows, a)
            if hit:
                out.setdefault(hit[0], {}).setdefault(hit[1], set()).add(writer)

    for t in traces:
        for snap in t.glob("snap-*"):
            rows = residency(snap / "residency.csv")
            if (snap / "writes.csv").exists():
                with (snap / "writes.csv").open() as f:
                    for r in csv.DictReader(f):
                        add(rows, int(r["first_linear"], 16), int(r["last_linear"], 16),
                            f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}")
        rows = residency(t / "residency.csv")
        with (t / "code-writes.csv").open() as f:
            for r in csv.DictReader(f):
                a = int(r["target_linear"], 16)
                add(rows, a, a + int(r["width"]) - 1,
                    f"{r['writer_module']}+{int(r['writer_offset'], 16):05X}")
    return out


# --- Loader model (port-plan P1.4, docs/pc-reference-loop.md "Loader model") ---
# Image offsets number the root and its overlays alike: the MZ load image is
# offsets 0..ROOT_IMAGE-1, and the FBOV area that follows it in the file keeps
# going at file offset - MZ header (the trace patch attributes overlay reads so).
SEG_TABLE = 0x16C40  # root: 8-byte segment records, word 0 = link segment (MEASURED)
DRIVERS = ("TM.DRV", "SUPERTM.DRV", "STRAX.DRV")  # GAMEDAT; read whole, not relocated


@dataclass
class Overlay:
    stub: int                   # image offset of its stub segment in the root
    code: int                   # image offset of its first code byte (FBOV area)
    size: int                   # code bytes
    relocs: list[int]           # code offsets of segment words (table byte offsets)

    @property
    def end(self) -> int:
        """Image offset after the code and its relocation records."""
        return self.code + self.size + 2 * len(self.relocs)


def overlays(ref: Path = REF) -> list[Overlay]:
    """The VROOMM overlays (tools/bc_exe.py), at image offsets."""
    import bc_exe
    x = bc_exe.load(str(ref / ROOT))
    base = x.fbov - x.header + 16
    out = []
    for o in x.overlays:
        code = base + o.file_off
        rel = x.data[x.header + code + o.code_size: x.header + code + o.code_size + o.reloc_size]
        out.append(Overlay(o.stub_off, code, o.code_size,
                           [struct.unpack_from("<H", rel, 2 * i)[0] for i in range(o.reloc_size // 2)]))
    return sorted(out, key=lambda o: o.code)


def image_file(ref: Path = REF) -> bytes:
    """WC2.EXE from the load image on: image offset k is byte k."""
    data = (ref / ROOT).read_bytes()
    return data[struct.unpack_from("<H", data, 8)[0] * 16:]


def root_image(load: int, ref: Path = REF) -> bytearray:
    """The MZ load image relocated at load segment `load`, with the entry frame
    of the DOS EXEC: DOSBox-X pushes the entry CS and IP on the initial stack and
    enters with RETF (src/dos/dos_execute.cpp, LOADNGO), so the 4 bytes below the
    initial SS:SP hold IP, then CS + load (MEASURED at entry: image 277DCh)."""
    image, rels, (cs, ip) = mz(ref / ROOT)
    out = bytearray(image)
    for off, seg in rels:
        a = seg * 16 + off
        struct.pack_into("<H", out, a, (struct.unpack_from("<H", out, a)[0] + load) & 0xFFFF)
    data = (ref / ROOT).read_bytes()
    ss, sp = struct.unpack_from("<HH", data, 0x0E)
    frame = ss * 16 + sp - 4
    if 0 <= frame <= len(out) - 4:
        struct.pack_into("<HH", out, frame, ip, (cs + load) & 0xFFFF)
    return out


def overlay_code(o: Overlay, load: int, ref: Path = REF, image: bytes | None = None) -> bytearray:
    """An overlay's code as VROOMM leaves it after the load: each segment word w
    becomes load + the link segment in segment record w / 8 (MEASURED: 1487 of
    1487 words in the resident overlays of a flight snapshot)."""
    image = image if image is not None else image_file(ref)
    code = bytearray(image[o.code:o.code + o.size])
    for f in o.relocs:
        w = struct.unpack_from("<H", code, f)[0]
        seg = struct.unpack_from("<H", image, SEG_TABLE + w)[0]
        struct.pack_into("<H", code, f, (seg + load) & 0xFFFF)
    return code


def load_modules(ref: Path = REF) -> dict[str, Module]:
    """The in-scope modules for the translator: none until the sweep (port-plan
    P2.3); the loader model above is the image proof's (P1.4)."""
    assert not SCOPE, "WC2 translator modules come with port-plan P2"
    return {}


def entry(ref: Path = REF) -> int:
    _, _, (cs, ip) = mz(ref / ROOT)
    return cs * 16 + ip


def thunks(mods: dict[str, Module]) -> list[tuple[int, str, int]]:
    """SWOTL's PLINK thunks; WC2's VROOMM stubs are port-plan P2.1."""
    return []
