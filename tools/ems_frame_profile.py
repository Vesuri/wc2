#!/usr/bin/env python3
"""EMS frame accesses on the host run to a milestone (open-work 10's input).

Runs tests/host_run.py's lockstep check with a memory hook on the frame
(E0000h-EFFFFh, reversed guest RAM) and reports, for generated code and for
the runtime separately: accesses and bytes, the segment value behind each
(DS, ES or SS, whichever addresses the frame; several when ambiguous), the
page the access falls in and whether it straddles a 16 KB page, and the
hottest code labels. The runtime's map copies are counted by the hook.

It also simulates a lazy policy on the same run (bytes it would copy): a frame
page holds its mapped page's bytes ("live") only while a segment register's
64 KB window overlaps it or the runtime touches it; a map writes a live page
back (16 KB, dirty or not) and copies the new one in only if a segment
register overlaps it; a segment load copies in the non-live pages its window
overlaps. A second policy ("access", lazy2) copies a page in only on the first
access to it after a map (generated code or the runtime), writing live pages
back on remap.

usage: tools/ems_frame_profile.py [--milestone m1b] [--top 25]
"""
import argparse
import bisect
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import host_run as H  # noqa: E402

FRAME, FRAME_END = 0xE0000, 0xF0000
PAGE = 0x4000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--milestone", default="m1b")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    stats = dict(gen=Counter(), rt=Counter(), seg=Counter(), page=Counter(),
                 label=Counter(), rt_label=Counter(), straddle=Counter(), model=Counter())
    sim, sim2 = Counter(), Counter()
    original_run = H.Host.run

    def run(self, script, timeout):
        names = sorted((a, n) for n, a in self.syms.items() if isinstance(a, int))
        addrs = [a for a, _ in names]
        tags = tuple(f"{t}_" for t in H.emit.TAG.values())
        lo, hi = H.TOP - (FRAME_END - 1), H.TOP - FRAME

        def where(pc):
            k = bisect.bisect_right(addrs, pc) - 1
            return names[k][1] if k >= 0 else "?"

        @H.U.MEM_CB
        def hook(h, access, addr, size, value, user):
            pc = self.r("pc")
            name = where(pc)
            lin = H.TOP - addr - size + 1           # lowest guest byte touched
            generated = name.startswith(tags)
            kind = "gen" if generated else "rt"
            stats[kind]["accesses"] += 1
            stats[kind]["bytes"] += size
            first, last = (lin - FRAME) // PAGE, (lin + size - 1 - FRAME) // PAGE
            if first != last:
                stats["straddle"][kind] += 1
            if mapped[first] is not None and not live2[first] and self.syms and where(pc) != "copy":
                live2[first] = True
                sim2["access copy-in"] += PAGE
            if generated:
                st = self.mem(H.STATE, 6)
                segs = {"ds": int.from_bytes(st[0:2], "big"), "ss": int.from_bytes(st[2:4], "big"),
                        "es": int.from_bytes(st[4:6], "big")}
                hits = sorted(f"{s}={v:04x}" for s, v in segs.items()
                              if v * 16 <= lin < v * 16 + 0x10000)
                stats["seg"][" ".join(hits) or "none"] += 1
                stats["page"][first] += 1
                stats["label"][name] += 1
            else:
                stats["rt_label"][name] += 1
            return True

        self.e.hook_range(H.U.HOOK_MEM_READ | H.U.HOOK_MEM_WRITE, hook, lo, hi)

        segs = {"ds": 0, "ss": 0, "es": 0}
        live, mapped, saved = [False] * 4, [None] * 4, {}
        live2 = [False] * 4

        def overlaps(p):
            a = FRAME + p * PAGE
            return any(v * 16 <= a + PAGE - 1 and a <= v * 16 + 0xFFFF for v in segs.values())

        def expose(p, why):
            if mapped[p] is not None and not live[p]:
                live[p] = True
                sim[why] += PAGE

        def remap(p, page):
            if mapped[p] == page:
                return
            if live2[p]:
                sim2["map write-back"] += PAGE
                live2[p] = False
            if live[p]:
                sim["map write-back"] += PAGE
                live[p] = False
            mapped[p] = page
            sim["maps"] += 1
            if page is not None and overlaps(p):
                expose(p, "map copy-in")

        @H.U.MEM_CB
        def seg_write(h, access, addr, size, value, user):
            raw = (value & ((1 << 8 * size) - 1)).to_bytes(size, "big")
            for k in range(size):             # bytes, big-endian slots: DS +0, SS +2, ES +4
                off = addr - H.STATE + k
                if 0 <= off < 6:
                    name = ("ds", "ss", "es")[off // 2]
                    shift = 8 if off % 2 == 0 else 0
                    segs[name] = segs[name] & ~(0xFF << shift) & 0xFFFF | raw[k] << shift
            for p in range(4):
                if overlaps(p):
                    expose(p, "segment copy-in")
            return True

        self.e.hook_range(H.U.HOOK_MEM_WRITE, seg_write, H.STATE, H.STATE + 5)

        @H.U.MEM_CB
        def rt_touch(h, access, addr, size, value, user):
            name = where(self.r("pc"))
            if name.startswith(tags) or name == "copy":
                return True
            lin = H.TOP - addr - size + 1
            expose((lin - FRAME) // PAGE, "runtime copy-in")
            return True

        self.e.hook_range(H.U.HOOK_MEM_READ | H.U.HOOK_MEM_WRITE, rt_touch, lo, hi)

        @H.U.CODE_CB
        def int67(h, addr, size, user):
            r = self.mem(self.syms["rt_r"], 16)
            ax, dx, bx = (int.from_bytes(r[k:k + 2], "big") for k in (0, 4, 6))
            if ax >> 8 == 0x44 and (ax & 0xFF) < 4:
                remap(ax & 0xFF, None if bx == 0xFFFF else (dx, bx))
            elif ax >> 8 == 0x47:
                saved[dx] = list(mapped)
            elif ax >> 8 == 0x48 and dx in saved:
                for p, page in enumerate(saved.pop(dx)):
                    remap(p, page)
            return None

        a = self.syms["rt_int67"]
        self.e.hook_range(H.U.HOOK_CODE, int67, a, a)

        # the EMS model's own copies (ems.c), by the entry that caused them
        cause = ["?"]
        entries = {self.syms[n]: n for n in ("rt_ems_es", "rt_ems_seg", "rt_int67", "rt_int_c",
                                             "rt_irq0_leave", "rt_ems_touch", "rt_ems_sync")
                   if n in self.syms}

        @H.U.CODE_CB
        def entry(h, addr, size, user):
            n = entries[addr]
            if n == "rt_ems_touch" and cause[0] in ("rt_ems_es", "rt_ems_seg", "rt_int_c",
                                                     "rt_irq0_leave", "rt_ems_sync"):
                return None         # inside one of those
            cause[0] = n
            return None

        for a in entries:
            self.e.hook_range(H.U.HOOK_CODE, entry, a, a)
        store_lo, store_hi = H.STATE + 16, H.STATE + 16 + 0xA4 * PAGE - 1

        @H.U.MEM_CB
        def copied(h, access, addr, size, value, user):
            if where(self.r("pc")) == "copy":
                into = "store" if store_lo <= addr <= store_hi else "frame"
                stats["model"][f"{cause[0]} -> {into}"] += size
            return True

        self.e.hook_range(H.U.HOOK_MEM_WRITE, copied, lo, store_hi)
        return original_run(self, script, timeout)

    H.Host.run = run
    problems = H.check(args.milestone, 5400, None, None)
    print(f"lockstep: {'ok' if not problems else problems[:3]}")
    for kind in ("gen", "rt"):
        c = stats[kind]
        print(f"{kind}: {c['accesses']} accesses, {c['bytes']} bytes, "
              f"{stats['straddle'][kind]} straddle a 16 KB page")
    print("lazy policy (simulated):", dict(sim),
          "bytes", sum(v for k, v in sim.items() if k != "maps"))
    print("access policy (simulated):", dict(sim2), "bytes", sum(sim2.values()))
    print("EMS model copies (bytes written, by cause):", dict(stats["model"]))
    print("generated accesses by the segment that addresses the frame:")
    for k, n in stats["seg"].most_common(args.top):
        print(f"  {n:10d}  {k}")
    print("generated accesses by frame page:", dict(sorted(stats["page"].items())))
    print("hottest generated labels (nearest symbol at or below the PC):")
    for k, n in stats["label"].most_common(args.top):
        print(f"  {n:10d}  {k}")
    print("runtime accesses by routine:")
    for k, n in stats["rt_label"].most_common(10):
        print(f"  {n:10d}  {k}")


if __name__ == "__main__":
    main()
