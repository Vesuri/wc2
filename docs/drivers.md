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
4–9.

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
(`tests/host_run.py reference_rom`). What the Amiga build holds there is open
([open-work.md](open-work.md) item 18).
