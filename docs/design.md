# Design

Status: project setup. No approach is validated on this game yet; the defaults below follow
the nearest sibling port (Secret Weapons of Luftwaffe) and stand until the owner changes them.

## Approach

The original is 16-bit real-mode DOS x86 (INFERRED from the installer, a Borland Turbo C++
1990 MZ executable; the game executable is still packed in `WC2.LZC` and unexamined). The
playbook's choice for x86 DOS is offline translation to 68020 assembly, oracle-tested
against x86, or routine-by-routine recovery into native code (Slicks). Default: the
translator, reusing Secret Weapons of Luftwaffe's x86 → IR → 68020 pipeline and its
guardrails (guest code reaches the Amiga only as translator output).

Facts that decide feasibility, all open ([open-work.md](open-work.md)):

- the unpacked executable: its packer, size, overlays, compiler runtime, CPU level (286 or
  386 instructions);
- memory: the installer says music needs EMS; how much conventional and EMS memory the game
  uses decides the A1200 Fast RAM requirement;
- the external surface: VGA mode 13h access, sound drivers (`*.DRV`), speech, timer rate,
  self-modifying or runtime-loaded code;
- the relation to Wing Commander I (same engine lineage; the WC1 PC disks are supplied as a
  cross-reference, as Their Finest Hour was for Secret Weapons of Luftwaffe).

## Owner decisions

Changed only by the owner.

| ID | Decision | Status |
|---|---|---|
| D1 | Target: PAL A1200, 68020, AGA; Fast RAM amount set once memory use is measured | default, from the handoff |
| D2 | Approach: offline x86 → 68020 translator as in Secret Weapons of Luftwaffe | default, from the handoff |
| D3 | Scope: VGA 320×200×256; which audio (AdLib or Sound Blaster music and effects; intro speech; the Speech Accessory Pack is not supplied) | **open: owner's call** |
| D4 | Version: the 7-disk DOS release in `ref-originals/` ([source-inventory.md](source-inventory.md)) | default |
