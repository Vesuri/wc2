# Feasibility

The owner's feasibility report: can WC2 run on D1's target (AGA, 68030 minimum, 68040 or
better recommended) by translation? The verdict comes first, then its measured inputs.

## Verdict against D1 (2026-11-21)

- **It runs.** The translated game matches the original in host lockstep through m6 and
  the exits, and the Amiga image on the 68030 model through m4, the first flight frame
  (gate 6, port-plan P6). Nothing found in P2's map (overlays, EMS, drivers,
  ports) needs more than the runtime already provides.
- **Memory fits** an 8 MiB Fast RAM machine: the code is 1.86 MB, the image allocates
  2.28 MB, and the WHDLoad slave runs in 7 MiB of Fast and 1.31 MiB of Chip with 0.5 MB of
  each to spare (below; [whdload.md](whdload.md) "Memory").
- **Speed misses on the 68030 before P7.** On the 50 MHz 68030 the frame the original
  draws in 4 timer ticks (15 fps) takes about 9 ticks in quiet flight and 10–12 in the
  Nav 1 fight: 2.2× over in flight, 2.4× (median) to 2.8× (p90) in that fight. A 40 MHz
  68040 meets quiet flight and the median fight frame. The 68030 minimum therefore holds
  for running the game, not for its original frame rate: P7 must cut the translated cost
  by about 2.5–3× to reach 15 fps there (DERIVED below; P7's targets come from the P5.4
  profile).
- **Unmeasured:** larger fights (capital ships, many fighters, the asteroid field), whose
  frames cost more than Nav 1's 10–13 objects; flight's own instruction mix on the target.

## Flight frame cost (port-plan P1.5)

Inputs (MEASURED, `reference/dosbox-x.conf`, 12000 fixed cycles; `tools/frame_time.py` on
a run into the first flight with its probes, 335 frames of the launch scene: wingman,
the Caernarvon, no enemies):

| Quantity | Value |
|---|---|
| Frame interval | median 66.7 ms (p10 65.1, p90 68.0): 4 ticks of the 60 Hz timer; also 66.7 ms at 24000 cycles, so the frame limiter (`WC2.EXE+10642`) sets it |
| Limiter wait | median 43.4 ms (p10 42.1, p90 44.5) |
| Work per frame | 23.3 ms, about 280,000 cycles |

Estimate (DERIVED; SWOTL's ratio, its fixtures and WC2's not matched):

- SWOTL's translated 68020 frames run 4–8× its 12000-cycle reference (port-plan P1.5), so
  this scene's work would take 93–187 ms on the 68020 model: 6–12 timer ticks a frame
  instead of 4, about 5–10 frames per second.
- The 68030 model runs about 3× the 68020: 31–62 ms, inside the 66.7 ms the game asks
  for: this scene is consistent with D1's 68030 minimum.
- Unknown: combat scenes (more ships, lasers, explosions) and the asteroid field cost
  more. The same measurement on a combat fixture, and the translated code's own cost
  (P5.4, P7), decide it.

## Translated cost on the target (port-plan P5.4)

Workload: the intro animation at IRQ0 ticks 300–423 (2.05 s), inside the lockstep range
(host run to m1b). There the reference presents 68 frames (one every 1.7 ticks from tick
220 to 525) with 824 calls of TM.DRV's sprite routine +00E93, and executes 12.97 M x86
instructions (WC2.EXE 2.89 M, TM.DRV 9.46 M, STRAX.DRV 0.62 M): 6.3 M a second, about one
per two DOSBox cycles (MEASURED: the host run on the reference's instruction stream,
block counts over the generated labels).

Target (MEASURED): the real image (`make amiga`) on FS-UAE's A1200 with a cycle-exact
50 MHz 68030, data cache, MMU model off (the profiler records nothing on the MMU core),
100 PAL fields from tick 300 (`amiga/perf_slice.gdb`, `tools/profile_report.py`,
`tools/profile_tree.py`):

