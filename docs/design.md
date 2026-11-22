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

- the executable: measured as installed; `WC2.LZC` is the resource container's LZW (`make inspect`);
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
| D9 | Dead-stack exemptions in host lockstep as in X-Wing (`40030a3`, `3dca119`): a service register loaded from, or a RAM byte stored from, a masked dead-stack byte may differ; each exemption is added only when a run needs it, with a sabotage control | owner, 2026-11-14 |
| D10 | Coverage beyond m6 (port-plan P6.2: every flight scene type, ship, cinematic, menu, save, the ending) is deferred; gate 6 runs over m1–m6 | owner, 2026-11-16 |
| D11 | The BIOS ROM segment F000h, which `SUPERTM.DRV`'s noise fill samples ([drivers.md](drivers.md)): the Amiga build fills it from a seeded pseudo-random generator, not from an emulator's BIOS; DOSBox-X's (1.4% of bytes with bit 0 set) is not era-appropriate. Host lockstep keeps the reference machine's bytes as a local fixture, since it compares with that run | owner, 2026-11-17 |
| D13 | FM effects prerendered (D6), from the pricing in open-work 19: captured from the original's driver, rendered and played on Paula as X-Wing's (`0eda68f`, `269828b`), with the HLE rows that needs, observe only (a capture point, the effect start `WC2.EXE+1254D`/`+121E9`), each in `annotations/hle.csv` with its oracle (`tools/sfx_capture.py`). The slave's Chip (`CHIPMEMSIZE`, `$C0000`) rises to what the samples need: the headroom it was kept for | owner, 2026-11-20 |
| D12 | Release 0.1 alpha, version 0.1 dated 19.11.2026: P8 (package) is done ahead of P6b.2 audio (open-work 19), P6b.4 memory (20) and gate 7 (P7); the alpha ships without item 19 (speech, prerendered effects) at the current speed. Its installer works from the 7 disks (the `WC2.LZC` and `SPEECH.S00` codecs, open-work 3 and 7, first), and the full C7 release matrix (port-plan P8.3) runs before it. Later releases keep the gate order | owner, 2026-11-19 |
| D14 | The one-shot effects `fm_effect` does not match stay on the live FM re-hoster, not captured or rendered: the ids `tools/fm_effect_check.cpp` fails at its thresholds (kept), listed in `fx_play.h` `FX_LIVE_IDS` (18, 26, 39, 40, 44, all feedback-7 patches, MEASURED 2026-11-21); the check fails if a listed id passes or an unlisted one fails | owner, 2026-11-21 |
| D15 | The effects (D13) are captured and prerendered at start-up, as Secret Weapons of Luftwaffe's: at the return of the game's sound init (`WC2.EXE+13641`, HLE `sfx_init`), before the first scene, not at the first effect start (a 15 s pause in the ORIGIN FX fireworks). `sfx.cache` is keyed on the capture's inputs, not its output: a kept cache loads without a capture | owner, 2026-11-22 |
