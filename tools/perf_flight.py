#!/usr/bin/env python3
"""P7 frames fixtures: quiet flight and the Nav 1 fight on an Amiga image (docs/perf-method.md).

  perf_flight.py OUT [--scene quiet|fight] [--exe amiga/out/Wc2.exe]
                 [--elf amiga/out/Wc2.elf] [--frames 60] [--no-profile] [--cpu 68030]

From X-Wing's tools/perf_film.py (0d20bcd). The non-release image starts from its icon
under amiga/debug.sh (WC2_WORKBENCH: the tool types carry the script) with a KEYS
script (src/platform/amiga/amiga_platform.c): amiga/play_walk.sh's keyed route through
the opening, the pilot file and the briefing into the first flight. From there its
steps count published frames (`nN`, the guest's plat_present calls), so the window
starts at the same point of the flight in every build. quiet: SCENES' frames after the
launch, before any fight. fight: the autopilot (A) from there, which drops out at Nav 1
into the Sartha attack (docs/feasibility.md "Combat frame cost"; the Amiga has no
command tail, so the plain game, not the references' `WC2 Origin -k`), and the mark
inside the fight. amiga/perf_flight.gdb takes the field and the objects drawn at each
of the next FRAMES visits to the flight frame label from the mark, then a 100-field
profile, which tools/profile_report.py reports and which is then deleted.

Output OUT/: gdb.log, fixture.gdb, frames.json (fields per frame, the frame-interval
median and spread in ms, objects per frame), profile.txt. Emulated fields, never wall
time; the 68030 model: the shared cycle-exact preset a1200-030 (50 MHz 68030, data
cache) without its MMU (--uae_mmu_model=0): FS-UAE's profiler records nothing on the MMU
core (AmigaXDev docs/reference/measurement-method.md); the game uses no MMU.
"""
import argparse
import hashlib
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# amiga/play_walk.sh's route to the briefing's Esc, without its stick steps; its waits
# end on mx+0 (no motion) where it marks, so the first mark is the window's.
ROUTE = ("uBUTTONS.V00:esc*10,d300:my-20,uCAMPAIGN.S00:lmb,uOPTIONS.V00:esc*10,t1000:mx+0,"
         "w:shift+c,t150:a,t50:enter,t100:b,t50:enter,t100:d,t50:enter,fMUSIC.A00:mx+0,"
         "uCAMPAIGN.S00:lmb,uMESSAGE.V00:esc*10")
# From the briefing's Esc, in published frames, the window mark (shot). MEASURED on the
# 68030 model (2026-11-24): the first flight frame 8 frames after the Esc, 4 or fewer
# objects a frame before the autopilot; the autopilot held 30 fields 301 frames after
# the Esc drops out at Nav 1 after about 60 frames, and its next 190 frames draw 8 to 13.
SCENES = {"quiet": "n200:shot", "fight": "n300:mx+0,n1:a*30,n100:shot"}


