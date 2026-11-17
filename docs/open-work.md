# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P6b: Amiga platform (stream C, beside P6)

18. Display and input on the Amiga (port-plan P6b.1, P6b.3): SWOTL's copper display,
    double buffer, changed-row C2P, display queue and frame cap; the key map, mouse and
    joystick; WC2's own joystick calibration runs. The F000h segment SUPERTM.DRV's noise
    fill samples ([drivers.md](drivers.md)) filled from a seeded generator (D11). The smoke into flight (moved from gate 6: the production build stops
    at the first SB block until item 19, and the game starts speech before flight, m2):
    `amiga/play_walk.sh` and `.gdb` are still SWOTL's steep-bank script and need WC2's
    keys and a flight label. Acceptance: the Amiga build shows m4's
    flight frame from generated code and the smoke flies with keyboard and joystick input.
19. Audio on Paula (port-plan P6b.2): FM music through SWOTL's `fm_paula.c`, effects priced
    by `fm_effect_check` then prerendered, speech on one Paula voice from the SB DMA blocks,
    channel ownership stated. The Amiga `plat_sb_block` stops today: it plays the block
    and posts IRQ 7 at its end (length / rate; the reference's acknowledgement within
    3.0 ms of it over m2–m4, [pc-reference-loop.md](pc-reference-loop.md)), and production delivers
    INT 0Fh without poll points, as IRQ0 (irq-plan I6, I8). Take X-Wing's two fixes to the
    SWOTL FM code first (not committed there as of 2026-11-16): `fm_paula.c` renders
    additive patches (C0h bit 0) with both operators at their relative levels (WC2: 7
    patch writes, 49 key-ons by m6), and `fm_check` measures vibrato notes (about half of
    WC2's key-ons by m6, 87% in m1b; MEASURED from the host references' `opl.csv`), skips
    fields whose registers change mid-field and released notes. Acceptance: the FM checks and
    their sabotage pass; the intro's speech plays on the Amiga build; the Chip cost MEASURED.
20. Memory (port-plan P6b.4): code, guest RAM and EMS pages for the Fast RAM requirement;
    Chip holds bitmaps, copper lists and audio only. Acceptance: the figures MEASURED in
    [feasibility.md](feasibility.md).

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

## P8: package

3. Map the game executable: Borland C++ 1991 medium model, 80186+, VROOMM overlays
   (`tools/bc_exe.py`, the P2 map: `make map`; the runtime image at entry and after overlay loads is proven by
   `tools/load_image.py`, [pc-reference-loop.md](pc-reference-loop.md)). Open: the
   `WC2.LZC` packing method, a `make inspect` target (playbook §3; port-plan P8.2).
   Acceptance: an independent `WC2.LZC` unpack equals the installed `WC2.EXE`.
7. `SPEECH.S00` codec (in scope, D3): disk entries flagged `E0` grow to twice their
   size when installed; needed by the installer (D7, port-plan P8.2). Acceptance:
   `tools/origin_pak.py verify` rebuilds it byte-exactly.

## Deferred (owner, D10)

16. Coverage beyond m6 (port-plan P6.2, deferred by D10): reference milestones for every flight scene type,
    the ships flown, cinematics, menus, saves and the ending path; later missions start
    from saves recorded under the reference, kept as local fixture inputs. Acceptance: the
    milestones in `reference/milestones.csv`, each recorded twice byte-identically
    (`tools/reference.py`).