| Quantity | Value |
|---|---|
| Frames presented | 8 (reference 68), 108 calls of TM.DRV+00E93 (13.5 a frame; reference 12.1) |
| Class | runtime and platform 50.7%, generated code 41.1% (TM.DRV 27.2, WC2.EXE 9.9, STRAX.DRV 3.9), c2p 5.7%, IRQ transitions 2.1% |
| Vertical retrace wait (WC2.EXE+14864, inclusive) | 28.4%: 42 calls of 13.7 ms, spinning on port 3DAh |
| Sprite drawing (TM.DRV+00E93, self) | 25.3%: 236 k cycles a call |
| Port reads (`rt_in8`, inclusive) | 24.9%: 68,826 reads of 364 cycles (`plat_vga_status` 183), mostly inside the retrace wait |
| PIT counter reads (`plat_pit_count`) | 5.5% |
| Present and c2p | 7.4% (`present`, inclusive) and 6.1% (outside the first hunk) |
| Generated code per x86 instruction | TM.DRV 4.7 68k instructions, 21.5 cycles; WC2.EXE 3.0, 14.0; STRAX.DRV 2.3, 11.6 |

Estimate (DERIVED; the instruction mix of flight is not measured, INFERRED to be alike):

- Outside the retrace wait the target spends 177 ms per presented frame; the reference's
  frame is 175 k x86 instructions outside its own wait (12.97 M less 3 instructions per
  3DAh poll, 68 frames): about 50 cycles per x86 instruction all in. This scene runs at
  one eighth of the reference's frame rate.