def check_emulator() -> str:
    """The FS-UAE build every P7 figure comes from (manifest/perf-tools.sha256, relative
    to ~/.local/share/amiga): the fs-uae on PATH must be it."""
    share = Path(os.environ.get("AMIGA_SHARE") or Path.home() / ".local/share/amiga")
    digest, name = (ROOT / "manifest/perf-tools.sha256").read_text().split()
    found = shutil.which(os.environ.get("FSUAE") or "fs-uae")
    if not found or Path(found).resolve() != (share / name).resolve():
        sys.exit(f"fs-uae on PATH is {found}, not {share / name} (source amiga/env.sh)")
    if hashlib.sha256(Path(found).read_bytes()).hexdigest() != digest:
        sys.exit(f"{found} differs from manifest/perf-tools.sha256")
    return digest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--scene", choices=sorted(SCENES), default="fight")
    ap.add_argument("--exe", type=Path, default=ROOT / "amiga/out/Wc2.exe")
    ap.add_argument("--elf", type=Path, default=ROOT / "amiga/out/Wc2.elf")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--cpu", default="68030", choices=("68030", "68040", "68060"))
    ap.add_argument("--no-profile", action="store_true")
    ap.add_argument("--keep-capture", action="store_true",
                    help="keep the capture (for tools/cost_meter.py --calibrate)")
    ap.add_argument("--timeout", type=int, default=7200)
    args = ap.parse_args()
    emulator = check_emulator()
    out = args.out.resolve()
    if (out / "gdb.log").exists():
        sys.exit(f"{out} already measured; never overwrite a measurement")
    run = out / "run"
    run.mkdir(parents=True, exist_ok=True)
    capture = out / "profile.bin"
    text = (ROOT / "amiga/perf_flight.gdb").read_text().replace("@FRAMES@", str(args.frames))
    profile_line = f'monitor profile 100 "" "{os.path.relpath(capture, ROOT / "amiga")}"\n'
    text = text.replace('monitor profile 100 "" "@OUT@"\n', "" if args.no_profile else profile_line)
    (out / "fixture.gdb").write_text(text)
    keys = f"{ROUTE},{SCENES[args.scene]}"
    with socket.socket() as s:      # its own gdb stub port: fixtures may run side by side
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED="1", FSUAE_RUN=os.path.relpath(run, ROOT / "amiga"), FSUAE_CLAIM_STRICT="1",
               AMIGA_CPU=args.cpu, AMIGA_SETUP=f"a1200-0{args.cpu[3:5]}", JOY0="none", JOY1="none",
               WC2_ELF=str(args.elf.resolve()), WC2_WORKBENCH="1", WC2_TOOLTYPES=f"KEYS={keys}",
               EXTRA_ARGS="--uae_mmu_model=0")
    for k in ("CPU", "FAST_KB", "FAST_MEMORY"):
        env.pop(k, None)
    with (out / "gdb.log").open("w") as log:
        r = subprocess.run(["nice", "-n", "10", "bash", str(ROOT / "amiga/debug.sh"), "",
                            str(out / "fixture.gdb"), str(args.exe.resolve())], env=env, stdout=log,
                           stderr=subprocess.STDOUT, timeout=args.timeout, cwd=ROOT / "amiga")
    lines = (out / "gdb.log").read_text().splitlines()
    shutil.rmtree(run, ignore_errors=True)
    if r.returncode or "WC2_PERF_OK" not in lines:
        print("\n".join(lines[-15:]))
        sys.exit(f"perf_flight: no window (exit {r.returncode}); see {out / 'gdb.log'}")
    frames = [x.split() for x in lines if x.startswith("FRAME ")]
    fields, objects = [int(f[3]) for f in frames], [int(f[5]) for f in frames]
    mark = next(int(x.split()[2]) for x in lines if x.startswith("WINDOW_MARK "))
    iv = [b - a for a, b in zip(fields, fields[1:])]
    # The pictures: the frames that drew objects (counted since the previous visit).
    # In the reference every visit draws (its 66.7 ms frame); on the 68030 model every
    # other one draws nothing in both scenes (MEASURED 2026-11-24), so the picture rate
    # is the drawn frames'.
    drawn = [f for f, o in zip(fields[1:], objects[1:]) if o]
    div = [b - a for a, b in zip(drawn, drawn[1:])]
    if len(div) < 2:
        sys.exit(f"perf_flight: {len(drawn)} frames drew objects; no picture rate")
    res = {"exe": str(args.exe), "scene": args.scene, "cpu": args.cpu, "fs-uae": emulator,
           "frames": args.frames, "mark_field": mark, "fields": fields, "objects": objects,
           "intervals": iv, "median_ms": statistics.median(iv) * 20,
           "mean_ms": round(sum(iv) / len(iv) * 20, 1), "min_ms": min(iv) * 20, "max_ms": max(iv) * 20,
           "window_fields": fields[-1] - fields[0], "drawn_intervals": div,
           "drawn_median_ms": statistics.median(div) * 20, "drawn_mean_ms": round(sum(div) / len(div) * 20, 1)}
    (out / "frames.json").write_text(json.dumps(res, indent=1) + "\n")
    print(f"{args.scene}: {len(iv)} frame intervals from the mark: median {res['median_ms']} ms, "
          f"mean {res['mean_ms']} ms, {res['min_ms']}-{res['max_ms']} ms, {res['window_fields']} "
          f"fields; {len(div)} between frames that drew: median {res['drawn_median_ms']} ms, mean "
          f"{res['drawn_mean_ms']} ms; objects a frame {min(objects)}-{max(objects)}")
    if capture.exists():
        rep = subprocess.run([sys.executable, str(ROOT / "tools/profile_report.py"), str(capture),
                              str(args.elf), "--count", "R_0813C"], capture_output=True, text=True)
        (out / "profile.txt").write_text(rep.stdout + rep.stderr)
        if rep.returncode:
            print(rep.stderr[-2000:])
            sys.exit("profile_report failed (capture kept)")
        if not args.keep_capture:
            capture.unlink()
        print(f"profile: {out / 'profile.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
