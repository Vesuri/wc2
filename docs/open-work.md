# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P7: performance (port-plan P7, the CD32 WC1 as the inspiration)

33. Runtime access costs (P7.6), the largest first (speed-plan §1, E1–E4, O1 done; P1 measured,
    not built): the EMS model's INT 67h copies (`copy` 3–7% of the
    fight profile) and `refresh` (1%). Acceptance: the meter's change for each; the EMS
    test, `ems_guard_problems`, `ems_irq_problems` and their plants; lockstep at m4 and m5.
32. Waits and the present (P7.5): the field wait in `rt_video_frame` (7.7–8.1 ms a visit),
    the palette rebuilt at every present (11.6 ms: the DAC is written every frame), the
    present's copy and c2p; the 3DAh spin outside flight. Acceptance: frames ranges that do
    not overlap (speed-plan §3), the Amiga replay at m4.
34. Changed-block c2p (P7.7): flight writes 178–192 of 200 rows a frame (P7.3), so only a
    block compare inside the marked rows can save conversion; first measure how many written
    32-pixel blocks change. Then the Wing Commander slave's converter inside the marked rows,
    with the owner's OK (it revisits SWOTL's S1). Acceptance: the display checks, frames A/B.
35. The other translator steps (P7.8): the profile-chosen annotations regenerated from
    the flight windows, then the forms `lowering_cost.py` ranks. Acceptance per step: the
    meter's change; the differentials, guards and sabotages.
36. Checkpoint (P7.9): frames on the 68030 model against the bar; the native
    candidates re-ranked. Acceptance: the figures in speed-plan §1.
37. Native routines (P7.11): priced first (the own-cost ceiling, the CD32 counterpart's
    cost), then built one at a time with the owner's authorization. Acceptance per routine:
    an `annotations/hle.csv` row with its oracle, S1–S9, meter and frames A/B.
38. Machines and gate 7 (P7.12): the 68040 and 68060 models, a frame recorder for real
    hardware. The 68040 fixture (`tools/perf_flight.py --cpu 68040 --no-profile`) stopped
    before its mark in 3 runs of 3, while the same keys under a gdb script with flight
    breakpoints from the start reached it in 2 of 2 (MEASURED 2026-11-24, cause unknown). Acceptance: the bar met on the frames fixtures with every fidelity gate green.

## P8: package (0.1 alpha ahead of the gates, D12)

26. Release tests (port-plan P8.3, C7): the full matrix. Acceptance: each row run and
    recorded in `docs/whdload.md` with its result.

## Deferred (owner, D10)

16. Coverage beyond m6 (port-plan P6.2, deferred by D10): reference milestones for every flight scene type,
    the ships flown, cinematics, menus, saves and the ending path; later missions start
    from saves recorded under the reference, kept as local fixture inputs. Acceptance: the
    milestones in `reference/milestones.csv`, each recorded twice byte-identically
    (`tools/reference.py`).