- Flight (above: 280 k DOSBox cycles of work a frame, about 148 k x86 instructions at this
  scene's ratio): about 7.4 M cycles, 148 ms on the 50 MHz 68030: 9 timer ticks a frame
  (6.7 fps) instead of 4 (15 fps), 2.2× over the frame the game asks for.
- 68040: FS-UAE's 040 timing is an instruction count and its profiler records nothing on
  that path, so it is priced from counts: 9.9 68k instructions per x86 instruction all in
  outside the wait (13.8 M over 1.40 M). At 1.3–1.5 cycles per instruction (INFERRED,
  cached integer code) a 25 MHz 68040 runs flight in 78–87 ms (11–13 fps), a 40 MHz one in
  49–55 ms, inside the 66.7 ms frame.
- Against D1 (68030 minimum, 68040 recommended): before P7 the translated build misses
  flight's frame rate by about 2× on the 50 MHz 68030 and by 1.2–1.3× on a 25 MHz 68040.
  P7's targets, by this profile: the drawing driver's cost per x86 instruction, the port
  read path (364 cycles a read), PIT reads, and present.

## FM music (port-plan P1.5, D6)

`STRAX.DRV` drives an OPL2 at 388h/389h (MEASURED, `tools/opl_use.py` on an `--opl` run from
launch through the first flight, 447,113 writes over 399 s):

- all 9 melodic channels are keyed, up to 9 at once;
- rhythm mode is never set (register BDh is only written 00h).

The FM synthesis must render 9 channels at once into the Paula voices that the sound
policy gives music (`docs/sound-plan.md`, P6b).

## Combat frame cost (MEASURED)

The original under the same DOSBox-X conf, m5's route (debug mode, so no scripted combat)
to its first autopilot, then no Alt-Ins: the autopilot drops out at Nav 1 into the Sartha
attack, and the Ferret holds its course while the fighters attack and pass (the shield
gauge takes hits; one snapshot shows a fighter on screen). Probes as for the flight frame,
plus `SUPERTM.DRV+153E` (the scaled sprite driver's entry 2; as many calls as entry 1,
one per scaled object drawn, INFERRED); `tools/frame_time.py --group` gives each frame its
own work (interval less its limiter wait). The run also pressed Backspace 600 ticks after
the autopilot key; the speed stayed 360.

| Objects drawn a frame | Frames | Interval median | Work median | p90 | max |
|---|---|---|---|---|---|
| 0 | 283 | 66.5 ms | 21.7 ms | 25.9 | 32.9 |
| 1–5 | 333 | 66.5 | 22.7–24.9 | 24.5–28.0 | 33.4 |
| 8 or more (the fight, 10–13) | 196 | 66.6 | 25.6 | 29.2 | 45.7 |

Every frame waits in the limiter: at 12000 cycles the original keeps its 4 ticks through
this fight, its work up 18% (median) over the empty frames, about 0.4 ms (5,000 cycles)
an object. An earlier run on the same route without the probe on objects (1,445 frames,
the fighters on radar, never in view) gave work median 22.8, p90 27.8, max 78.5 ms (one
frame over budget).

Estimate (DERIVED, the P5.4 ratio: 148 ms on the target for flight's 23.3 ms, 6.35×;
SUPERTM.DRV's own cost per instruction not measured, INFERRED alike):

| | Quiet flight | Fight, median | Fight, p90 |
|---|---|---|---|
| 12000-cycle reference | 23.3 ms | 25.6 ms | 29.2 ms |
| 50 MHz 68030 | 148 ms (9 ticks, 6.7 fps) | 163 ms (10 ticks, 6 fps) | 185 ms (12 ticks, 5 fps) |
| 25 MHz 68040 | 78–87 ms | 86–96 ms | 98–109 ms |
| 40 MHz 68040 | 49–55 ms | 54–60 ms | 61–69 ms |

The 66.7 ms frame is met where the figure is below it.

## Code size (MEASURED, `make amiga-release`, `tools/code_size.py`)

The release image `Wc2-release.exe` is 1,991,248 bytes: code 1,864,080, relocations
120,040, data 7,012 (`make size`); its hunks allocate 2,275,564 bytes with BSS. Its
.text by source:

| Source | Amiga bytes | x86 bytes | Ratio |
|---|---|---|---|
| `WC2.EXE`, translated | 1,461,544 | 279,857 (resident and overlay code, [wc1-wc2-comparison.md](wc1-wc2-comparison.md)) | 5.2× |
| `SUPERTM.DRV`, translated | 149,952 | 30,053 (the loaded entry, [drivers.md](drivers.md)) | 5.0× |
| `TM.DRV`, translated | 39,124 | 11,802 | 3.3× |
| `STRAX.DRV`, translated | 13,928 | 3,986 | 3.5× |
| runtime and platform | 197,928 | | |

Every overlay's 68k code is in the image; the VROOMM manager still runs, translated, and
loads the overlay bytes into guest RAM, and far dispatch reads its residency record
(port-plan P4). So code size is fixed at link time; the game's data paging (EMS, below)
is unchanged.

## P2's inputs (MEASURED; the docs hold the detail)

- **Overlays** ([vroomm.md](vroomm.md)): Borland VROOMM, 124 overlays, 184,673 bytes of
  code, its EMS caching off; translated as SWOTL's overlays, each at its link segment
  with a residency check.
- **Drivers** ([drivers.md](drivers.md)): three, each loaded once at a fixed paragraph and
  never moved: `TM.DRV` (VGA drawing, the DAC), `SUPERTM.DRV` (scaled sprites, the space
  view), `STRAX.DRV` (every OPL write). Translated at one CS each; speech is root code on
  the Sound Blaster DSP and DMA 1.
- **EMS** ([external-surface.md](external-surface.md) "EMS"): one handle of 164 pages
  (2.6 MB), four physical pages, 4–15 maps a timer tick; the runtime serves it from the
  guest block in Fast RAM.
- **Surface** ([external-surface.md](external-surface.md)): DOS files, BIOS, INT 33h, the
  PIT, PIC, VGA, OPL, Sound Blaster and joystick ports; all are runtime services, and an
  unknown one stops.

## The engine and WC1 (MEASURED, [wc1-wc2-comparison.md](wc1-wc2-comparison.md))

WC2 is WC1's engine moved to Borland C++ 1991: 29.5% of WC2's code is a WC1 function
nearly unchanged (similarity 0.85 or more), another 14.3% a modified one; the music, the
span/sprite drawing module and ship loading are 64–100% shared, the cinematics and the
pilot-file menu new. For feasibility this means the translated route stands on its own;
WC1's Amiga CD32 routines are an optimisation (open-work 8, after gate 6), not a
dependency.
