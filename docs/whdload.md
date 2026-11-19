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

`make test-whdload` runs all four.
