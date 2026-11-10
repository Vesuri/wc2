# Port plan

How Wing Commander II reaches the Amiga: Secret Weapons of Luftwaffe's (SWOTL) translator,
runtime, Amiga layer, tests and tools are copied at SWOTL `658fc60` (release 0.93,
2026-10-31) and adapted, never rewritten. Phases and gates are SWOTL's (`docs/phases.md`
there), with a phase 0 for the import. Code shared with PC Wing Commander I is a phase 7
refinement (W steps), entered only when a profile names it. Owner decisions:
[design.md](design.md). Work queue: [open-work.md](open-work.md). Evidence: MEASURED,
DERIVED, INFERRED. SWOTL files are cited by their path in that repository.

## What SWOTL teaches

Its own record: SWOTL `docs/translation-lessons.md` (G1–G8, lessons 1–50),
`docs/speed-plan.md` §2–§6 and §10, `docs/irq-plan.md`, `docs/native-plan.md`, AmigaXDev
`docs/playbooks/new-port-playbook.md`.

### Keep: what made it fast (MEASURED from its git history)

| Lesson | SWOTL evidence | Here |
|---|---|---|
| Reference loop and image proof first | gates 1–2 on day 2 (2026-10-03) | phase 1 before any translator change |
| Deterministic reference: pinned BIOS ticks and DOS date, interrupts held to sync points | every milestone byte-identical; host lockstep finds the first differing service | copy the patches and the rules unchanged |
| Pixels from the translator early (G7) | Lucasfilm logo from generated code on the A1200 model on day 2; host lockstep to m7 on day 3 | phase 5 targets the first WC2 picture |
| Oracles on the host: Unicorn x86-16 vs Unicorn 68020, the whole program on Unicorn against DOSBox | no Amiga in the inner loop | same; Amiga runs only for platform and timing |
| Fail loudly: unknown flow, code writes, ports and interrupts stop with a name | new surfaces arrive as named stops | same |
| Every gate has a sabotage plant | `make test-sabotage`, `t-sab-*` | copied with each gate |
| Select gates by dependency | AGENTS.md "Validation scope" | adopt the rule in phase 0 |
| 68030 development model | logo at 80 vs 252 frames on the 68020 (`translator-design.md`) | 68030 is the minimum here (D1): development and timing runs; 68040 checks the recommended class |

### Day-one choices: what SWOTL had to undo

SWOTL was playable after 3 days. Most of the next 3 weeks went to making it fast, and much
of that was undoing early choices. Here each one is made in its final form from the start
(AmigaXDev `docs/playbooks/new-port-playbook.md`, 2026-11-01, holds the generic form).

