# PC reference loop

Ground truth is the original running unattended under DOSBox-X from a disposable copy,
never `ref/` itself. Secret Weapons of Luftwaffe `docs/pc-reference-loop.md` has the full
method (instrumented DOSBox-X, milestones, traces); reuse it rather than re-deriving.

## Pipeline

| Step | Command | Result |
|---|---|---|
| Extract | `make extract` (`tools/extract_originals.sh`) | `tmp/extract/`, `tmp/disks/diskN/`, `tmp/union/` (185 files), `tmp/wc1/`; every stage hash-checked |
| Install | `make install` (`tools/pc_install.sh`) | the original `INSTALL.EXE` headless, A: = copy of `tmp/union`, C: = `tmp/pc-install/c`; checked against `reference/install.sha256`, copied read-only to `ref/` |
| Disposable root | `make prepare-reference` | `tmp/pc-root` (= C:) |
| Play | `make reference-staging` | DOSBox Staging, `reference/dosbox-staging.conf` |

## Installer facts (MEASURED)

- Runs from one flat directory; never asks for a disk swap (no file name repeats across
  disks, all volume labels are equal).
- Keys (`autotype -w 2 -p 0.5`): `enter enter enter enter s enter enter y enter` =
  C:\WING2, Save Time (unpack), VGA, Sound Blaster, speech Yes (IRQ 7), confirm.
- Unpacking is CPU-bound: at `cycles=max` a 300 s wall-clock limit ends during disk 5
  (`HITDEMO.V00`) with every 20 s frame still changing, so the limit, not a stall,
  stopped it. `reference/dosbox-x-install.conf`.
- DOSBox-X: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`, `-nogui -nomenu -fastlaunch
  -time-limit`, `dx-capture /v` for an AVI; paths relative (the project path has spaces).
  Scripts record and wait on their own pid.

## Game runs

`reference/dosbox-x.conf`: S3 SVGA, 4 MB, 386 normal core, fixed 12000 cycles, EMS and
XMS on, SB16 at 220/7/1. The game's CPU level and cycle needs are open (open-work 3, 4).
