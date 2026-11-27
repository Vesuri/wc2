# Amiga platform architecture

> Copied from Secret Weapons of Luftwaffe `658fc60` ([upstream.md](upstream.md)). Its rules
> and methods apply here; its addresses, measurements, step history and decisions are
> SWOTL's, kept for reference until a WC2 phase re-derives them.

How the target side of this port is structured. Each rule is derived from what shipped
in Slicks (SL), Vette (VT) and Revs (RV); the numbered lessons cited as `L<n>` are in
[amiga-lessons.md](amiga-lessons.md). Translation design: [translation-lessons.md](translation-lessons.md);
build: [toolchain.md](toolchain.md); emulator harness: [headless-fsuae.md](headless-fsuae.md);
slave: [whdload.md](whdload.md).

## Target contract

| Item | Value |
| --- | --- |
| Machine | PAL or NTSC A1200, 68020, AGA required (`GFXF_AA_LISA` after `SetPatch`), L8 |
| Memory | 2 MiB Chip for DMA data; Fast RAM required (D15, [translator-design.md](translator-design.md)); default 4 KiB Shell stack, L52 |
| Launch | Shell, Workbench (L84: the icon's tool types and drawer) and a WHDLoad slave (kickemu, INITAGA; [whdload.md](whdload.md)), the same executable; the release image takes the player options only |
| Display | 320×200, 8 non-interleaved planes, 256 colours from the 18-bit VGA palette, L31 |
| Timebase | vblank (50 Hz PAL, 60 Hz NTSC: graphics' `DisplayFlags`, `amiga_ntsc`) for display, input and audio; PIT channel 0 on a CIA-B timer (D8) |

## Layers

| Layer | Contents | Rule |
| --- | --- | --- |
| Framework | `src/platform/amiga/framework/`: `AmigaHardware`, `Bitmap`, `CopperList`, `Palette24Bit` (+ `Palette`, `Sprite`, `Util` headers) from SL's DanceDiverse3 set | C++ bodies only; every local change recorded in `framework/README.md` (L90, L95) |
| Platform | takeover, VBI, display views, C2P, Paula, keyboard/mouse, PIT timer, I/O windows, allocation | single owner per hardware register group; no game logic |
| Runtime | `src/runtime/`: the reference machine as the guest sees it (DOS, BIOS/EMS, INT 33h, IVT; PIC/PIT/AdLib/joystick ports in `ports.c`); RTSVGA and SPAZ run translated | behind `platform.h`, one implementation for host and A1200; any other port stops ([architecture.md](architecture.md)) |
| Translated game | generated 68020 code | calls the runtime through explicit register contracts ([translator-design.md](translator-design.md)) |

Not used: the framework's `Production`/`Part`/`Script` timeline and module player
(RV, VT `framework/UPSTREAM.md`). `Swotl` follows `ProductionRunner`'s takeover through
`AmigaHardware` but owns Exec's VERTB vector, not the level-3 autovector (L10, L13). The
template (dA JoRMaS `Template/C++`) has no AGA 256-colour palette; the vendored
DanceDiverse3 set (`Palette24Bit`, `setPalette24Bit`) is kept for it.

## Lifecycle

1. **Entry.** `start.c`'s `_start` replaces the shared one (L86; the link holds it at the
   hunk start): without `pr_CLI` it takes the WBStartup message before the constructors
   (L84). Open dos/graphics outside `Forbid`; require AGA (L8); parse the arguments with
   `ReadArgs` (`ANALOGJOYSTICK/S,MUSIC/S,BENCH/S,KEYS/K` from `Input()`'s buffer,
   where the Shell and the slave's `RunCommand` put the line; `?` prompts; a bad line:
   `PrintFault`, 20), or from Workbench `CurrentDir` to the icon's drawer and read its
   tool types (same keywords; `KEYS` copied). The release image (`WC2_RELEASE`,
   [release.md](release.md)) takes `ANALOGJOYSTICK` only.
2. **Reserve.** Every game-owned block, all-or-nothing, largest first; Chip only for DMA
   data (L53, L54); only find-first's name list and records are allocated later, inside
   their I/O window (`plat_alloc`): one directory pass (`plat_dir_names`), then one
   `Lock`/`Examine` per matching name (`plat_file_info`). Failure frees everything before
   takeover; `main` returns 20 (0 after a run), which `_start` returns (L86).
3. **Load.** The guest's own files, later, through I/O windows.
4. **Build.** Bitmaps, copper lists and palettes completely, then publish them to the ISR
   (L15).
5. **Take over** in SL's order (L2, L3), VERTB vector (L10), keyboard SP off in CIA-A's
   ICR mask (L72, irq-plan I7), `Forbid` (L6).
6. **Run.** The translated program runs on its own stack (`amiga_guest_run`); SPAZ's
   tick runs in the CIA-B interrupt, keys reach the guest at its services (D8); the field
   task presents (D9). Disk access only
   inside I/O windows (L7). SWOTL: every DOS call of `amiga_platform.c` is one window
   (`Swotl::beginIO`/`endIO`): Exec's VERTB and SOFTINT vectors, saved INTENA and DISK|BLITTER DMA
   back, `Permit`; the copper display stays, a VERTB server reads the keyboard; fields the
   OS serves are added from `GfxBase->VBCounter`.
7. **Return** in SL/VT's order (L4), then pending saves, frees, `releaseBlitterQueue`
   (L50), the previous current directory and library closes; after the finalizers `_start` replies
   the WBStartup message under `Forbid` (L84). A readable-state restore check runs in
   the harness (L5).

## Interrupts

| Source | Owner | Content |
| --- | --- | --- |
| Level 3 VERTB | taken-over Exec vector | clear INTREQ (L11) → display publication (L17, L25–27) → field counter → keyboard byte if `ciaa.resource` flags SP ([irq-plan](irq-plan.md) I7) → mouse and typematic repeat (L77, L79–80) → Paula staging (L62–63) → request SOFTINT |
| Level 1 SOFTINT | taken-over Exec vector | field task ([irq-plan](irq-plan.md) I5): clear INTREQ → key script, `fm_field` on an OPL snapshot taken under `Disable` → the due present (D9) unless a driver call or the main thread's present or video BIOS call runs (`video.c` busy) |
| Level 2 PORTS | Exec chain | `ciaa.resource` for the OS's CIA-A sources (L13); keyboard SP disabled (I7) |
| Level 6 EXTER | Exec chain | PIT via a `ciab.resource` timer (`amiga_platform.c`): SPAZ's handler at once through `rt_irq_interrupt` when `rt_irq0_ready` ([irq-plan](irq-plan.md) I6), EXTER acknowledged and the mask lowered to 2 so the vertical blank preempts it; else posts vector 08h (always under `BENCH`) |
| Level 3 BLIT | masked | unless the framework blitter queue is adopted (L14) |
| Others | Exec | untouched; restored masks on exit |

The original's keyboard (INT 09h) handler does not run in Amiga interrupt context
(L18). SPAZ's timer handler runs in the CIA-B interrupt (RC1, L18 exception, irq-plan I6);
the keyboard is read at the vertical blank (RC4, irq-plan I7). A tick the
interrupt cannot run goes to `rt_irq_ring` and is taken by the next CIA tick
(`rt_irq0_take`) or at the guest's next IF 0→1; keyboard events go to `rt_key_ring`,
drained at service entry with guest IF set (`rt_keyboard_drain`). Generated code has no
poll checks ([translator-design.md](translator-design.md) D8). Shared rings are guarded
by `Disable`/`Enable` (L20).

## Display

- **Mode.** 320×200, eight non-interleaved planes, 40-byte rows; the framework
  programs AGA wide fetches and DIW `$38..$ff`. Plane allocations are 8-byte aligned.
- **Surfaces.** Translated drawing writes guest VGA memory. The runtime snapshots
  published dirty rectangles into persistent chunky storage with 32 bytes of C2P
  lookahead; the platform alone converts to bitplanes.
- **Conversion.** Kalms `c2p1x1_8_c5_bm`. The runtime presents only the 32-pixel blocks
  of the marked rows whose pixels differ from its persistent frame (D19, `video.c`
  `present`); `DisplayQueue` keeps, per bitmap and row, a mask of the blocks changed
  since that bitmap's own conversion, so each bitmap converts exactly what it lacks: one
  call per run of blocks in a row, or per band of wholly changed rows. Plant
  `PLANT=BLOCK_INHERIT` (a conversion clears both bitmaps' marks) fails
  `amiga/display_audit.sh`.
- **Buffering.** Two Chip bitmaps and two complete copper lists. Each bitmap retains
  dirty rows until its own conversion, including updates superseded before a VBI.
  Main withdraws the pending list before writing its bitmap; VERTB publishes only
  completed lists.
- **Palette.** DAC changes invalidate both physical lists. A publication
  rebuilds its inactive list only if stale, and carries forward its dirty
  pixels, including palette-only updates. Validity is main-thread state. The list and bitmap are handed
  off together; live copper words are never patched.
- **Publication timing.** Queued handoffs are beam-stamped and deferred if VERTB
  arrives too late. `amiga/display_audit.sh` requires zero late switches, also on
  `AMIGA_CPU=68040` (L26, L29).
- **Copper lists.** Fully written up to the terminator (no NOP prefill in this lineage,
  L22); one owner per write-only register (L30).
- **Pointer.** The guest's software pointer is masked out of the presented frame (runtime
  `pointer.c`) and shown by sprites 4 and 6 (`Pointer.cpp`, BPLCON4 `$00FF`: `FE` exact,
  the other colour through entry `F9`, unused on pointer screens). Sprite data per buffer,
  rewritten only on a shape change; all eight `SPRxPT` before the palette; the VBI writes
  position (guest position + lead + hotspot) and visibility (a state held for a field).
  Fetch window `DDFSTRT $38`/`DDFSTOP $B0` (the framework's AGA `$20` takes the slots of
  sprites 3–7).
  Facts and checks: [pointer-plan.md](pointer-plan.md).

## Timing

Game time is the original's own PIT channel 0 at the rate the guest programs
(`plat_timer_rate`: CIA latch = PIT divisor scaled to the PAL or NTSC E-clock), one posted INT 08h
per period (L44). Publication never feeds back into simulation; missed slots are not queued
(L43). `BENCH` replaces the timer by ticks from guest progress for deterministic benchmarks
([speed-plan.md](speed-plan.md) §4).

## Audio

- **Sources (MEASURED, m6 and the exit traces):** STRAX.DRV plays music and effects on the
  OPL (ports 388h/389h); WC2.EXE drives the Sound Blaster DSP itself for the digitised
  speech (single-cycle DMA blocks, IRQ 7; the commands in `src/runtime/ports.c`).
- **Music and effects**: STRAX.DRV runs translated into the runtime's OPL register shadow
  (`rt_opl`); a Paula-only re-hoster (`fm_paula.c`, `Audio.cpp`, fed each field by
  `amiga_audio_service`) never decides what sounds (L71). The one-shot effects are
  prerendered at the game's sound init, before the first scene, or loaded from `sfx.cache`
  without a capture, and played by `fx_play.c` (D13, D14, D15, [drivers.md](drivers.md) "FM effects").
- **Speech**: `plat_sb_block` hands each DSP block to `Audio.cpp`, which converts it to
  signed samples in one of two 64 KiB Chip blocks; `sb_play.c` (X-Wing's) plays it on Paula
  voice 3 from the next field, the FM re-hoster giving that voice up while it plays, at
  volume 64 with the DSP speaker on (D1h); the next block, which the game starts at the
  last one's IRQ 7, is latched behind it without a restart. IRQ 7 comes at length / rate from the block
  timer on CIA-B's other timer, not from the player's fields (`make test-amiga-speech`).
  Facts and methods: [sound-plan.md](sound-plan.md) (SWOTL's until re-derived).
- **Shared rules.** Channel ownership between music and effects is an explicit policy
  (L59); stereo placement deliberate (L68); the LED filter is off from the takeover and restored as found at the hand-back (L69).

## Input

The vertical blank's keyboard read (L72; in I/O windows a VERTB server) maps each raw key
edge through one table to a PC set 1 make/break code and posts it to `rt_key_ring` with
vector 09h; unmapped codes are counted (`amiga_unmapped_keys`, L76). Presses stay pending until the original reads them (L75);
typematic repeat runs in the VBI (L77). The mouse (port 0) is sampled per VBI
(L79–80) and at each INT 33h request (`Input::sample`), so a frame's motion runs up to
its poll; a button pressed at any sample is held until the next INT 33h read
(`mouseLatched`: the game polls AX=03h only between frames, and a short click on a menu
item was lost, user report); its deltas feed the runtime's INT 33h driver (`plat_mouse`; in flight scaled to
a fixed frame time, `rt_mouse_scale`; vertical counts 1:1, `rt_mickeys_y`;
[translator-design](translator-design.md) D9), and the counts
not yet taken feed the pointer sprite's lead (`rt_pointer_lead`, the guest's own motion
rule). Port 2 (`Input.cpp`): by default a digital joystick whose directions are
cursor-key edges (typematic as keys) and whose fire and pin-9 buttons are mouse
buttons 1 and 2; port `201h` answers as the reference's absent one. With
`ANALOGJOYSTICK` (`rt_joystick`) port 2 is a proportional stick: POTGO START per field,
each field's POT1DAT (X the high byte, pin 9, Y the low, pin 5: the HRM's names swapped
the axes on a real stick, SWOTL user report 0.91; unaveraged: HRM 8-1-4-4's jitter is
the stick's pots, the PC original reads raw) + 16 is the reads before each axis one-shot
times out (`src/runtime/ports.c`), counted by the game's timing loop `WC2.EXE+14F5A`;
buttons on pins 3/4 reach the gameport only (in SWOTL the game ors gameport and swapped
mouse buttons, so a mouse copy made each stick button both, SWOTL user report 0.92).
POTINP's mouse buttons are read before the START (its discharge pulls the pins low).
WC2 calibrates in flight: Ctrl+J. The flight key handler `WC2.EXE+04C58` runs once per
flight frame on the scan byte at DGROUP 43C0h; on scan 24h with the game's Ctrl bits
(word D148h & 1800h, set by its key reader `WC2.EXE+10100` for scan 1Dh; Alt is 600h) it
calls overlay stub `17BF:002F` (entry 3), `WC2.EXE+36FFA`, whose prompts are DGROUP
8738h, 8766h, 8793h and 87C1h (DERIVED by reading). The game keeps its own key state: its
INT 15h intercept (`WC2.EXE+0FD93`) calls `WC2.EXE+1036B` per scan code, which marks the
table at DGROUP D184h (40h made, 80h broken); the reader turns it into press, repeat and
release events whose character comes from `WC2.EXE+10785` (lower case unless the game's
Shift bits C0h are set; MEASURED on the Amiga build at the personnel screen: `c` made
at 40h, broken at 80h). The personnel screen's [C]reate takes Shift+C on the Amiga build
(user report); the reference took a plain `c` whose make and break (about 120,000
instructions apart) fell inside one reader call, so the game saw only the release
(INFERRED). Human-length presses on the original may behave as on the Amiga build.
The game's input events (DERIVED by reading, MEASURED on the Amiga build with a
`tmp/` gdb probe): the input tick `WC2.EXE+106CD` (`106C:000D`) empties the event ring
(`1066:000C`) on every call, then, once the poll interval `A316` has passed since the last
poll, polls the devices: the mouse (one INT 33h AX=03h, `amiga_mouse_reads`) before the
key reader `WC2.EXE+10100`, which emits through `WC2.EXE+0FFF0` a press (type 4) the
first time it sees a scan's make, a repeat (6) at its typematic count, and a release (5)
on the break; a make and break between two polls leave only the release. So an event
reaches only the consumer that runs between its poll and the next tick. The personnel
screen runs two, each after its own tick, and on the 68030 model every tick polls, so they
alternate poll for poll (every 3–7 fields): the menu `WC2.EXE+5139F` (`50FA:03FF`) takes
a click (type 1; a press only for scan 24h, the calibration), and the scan-byte reader
`WC2.EXE+33400` (`3340:0000`) turns a press or repeat into DGROUP 43C0h, where the
screen's hotkeys ([C]reate) read it. A press seen at the menu's poll is lost: Create is
taken only when the key's first poll is the reader's (in about half the runs), whatever
the hold, as measured before (7 of 12, 2 of 4 and 0 of 4 runs at 5, 10 and 20 fields;
a 5-field press could also fall between two polls). The smoke's `w:shift+c` holds each
press over two mouse reads and repeats it until the name prompt waits on the console
(`rt_key_waits`). Its repeat is 60 frames less 0–7 in turn: with D18's skip the screen's polls
kept pace with a fixed 60, and every press met the menu's poll (0 of 44 presses taken in
one run, 2 runs of 2 stalled; with the shift 3 of 3 passed, MEASURED 2026-11-26). A click 5 fields
after a move came before the hover highlight; a later one was dropped; the menu snaps the
pointer to the item under it (an AX=4 of its own, which lost a following move); a held
button repeats clicks every 5 fields; an Enter there acts as a click and, on no item,
exits to the OS. The menu puts the pointer at (400,54) on entry (MEASURED). The name
prompt reads keys through DOS, and its first poll comes before it takes them (a `k1:a`
lost the first key, MEASURED), so the smoke types the names 150 ticks after Shift+C. Esc held for 10 fields skips each
cinematic scene; a repeated Esc must stop at the title's own BUTTONS.V00. In the original
Esc on the title menu does not quit, and Alt+X does: it frees its EMS handles, sets mode 3 and
ends with INT 21h AX=4C00 at WC2.EXE+00160 (MEASURED, milestone `mx1`). The hand-back seen at
field 1,953 after a repeated Esc on the Amiga is therefore not the original's quit.

