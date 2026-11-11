# Feasibility

The owner's feasibility report (open-work 6). This page holds its measured inputs as they
arrive; port-plan P1.5 supplies the first ones.

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
