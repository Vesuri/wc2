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
| Play | `make reference-staging` | DOSBox Staging, `reference/dosbox-staging.conf`: a period 386DX-33 (6000 cycles, `cputype=386`, normal core), 4 MB with EMS, `vgaonly`, Sound Blaster 2.0 (OPL2) at 220/7/1 |

## Installer facts (MEASURED)

- Runs from one flat directory; never asks for a disk swap (no file name repeats across
  disks, all volume labels are equal).
- Keys (`autotype -w 2 -p 0.5`): `enter enter enter enter s enter enter y enter` =
  C:\WING2, Save Time (unpack), VGA, Sound Blaster, speech Yes (IRQ 7), confirm.
- Unpacking is CPU-bound: a full install takes about 505 s wall clock at `cycles=max`
  (`reference/dosbox-x-install.conf`); 300 s ends during disk 5. The installer ends with
  "Installation completed. Type WC2 to play the game." and returns to DOS, where the
  batch line after it writes the completion marker.
- DOSBox-X: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`, `-nogui -nomenu -fastlaunch
  -time-limit`, `dx-capture /v` for an AVI; paths relative (the project path has spaces).
  Scripts record and wait on their own pid.

## Game runs

The game writes into `GAMEDAT` (`MEM.$$$`, `TEMPGLOB.000`, saves) and exits after
`ERR.$$$` when it cannot (MEASURED: macOS openrsync ignores `--chmod`, so
`prepare-reference` and `tools/pc_run.py` make the copy writable with `chmod`).

`reference/dosbox-x.conf`: the Staging machine (`vgaonly`, 386 normal core, 4 MB, EMS
and XMS, SB 2.0 with OPL2 at 220/7/1) at fixed 12000 cycles, `nosound=true` (devices
still emulated). `tools/pc_run.py` runs `cd WING2` then `WC2` with `-exit`, never
`-silent`: DOSBox-X's `-silent` sets the Sound Blaster type to none (MEASURED: the DSP
reset read FFh and the game ran without digitised sound).

## Trace patch (`tools/patches/dosbox-x-wc2-trace.patch`)

SWOTL's trace patch, adapted: armed at `WC2.EXE+0` (entry `0000:0000`), root image
161,760 bytes after a 6656-byte header. A module offset of `WC2.EXE` is the file offset
minus 6656, for the root and the FBOV overlays alike; driver offsets (`.DRV`) are file
offsets. Outputs beside SWOTL's (`events.csv`, `interrupts.csv`, snapshots with
`residency.csv` and `writes.csv`, `probe.csv` with the caller's return address):

- `vroomm.csv` (`icount,kind,stub,entry,linear,detail`): INT 3Fh traps, overlay reads,
  first entry into a loaded overlay (the first instruction in the overlay area after the
  trap; the timer handler and DOS run inside a trap), stub and trap-frame writes with the
  value written (`v=`), and buffer moves ([vroomm.md](vroomm.md)).
- `code-writes.csv` (`writer_module,writer_offset,target_linear,width,count,target_module,target_offset`):
  every write into an executed paragraph, with the module offset the target held at
  write time (`tools/code_writes.py`).
- `events.csv` file events: `open`, `create`, `read`, `write`, `delete`, `seek`, `close`
  by file name.
- `WC2_OPL`: OPL at 388h/389h, 220h/221h and 228h/229h (`opl.csv`); DSP, mixer and DMA
  ports in `sound.csv`.
- `WC2_REPLAY_PORTS` (`--replay-ports`): PIT (40h–42h), 3DAh and DSP status (22Ch, 22Eh:
  DOSBox-X times their busy and ready bits) reads, run-length coded, in `replay-ports.csv`.
  Host references (`tools/reference.py --host`) also take `WC2_OPL` for the DSP blocks.
- With poll points (`WC2_POLLS`) the gate also opens while the CPU halts in DOS's INT 28h
  idle stub, where DOSBox-X's CON read waits for a key (`dosbox-x-wc2-idle-irq.patch`):
  `irq` rows at module `-` (the halt, F000:D106) with `stack=SS:SP` and six words (the INT
  28h frame, then INT 21h's). Without it the name entry's `getch` (WC2.EXE+15080: flush,
  then INT 21h AH=07h) held every interrupt and the run stalled (host-m4, MEASURED).
- A key script hold per key: `key*N` holds for N instructions (flight polls keys once a
  frame and needs about 1.5 M; text entry repeats at holds above about 150 k).

## Loader model (MEASURED; `tools/wc2_model.py`, `tools/load_image.py`)

- Root: the MZ load image at the load segment (0824h with the reference config), each
  relocation word plus the load segment.
- Overlays (124, Borland VROOMM, FBOV at file 0x291e0): an INT 3Fh trap at the overlay's
  stub reads code and its 2-byte relocation records into a buffer. Each relocated word w
  becomes the load segment plus word 0 of the 8-byte root segment record at image
  0x16C40 + w (1487 of 1487 words). The buffer is compacted by a `rep movsw` at
  `WC2.EXE+F81F`, which then rewrites stub entries; the trace moves ownership with it.
- EMS: page maps only (functions 44h, 47h, 48h), no moves; no code runs in the frame.
- Drivers: `TM.DRV` and `SUPERTM.DRV` (VGA; `TM.DRV+1990` is the rectangle copy to the
  screen), `STRAX.DRV` (OPL), loaded as file bytes.

Every snapshot byte equals the model, or has a CPU writer, or is what the last DOS read
put there, or lies in a read's trailing paragraph outside the module.

## Game facts (MEASURED at 12000 cycles)

- Timer: PIT divisor 4DAEh (about 60 Hz), handler `WC2.EXE+0FD10`; about 8.2 ticks
  per million instructions. Milestone keys count its entries (`WC2.EXE+fd10#N`).