## Files

Each guest DOS file call (open, create, read, write, seek, delete, directory) is one
dos.library call in its own I/O window, relative to the current directory (L7). Saves are
the guest's own create/write calls; L83 and L88 are not applied. Any code loaded or patched
at runtime is followed by `CacheClearU()` (L87). The effect cache `sfx.cache` is read
per effect straight into Chip and written by one `Write` from a Fast image (sound-plan R4);
its key is the file bytes the game read before its sound init and the build (D15).

## Build rules

`-m68020 -msoft-float -nostdlib -fcheck-new`, framework headers via `SASCCompat.h`,
`AmigaHardware.h` included last, vasm `-no-opt` for hand-written asm, replaced
`memset`/`memcpy`, `elf2hunk -s` for release (L94, L96–103, L105); L104 (`alignas(4)` with a
link audit) not applied (open-work 41). Exact flags: [toolchain.md](toolchain.md).

## Standing target checks

| Check | Proves | Source |
| --- | --- | --- |
| Restore status | OS view, vector, DMA and INTENA restored; LED filter off during the run and restored | `make test-amiga-restore` |
| Beam watch | zero late display handoffs; no conversion into the shown bitmap | `amiga/display_audit.sh` |
| Workbench start | icon start: tool types read, data from the icon's drawer, menu exit (EMS release, mode 3, console text) without a runtime stop restores, result 0 with the message held; `BENCH` from the icon and the Shell: 20; Shell arguments in lower case, after `?` and a bad one (IoErr 118, 20); the release image: `tfh analogjoystick` taken, `KEYS`, `MUSIC`, `BENCH` refused (IoErr 118, 20) | `make test-amiga-workbench` |
| Keyboard | `monitor key` edges read by the I/O windows' VERTB server and the takeover VBI, typematic 1 + 7 in 61 fields | `make test-amiga-keyboard` |
| Audio VBI spills | Paula work stays in blanking | none here; Slicks `g_slicks_audio_vbi_spills` |
| C2P store verifier | converters write only final, correct plane words | none here; Slicks `tools/verify_planar_writes.sh` |
| Allocation audit | zero outstanding blocks, repeat launch, low-Chip failure | none here; Slicks `tools/memory_audit.py` |
| Stack watermark | fits the 4 KiB default stack | none here; Slicks `STACKCHECK=1` |
