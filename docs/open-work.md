# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P7: performance (port-plan P7, the CD32 WC1 as the inspiration)

30. Baseline and hot list (P7.3): the windows profiled on the 68030 model, the 68040's
    frame intervals (`tools/perf_flight.py --cpu 68040 --no-profile` stopped before its mark
    in 3 runs of 3, while the same keys under a gdb script with flight breakpoints from the
    start reached it in 2 of 2: MEASURED 2026-11-24, cause unknown), each hot routine's PC
    WC1 counterpart. Acceptance: speed-plan §1 and §9 re-derived for WC2 and feasibility's
    flight estimates replaced, MEASURED.
31. The bar (P7.4): the owner's, from item 30's numbers (proposed tiers B1–B3 in port-plan
    P7.4). Acceptance: a row in `docs/design.md`.
8. WC1 lineage on the Amiga (P7.10; desk work beside items 32–35): item 30's hot routines
   matched to PC WC1 and the CD32 WC1 ([wc1-wc2-comparison.md](wc1-wc2-comparison.md)),
   `SUPERTM.DRV` first. Acceptance: `docs/wc1-cross-reference.md` with each hot routine's
   PC WC1 and CD32 counterparts and their evidence, and the CD32 routine's cost on the
   68030 model where the Wing Commander project measured it.
32. Waits (P7.5): the 3DAh retrace spin and the present's waits measured in flight, then
    cut in the runtime where they cost. Acceptance: frames ranges that do not overlap
    (speed-plan §3), the Amiga replay at m4.
33. Runtime access costs (P7.6): X-Wing's EMS guard cache (`4c50051`), the port read path,
    the PIT reads. Acceptance: the meter's change for each; `ems_guard_problems` and its
    sabotages; lockstep at m4 and m5.
34. Changed-block c2p (P7.7), if item 30 shows unchanged rows converted: the Wing Commander
    slave's converter inside the marked rows, with the owner's OK (it revisits SWOTL's S1).
    Acceptance: the display checks, frames A/B.
11. Flag liveness through the dispatcher (P7.8): 59 PUSHF and 2 INT sites read the whole
    FLAGS word and make every flag live at the dispatcher, so `tests/audit.csv` allows
    1,931 full-flag materialisations (MEASURED, `make gen`). Proved save/restore pairs in
    `annotations/flags.csv` (DERIVED by reading) shrink it; start from X-Wing's four
    overlay-manager rows (the same Borland overlay manager). Acceptance: the
    pairs listed with their evidence, the audit counts lowered to the new measurement, the
    68020 block differential passing.
35. The other translator steps (P7.8): the profile-chosen annotations regenerated from
    the flight windows, then the forms `lowering_cost.py` ranks. Acceptance per step: the
    meter's change; the differentials, guards and sabotages.
36. Checkpoint (P7.9): frames on the 68030 and 68040 models against the bar; the native
    candidates re-ranked. Acceptance: the figures in speed-plan §1.
37. Native routines (P7.11): priced first (the own-cost ceiling, the CD32 counterpart's
    cost), then built one at a time with the owner's authorization. Acceptance per routine:
    an `annotations/hle.csv` row with its oracle, S1–S9, meter and frames A/B.
38. Machines and gate 7 (P7.12): the 68040 and 68060 models, a frame recorder for real
    hardware. Acceptance: the bar met on the frames fixtures with every fidelity gate green.

## P8: package (0.1 alpha ahead of the gates, D12)

26. Release tests (port-plan P8.3, C7): the full matrix. Acceptance: each row run and
    recorded in `docs/whdload.md` with its result.

## Deferred (owner, D10)

16. Coverage beyond m6 (port-plan P6.2, deferred by D10): reference milestones for every flight scene type,
    the ships flown, cinematics, menus, saves and the ending path; later missions start
    from saves recorded under the reference, kept as local fixture inputs. Acceptance: the
    milestones in `reference/milestones.csv`, each recorded twice byte-identically
    (`tools/reference.py`).
