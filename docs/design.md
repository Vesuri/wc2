# Design

Status: project setup. No approach is validated on this game yet; the defaults below follow
the nearest sibling port (Secret Weapons of Luftwaffe) and stand until the owner changes them.

## Approach

The original is 16-bit real-mode DOS x86: `WC2.EXE` is Borland C++ 1991, large model,
80186, with 124 VROOMM overlays and sound drivers loaded from files (MEASURED,
[source-inventory.md](source-inventory.md)). The playbook's choice for x86 DOS is offline
translation to 68020 assembly, oracle-tested against x86, or routine-by-routine recovery
into native code (Slicks). Default: the translator, reusing Secret Weapons of Luftwaffe's
x86 → IR → 68020 pipeline and its guardrails (guest code reaches the Amiga only as
translator output). Phases, the copy map and proposed decisions: [port-plan.md](port-plan.md).

Facts that decide feasibility, open unless marked ([open-work.md](open-work.md)):

- the executable: measured as installed; the `WC2.LZC` packing is open;
- memory: the installer says music needs EMS; how much conventional and EMS memory the game
  uses decides the A1200 Fast RAM requirement;
- the external surface: VGA mode 13h access, sound drivers (`*.DRV`), speech, timer rate,
  self-modifying or runtime-loaded code;
- the relation to Wing Commander I (same engine lineage; the WC1 PC disks are supplied as a
  cross-reference, as Their Finest Hour was for Secret Weapons of Luftwaffe): measured
  statically in [wc1-wc2-comparison.md](wc1-wc2-comparison.md); its hot paths are open.

## Owner decisions

Changed only by the owner.

| ID | Decision | Status |
|---|---|---|
| D1 | Target: AGA Amiga, 68030 minimum, 68040 or better recommended; Fast RAM amount set once memory use is measured | owner, 2026-11-01 |
| D2 | Approach: offline x86 → 68020 translator as in Secret Weapons of Luftwaffe | default, from the handoff |
| D3 | Scope: VGA 320×200×256; FM music and effects (`MUSIC.A00`, as played on AdLib/Sound Blaster) resynthesised on Paula, plus the digitised intro speech (`SPEECH.S00`); Roland, PC speaker and the Speech Accessory Pack are out | owner, 2026-10-29 |
| D4 | Version: the 7-disk DOS release in `ref-originals/` ([source-inventory.md](source-inventory.md)) | default |
| D5 | Translator: copied from Secret Weapons of Luftwaffe into this repository (origins in `docs/upstream.md`); a shared translator extracted into AmigaXDev afterwards, if feasible | owner, 2026-11-01 |
| D6 | FM on Paula: Secret Weapons of Luftwaffe's AdLib implementation (OPL register re-hoster, effects prerendered at start-up), then judged by result | owner, 2026-11-01 |
| D7 | Installer: from the 7 disks | owner, 2026-11-01 |
| D8 | Lockstep of services inside IRQ0's handler: the handler keeps SWOTL's private stack (irq-plan I4); SS must be its B000h and compares as the interrupted SS; SP, and BP while it points into the private stack, compare as their offsets below 8000h applied to the interrupted SP; every other register is strict (`tests/host_run.py relocated`, `tests/amiga_replay.c`; sabotage `irq-stack`, `irq-offset`) | owner, 2026-11-10 |
