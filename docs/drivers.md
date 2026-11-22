# Drivers

The game's three drivers (port-plan P2.2). Offsets are file offsets (`TM.DRV+x`), the
tracer's module offsets. MEASURED over the milestone traces unless marked.

| Driver | Serves (INFERRED from its ports and callers) | Loaded entry | Bytes | Linear address (load segment 0824h) | Entry table |
|---|---|---|---|---|---|
| `TM.DRV` | VGA mode 13h drawing: blits, rectangles, fills, the DAC (3C7h–3C9h) | entry 0, `TM.DRV+000C..2E26` | 11,802 | 450D0h (load + 3CE9h paragraphs) | 22 words |
| `SUPERTM.DRV` | scaled and rotated sprite drawing (the space view) | entry 0, `SUPERTM.DRV+000C..7571` | 30,053 | 47EF0h (load + 3FCBh) | 5 words |
| `STRAX.DRV` | the FM music and effects: every OPL write (388h/389h) | entry 1, `STRAX.DRV+04DD..146F` | 3,986 | 4F470h (load + 4723h) | 12 words |

Speech is not a driver: root code programs the Sound Blaster DSP (226h–22Eh) and DMA
channel 1 (`WC2.EXE+06CBF`), and takes IRQ 7 at `WC2.EXE+06F3F`
([external-surface.md](external-surface.md)).

## File and load

A driver file is an Origin container (as `tools/origin_pak.py` reads): a dword file
size, then dword entry offsets with flags in the high byte (E0h), the first entry
starting after the table. `TM.DRV` and `SUPERTM.DRV` hold two entries, `STRAX.DRV`
three; the other entries are never read in the traces (INFERRED: other video and sound
cards). The game's container reader opens the file (`WC2.EXE+116DA`), reads the size
and the entry table, seeks to the entry (`WC2.EXE+118F5`), and reads the whole entry in
one DOS read (`WC2.EXE+117F7`) into a paragraph-aligned block from the game's
allocator (INFERRED: its pool is one `farmalloc` of `[C992h]` KB at `WC2.EXE+3EAE`), right above the overlay buffer (319Ch–450Ch). Each driver is loaded once,
never moved or freed, and runs with CS = its block's segment, IP 0 = the entry's first
byte. No relocation is applied: the bytes in memory are the file bytes (gate 1's image
proof, `tools/load_image.py`).

Every trace loads the three at the same paragraphs relative to the load segment (the
milestones at load segment 0824h; six earlier exploration runs at 0822h, all two
paragraphs lower). So each is translated at one CS with a residency check (static CS,
as SWOTL's overlays), not as a dynamic-CS module (port-plan P2.2, P4.2).

## Entry table and calls

The entry starts with a table of near offsets: word 0 is 0, then one word per function
(0 for an unused slot). The game copies far pointers (driver segment : table word) into
its data and calls them with `call far [mem]` from root and overlay code, e.g.
`WC2.EXE+40C0` → `TM.DRV+199C` (entry 11, the rectangle copy to the screen, P1's
frame chain) and the timer handler `WC2.EXE+0FD8E` → `STRAX.DRV+12BA` (entry 4, the
music tick). Traced entries: `TM.DRV` 1, 3–15; `SUPERTM.DRV` 1–4; `STRAX.DRV` 1, 2,
4–9. The game's driver loader `WC2.EXE+565B3..566B1` copies the loaded graphics driver's
table words 1–22 and 25 (offsets 2..2Ch, 32h) with its segment into 23 DGROUP slots (A83Ch,
A840h, A844h, DECAh..DF0Eh, DF12h, DF26h; `annotations/driver-slots.csv`, DERIVED by
reading), then writes the callback 1581:0021 over words 23–24. Every far call through one
of them is a driver call (D9), traced or not: WC2's joystick calibration (Ctrl+J) fills
the screen through DF06h (`TM.DRV` entry 19, 1B6Ch), which no reference trace reached.

The drivers call back into the game through far pointers the game writes into them:
`TM.DRV` `cs:[2Eh]` and `SUPERTM.DRV` `cs:[0Ch]` → `WC2.EXE+15831`, `STRAX.DRV`
`[1Ch]` → `WC2.EXE+132CC`. `SUPERTM.DRV` dispatches internally through near pointers in
its code segment (`cs:[6C2h]`, `cs:[6C4h]`) and two jump tables (`cs:[di+4ACh]`,
`cs:[di+4ECh]`); `tools/sweep.py` lists their traced targets (tmp/sweep/indirect.csv).

## Vectors and services

No driver installs an interrupt vector, calls DOS or the BIOS, or runs an interrupt
handler of its own: every handler the traces took is root code, and no service event
comes from a driver. `STRAX.DRV` reads PIT counter 0 around its OPL writes (43h ← 06h,
then two reads of 40h: about 18 M reads in m0–m4), the OPL delay loop. The loop (`+0714h`) sums the
counter's fall from latch to latch until CX ticks pass (0Ah after the register write, 37h
after the data), so the sum telescopes and only the latch that ends a loop sets its length
(DERIVED by reading; replaying that loop over m1b's 207,308 reference latches ends exactly
at the last, MEASURED). The `pit` host plant therefore answers a mid-loop latch, not a low bit. The drivers keep
variables in their code segments (`tools/code_writes.py`: class `data`, no write into a
decoded instruction).

