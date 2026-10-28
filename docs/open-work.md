# Open work

The single list of open work. Remove items when done; history is in git.

## Setup

1. Owner decision D3 ([design.md](design.md)): audio and speech scope. Acceptance: the
   owner's answer in the decision table.
2. Amiga scaffold (playbook §6): framework subset from AmigaXDev, `amiga/Makefile`,
   `run.sh`, `debug.sh`, an empty A1200 takeover that boots and quits under FS-UAE.
   Copy from Secret Weapons of Luftwaffe. Acceptance: `make amiga` and `make smoke` pass.

## The original

3. Map the game executable: `WC2.EXE` is Borland C++ 1991 with 195,280 B after the MZ
   image ([source-inventory.md](source-inventory.md)). Open: the format of that tail
   (Borland overlays, INFERRED), the CPU level (286 or 386 instructions), the `WC2.LZC`
   packing method. Acceptance: a `make inspect` tool reproduces the facts; an independent
   `WC2.LZC` unpack matches the installed `WC2.EXE`; the runtime image matches a DOSBox-X
   dump at entry (playbook §3, §4).
4. Game reference loop (playbook §4): boot `tmp/pc-root` headless under DOSBox-X with
   fixed input to a named milestone (title, then the first space flight), with a capture.
   Acceptance: one command reaches the milestone from guest state, twice, with matching
   stable crops.
5. Memory and external surface, first pass: conventional and EMS use, interrupts, ports,
   video modes, DOS file opens, timer rate, from the DOSBox-X log or an instrumented build
   (Secret Weapons of Luftwaffe `tools/patches/`). Acceptance: `docs/external-surface.md`
   with each row MEASURED or DERIVED.
6. Feasibility report for the owner: code size, overlay or EMS paging scheme, drivers, the
   engine's relation to WC1 (supplied disks in `tmp/wc1/`), expected A1200 cost. Acceptance:
   a doc with measured inputs and a recommendation on D1/D2.
