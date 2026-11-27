# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P7: performance (port-plan P7, the CD32 WC1 as the inspiration)

32. Waits and the present (P7.5; W1 the field wait, W2 the palette, W3 the present's
    compare, speed-plan §1; the 3DAh spin is not in flight, P7.3, so no step): the Amiga
    replay at m4 on the W3 tree, with `build/host` left alone until its check ends (a run
    on 2026-11-27 was void: the host build changed under it). Acceptance: the replay ok.
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
