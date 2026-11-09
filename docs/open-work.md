# Open work

The single list of open work. Remove items when done; history is in git.
Plan, phases and gates: [port-plan.md](port-plan.md); each item names its phase.

## The original

3. Map the game executable: Borland C++ 1991 large model, 80186+, VROOMM overlays
   (`tools/bc_exe.py`; the runtime image at entry and after overlay loads is proven by
   `tools/load_image.py`, [pc-reference-loop.md](pc-reference-loop.md)). Open: the
   `WC2.LZC` packing method, a `make inspect` target (playbook §3; port-plan P8.2).
   Acceptance: an independent `WC2.LZC` unpack equals the installed `WC2.EXE`.
5. Memory and external surface, first pass: conventional and EMS use, interrupts, ports,
   video modes, DOS file opens, timer rate, from the DOSBox-X log or an instrumented build
   (Secret Weapons of Luftwaffe `tools/patches/`; port-plan P2.5). Acceptance:
   `docs/external-surface.md` with each row MEASURED or DERIVED.
6. Feasibility report for the owner ([feasibility.md](feasibility.md): the quiet flight
   frame and FM channel use are in). Open: code size, overlay or EMS paging scheme,
   drivers, the engine's relation to WC1 (supplied disks in `tmp/wc1/`), a combat frame's
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
