# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.
Items are in work order; numbers are identifiers and are not reused.

## P6: whole game (gate 6, the current phase)

12. Host lockstep at m2 (the intro, [pc-reference-loop.md](pc-reference-loop.md)): the SB
    DSP (reset, version as SB 2.0, time constant, 8-bit DMA, speaker), DMA channel 1, and
    IRQ 7 at each block's end timed by the sample rate, delivering INT 0Fh to
    WC2.EXE+06F3F under the footprint proof (port-plan P6.1 "Sound"). Acceptance:
    `make test-host` in lockstep at m2 with 0 monitor problems and INT 0Fh handler runs
    counted, and an SB sabotage plant caught.
13. Host lockstep at m3 and m4 (the pilot file, the first flight frames; `STRAX.DRV`
    resident): the surfaces those traces show. WC2's INT 15h handler at WC2.EXE+0FD93 runs
    as often as IRQ1 (1064 times each, MEASURED, [external-surface.md](external-surface.md)),
    so the BIOS keyboard intercept is INFERRED; it joins the footprint proof. Input: INT 16h,
    INT 33h (the mouse, copied) and the game port at 201h (the joystick, copied). Acceptance:
    m3 and m4 in lockstep with 0 monitor problems; each new surface has a caught sabotage
    plant.
14. PIT sabotage that changes the run: `tests/host_run.py --sabotage pit` flips one latch's
    low bit and is caught at neither m1 nor m1b (0 problems, MEASURED in `66e6de5`).
    Acceptance: a pit plant caught at m1b, with its effect stated.
15. Host lockstep at m5 and m6 (the flight route, the save and the load): DOS writes into
    `GAMEDAT` (`SAVEGAME.WC2`, `TEMPGLOB.000`, `MEM.$$$`, `AUTO.$$$`, `TAPE.TMP`) through
    SWOTL's I/O windows, any DOS or EMS function the traces show that the runtime lacks.
    Acceptance: m5 and m6 in lockstep with 0 monitor problems.
16. Coverage beyond m6 (port-plan P6.2): reference milestones for every flight scene type,
    the ships flown, cinematics, menus, saves and the ending path; later missions start
    from saves recorded under the reference, kept as local fixture inputs. Acceptance: the
    milestones in `reference/milestones.csv`, each recorded twice byte-identically
    (`tools/reference.py`).
17. Gate 6 (port-plan P6.3–4): `make test-host-all` lockstep over all milestones,
    `make test-amiga-replay` on a few, a `play_walk.sh` smoke into flight. Acceptance:
    every overlay and driver translated, zero unclassified executed instructions (G6), the
    HLE share reported, lockstep clean over all milestones.

## P6b: Amiga platform (stream C, beside P6)

18. Display and input on the Amiga (port-plan P6b.1, P6b.3): SWOTL's copper display,
    double buffer, changed-row C2P, display queue and frame cap; the key map, mouse and
    joystick; WC2's own joystick calibration runs. Acceptance: the Amiga build shows m4's
    flight frame from generated code and the smoke flies with keyboard and joystick input.
19. Audio on Paula (port-plan P6b.2): FM music through SWOTL's `fm_paula.c`, effects priced
    by `fm_effect_check` then prerendered, speech on one Paula voice from the SB DMA blocks,
    channel ownership stated. Acceptance: the FM checks and their sabotage pass; the Chip
    cost MEASURED.
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
    1,917 full-flag materialisations (MEASURED, `make gen`). Proved save/restore pairs in
    `annotations/flags.csv` (DERIVED by reading, as X-Wing's) shrink it. Acceptance: the
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
