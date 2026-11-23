# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P6b: Amiga platform (stream C, beside P6)

20. Memory (port-plan P6b.4): code, guest RAM and EMS pages for the Fast RAM requirement;
    Chip holds bitmaps, copper lists and audio only. Acceptance: the figures MEASURED in
    [feasibility.md](feasibility.md).

## P7: performance (after gate 6)

11. Flag liveness through the dispatcher: 59 PUSHF and 2 INT sites read the whole
    FLAGS word and make every flag live at the dispatcher, so `tests/audit.csv` allows
    1,931 full-flag materialisations (MEASURED, `make gen`). Proved save/restore pairs in
    `annotations/flags.csv` (DERIVED by reading) shrink it; start from X-Wing's four
    overlay-manager rows (the same Borland overlay manager). Acceptance: the
    pairs listed with their evidence, the audit counts lowered to the new measurement, the
    68020 block differential passing.

## P7W: WC1 refinement (the owner's plan)

8. WC1 reuse ([wc1-wc2-comparison.md](wc1-wc2-comparison.md)): profile WC2 in flight on the
   PC reference to find the hot modules, then check whether those have WC1 counterparts and
   whether the Amiga WC1 has a matching native routine. Acceptance: a table of hot WC2
   modules with their WC1 PC and Amiga WC1 counterparts, MEASURED.

## P8: package (0.1 alpha ahead of the gates, D12)

26. Release tests (port-plan P8.3, C7): the full matrix. Acceptance: each row run and
    recorded in `docs/whdload.md` with its result.

## Deferred (owner, D10)

16. Coverage beyond m6 (port-plan P6.2, deferred by D10): reference milestones for every flight scene type,
    the ships flown, cinematics, menus, saves and the ending path; later missions start
    from saves recorded under the reference, kept as local fixture inputs. Acceptance: the
    milestones in `reference/milestones.csv`, each recorded twice byte-identically
    (`tools/reference.py`).
