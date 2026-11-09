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

## FM music (port-plan P1.5, D6)

`STRAX.DRV` drives an OPL2 at 388h/389h (MEASURED, `tools/opl_use.py` on an `--opl` run from
launch through the first flight, 447,113 writes over 399 s):

- all 9 melodic channels are keyed, up to 9 at once;
- rhythm mode is never set (register BDh is only written 00h).

The FM synthesis must render 9 channels at once into the Paula voices that the sound
policy gives music (`docs/sound-plan.md`, P6b).
