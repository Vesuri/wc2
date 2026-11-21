# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P6b: Amiga platform (stream C, beside P6)

19. Audio on Paula (port-plan P6b.2): speech on one Paula voice from the SB DMA blocks,
    channel ownership stated. The Amiga `plat_sb_block` is silent today: it times the block
    and posts IRQ 7 at its end (length / rate; the reference's acknowledgement within
    3.0 ms of it over m2–m4, [pc-reference-loop.md](pc-reference-loop.md)); production delivers
    INT 0Fh without poll points, as IRQ0 (irq-plan I6, I8), up to 57 retries of about 1 ms
    late for one block (MEASURED over the intro's blocks). Playing it keeps that timing.
    Music: `make gates-audio` passes on the host references' OPL logs (m6, mx1, mx2: level
    97.5-98.8%, pitch 99.7-100%, MEASURED 2026-11-20). Effects are prerendered (D13, D14,
    [drivers.md](drivers.md) "FM effects"): 39 one-shots, 573,963 bytes of Chip, the rest live;
    the slave's `CHIPMEMSIZE` is `$150000` ([whdload.md](whdload.md) "Memory"). Not yet run on
    the Amiga model: the capture, render, cache and player in one replay, as X-Wing's
    `t-amiga-sfx` (`tests/amiga_replay.py --sfx`, `269828b`). Acceptance: the FM checks and
    their sabotage pass; the effect replay shows every start of an effect with a sample
    played and its channels muted; the intro's speech plays on the Amiga build.
20. Memory (port-plan P6b.4): code, guest RAM and EMS pages for the Fast RAM requirement;
    Chip holds bitmaps, copper lists and audio only. Acceptance: the figures MEASURED in
    [feasibility.md](feasibility.md).
23. The flight smoke's personnel menu route (`amiga/play_walk.sh`, owner-accepted for item 18
    on its passing runs): scripted Create is taken in about half the runs, then the names go
    astray or an Enter quits ([amiga-arch.md](amiga-arch.md) "Input" has the measured
    mechanisms). Read the menu's event handling (`WC2.EXE+0FFF0`'s consumer) and script it from
    that. Acceptance: 8 parallel runs of `amiga/play_walk.sh` all print `WC2_PLAY_OK`.

## Owner report (no phase)

6. Feasibility report for the owner ([feasibility.md](feasibility.md): the quiet flight
   frame and FM channel use are in; P2 measured the overlay and EMS paging and the drivers:
   [vroomm.md](vroomm.md), [drivers.md](drivers.md), [external-surface.md](external-surface.md)).
   The translated cost is in (port-plan P5.4: the intro animation on the 50 MHz 68030, flight
   about 2× short by estimate). Open: code size, those inputs written into the report, the
   engine's relation to WC1 (supplied disks in `tmp/wc1/`), a combat frame's cost.
   Acceptance: the doc with measured inputs, checked against D1 (68030 minimum).

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