- Sound Blaster IRQ 7 (vector 0Fh, handler `WC2.EXE+06F3F`), DMA 1; speech from
  `SPEECH.S00`. Joystick port 201h is probed.
- Speech (host-m2 `sound.csv`; DSP commands and DMA mode the same through m6): time
  constant A3h (10752 Hz), 4000-byte 8-bit single-cycle blocks (DSP 14h, DMA mode 49h)
  alternating between 5:1E10 and 5:2DB0; the handler acknowledges each IRQ 7 with a 22Eh
  read and starts the next. The acknowledgement comes −1.4 to +0.9 ms from length / rate
  after the block's start (8 blocks, host-m2); −2.1 to +3.0 ms (170 blocks, host-m3) and
  −2.7 to +1.4 ms (170, host-m4).
- Mode 13h is set by INT 10h at `WC2.EXE+5600E`, an overlay's generic set-mode routine.
- Flight frame: 66.7 ms (4 timer ticks, set by the frame limiter at `WC2.EXE+10642`,
  which waits in `WC2.EXE+10636`–`10640`), of which 23.3 ms is work at 12000 cycles
  (`tools/frame_time.py`, [feasibility.md](feasibility.md)). Each frame blits five
  cockpit windows through `WC2.EXE+7626` (window index) and `WC2.EXE+7400` (rectangle
  to the `TM.DRV` table); the first returns to `WC2.EXE+813C`, which runs once a frame
  and only in flight (335 times in 335 frames).
- Mission 1 (MEASURED): the Caernarvon refuses landing ("Negative, do not land.") until
  Nav 1–3 are flown. A Sartha attack at Nav 1 kills a passive or firing Ferret; the nav
  is done only when flown within about 1600 km (Nav 2 from 2000 km stays open, and after
  Nav 3 the destination returns to it).
- Debug mode, the game's own (`WC2 Origin -k`, MEASURED in the argument parser at
  `WC2.EXE+39FE0`): "Origin" sets `[00BC]`, `-k` then clears `[00C0]` (invincibility);
  Alt-Ins destroys the enemy fighters on the radar. It also writes `LOGFILE.TXT`. m5
  and m6 use it, so the reference reaches the landing without scripted combat.
- Flight keys: A autopilot (refused with "Enemy Near" or "Hazard Near"); N opens the
  nav map, N cycles the destination, Enter keeps it, Esc reverts; C opens comms
  (1 Shadow, 2 Caernarvon; 1 Request landing); the keypad changes speed. The white
  cross on the left radar is the destination: centred at (78,137) when ahead.
- Quarters pointer: it starts near (280,109), 2 mickeys a pixel; `mx-516,my+18`
  reaches the Save/Load terminal, which opens on the load list; any input returns to
  the personnel menu ([L]oad, [S]ave, [D]elete). Saves go to `SAVEGAME.WC2` (8 slots,
  which pilot creation writes first).
- Input path to flight: main menu (about 2400 timer ticks), click "Start New Game"; the
  intro with speech (about 13,600 ticks; the reference's scripted Esc taps and clicks did
  not skip it, but Esc held for 10 fields skips each scene on the Amiga build: OPTIONS.V00
  at field 5,945 instead of 57,132, MEASURED); the pilot file
  ([C]reate, first name, last name, callsign); quarters (airlock = fly, left terminal =
  save/load, right door = storyline); the flight-deck briefing and launch (about 6400
  ticks).

## Milestones (`reference/milestones.csv`, `make reference`)

Keys and snapshot triggers count entries of the timer handler (`WC2.EXE+fd10#N`, relative
to the previous trigger) or of a code address; `key*N` holds a key for N instructions.
Every milestone runs twice; every snapshot of both runs passes the image proof, and
their RAM, VRAM and DAC are byte-identical (`tools/reference.py`).

| Milestone | Snapshot | Signal |
|---|---|---|
| m0 | `WC2.EXE+0`, the entry | text mode; the root image at the load segment |
| m1 | `WC2.EXE+56010#1`, after the mode 13h INT 10h | mode 13h |
| m1b | 700 ticks: the first stable picture | `TM.DRV` resident |
| m2 | 2100 ticks after "Start New Game": the intro | `SPEECH.S00` opened, IRQ 7 taken |
| m3 | 13,700 ticks after the click: the pilot file | |
| m4 | the first flight frame (`WC2.EXE+813c#1`), then 50 frames later | `STRAX.DRV` resident |
| m5 | debug mode; autopilot and Alt-Ins through Nav 1, a 20M-instruction dive and a 3M climb into Nav 2, Enter on Nav 3 in the nav map, autopilot home, landing request: the radio debriefing, then the landing approach | two snapshots advance |
| m5f | debug mode; m5's route to its first autopilot, which drops out at Nav 1 into the Sartha attack, Backspace 600 ticks later; the first and the 50th flight frame (`WC2.EXE+813c`) after it, every frame between drawing 9–14 scaled objects (MEASURED on a probed run of the route) (P7.2: the meter's fight window) | `SUPERTM.DRV` resident |
| m6 | m5's route, then the quarters terminal: Enter, S, Enter (slot 0), name, Enter (save); L, Enter, Enter (load) | `SAVEGAME.WC2` opened (the exploration runs saw it written to slot 0, then read back) |