| # | Choice | SWOTL evidence | Where |
|---|---|---|---|
| C1 | **Memory and register contract**, final before any code is generated: byte-reversed guest RAM with biased segment bases, SP/BP mirrored, upper register words undefined, virtual flags | SWOTL started with little-endian RAM, zero-extended registers and flags in memory, and changed the contract on days 8–10 (R1b, R4, R5: −1.9%, −2.6%, −2.0% of the meter), re-plumbing its harness and plants | P0 imports it; the P4 lowerings are written to it; it changes only with the owner |
| C2 | **Timer interrupt**: the guest's handler runs from the Amiga timer interrupt (CIA-B) whenever guest IF is set and no handler is active, on a private guest stack, justified by the generation-time footprint proof (`translator/irq.py`) and the host-run monitor; sync points only in test builds | polls at 2,096 loop heads cost 5.15% of the meter's cycles; removing them cut frames from 330 to 300 ms (irq-plan) | P4.4 for every WC2 handler; long references wait for the final sync set |
| C3 | **EMS page switching nearly free**: a map is a table update where provably exact; copies are the guarded fallback | two 16 KB pages copied byte by byte per map (240K cycles), about 25% of the cycles in close-bomber scenes; F1's long copies and identical-remap skip cut that scene's meter 27.7% | P2.5 measures the access pattern; P4.5 designs the model before the first profile |
| C4 | **Display**: take the machine over, convert only the rows the game drew (marks at its stores, never frame compares), present each frame at the game's own frame boundary | rebuilt four times: periodic present (10-04), changed rows (10-06), takeover copper display (10-07), double-buffered publication (10-13), frame-boundary present (10-28) | P2 finds the boundary; P6b.1 copies the final path |
| C5 | **Speed work** starts with the deterministic cost meter and lowering-cost meter, and profiles of several heavy scenes | round 1 judged steps on frame medians inside trajectory noise and ±0.7% layout noise, priced in instructions (speed-plan §5) | P7.1 before the first speed step |
| C6 | **Sound**: price the worst-case effect first; prerender effects at start-up | the heavy gun rendered live cost about 19 M cycles per 0.88 s shot, about 40% of a 50 MHz 68030; prerendering (capture the driver's OPL writes per effect id at start-up, synthesise into Chip, cache on disk) came after release 0.90: 465 KB Chip, 6.5 s first start, 0.9 s cached on a 68030 | P6b.2 |
| C7 | **Release tests before the first release**: exit to DOS, save and load, every input device, NTSC, the CPU range 68030–68060 with the cache and MMU options | after 0.90: exit path (EMS release, mode 3, console text; 0.91), Paula restarts on fast CPUs (0.92), 68030 data cache with WHDLoad's MMU option, mouse rates, analog joystick axes and buttons (0.92, 0.93), NTSC timing | P8.3 |

### Also avoid

| Cost | SWOTL evidence | Here |
|---|---|---|
| Native contract with byte write histories, retired later | native-plan U3, irq-plan RC5 | start with the RC5 final-state contract |
| Narrow native rows with frequent exits | BB70, F290, BD68, FDE0 deferred without a positive price | price before building; prefer whole routines (F3, F5) |
| References re-recorded whenever the sync set changed | irq-plan RC3 | record long references once the sync set is final (C2) |
| Speed work took most of the calendar | 2026-10-06 to 2026-10-31; 68020 frames 290–300 ms after it | phase 7 only against a measured, owner-set bar |

The translator's kept speed forms (R1–R48, F1–F9) and the end states of the irq plan, the
display queue and FM sound all come with the import. Only their profile-chosen annotation
rows (`align.csv`, `bp-regions.csv`, `outline.csv`, `seg-repeat.csv`) are regenerated
from WC2 profiles by the same tools.

## What differs in WC2

| Item | SWOTL | WC2 | Work |
|---|---|---|---|
| Code | MS C 5, medium model, 8086 only | Borland C++ 1991, medium model (the runtime takes near data pointers: `strlen`, `strcpy`, `malloc`, `annotations/runtime.csv`; DERIVED), 80186: in a linear decode 4,633 `push imm`, 454 `leave`, 467 `shl r,imm` (MEASURED, an upper bound); no INT 34h–3Dh FPU emulator calls (MEASURED) | 186 opcodes (P3, P4); Borland runtime names (P2) |
| Overlays | PLINK: 12 files at fixed load segments; a load never replaces the caller | VROOMM: 124 overlays inside `WC2.EXE`, 184,673 B of code, read into a buffer at run-time segments; stub entries `CD 3F` patched to `JMP FAR` (format MEASURED, `tools/bc_exe.py`; behaviour INFERRED) | VROOMM model (P2), dynamic-CS modules (P4) |
| Drivers | RTSVGA and SPAZ are overlays | no video driver: the renderer is in the EXE. Sound drivers `STRAX.DRV` 6,462 B, `TM.DRV` 28,337 B, `SUPERTM.DRV` 87,198 B are files read at run time (sizes MEASURED, roles INFERRED) | drivers become modules (P2, P4) |
| Video | mode 13h and DAC through INT 10h only; only RTSVGA writes VRAM | 45 `in al,dx` and 9 `out dx,al` sites in the EXE (MEASURED, linear): likely DAC and status ports | DAC and 3DAh models, VRAM writer set, WC2's frame boundary (P2, P6) |
| Timer | SPAZ's 236.7 Hz IRQ0 handler | PIT writes and 4 counter reads (`in al,40h`) in the EXE (MEASURED); handler unknown | PIT counter model; footprint of WC2's handlers |
| Keyboard | runtime BIOS handler | `in al,60h`, port 61h and EOI in the EXE: its own IRQ1 handler (INFERRED) | IRQ1 to a guest handler with a port 60h/61h model |
| Sound | OPL2 only; music only on title and side choice | FM music throughout, FM effects, digitised intro speech on a Sound Blaster (DSP, DMA, IRQ 7) | OPL status reads, SB model, Paula speech voice, music voice policy (D6) |
| Memory | 1.06 MiB guest RAM, 1.36 MB code, EMS 40h–45h | 279,857 B code plus 121,997 B drivers; EMS for ships, speech and replay (`README.DOC`) | Fast RAM budget (D1); EMS functions as traced |
| Code writes | 678 sites in one unrolled block (cell walk, D16) | VROOMM stub patches; others unknown | code-write audit (P2) |

SWOTL's translator is about 8,500 lines, and about 70% of them carry over unchanged. The
coupling to its game is localised:

- `lower.py`: `LOADSEG`, the PLINK `dw id`, the graphics-driver VRAM rule and
  `GUEST_VECTORS`.
- `cfg.py`: PLINK thunks and the parent chain. It also rejects an instruction reached with
  two CS values.
- `emit.py`: module tags, `GRAPHICS_DRIVER`, and CS as the assemble-time constant
  `LOADSEG+cs`.
- `image.py`: builds on `tools/swotl_model.py`.
- `irq.py`: SPAZ's segments and ports.

About half of the runtime is generic. `compute_*.s`, `sfx.c` and `compute_opl.s` are SWOTL
only. These counts come from reading the code at `658fc60` (DERIVED).

## Phases

Each phase ends at a gate; do not commit the next phase's work until it passes
(playbook §7). Streams B (translator, P3–P4 on synthetic corpora) and C (Amiga platform)
can run beside stream A (reference and map, P1–P2) once P0 is in.

### P0. Import (gate: `make test` on synthetic corpora, `make amiga`, `make smoke`)

1. Copy by the copy map below in one commit that names SWOTL `658fc60`. Record each file's
   origin and every later local change in `docs/upstream.md`, so that fixes can move
   between the two ports.
2. Framework: SWOTL's copy (the DanceDiverse3 lineage, shared with Slicks), recorded in
   `src/platform/amiga/framework/README.md`. AmigaXDev's canonical tree has not merged that
   lineage, and the copied platform code does not build against it (MEASURED at P0).
3. Rename mechanically in one commit: `SWOTL_` → `WC2_` (environment, macros, probe
   symbols), `Swotl` → `Wc2`, the `swotl-gen` header. Rename nothing else yet.
4. Empty every `annotations/*.csv` to its header. Remove SWOTL's fixtures,
   `tests/audit.csv` rows, natives (`compute_*.s` rows, `hle.csv`) and TFH mode.
5. Copy SWOTL's AGENTS.md rules not already here: "Guest code reaches the Amiga only as
   translator output", the HLE table rule, the validation scope and phase gates.
6. Gate checks:
   - `make test-decode test-x86 test-m68k test-sabotage` pass on the "space" and
     "boundary" corpora;
   - the "forms" corpus is empty until P2;
   - an empty `Wc2` boots and quits under FS-UAE.

   This closes open-work 2.

### P1. PC reference loop (gate 1, SWOTL `docs/phases.md`)

1. Patched DOSBox-X:
   - copy `tools/patches/`, `ORDER` and `build_dosbox_x.sh`;
   - build into a tree of its own, so SWOTL's is never touched.
   - adapt the trace patch:
     - arm at WC2's MZ entry (`0000:0000` + PSP + 10h);
     - attribute a paragraph to `WC2.EXE+fileoffset` when it comes from the FBOV area
       (overlay = FBOV entry), or to a driver file;
     - replace `plink.csv` with `vroomm.csv`, one row per event (load, evict, EMS copy,
       stub patch, return-address patch).
   - Sound patch:
     - log OPL at 388h/389h and at the SB aliases 220h–229h;
     - log SB DSP (22xh) and the DMA ports (02h, 03h, 83h, 0Ah–0Ch);
     - record PIT counter and 3DAh reads for replay, as `joystick.csv` does.
2. `reference/dosbox-x.conf`:
   - cputype 386, normal core, fixed cycles;
   - EMS on, sized for the full feature set;
   - SB 2.0 at 220/7/1 with OPL2, as in `reference/dosbox-staging.conf`.
   - FPU off if the Borland startup probes for one and nothing uses it: the reference must
     answer as the A1200 model will (settle in P2).
3. Milestones (`reference/milestones.csv`, keys at instruction triggers as in SWOTL):
   - m0 entry;
   - m1 mode 13h;
   - m1b the first stable picture;
   - m2 the intro with speech;
   - m3 the pilot-file menu;
   - m4 the first space flight, then 50 frames later;
   - m5 the landing and debriefing;
   - m6 save and load.

   A protection question, if one is asked, is answered by the key script, never patched.
4. Image proof: `tools/load_image.py` with a WC2 loader model built on `tools/bc_exe.py`
   (`tools/wc2_model.py`):
   - root from MZ plus relocations at the reference load segment;
   - each resident overlay from FBOV plus its relocation records at its observed buffer
     segment;
   - each driver from its file, unpacked by `tools/origin_pak.py` if packed.

   The DOSBox-X entry dump diff closes open-work 3's entry part.
5. Feasibility estimate (feeds open-work 6; checks D1's 68030 minimum). Measure the reference's flight frame
   time at fixed cycles (ticks per frame from WC2's own clock or from the frame boundary)
   and apply SWOTL's ratio:
   - its 68020 frames are 290–300 ms;
   - its 12,000-cycle reference takes 9–18 ticks at 236.7 Hz (38–76 ms, `docs/game-timing.md`);
   - so the translated game is roughly 4–8× slower than its reference (DERIVED; fixtures not
     matched);
   - the 68030 model runs about 3× the 68020.

   Also record OPL channel use (`opl.csv`: simultaneous voices, rhythm mode) for D6.
6. Gate checks:
   - `make reference` reaches every milestone twice with byte-identical RAM, VRAM and DAC;
   - the image proof passes for the root and for every overlay and driver resident at any
     milestone.

   This closes open-work 4.

### P2. Static and live map (gate 2)

1. VROOMM, written up as `docs/vroomm.md` the way SWOTL wrote `docs/plink.md`:
   - stub header fields at run time;
   - buffer bounds;
   - eviction order;
   - return trapping (how live frames of an evicted overlay are patched);
   - EMS caching;
   - the INT 3Fh path.

   `tools/vroomm_check.py` over every trace must report 0 model violations.
2. Drivers: which file serves FM and which serves speech, how each is loaded (file,
   container entry, allocator, segment), its entry table and relocations, and its
   vectors. If every trace loads a driver at one segment, translate it there with a
   residency check (static CS, as SWOTL's overlays). Otherwise it becomes a dynamic-CS
   module (P4.2).
3. Sweep (`tools/sweep.py`, recursive descent only, never linear). Seeds:
   - the MZ entry;
   - every stub entry of the 124 overlays;
   - vectors set through AH=25h;
   - Borland's startup and exit tables;
   - switch and function-pointer tables (`tables.csv`);
   - driver entry tables.

   Name the Borland runtime entries in `annotations/runtime.csv` with evidence; Slicks is the
   prior Borland port.
4. Code-write audit (`tools/code_writes.py`):
   - stub patches as a two-form region;
   - returns patched on the stack (data, not code);
   - any other write to executed bytes classified mechanically.
5. External surface: `tools/surface.py` generates `docs/external-surface.md`. It covers
   - INTs and the vectors installed (08h, 09h, 0Fh, 3Fh, 1Ch, 23h, 24h, 00h as found);
   - ports;
   - the VGA mode (chained or not) and retrace waits;
   - EMS functions, pages and map rate;
   - DOS files read and written;
   - the PIT rate.

   This closes open-work 5.
6. Gate checks:
   - static and live evidence agree;
   - no executed byte is unclassified;
   - every indirect site is resolved or fails loudly;
   - `make map` is reproducible.

### P3. x86 semantics for 80186 (gate 3)

Done from X-Wing's translator, not from SWOTL's again (owner's direction, 2026-11-09):
X-Wing `3dea12a` added the 80186 forms to SWOTL's `decode.py` and `sem.py`, with
boundary cases and sabotage plants; `docs/upstream.md` lists what came over.

1. `decode.py` and `sem.py`: `push imm` (68h, 6Ah), `imul r16,r/m16,imm` (69h, 6Bh),
   shifts and rotates by an immediate (C0h, C1h; count masked to 5 bits, 0 a no-op),
   `enter` (C8h; level masked to 5 bits) and `leave` (C9h). WC2's sweep has 68h, 6Ah,
   C0h, C1h and C9h only; no `pusha`/`popa`, `bound`, `ins`/`outs`, `enter` or
   three-operand `imul` (MEASURED, `docs/external-surface.md`). Those and 0Fh still raise.
2. Two scopes in `tools/wc2_model.py`: `X86_SCOPE` (`WC2.EXE` with its overlays and
   the three drivers) is decoded and lifted; `SCOPE`, the modules generated as 68020
   code, stays empty until P4. `cfg.py` takes WC2's code ranges (root, overlays, driver
   entries) and seeds from the stub entries and `entries.csv` (written by
   `tools/sweep.py --annotations`).
3. Corpora: "forms" and "blocks" from WC2's code, drivers included; i186 boundary cases
   (counts 0, 1, around the widths and ≥ 32, `enter` levels); five sabotage plants on
   the new forms.
4. Gate checks (`make test`): the decoder's starts are the sweep's, one for one, and
   agree with Capstone (`tests/test_decode.py`); the IR agrees with Unicorn x86-16 over
   forms, blocks, space and boundary; `make test-sabotage` catches every plant.

### P4. 68020 backend for WC2 (gate 4)

1. Lowerings in `lower.py` (X-Wing `ec4a238` has them for SWOTL's lowering; bring them
   over as P3 brought the decoder):
   - `push imm`;
   - `imul` with an immediate (no longer assumes AX);
   - shifts by an immediate above 8 through a register;
   - `enter`/`leave` and `pusha`/`popa` on the mirrored SP/BP;
   - entries in `reads`/`writes`, the flags plain set and `irq.py`;
   - WC2's start-up self-modification (`annotations/self-modifying.csv`: the `imm8`
     operand at `WC2.EXE+1DC` and the `ja`/`jb` pair at `+1ED`): neither SWOTL's nor
     X-Wing's `smc.py` lowers it, and `make gen` stops on it once `WC2.EXE` is in `SCOPE`;
   - the 68020 differential then takes the 80186 forms: `tests/m68k_diff.py` skips every
     case holding one until this step, because SWOTL's lowering takes some of them
     without an error and wrongly (a shift by an immediate as a shift by one, MEASURED).
2. Dynamic-CS modules (new contract, written into `docs/translator-design.md` first):
   - **Keys.** Overlay and dynamic driver code is translated once, keyed by
     (module, offset).
   - **CS slot.** CS uses read a per-module slot in the state block: `push cs`, `cs:`
     bases, far pushes, return checks, `int` frames and dispatch d6.
   - **Stub entries** are a two-form cell:
     - `CD 3F` runs the guest INT 3Fh;
     - `EA off seg` sets the slot from `seg` and branches to the native label of (overlay,
       `off`). `off` must equal the offset the entry holds in the file;
     - anything else stops.
   - **Far dispatch** maps a segment to a module through the manager's own residency
     record, read from guest RAM as `resident()` reads PLINK's table.
   - **Return checks.** A mismatch re-dispatches, because VROOMM patches the returns of
     evicted frames.
   - `cfg.py` keys these modules by offset, not by CS.
   - The VROOMM manager itself runs translated; a native overlay service would break
     lockstep and the rule against replacing the original's decisions.
3. Borland forms: `push cs; call near` far calls, switch tables read through the module's CS
   base, huge-pointer helpers as ordinary guest code.
4. Interrupt handlers (C2): `irq.py`'s footprint proof generalised from SPAZ's IRQ0 to each
   handler WC2 installs (timer, keyboard if its own, SB IRQ 7), with the host-run monitor.
   Production delivers them from the Amiga interrupts; sync points exist only in test
   builds. Record the long references only after this set is final.
5. EMS model (C3), written into `docs/translator-design.md` before the first profile:
   - a map is a table update where exact: segment bases for the frame (E000h–EFFFh) point
     at the mapped logical page when the access cannot leave that 16 KB page (guarded, as
     R6's BP regions are, with the exact path as fallback);
   - copies remain the fallback, with F1's long copies and identical-remap skip;
   - DOS reads into the frame and the runtime's own accesses take the same path.

   The x86 and 68020 differentials and a sabotage plant cover the guard edges.
6. Gate checks:
   - `make test-m68k` and `make test-blocks` pass over WC2's corpora and the generated program;
   - the audits pass: spills 0, full-flag materialisations and dispatcher exits within
     `tests/audit.csv`;
   - the G1 header and G2 lint pass.

Status: 1–3 and 6 as built ([translator-design.md](translator-design.md), "WC2: VROOMM
overlays and dynamic CS"; the CS is the stub's word 10h, not a state-block slot). 4 moves to
P5 (open-work 9). 5 is built with lazy pages ("WC2 EMS model"); access without a copy is open-work 10.

### P5. First vertical slice (gate 5)

1. `machine.c` reference values re-measured from WC2's reference:
   - PSP;
   - MCB chain;
   - environment and command tail (`wc2`);
   - IVT values;
   - BIOS data;
   - EMS and mouse answers;
   - the sound detection answers the drivers read.
2. `make test-host` from the MZ entry to m1 and m1b. Services, RAM and the framebuffer and
   DAC must equal the reference.
3. `make test-amiga` at m1b: the shown bitplanes and colours equal the reference frame.
4. First profile on the target: where the frame time goes, and the feasibility estimate
   recomputed from it on the 68030 and 68040 models. That makes open-work 6's report, checked
   against D1.

Status: 1–3 pass (`make test-host`: m1 and m1b in lockstep, services inside IRQ0's handler
compared relocated, design D8; `make test-amiga` at m1b on the 68030 model, 32 MB Zorro III
Fast RAM for the diagnostic image). 4 waits on open-work 9 and 10.

### P6. Whole game (gate 6)

1. Runtime surfaces, in milestone order:
   - **DOS**: game writes into `GAMEDAT` (`SAVEGAME.WC2`, `TEMPGLOB.000`, `MEM.$$$`, `AUTO.$$$`, `TAPE.TMP`) through
     SWOTL's I/O windows, plus any DOS function the traces show that `dos.c` lacks.
   - **EMS functions** as traced.
   - **Mouse**: INT 33h, copied.
   - **Keyboard**: IRQ1 to WC2's handler, if P2 confirms that it installs one; the port 60h/61h model; asynchronous delivery
     under a footprint proof, with `irq.py` extended from IRQ0 to a set of handlers.
   - **PIT**: rate to CIA-B; counter reads from the CIA timer; host runs replay the
     recorded reads.
   - **Joystick**: 201h, the analog and digital model copied.
   - **VGA**: DAC through ports 3C7h–3C9h to `plat_palette`; 3DAh from the beam;
     `rt_vram_mark` on stores by WC2's writer set (replacing the graphics-driver rule);
     present at WC2's own last per-frame call (found in P2), with SWOTL's fallback.
   - **Sound**:
     - OPL status and timer reads for detection;
     - the SB DSP (reset, version as SB 2.0, time constant, 8-bit DMA, speaker);
     - DMA channel 1;
     - IRQ 7 at the end of each block, timed by the sample rate.
2. Coverage scripts (`reference/coverage.csv`): every flight scene type, the ships flown,
   cinematics, menus, saves and the ending path. Later missions start from saves recorded
   under the reference, as local fixture inputs.
3. `make test-host-all` lockstep, `make test-amiga-replay` on a few milestones, a
   `play_walk.sh` smoke into flight.
4. Gate checks:
   - every overlay and driver is translated;
   - zero unclassified executed instructions (G6);
   - the HLE share is reported (0 so far);
   - lockstep is clean over all milestones.

### P6b. Amiga platform (stream C, beside P5–P6)

1. Display: SWOTL's 320×200×8 copper display, double buffer, changed-row Kalms C2P, display
   queue and frame cap, all copied. Pointer sprites only if WC2 draws a software pointer;
   re-derive the save-buffer rule (SWOTL `docs/pointer-plan.md`).
2. Audio:
   - **FM (D6)**: SWOTL's AdLib implementation as is: `fm_paula.c` and `Audio.cpp`
     (OPL register file to 4 Paula voices); then see how it goes. SWOTL plays 4 voices; the
     OPL2 has 9 channels; P1.5 counts how many WC2's music uses.
   - **Effects (C6)**: price the worst-case effect first (`fm_effect_check` on P1's OPL log),
     then prerender at start-up as SWOTL's R1–R4: capture the driver's OPL writes per effect,
     synthesise into Chip, cache on disk; measure the Chip cost.
   - **Speech**: one Paula voice playing SB DMA blocks copied to Chip; channel ownership
     between speech, music and effects is an explicit policy.
3. Input: the key map, mouse and joystick from SWOTL; WC2's own joystick calibration runs.
4. Memory: measure code, guest RAM and EMS pages for the Fast RAM requirement; Chip holds
   bitmaps, copper lists, audio only.

### P7. Performance (gate 7)

1. Instruments copied:
   - the cost meter and model;
   - lowering cost;
   - `profile_report` and `profile_tree`;
   - `ab_runs`;
   - the frames and flyby fixtures.

   Before the first speed step (C5): deterministic fixtures for several heavy scenes (a
   dogfight with many ships, a capital-ship battle, a cinematic, the busiest menu), and a
   cost model recalibrated on them.
2. Timing on the 68030 model (D1's minimum), checked on the 68040. The owner sets the
   frame-rate bar from the P5 measurement.
3. System first:
   - CACHECHIP or CACHE on the slave;
   - chunky buffers and guest RAM in Fast;
   - changed rows only.

   Their Finest Hour's slave got most of its gain from these (SWOTL
   `docs/swotl-tfh-rendering-map.md`).
4. Translator and runtime:
   - regenerate the profile-chosen annotations;
   - check the EMS map rate (F1) and REP copies (F2) first.
5. Native routines: only with the owner's authorization per routine, by SWOTL
   `docs/native-compute.md` and the S1–S9 procedure. Every row is priced before it is
   built, and the WC2 x86 stays the oracle.

### P7W. WC1 refinement (the owner's plan; open-work 8)

The Their Finest Hour precedent applies: same engine family, Amiga original, the
user's improved slave.

1. **W1, hot list.** The P7 profile on the 68030 model gives WC2's top routines by own and
   inclusive cycles.
2. **W2, PC lineage.** `make compare` (`tmp/compare/funcs.csv`) gives each hot routine's PC WC1
   counterpart and ratio. Prime suspects:
   - `R:15AD` "SPACE BUFFER" span/sprite (100% shared);
   - `R:0BD7` ship loading and timing (64%);
   - `R:073C` HUD (31%);
   - `O:1764` weapons (16%).
3. **W3, Amiga lineage.** A cross-reference doc (as SWOTL `docs/tfh-cross-reference.md`)
   matches WC1 PC routines to the Amiga CD32 WC1 by behaviour, constants, tables and
   strings. Starting points are the Wing Commander project's measured routines
   (`docs/internals.md`, "Phase 11b rendering costs"):
   - TM6 image drawing, plain `E:2efe8`, scaled `E:2ec98` and rotated `E:2d746`;
   - geometry `E:2a086`;
   - maths `E:2a9d4–2cbd8`;
   - orientation `E:2bb30`;
   - view clear `E:31cd6`;
   - glyphs `E:2fd6a`.

   That game is a Manx Aztec C build with hand-written assembly. It reads big-endian
   repacked resources (`.pkt`, `LZNP`/`NJMP`, TM6 images) and plays ProTracker modules.
   So the correspondence is algorithmic, not drop-in, and its data and music layers do not
   transfer (Wing Commander project survey, 2026-11-01).
4. **W4, sources** (SWOTL U0 rule):
   - original Amiga WC1 code is reference only and never enters the port;
   - adaptable sources are the owner's own improved routines (the Wing Commander slave's,
     such as its software c2p), or new 68020 code written against WC2's x86.
   - WC2's constants, rounding, branch order and tables are kept.
5. **W5, price.** Own-cost ceiling at zero native cost (SWOTL B3) before asking for
   authorization.
6. **W6, build.** Owner authorizes per routine, then S1–S9 and the native-compute contract.
   Each one is one commit with a meter A/B.
7. **W7, expectation.** SWOTL's best single native row cut the meter 4.68% (R35); TFH's
   routine rewrites gave 22.4 → 23.5 fps after system changes. The Amiga WC1 spends about 65%
   of 68020 flight time in c2p, about 12–13% in maths and about 8% in drawing
   (Wing Commander project, "Representative flight costs"). So W is a refinement, and
   its first comparison is WC2's C2P cost against that slave's c2p.

### P8. Package (gate 8)

1. WHDLoad kickemu slave, Installer 43 script, ReadMe, icons and release audits from
   SWOTL. Memory comes from a MemFree measurement, as `docs/whdload.md` there does.
2. Installer from the 7 disks (D7). A helper unpacks `WC2.LZC` (open-work 3's codec) and
   `SPEECH.S00` (open-work 7), unless P2 shows the game reads them packed. It checks each
   disk's hash, writes to staging and replaces `data/` only on success, as SWOTL's
   `tools/install-data/` does.
3. Release tests (C7), all before the first release:
   - exit to DOS from every exit path;
   - save and load;
   - keyboard, mouse, digital and analog joystick;
   - PAL and NTSC;
   - 68030 (with and without WHDLoad's MMU option), 68040 and 68060, caches on and off;
   - WHDLoad and standalone runs, PRELOAD on and off.
4. `make release`: a clean build, an allowlisted package that refuses originals, an
   independent check, then the version record and tag (playbook §13).

### After P8. Shared translator (D5)

If feasible, extract the translator and the generic runtime into AmigaXDev, with SWOTL and
WC2 as its two consumers. `docs/upstream.md` lists what has diverged by then.

## Copy map (SWOTL `658fc60` → here)

| SWOTL | Treatment |
|---|---|
| `translator/`, except below | copy as is |
| `translator/lower.py`, `emit.py`, `cfg.py`, `image.py`, `gen.py`, `check.py` | copy, then adapt (P4.2): `LOADSEG`, VROOMM in place of PLINK, VRAM writer set, CS slots, module names |
| `translator/irq.py` | copy the method; WC2's handlers and ports replace SPAZ's constants |
| `annotations/*.csv` | headers only; every row re-derived for WC2 |
| `src/runtime/`: `dos.c`, `ems.c`, `input.c`, `machine.c`, `ports.c`, `video.c`, `pointer.c`, `rt_entry.s`, `runtime.h`, `platform.h` | copy. `machine.c` values re-measured. `ports.c` gains OPL status, SB, DMA, DAC, 3DAh, PIT counter and 60h/61h. `video.c` takes WC2's frame boundary |
| `src/runtime/compute_*.s`, `sfx.c`, `compute_opl.s` | not copied: SWOTL natives and SPAZ effect capture |
| `src/platform/host/` | copy |
| `src/platform/amiga/` | copy. `Swotl.cpp` becomes `Wc2.cpp`. `tfh_paula.c` dropped. A speech voice added |
| `src/platform/amiga/framework/` | SWOTL's copy (P0.2: the canonical tree lacks its lineage) |
| `tests/` generic harnesses: `x86_diff`, `m68k_diff`, `m68k_blocks`, `host_run`, sabotage, guards, `uc.py`, display, EMS, DOS, FM, input | copy; SWOTL fixtures and audit rows dropped |
| `tools/` generic: `pc_run`, `reference`, `trace_summary`, `snap_png`, `surface`, `profile_*`, `cost_meter`, `lowering_cost`, `ab_*`, `host_census`, `irq_profile`, `align_targets`, `bp_regions`, `outline_sites`, `seg_repeat`, `fm_check`, `opl_render`, `gate_launch`, `fixture_inputs`, `hunk_size`, `tool_icon`, `build_dosbox_x.sh`, `_amigaxdev.py` | copy; defaults (milestone names, ELF names, prefixes) adapted |
| `tools/` game-specific: `swotl_model`, `plink_check`, `load_image`, `ovl_info`, `sweep`, `code_writes`, `compute_oracle`, `native_entries`, `sound_reference`, `install-data/`, release tools | rewrite or adapt, keeping each tool's interface: `wc2_model` from `bc_exe.py`, `vroomm_check` |
| `tools/patches/` | copy; the trace and sound patches adapted (P1.1) |
| `amiga/` (Makefile, launchers, `.gdb` probes) | copy |
| `whdload/`, `release/` | copy in P8 |
| `Makefile` | copy the targets; drop SWOTL-only ones (TFH, the named native rows) |
| docs | the contracts (`translator-design`, `translation-lessons`, the generic rows of `x86-notes`, `amiga-arch`, `native-compute`, the speed rules §2–§6), stripped of SWOTL facts; history stays in SWOTL |

## Owner decisions this plan follows

[design.md](design.md): D1 (68030 minimum, 68040 or better recommended), D5 (copy now,
share afterwards if feasible), D6 (SWOTL's AdLib implementation, then see), D7 (install
from the 7 disks), all 2026-11-01.

## Pace reference (SWOTL, MEASURED from its git history)

| Day | Reached |
|---|---|
| 2026-10-02 | setup, reference loop, first traces |
| 2026-10-03 | gates 1–5: image proof, map, decoder and IR differential, 68020 backend, logo on the A1200 model |
| 2026-10-04 | host lockstep to m7, interrupts replayed, A1200 model runs the demo |
| 2026-10-05 | keyboard, mouse, file writes |
| 2026-10-06 to 10-13 | translator speed rounds 1–2 |
| 2026-10-14 to 10-15 | FM re-hoster and Paula |
| 2026-10-16 to 10-23 | speed steps R20–R48, TFH cross-reference, native routines |
| 2026-10-24 | WHDLoad slave, installer, release 0.90 |
| 2026-10-24 to 10-31 | irq plan, pointer sprites, prerendered effects, releases 0.91–0.93 (322 commits in all) |

WC2 adds work SWOTL did not need: P2's VROOMM model, P4.2's dynamic CS, the 186 opcodes,
the SB speech path and a guest keyboard handler. The input is of similar size. SWOTL's
in-scope EXE and overlay files total 426,672 B in 9 modules. WC2 has `WC2.EXE` at
363,696 B with 124 overlays, plus its drivers (MEASURED, file sizes including data). The
coverage scripts, though, must reach many more scenes.