`SUPERTM.DRV`'s noise fill (the far procedure at `+74D2`, after entry 4's) reads the BIOS
ROM: `DS = F000h`, SI from a pseudo-random sequence in `cs:[74C2h]`/`cs:[74C4h]`, a pixel
of colour AL where bit 0 of the ROM byte is set (DERIVED by reading). The m5/m6 routes
run it from service 368,836 on (MEASURED, host lockstep); the shape it fills is later
drawn by the RLE routines, so the ROM contents steer control flow (with zero ROM the
host left the reference's path at `+29A9`, table index 0 → `+2AD6`, never traced). The
reference machine's ROM (DOSBox-X's) is byte-identical in every snapshot, m0 to m6
(MEASURED); host lockstep loads it from the m0 snapshot as a local fixture
(`tests/host_run.py reference_rom`). Of its 64 KB, 95.8% are zero and 1.4% have bit 0
set (MEASURED, m0 snapshot); a PC BIOS of the period is dense code and data (INFERRED). The
Amiga build fills the segment from a seeded xorshift32 (D11, `src/runtime/machine.c`
`bios_rom_noise`).

`SUPERTM.DRV` dispatches its drawing inner loops through forms the sweep cannot bound by
itself; their targets are curated with evidence and checked by `tools/sweep.py`:
`annotations/tables.csv` (`call/jmp cs:[di+T]` and `add di,T; call/jmp cs:[di]`: eight
two-entry direction tables and four 32-entry tables) and `annotations/code-vars.csv` (the
code-pointer words `cs:[6C2h]`, 32 targets, and `cs:[6C4h]`, 16, called from 32 sites;
every decoded write to them must store a listed target, `check_code_vars`). Flight runs
targets no trace reached (`+4CFA` through `cs:[6C4h]`, MEASURED on the Amiga build).

## FM effects (STRAX.DRV)

`STRAX.DRV` is a MIDI-style driver: entry 5 (`+074D`) note on/off (channel, note, velocity),
entry 6 (`+0B61`) controller (channel, controller, value: 1, 7 volume, 0Ah pan, 79h reset,
7Bh all notes off), entry 8 (`+0CAC`) program change, entry 4 (`+0DDD`) the tick on every
INT 08h (60 Hz), which steps each voice's software pitch envelope and vibrato and rewrites
its A0h/B0h, then calls the game's callback (`[1Ch]` → `WC2.EXE+132CC`: music fades, the
song sequencer, then the effect tick). DERIVED by reading.

An effect is a chain of 8-byte records: flags, program, note, velocity, duration in
ticks (word), target note, in the effect table at DS:0540h (id k at + 8k; ids 1-55).
WC2.EXE holds that table; `FX.000`, loaded into a heap buffer, differs from it in 6
records and is not what the starts read (MEASURED on snap-m4-1). `WC2.EXE+06B48` (sound on: DS:070Eh) passes a request to
`+1254D`, which takes one of 32 slots (DS:A54Ch, 14 bytes) and one or two MIDI channels
(`+1219E`) and starts it in `+121E9` (all notes off, program, volume, pan, note on). The
effect tick `+123F4` counts the duration down; at 0, the note ends and flag bit 1 slides
the note a step toward the target note and restarts it, bit 3 restarts it, bit 0 moves
to the next record, none releases the channel; bit 2 holds the note without a duration.
Callers push flags 0, volume 7Fh and a pan (`+0AB40`, `+0BC59`, `+2917B`, `+375C0`).
DERIVED by reading.

`tools/sfx_capture.py` runs that code and the driver under Unicorn from the m4 flight
snapshot, one effect alone (`make sfx-price`): 44 effects end (2,551 ticks, 42.5 s to
their release), 11 are held (11, 12, 14, 15, 17, 32, 38, 45, 48, 53, 54); no record chains;
36 use feedback 7. Control: a captured effect's per-tick pitch writes after its key-on
equal the reference's for the same patch (ids 1 and 37 against `host-m6`); 23 of the 55
patches occur at key-ons of the m6 and mx2 references (MEASURED 2026-11-20).

Prerendered (owner decisions D13, D14): at the first effect start the runtime
(`src/runtime/sfx.c`, HLE `sfx_start` at the start's RETF `WC2.EXE+126D4`) captures every
one-shot the same way. The callback cannot be redirected (`indirect.csv` knows only
`+132CC`), so its gates in DGROUP hold it to the effect tick: A53Ch 0 (no fade), A801h 1
and A544h/A546h 0 (no song). The BIOS chain after it (`+10080`, `pushf; callf [DEBE]`)
adds its step to an accumulator and jumps to the BIOS on a carry, so each tick sets the
step to 1 and the accumulator to 0. The driver's OPL delay reads the PIT, so a capture's
latches read a count falling 40h a latch. `tools/sfx_capture.py` uses the same method and
is its oracle (`tests/host_run.py --sfx-capture`). The start is reached only by direct far
calls, so it needs an `entries.csv` row for the runtime's call. The capture keeps only
writes that change a register: 10,566 of 133,254 (MEASURED, m4 snapshot).

In play, `fx_play.c` reads the slots once a field from the Paula field task, at Amiga
interrupt level, whatever the guest's IF. The start fills the slot (channel byte first,
record last), keys the note on through the driver (`+121E9`, OPL writes with PIT delay
loops), then returns, where HLE `sfx_start` counts it: a field in between sees the slot,
or its last effect's record, with no start. A slot starts a play only once its id's start
is counted; until then its channels are muted. Starting on sight played nearly every start
of mx1's effect 37 twice, the count a field later taken for a restart (MEASURED,
`make t-amiga-sfx`: 106 plays for 69 starts, 69 for 69 after).
