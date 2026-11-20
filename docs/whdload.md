# WHDLoad slave

`whdload/Wc2Slave.s`, from SWOTL's slave (SWOTL `docs/whdload.md` holds the sibling rules
and their provenance; [upstream.md](upstream.md) the import). Packaging, Installer and
audits: [release.md](release.md).

## Model

Kickemu (Kickstart 3.1, `BOOTDOS`, `INITAGA`, `HDINIT`): the slave runs the native
executable `data/Wc2` through `dos.RunCommand` with a 16 KiB stack. The argument line goes
into `Input()`'s buffer as a Shell puts it, so the same executable runs from a Shell or from
Workbench (amiga-arch.md "Entry"). The program opens `WC2.EXE` itself (`machine.c`
`exec_root`) and the overlay manager reads overlays from it during play (vroomm.md).

| Field | Value | Why |
|---|---|---|
| `slv_Flags` | `NoError`, `Req68020`, `ReqAGA` | D1 (AGA, 68030 minimum; WHDLoad has no 68030 flag) |
| `slv_keyexit` | `$5F` Help | the game's key table has no Help key |
| `slv_CurrentDir` | `data` | installed layout ([release.md](release.md)) |
| `ws_DontCache` | `(Wc2)` | `_load` reads `Wc2` in two reads (hunk header, then the file into one block for `resload_Relocate`); `WC2.EXE` stays cached, as its relocations are read 4 bytes at a time and overlays during play, each uncached read an OS switch |
| `slv_config` | `C1:B:Analog joystick in port 2;` | Custom1 passes `ANALOGJOYSTICK` |
| `$VER` | `Wc2.slave 0.1 (19.11.2026)` | checked by `tools/check_release.py` |

Variants (`whdload/Makefile`, test scaffolding, never packaged): `Smoke.slave` (harness),
`BootTest.slave` (Kickstart boots), `LoadTest.slave` (`_load` and PROGDIR; its relocated
block saved), `Wc2Test.slave` (marks), `MemFree.slave` (low-water free memory at `$100`).

## Memory

`CHIPMEMSIZE = $C0000`, `FASTMEMSIZE = $700000` (ExpMem `$780000` with Kickstart). The game's
blocks are reserved at start (amiga-arch.md "Reserve"): code and BSS, the guest block
(state, 1 MiB guest RAM, the EMS store), the guest stack; in Chip two screens and copper lists, the
pointer and the FM audio pool. Later allocations are only find-first's name lists, freed in their I/O
window (`dos.c`), so the attract mode's low water stands for flight too (INFERRED from the
code; no WHDLoad route into flight exists yet: the release image has no `KEYS`).

MemFree low water (largest free chunk), `tools/test_whdload.py --mode run --slave
build/whdload/MemFree.slave`, release image, 68030, PreLoad, attract mode, 2026-11-19, MEASURED:

| FASTMEMSIZE | Host Fast | Fields | Chip free | Fast free | Result |
|---|---|---|---|---|---|
| `$700000` | 8 MiB Zorro II + 8 MiB Zorro III | 1,500 | 535,248 | 1,212,536 | runs |
| `$700000` | 16 MiB as above | 6,000 | 535,248 | 1,207,096 | runs |
| `$700000` | 8 MiB Zorro II | 3,000 | 535,248 | 1,207,096 | runs |
| `$640000` | 8 MiB, 16 MiB | 3,000 | 535,248 | 420,664 | runs |
| `$600000` | 8 MiB, 16 MiB | 3,000 | 535,248 | 158,520 | runs |
| `$700000` | 4 MiB Zorro II (control) | — | — | — | WHDLoad: "Can't allocate ExpMem." |

`$700000` is kept: an 8 MiB host runs it, and its 1.2 MiB headroom is left for open-work 19
(the sound still to come, its cost unmeasured). Chip keeps `$C0000` (251 KiB used) for the
same reason. `make -C whdload memfree 'FASTSIZE=\$$600000'` builds a sizing variant (the `$` is
escaped for both make and the shell). A 68EC020 board maps at most 8 MiB Zorro II beside
the slave, so the tests default to a 68030 (D1's minimum).

## Caches

`CACHE`: ExpMem copyback, BaseMem noncacheable, which needs WHDLoad's MMU (68040/060, or a
68030 with the `MMU` option). Without it WHDLoad switches every cache off (CACR 0); then
`_bootdos` sets `CACHECHIP`'s instruction cache. Measured CACR (`test_whdload.py` judges it
from the core dump): 68030 without the MMU option `2011` (2026-11-19).

## Checks

`tools/test_whdload.py` (FS-UAE, isolated `tmp/whdload-test-*` fixture, own pid only):

| Mode | Positive signal | 2026-11-19 |
|---|---|---|
| `smoke` | the harness slave returns | PASS |
| `boot` | Kickstart 3.1 kickemu boots, `TDREASON_OK` | PASS |
| `load` | the relocated block equals the executable relocated independently | PASS (6 hunks, 2,144,728 bytes) |
| `run` | TIMEOUT reason (not a fault), most `WC2.EXE` load-image blocks in guest RAM (reversed), CACR as the cache policy says | PASS (1,013 of 1,889 blocks, CACR `2011`) |
| `script` | `KeysTest.slave` (`-DKEYS`: `data/keys` appended to the argument line) runs the diagnostic image `Wc2-diag.exe` (`make amiga-diag`) under a key script; `--expect exit`: the core dump says `Return OK.` (the slave quits with `TDREASON_OK` only when the program returned 0) with no TIMEOUT, and the boot script passed; `--expect timeout`: the TIMEOUT reason; `--expect-file`, `--expect-read` (FILELOG) for saves | see the matrix |

`make test-whdload` runs the first four.

## Release matrix (C7, open-work 26)

The release slave and image unless the row says otherwise; FS-UAE `a1200` (68030, 8 MiB
Zorro III) by default. MEASURED 2026-11-19 and 2026-11-20.

| Row | Run | Result |
|---|---|---|
| 68030, PreLoad / no PreLoad / NTSC / analog joystick (Custom1) | `--mode run [--no-preload] [--ntsc] [--analog]` | PASS: CACR `2011` each |
| 68030 with MMU emulation, WHDLoad's MMU unused / used | `--setup a1200-030 [--whdload-mmu]` | PASS: CACR `2011` / `2111` |
| 68040, 68060 | `--setup a1200-040`, `a1200-060` | PASS: CACR `80008000`, `A0808000` |
| Exit: Alt+X on the title menu | `--mode script --keys 'uBUTTONS.V00:esc*10,d300:alt+x' --expect exit --max-speed` | PASS (host lockstep to the original's INT 21h AX=4C00, milestone `mx1`) |
| Exit: the quarters window (Exit to DOS) | `--mode script --expect exit --max-speed --ticks 6000`, the `play_walk.sh` route to the quarters, then `mx-2000,my-2000,mx+156,my+101,lmb` | PASS (host lockstep, milestone `mx2`) |
| Control: Esc on the title menu does not exit | the Alt+X route with `esc`, `--expect exit` | FAIL as required: TIMEOUT (`DEBUG caused`) |
| Exit: WHDLoad's QuitKey (Help) | real keyboard only | not run: the owner's manual pass |
| Save and load | a save from the quarters terminal, read back (`--expect-read`) | not run: needs the save route recorded in DOSBox-X first |
| Input devices (mouse, joystick, analog stick on hardware ports) | the KEYS paths are covered by `amiga/play_walk.sh` | hardware pass not run: the owner's manual pass |
| Standalone (no WHDLoad) start | `make test-amiga-workbench` | not run in this pass |
