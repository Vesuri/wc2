#!/usr/bin/env python3
"""Run the original under instrumented DOSBox-X, headless, from a fresh root.

Outputs in tmp/pc-runs/<name>/: root/ (disposable game copy), trace/ (hook
outputs), dosbox-x.log, result.txt. Exit status: 0 success (WC2_EXIT_AFTER
snapshot reached), 2 time limit, 3 guest fault, 4 emulator failure.
A time limit is never success.
"""

from __future__ import annotations

import json
import fixture_inputs
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOSBOX = REPO / "tools/vendor/dosbox-x/src/dosbox-x"
CONF = REPO / "reference/dosbox-x.conf"
LAUNCH = "WC2"
GAME_DIR = "WING2"  # the installer's C:\WING2 (docs/pc-reference-loop.md)

EXIT_SUCCESS, EXIT_LIMIT, EXIT_FAULT, EXIT_EMULATOR = 0, 2, 3, 4


def prepare(run: Path) -> Path:
    if run.exists():
        shutil.rmtree(run)
    root = run / "root"
    subprocess.run(["rsync", "-a", "--exclude", "*.pdf", f"{REPO / 'ref'}/", f"{root}/"],
                   check=True)
    # ref/ is read-only; the game writes into GAMEDAT and exits when it cannot
    subprocess.run(["chmod", "-R", "u+w", str(root)], check=True)
    (run / "trace").mkdir()
    return root


def classify(run: Path, returncode: int) -> tuple[int, str]:
    trace = run / "trace"
    exit_file = trace / "exit.txt"
    if exit_file.exists():
        return EXIT_SUCCESS, exit_file.read_text().strip()
    events = trace / "events.csv"
    if events.exists():
        for line in events.read_text(errors="replace").splitlines():
            if ",fault," in line:
                return EXIT_FAULT, f"guest fault: {line}"
    if not (trace / "summary.txt").exists():
        return EXIT_EMULATOR, f"emulator exited {returncode} without trace output"
    return EXIT_LIMIT, "time limit"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--time-limit", type=int, default=60, help="wall-clock seconds")
    parser.add_argument("--cputype", default=None, help="override conf cputype (286, 386)")
    parser.add_argument("--cycles", type=int, default=None)
    parser.add_argument("--snapshots", default="", help="name@MODULE+HEX[#N],...")
    parser.add_argument("--exit-after", default="", help="snapshot name that ends the run")
    parser.add_argument("--keys", default="", help="MODULE+HEX[#N]=key/mx+N/my-N/mb0..7,... (mouse actions are immediate)")
    parser.add_argument("--key-hold", type=int, default=None)
    parser.add_argument("--missing-file", action="append", default=[],
                        help="omit a named file from the disposable fixture copy")
    parser.add_argument("--launch", default=LAUNCH)
    parser.add_argument("--services", action="store_true",
                        help="log every software INT from module code with entry/return registers")
    parser.add_argument("--joystick", action="store_true",
                        help="enable deterministic joystick inputs and record exact gameport accesses")
    parser.add_argument("--rep-chunks", action="store_true",
                        help="record original REP decoder slices at poll points")
    parser.add_argument("--opl", action="store_true",
                        help="log every OPL register write (trace/opl.csv) and Sound Blaster DSP/DMA access "
                             "(trace/sound.csv) with emulated ms")
    parser.add_argument("--replay-ports", action="store_true",
                        help="record PIT counter, 3DAh and SB DSP status (22Ch, 22Eh) reads, run-length coded (trace/replay-ports.csv)")
    parser.add_argument("--probes", default="",
                        help="MODULE+HEX:N=name,...: log entry ms and N far-call stack words (trace/probe.csv)")
    parser.add_argument("--polls", type=Path,
                        help="translator poll points: hardware interrupts only there, logged")
    args = parser.parse_args()

    run = REPO / "tmp/pc-runs" / args.name
    missing = fixture_inputs.missing_files(" ".join(args.missing_file))
    root = prepare(run)
    fixture_inputs.stage_missing(root, missing)
    fixture_inputs.record(run, missing)
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy",
               WC2_TRACE="1", WC2_TRACE_DIR=str(run / "trace"),
               WC2_FIXED_FILE_CLOCK="1",
               WC2_SNAPSHOTS=args.snapshots, WC2_EXIT_AFTER=args.exit_after,
               WC2_KEYS=args.keys)
    env.pop('WC2_JOYSTICK', None)
    if args.joystick:
        env['WC2_JOYSTICK'] = '1'
    if args.services:
        env["WC2_SERVICES"] = "1"
    if args.rep_chunks:
        env["WC2_REP_CHUNKS"] = "1"
    if args.opl:
        env["WC2_OPL"] = "1"
    if args.probes:
        env["WC2_PROBES"] = args.probes
    if args.replay_ports:
        env["WC2_REPLAY_PORTS"] = "1"
    if args.polls:
        env["WC2_POLLS"] = str(args.polls.resolve())
    if args.key_hold is not None:
        env["WC2_KEY_HOLD"] = str(args.key_hold)
    # -exit, not -silent: -silent also removes the Sound Blaster (WC2's speech)
    command = [str(DOSBOX), "-conf", str(CONF), "-nogui", "-nomenu", "-exit", "-fastlaunch",
               "-time-limit", str(args.time_limit),
               "-set", f"log logfile={run / 'dosbox-x.log'}"]
    if args.cputype:
        command += ["-set", f"cpu cputype={args.cputype}"]
    if args.cycles:
        command += ["-set", f"cpu cycles=fixed {args.cycles}"]
    # relative to the run directory (cwd): DOSBox echoes the command on the screen,
    # so an absolute path would differ between runs
    command += ["-c", "mount c root", "-c", "c:", "-c", f"cd {GAME_DIR}",
                "-c", args.launch, "-c", "exit"]
    (run / "clock-inputs.json").write_text(json.dumps({
        "host_file_clock": "1991-01-01T12:00:00", "basis": "local calendar",
        "WC2_FIXED_FILE_CLOCK": env["WC2_FIXED_FILE_CLOCK"]}, indent=2) + "\n")
    with open(run / "stdout.txt", "w") as out:
        try:
            proc = subprocess.run(command, cwd=run, env=env, stdout=out, stderr=subprocess.STDOUT,
                                  timeout=args.time_limit + 60)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            returncode = -1
    status, reason = classify(run, returncode)
    (run / "result.txt").write_text(f"{status} {reason}\n")
    print(f"{args.name}: {reason}")
    return status


if __name__ == "__main__":
    sys.exit(main())
