# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.

## The original

3. Map the game executable: Borland C++ 1991 medium model, 80186+, VROOMM overlays
   (`tools/bc_exe.py`, the P2 map: `make map`; the runtime image at entry and after overlay loads is proven by
   `tools/load_image.py`, [pc-reference-loop.md](pc-reference-loop.md)). Open: the
   `WC2.LZC` packing method, a `make inspect` target (playbook §3; port-plan P8.2).
   Acceptance: an independent `WC2.LZC` unpack equals the installed `WC2.EXE`.
6. Feasibility report for the owner ([feasibility.md](feasibility.md): the quiet flight
   frame and FM channel use are in; P2 measured the overlay and EMS paging and the drivers:
   [vroomm.md](vroomm.md), [drivers.md](drivers.md), [external-surface.md](external-surface.md)).
   Open: code size, those inputs written into the report, the engine's relation to WC1 (supplied disks in `tmp/wc1/`), a combat frame's
   cost, the translated cost (port-plan P5.4). Acceptance: the doc with measured inputs,
   checked against D1 (68030 minimum).
7. `SPEECH.S00` codec (in scope, D3): disk entries flagged `E0` grow to twice their
   size when installed; needed by the installer (D7, port-plan P8.2). Acceptance: `tools/origin_pak.py verify` rebuilds
   it byte-exactly.
8. WC1 reuse (owner's plan, [wc1-wc2-comparison.md](wc1-wc2-comparison.md); port-plan
   P7W): profile WC2 in flight on the PC reference to find the hot modules, then check
   whether those have
   WC1 counterparts and whether the Amiga WC1 has a matching native routine. Acceptance: a
   table of hot WC2 modules with their WC1 PC and Amiga WC1 counterparts, MEASURED.
9. IRQ handler footprint proof for WC2 (port-plan P4.4, moved to P5 as in X-Wing): `irq.py`
   is SPAZ's IRQ0 proof (MS C, PLINK classes); WC2's timer handler calls the sound driver
   through a far pointer set at run time, and the proof pairs with P5's host-run monitor.
   Until then interrupts are taken at the loop-head poll points only (`gen.IRQ_PROOF`
   off). Acceptance: `IRQ_PROOF` on, `build/gen/irq-footprint.csv` proves every handler
   WC2 installs (INT 08h, 0Fh and the drivers' entries), the host-run monitor finds no
   access outside it, and its sabotage is caught.
10. EMS model (C3; designed in [translator-design.md](translator-design.md), "WC2 EMS
    model"): build it before the first profile (port-plan P5.4). Acceptance: guarded
    frame accesses touch the mapped page without a copy, the guard edges are in the x86
    and 68020 differentials with a sabotage plant, and the host lockstep still passes.
11. Flag liveness through the dispatcher (P7): 59 PUSHF and 2 INT sites read the whole
    FLAGS word and make every flag live at the dispatcher, so `tests/audit.csv` allows
    1,917 full-flag materialisations (MEASURED, `make gen`). Proved save/restore pairs in
    `annotations/flags.csv` (DERIVED by reading, as X-Wing's) shrink it. Acceptance: the
    pairs listed with their evidence, the audit counts lowered to the new measurement, the
    68020 block differential passing.
