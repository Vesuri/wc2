# Port plan

How Wing Commander II reaches the Amiga: Secret Weapons of Luftwaffe's (SWOTL) translator,
runtime, Amiga layer, tests and tools are copied at SWOTL `658fc60` (release 0.93,
2026-10-31) and adapted, never rewritten. Phases and gates are SWOTL's (`docs/phases.md`
there), with a phase 0 for the import. Code shared with PC Wing Commander I enters in
phase 7 (P7.3, P7.10, P7.11), where a profile names it. Owner decisions:
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
| C5 | **Speed work** starts with the deterministic cost meter and lowering-cost meter, and profiles of several heavy scenes | round 1 judged steps on frame medians inside trajectory noise and ±0.7% layout noise, priced in instructions (speed-plan §5) | P7.2 before the first speed step |
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

   The DOSBox-X entry dump diff proves the image at entry.
5. Feasibility estimate (feeds [feasibility.md](feasibility.md); checks D1's 68030 minimum). Measure the reference's flight frame
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
overlays and dynamic CS"; the CS is the stub's word 10h, not a state-block slot). 4 is built
in P5 (`gen.IRQ_PROOF`: INT 08h at WC2.EXE+0FD10 and +148E0, INT 0Fh at +06F3F, the INT 08h
handler's calls into STRAX.DRV and the EMS resolver; "IRQ footprint" in
[translator-design.md](translator-design.md)). 5 is built: lazy pages, ES accesses on the
store page ("WC2 EMS model").

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
   recomputed from it on the 68030 and 68040 models. That makes the feasibility report ([feasibility.md](feasibility.md)), checked
   against D1.

Status: 1–3 pass (`make test-host`: m1 and m1b in lockstep, services inside IRQ0's handler
compared relocated, design D8; `make test-amiga` at m1b on the 68030 model, 32 MB Zorro III
Fast RAM for the diagnostic image). 4 is measured ([feasibility.md](feasibility.md),
"Translated cost on the target": the intro animation on the 50 MHz 68030; flight about 2×
short of its frame rate by estimate). Gate 5 passes: the IRQ footprint proof is on, the
host-run monitor finds no access outside it at m1 and m1b (0 problems; 122 and 699 handler
runs, 44 and 116 sync sites hit, MEASURED), and its sabotages are caught.

### P6. Whole game (gate 6)

1. Runtime surfaces, in milestone order:
   - **DOS**: game writes into `GAMEDAT` (`SAVEGAME.WC2`, `TEMPGLOB.000`, `MEM.$$$`, `AUTO.$$$`, `TAPE.TMP`) through
     SWOTL's I/O windows, plus any DOS function the traces show that `dos.c` lacks.
   - **EMS functions** as traced.
   - **Mouse**: INT 33h, copied.
   - **Keyboard**: IRQ1 to WC2's handler, if P2 confirms that it installs one; the port 60h/61h model; asynchronous delivery
     under a footprint proof, with `irq.py` extended from IRQ0 to a set of handlers.
     - Status: WC2 keeps the BIOS INT 09h and hooks INT 15h AH=4Fh (WC2.EXE+0FD93): the
       runtime's BIOS model calls it per scan byte, on the interrupted stack with the
       reference's frames (`rt_key_hook`), at sync points in tests and at service entry
       in production (irq-plan RC4), and takes the key unless CF comes back clear. The
       hook is in the footprint proof (entry AH=4Fh, AL, CF as the BIOS stub sets them;
       INT 16h AH=00h/01h and the chain to the BIOS INT 15h as runtime rows; its
       Ctrl+Alt+Del overlay calls an `irq-stops.csv` stop). Interrupts are held while it
       runs (the reference could take IRQ0 at its loop head once INT 16h AH=01h sets IF;
       the host run fails if a reference does). A console read that waits (INT 21h
       AH=07h/08h, the name entry's `getch` at WC2.EXE+15080) takes interrupts: the
       reference opens its poll gate in DOS's INT 28h idle HLT
       (`dosbox-x-wc2-idle-irq.patch`), sync builds replay those at `rt_idle` on the
       reference's stack, production lets the CIA tick run IRQ0 while it drains keys.
       Host lockstep at m1–m4 (MEASURED, `make test-host`).
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
     - Status: host lockstep at m2 (`make test-host`), the DSP commands the game sends
       (14h, 40h, D1h; no version query in m2–m6, MEASURED), blocks checked against the
       reference's port log, INT 0Fh runs under the footprint monitor; the Amiga's
       speech and IRQ 7 are P6b.2.
2. Deferred (D10; gate 6 runs over m1–m6). Coverage scripts (`reference/coverage.csv`): every flight scene type, the ships flown,
   cinematics, menus, saves and the ending path. Later missions start from saves recorded
   under the reference, as local fixture inputs.
3. `make test-host` lockstep over every milestone (`HOST_MILESTONES`), the Amiga
   replay (`tests/amiga_replay.py`) on a few. The `play_walk.sh` smoke into flight moved to
   P6b (open-work 18, done): the game starts speech before flight, so it needed the Amiga's
   IRQ 7 (silent until P6b.2).
4. Gate checks:
   - every overlay and driver is translated;
   - zero unclassified executed instructions (G6);
   - the HLE share is reported (0 so far);
   - the indirect sites no trace ran are reviewed ([indirect-coverage.md](indirect-coverage.md),
     `tools/indirect_review.py`, as X-Wing `33d685a`); none is excluded;
   - lockstep is clean over all milestones (m1–m6 while P6.2 is deferred, D10).

Status: gate 6 passes (2026-11-17, MEASURED).
- **Coverage:** `make gen`: 0 unclassified of 64,733 executed instruction starts over 23
  traces (`WC2.EXE` 56,001, 256 of them VROOMM stub cells; `TM.DRV` 1,180; `SUPERTM.DRV`
  6,300; `STRAX.DRV` 1,252); HLE 0. All 124 overlays and the three drivers translated; 94
  overlays run on the m1–m6 routes.
- **Lockstep:** `make test-host`: m1, m1b and m2–m6, 0 problems each (m6: 653,118
  service events, 34,817 interrupts, 576,935 OPL writes, 170 SB blocks).
- **Amiga replay:** on the 68030 model at m1b (gate 5), m2 and m4. The replay checks each
  SB block against the reference's, with sabotage `--sabotage sb-block` caught at m2,
  replays the interrupts DOS's idle wait took (`replay_idle`, m4: 585) and releases keys
  after their recorded visits (X-Wing `c737385`). It masks the undefined-flag bits as the
  host does, and shows the rows drawn since the last present before the capture, so m4's
  label inside a frame compares the live frame; the 3DAh and PIT runs are byte streams
  (m4: 23 MB, as 12-byte rows 130 MB). m5 and m6 hold typematic repeats, which
  the replay does not feed (one make and break per key), so they are not replayed.
- **Indirect sites:** 258 of 628 sites never ran. 48 have a proved table, and 173 read a
  constant slot that has a dispatch row in every snapshot. 15 read a slot with no row in
  some snapshot: the paths to translate when a route reaches them. The rest are 1 saved
  vector, 2 null slots and 19 computed operands.

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
     between speech, music and effects is an explicit policy. Status: X-Wing's `sb_play.c`
     on voice 3, which the FM re-hoster gives up while a block plays; the effects take
     voices from 0 up ([amiga-arch.md](amiga-arch.md) "Audio", `make test-amiga-speech`).
3. Input: the key map, mouse and joystick from SWOTL; WC2's own joystick calibration runs.
   - Status (1, 3): `amiga/play_walk.sh` flies m4's route from generated code with the
     keyboard, WC2's calibration (Ctrl+J) and the proportional stick (`WC2_PLAY_OK`: 155
     flight frames, 122 after the calibration; without Ctrl+J it fails). Held Esc, repeated
     until each next screen's file opens, skips the opening, the intro and the briefing:
     flight at field 3,171 instead of about 88,300 (MEASURED), about 2 minutes at the
     emulator's maximum speed. The personnel screen takes [C]reate only from a press first
     seen at every other input poll, so the smoke repeats Shift+C until the name prompt
     waits (`w:shift+c`, [amiga-arch.md](amiga-arch.md) "Input"): 9 of 9 runs, four at a
     time (MEASURED 2026-11-23).
4. Memory: measure code, guest RAM and EMS pages for the Fast RAM requirement; Chip holds
   bitmaps, copper lists, audio only.
   - Status: measured ([feasibility.md](feasibility.md) "Memory"): 4.51 MB of reserved Fast
     blocks (program 2.28 MB, guest RAM and the 64-page EMS store 2.16 MB, guest stack) in
     the slave's 5.44 MiB, 0.5 MB left in flight; Chip 0.42 MB left. 8 MiB of Fast RAM
     runs with and without WHDLoad, 4 MiB with neither (D1).

Status: P6b done (2026-11-23).

### P7. Performance (gate 7)

Gate 7 ([phases.md](phases.md)): profiled on the target; optimizations in the translator
(with its runtime and platform) or the G3 table (`annotations/hle.csv`) only; all relevant
fidelity gates green.
Rules and method: [speed-plan.md](speed-plan.md) §2–§6, [perf-method.md](perf-method.md).
X-Wing's speed phase (its P8, from X-Wing `0d20bcd`) runs on the same Borland code a step
ahead; each instrument starts from its commit. Code shared with PC WC1, and the Amiga CD32
WC1 with the owner's improvements to it, enter at P7.3, P7.10 and P7.11 (the owner's plan,
2026-10-28; part of this phase since 2026-11-23).

**Where it stands** (MEASURED, P7.3, [speed-plan.md](speed-plan.md) §1 and §9). On the
50 MHz 68030 model the game visits its flight frame label every 160 ms and draws every
other visit: a picture every 280 ms in quiet flight, 300 ms in the Nav 1 fight, against the
bar's 100 ms (D16: the original's correct game speed; its default limiter gives 66.7 ms). A fight visit (167 ms): EMS page
copies and maps 41 ms (48 16 KB copies), generated code 49 ms (10.8 cycles an x86
instruction; `TM.DRV` and `SUPERTM.DRV` 22), present 24 ms (half of it the palette, rebuilt
every frame), the c2p about 18 ms, PIT and port I/O 17 ms, the field wait 8 ms. No retrace
spin and no limiter wait in flight. SWOTL's system steps are in: the slave's CACHE, guest RAM
in Fast, changed-row c2p (P6b).

**The inspiration: the CD32 WC1.** The same engine family in native 68k, measured in FS-UAE
by the Wing Commander project (its `docs/internals.md`: "Native speed/range anchor",
"Representative flight costs", "Phase 11b rendering costs: D1"):

- 14 MHz 68EC020 (the WHDLoad version on an A1200: a software c2p in place of the CD32's
  Akiko): flight at 10.2 pictures a second (98 ms), 65% of it c2p, 12–13% maths, 8% drawing.
- 50 MHz 68030: its limiter's cap, 25 a second (40 ms). With the owner's patches it shows one
  picture every PAL field in the Nav 1 fight (49.9 a second, 47.5 in a held turn): under a
  field (20 ms) of work a picture (composition 3.8 ms, HUD 2.8, geometry 1.9, conversion
  2.2).

WC2 keeps its own limiter (game logic): a minimum frame duration, 4/60 s by default and
1–19 ticks with Alt+keypad +/− (speed-plan §1). Its world moves one fixed step a frame, so the
frame rate is the game speed: 200 kps is true at 10 frames a second, and the default 15 fps
is 1.5× fast (speed-plan §1 "World rate"). The CD32's figure is a cost a frame: 40 ms is 3.7×
below today's quiet flight, 20 ms 7.4×. Under 66.7 ms the gain shows as the default rate held
in heavier scenes and on slower machines (68030 boards from 25 MHz, the 25 MHz 68040), or as
a higher rate when the player shortens the frame duration. A WC2 "Enhanced framerate" (world
time decoupled from the frame, as in the Wing Commander slave) changes game logic: an owner
decision, not this plan.

**Where the time can come from** (MEASURED shares, P7.3; the savings are INFERRED until each
step's meter and frames): the EMS model's page copies (a quarter of a visit; X-Wing's
steps 6 and 7, the guard cache and the cache over runs of frame pages, `b5dda4c`,
`b9ebd7b`); the present (the palette rebuilt every frame, the c2p); the runtime's
per-access costs (PIT counts at 0.44 ms each, port calls); the second INT 33h read's field
wait; then generated code (a third) and native routines for the 3D maths module and the
sprite drivers, where WC1 helps most. Every second visit drawing nothing doubles the
picture time: cutting a visit's cost to 100 ms is the bar's first half (INFERRED: the
game drops a late frame's drawing).

Steps: each is one commit or a short series with its meter and frames figures, the biggest
priced win first once the instruments exist (X-Wing's order). Below about 5% the frames
fixture cannot resolve a step and the meter decides.

1. **References current.** Done 2026-11-23: one `--stale-polls` pass on m1b, m2, m3, m5 and
   m6 found no problem besides the stale poll points, the five were re-recorded once, and
   `make test-host` passes m1–m6 on them. The meter's runs are lockstep checks, so its
   windows need current references.
2. **Instruments** (C5), from X-Wing `0d20bcd`. Done 2026-11-24
   ([perf-method.md](perf-method.md)): `tools/cost_meter.py` on the lockstep check with
   X-Wing's block hook, windows m4 (the launch), m5f (the Nav 1 fight, a milestone for it:
   m5's route to the first autopilot, 49 frames drawing 8 objects or more), m2's intro and
   m3's pilot-file screen; `tools/cost_model.json` refit on the 68030 model's fight capture;
   the frames fixtures `tools/perf_flight.py` (quiet flight, the fight) on `KEYS` steps
   counted in presents (`nN`), which replace SWOTL's `perf_frames`, `perf_flyby`,
   `bench_frames`, `bench_palette` and `frame_pace`; the FS-UAE build pinned. The fight's
   window found a site to sync (`irq-sync.csv` `WC2.EXE+068B8`), for which every host
   reference was re-recorded once, and DOS's saved SS:SP after a file's write stamp
   ([upstream.md](upstream.md) "P7.2").
3. **Baseline and hot list** (W1, W2). Done 2026-11-25 ([speed-plan.md](speed-plan.md) §1
   and §9, [feasibility.md](feasibility.md) "Combat frame cost"): both frames scenes
   profiled on the 68030 model with their call trees and x86 forms, the waits, the rows
   marked (`host_census.py --vram` on m5f, 50 frames: 178–192 of 200 rows written a frame, median 180; 31.6 KB a frame, 88% of it `SUPERTM.DRV+074BE`), each hot routine's PC WC1 counterpart
   (`tools/wc1_counterparts.py` on `make compare`). The 68040's frame intervals are dropped
   from this step (owner, 2026-11-25: profile the 68030 and fix what it shows; open-work 38
   keeps the 68040 fixture's stall). Tool fixes on the way: `host_census.py` on the meter's
   run and window (`cost_meter.windowed`), `lowering_cost.py`'s far-call returns and IRET
   resumes ([upstream.md](upstream.md) "P7.3").
4. **The bar** (owner, from P7.3's numbers). Done 2026-11-25: B1 ([design.md](design.md) D16).
   The tiers proposed on the 50 MHz 68030 model:
   - B1: as proposed 66.7 ms (15 fps), set by the owner at 100 ms (10 fps, the correct game
     speed) in quiet flight and the median Nav 1 fight frame (2.8–3.0× from 280–300 ms a
     drawn frame, MEASURED);
   - B2: the same at the fight's p90 and in a heavier fight, and B1 on the 25 MHz 68040
     (about 3×);
   - B3, the CD32's: 40 ms of work a flight frame, its original rate on the same machine
     (4× a visit's 154–167 ms, MEASURED).
5. **Waits** (runtime).
   - The 3DAh retrace spin: not in flight (P7.3: no `plat_vga_status` in either profile);
     the intro and menus spin (P5.4: 28.4% of the intro). 3DAh follows the 50 Hz PAL beam,
     so a wait lasts up to 20 ms where the VGA's 70 Hz retrace ends it within 14.3 ms.
   - The field wait in `rt_video_frame` (P7.3: 7.7–8.1 ms a visit, MEASURED): INT 33h is
     called twice a visit, and the second, the position read `WC2.EXE+108B8` in the field
     of the pointer hook's poll, waited for the next field (MEASURED, P7.5 W1); since W1 only
     a poll ending a drawn frame waits (speed-plan §1).
   - The present's waits (the frames fixture's profile). If the present blocks, the Wing Commander slave's
     queued buffers (`release_buffer.s`: the renderer waits only to reuse a buffer not yet
     shown; 6–7 ms a picture there).
   - The limiter passes at once when a frame is late (P7.3: `WC2.EXE+10636` 0.38% of the fight, MEASURED).
6. **Runtime access costs.**
   - The EMS model's page copies (P7.3: 37–41 ms a visit, 48 16 KB copies from INT 67h maps
     and segment loads): X-Wing's cache over runs of frame pages (`b9ebd7b`) and inline guard
     hit (`b5dda4c`) start here.
   - The EMS guard's one-entry cache with the IRQ0 hold (X-Wing `4c50051`: its meter −10%,
     360 → 320 ms a frame); WC2's generated code has 2,253 guard calls (`jsr rt_ems_es`).
   - The port read path (364 cycles a read): constant-port sites to direct calls.
   - The PIT counter reads.

   Controls: `ems_guard_problems` and its sabotages, from X-Wing.
7. **c2p** (platform). If flight rewrites rows whose bytes do not change (P7.3), the Wing
   Commander slave's changed-block converter (`flight_render.s`, the owner's code):
   - 32-pixel blocks inside the marked rows, compared with a history per planar buffer;
   - only changed blocks converted, through a Kalms 030 specialisation;
   - there −80% of conversion on the 68030 (15.5 → 3.1 ms).

   It revisits SWOTL's S1 (a frame compare, rejected before it was built, speed-plan §10),
   so it needs the owner's OK with the price. The history is 2 × 64,000 bytes of Fast; 0.5 MB
   is free in flight. Kalms 030 or 040 per CPU, as that slave measured (its D5).
   - Status: done (P7.7 C1, D19, speed-plan §1): 1.7% of the marked blocks change in the
     fight window (MEASURED), conversion 17.6% → 0.8% of the profile.
8. **Translator** (the meter accepts, speed-plan §3):
   - flag liveness (open-work 11);
   - the profile-chosen annotations (`align`, `bp-regions`, `outline`, `seg-repeat`)
     regenerated from the flight windows;
   - the forms `lowering_cost.py` ranks in `SUPERTM.DRV` and `TM.DRV`;
   - X-Wing's string and index steps where WC2's profile shows them (the REPE CMPSW restart,
     short-count REP STOSW and MOVSW, the reversed index reused);
   - overlay calls and residency checks in flight.
9. **Checkpoint.** Frames on the 68030 and 68040 models against the bar; the native
   candidates re-ranked on the new profile.
10. **WC1 lineage on the Amiga** (W3; desk work beside 5–8). A cross-reference
    (`docs/wc1-cross-reference.md`, as SWOTL's `docs/tfh-cross-reference.md`) matches each
    hot WC2 routine to its PC WC1 counterpart and to the CD32 WC1 routine by behaviour,
    constants, tables and strings. Anchors:
    - `SUPERTM.DRV` (scaled and rotated sprites, identical in PC WC1) ↔ the CD32's object
      dispatch `E:2ca3e` and image drawing (plain `E:2efe8`, scaled `E:2ec98`, rotated
      `E:2d746`);
    - the 3D maths ↔ `E:2a9d4–2cbd8`, geometry `E:2a086`, orientation `E:2bb30`;
    - view clear `E:31cd6`, cockpit composition `E:2cf0a`, the HUD `E:46e6`, glyphs
      `E:2fd6a`;
    - the method's proof: PC WC1's flight rates at `4896` are the CD32's `E:7a4` term for term
      (Wing Commander project, "The PC's signs").

    The CD32's cost per routine on the same 68030 model (its D1 table) is the expected cost
    of a native one. That game is a Manx Aztec C build with hand-written assembly, reading
    big-endian repacked resources (`.pkt`, TM6 images) where WC2 reads PC formats in
    byte-reversed guest RAM. So the correspondence is algorithmic, not drop-in.
11. **Native routines** (W4–W6), each with the owner's authorization (S1–S9,
    [native-compute.md](native-compute.md), an `annotations/hle.csv` row with reason and
    oracle), one commit each with meter and frames A/B.
    - Sources (SWOTL U0). Original code, PC or CD32, is reference only and never enters the
      port. Adaptable: the owner's Wing Commander slave code (the changed-block converter,
      `view_regions.s`'s MOVEM clears and span copies, the queued buffers), Kalms'
      public-domain c2p, and new 68020 code written against WC2's x86, which stays the
      oracle (its constants, rounding, branch order and tables).
    - Price (W5): the own-cost ceiling at zero native cost (SWOTL B3) and the CD32
      counterpart's measured cost, before asking.
    - Candidates (INFERRED until P7.3):
      - `SUPERTM.DRV`'s drawing: about 0.4 ms an object on the 12000-cycle reference, so the
        fight's cost;
      - the transform and projection (SWOTL's N1, F3a, F3b: −4.7%, −1.5%, −1.6% of its
        meter);
      - `TM.DRV`'s blits and fills (one sprite routine is 25.3% of the intro);
      - the view clear and composition.
12. **Machines and gate 7.**
    - The 68040 and 68060 models.
    - A frame recorder for the owner's real hardware (the Wing Commander slave's
      `frame_stats.s`: field-stamped events saved with `resload_SaveFile`).
    - Gate 7: the bar met on the frames fixtures; host lockstep m1–m6 and the replay on the
      current references; the sabotages. The release matrix (P8.3) is re-run for the next
      release.

### P8. Package (gate 8)

1. WHDLoad kickemu slave, Installer 43 script, ReadMe, icons and release audits from
   SWOTL. Memory comes from a MemFree measurement, as `docs/whdload.md` there does.
   - Status: `whdload/`, `release/`, the release tools ([whdload.md](whdload.md),
     [release.md](release.md)); the slave's four FS-UAE checks, the archive audit and the
     Installer's nine modes pass (MEASURED 2026-11-19).
2. Installer from the 7 disks (D7). A helper unpacks `WC2.LZC` and `SPEECH.S00` (the codecs in
   `tools/origin_pak.py`, checked by `make inspect`), unless P2 shows the game reads them packed. It checks each
   disk's hash, writes to staging and replaces `data/` only on success, as SWOTL's
   `tools/install-data/` does.
   - Status: `tools/install-data/` (WC2InstallData) installs by the original's `INSTALL.DAT`
     from the images or the disks' files, each disk file and each file written checked by
     SHA-256; byte-identical to the original installer's tree on the host and on the
     emulated 68020 (`make test-install-data`, MEASURED 2026-11-19).
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

## Sibling: X-Wing

X-Wing copied the same SWOTL commit for Borland 80186 code and is a phase ahead (gate 6 at
X-Wing `b7c8a8c`); WC2 took its front end, lowering, host lockstep and Amiga replay to its
P5 (`2de0225`, [upstream.md](upstream.md) "From X-Wing"). X-Wing keeps the mirror table
("Sibling: Wing Commander 2" in its `docs/port-plan.md`). Before building a runtime
surface, a test harness feature or a translator feature, check both tables and start from
the other port's commit. Hashes as of X-Wing `0eec632`.

| Work | Where it is | Use here |
|---|---|---|
| DOS: AH=2Fh (`002ff01`; built twice, WC2 `737004c` adds the DOSBox-X test), AH=0Eh (`32bbd04`), find-first of directories and dot entries (`e952d8b`), free of a segment with no MCB is error 9 (`9958487`); INT 16h enhanced keys (`9ee47eb`) | X-Wing P6 | take each when a WC2 trace shows the call |
| An interrupt handler's far call through a pointer into other code (`irq-hooks.csv`, hooked entries and bounds) in `translator/irq.py`, the I3 monitor's request counting (`6e1e46b`); interrupt-level sync rows for flights (`d761b39`) | X-Wing P6 | WC2's INT 15h handler's call through DS:D150h needed none of it: one traced target (indirect.csv). `irq-stops.csv` is taken (WC2 P6, `git log -S rt_key_hook`). Compare with WC2's `irq.py` (`66e6de5`, the hold) before either changes it |
| Host lockstep: flight logs in bounded memory (`9c59569`), parallel runs from the entry (`2b047e5`), a run that reaches its timeout says so (`e556fcb`) | X-Wing P6 | open-work 13–17 |
| Service registers and RAM from dead stack may differ, the replay's exempt table (`40030a3`, `3dca119`, `892b8d5`) | X-Wing P6, X-Wing owner decisions 2026-11-09 and 2026-11-10 | open-work 15–17, after an owner decision here |
| Code the traces missed translated, indirect-coverage review (`423b2dd`, `33d685a`) | X-Wing P6 | open-work 17 |
| Amiga replay in the host run's modes for every milestone (`c737385`), the shown frame at a mid-frame label (`a3f71a9`), the program on `C:` (`b2c1c29`) | X-Wing P6 | open-work 17, 18 |
| Flag save/restore pairs in the Borland overlay manager (`annotations/flags.csv`, 4 rows, DERIVED) | X-Wing P2–P4 | open-work 11: the same overlay manager, so its rows probably map onto WC2's sites (INFERRED until compared) |
| Copy-free EMS (`bfaebe3`, `c31004f`), the IRQ footprint for several handlers with the atomic hold (`66e6de5`), the smoke in SWOTL's form (`737004c`) | WC2 P5 | X-Wing's open-work 2 starts from the EMS model |
| SB DSP (14h, 40h, D1h), DMA channel 1 and IRQ 7 for host lockstep: `ports.c`, `plat_dsp_status` and `plat_sb_block`, the DSP status replay, the block oracle from `sound.csv`, INT 0Fh runs in the IRQ monitor, sabotages `sb-block`, `sb-irq`, `dsp-status`; `irq.hold_span` (a far call through a handler-written pointer held over its loads); the monitor's EMS copy rule | WC2 P6 (`git log -S plat_sb_block`) | to X-Wing (its P10) |
| A guest INT 15h keyboard intercept called from the BIOS INT 09h model (`rt_key_hook`, `rt_bios_int15`, INT 16h AH=00h/01h with DOSBox-X's enhanced-key rule); the handler set's per-handler entry state (`irq.ENTRY`) and `irq-stops.csv` in WC2's emitter; the intercept oracle and sabotages `key-hook`, `hook-cf`, `int16-zf`; the monitor's per-site main-access faults | WC2 P6 (`git log -S rt_key_hook`) | to X-Wing if its game hooks INT 15h |
| Interrupts inside DOS's console wait: the reference's poll gate opens in the INT 28h idle HLT (`dosbox-x-wc2-idle-irq.patch`, irq rows at module `-` with the stack), `rt_idle` replays them in sync builds (X-Wing's sync `rt_key_wait` stops instead), sabotages `idle`, `idle-stack`; undefined flags that reach a register masked per site (`annotations/undefined-flags.csv`, owner 2026-11-13) | WC2 P6 (`git log -S rt_idle`) | to X-Wing and SWOTL (its open-work 24) when a wait or an undefined flag shows |
| `rt_ems_touch` with an access outside the frame exposes no page (found by X-Wing in the copy-free EMS model; WC2 open-work 21 with a `test_ems` case) | WC2 P6 | X-Wing: its EMS model if it kept the clamp (not checked here) |
| The divide lowering keeps the stubs queued before its divide-error stub (found by X-Wing; WC2 open-work 22, boundary cases through ES) | WC2 P6 | X-Wing: its `lower.py` if it has the same assignment (not checked here) |
| Host lockstep in C-filtered memory hooks (`tests/memwatch.c`), service compare as logged and a watchdog (first problem, stall) | WC2 P6 (`git log -S memwatch`) | to X-Wing: its host runs spend most of their time in the same Python hooks (INFERRED) |
| Indirect-coverage review generated by a tool (`tools/indirect_review.py`: snapshot values of constant slots against the dispatch table, a control on the executed sites); Amiga replay with SB blocks and DOS's idle wait | WC2 P6 (`git log -S indirect_review`) | to X-Wing: its review (`33d685a`) is by hand; its replay has no idle wait (INFERRED) |
| Trace corpus includes the host references (`wc2_model.CORPUS`); typematic repeats and the BIOS ROM in host lockstep | WC2 P6 (`git log -S typematic`) | to X-Wing: its sweep corpus and key script have the same gaps when a key is held past DOSBox-X's typematic delay or code samples ROM (INFERRED) |
| Amiga display and input | WC2 (P6b.1, P6b.3: SWOTL's display and input, the flight smoke with the game's calibration; `git log -S driver-slots`) | to X-Wing: the driver loader's slots in the driver-call bracket, the key script's `tN`, `alt+`/`ctrl+` and ReadArgs quoting |
| Music on Paula through SWOTL's FM re-hoster with additive patches and `fm_check` on vibrato notes (`ba28410`); FM effects captured from the driver and prerendered (`0eda68f`, owner decision 2026-11-15, HLE `sfx_prerender`); effects played from the driver's players (`269828b`, `fx_play.c`, HLE `sfx_start`) | X-Wing P7 | taken (owner decisions D13, D15, [upstream.md](upstream.md) rows "D13", "D15"): two HLE rows (`sfx_init`, the capture at the game's sound init before the first scene; `sfx_start`, the start count); `t-amiga-sfx` checks each play and runs the host check; WC2's two render fixes, the counted-start rule and the input-keyed cache go back |
| SB speech on Paula: `sb_play.c` on voice 3 from the DSP model's blocks, the block's end from the DSP's own time on a CIA-B timer | X-Wing P10 (`baea334`) | taken ([upstream.md](upstream.md)): the player and its test; WC2 keeps its block timer and retries (no pause in WC2's DSP model); the follow-on of back-to-back blocks without a restart goes back |
| The meter on the lockstep check with a C block hook, the cost model refit on the 68030 model, a frames fixture on `KEYS` steps counted in presents (`0d20bcd`) | X-Wing P8 step 1 | taken at P7.2 ([upstream.md](upstream.md)); to X-Wing: the meter's own-host hook (the check's controls build hosts too) and the cold-section return labels in `profile_report.INSIDE` if its emitter has them |
| EMS frame through DS guarded in listed code (`annotations/ems-ds.csv`, `rt_ems_ds`, the exit check `rt_ems_ds_leave`), a string's byte range in the guard, lods/xlat with ES: guarded, the store reversed (`5f720a2`) | X-Wing P6 | taken at P7.6 (D17) on WC2's alias model; a range covering a whole driver module admits its indirect near transfers (WC2's addition, to X-Wing if its drivers need it); X-Wing's `keep` rows and its interrupt-level stop not taken: WC2's INT 08h handler calls the EMS resolver; its `restore` rows taken at P7.6 E5 with a runtime condition (`rt_ems_restore`: inside the interrupt's hold, the interrupted DS) and a check of the run to the exit (`emit.py ems_restore_problem`; to X-Wing: its rows are reasoned, not checked) |
| Consecutive timer ticks counted onto one interrupt ring entry (`2029582`: a service holding the ticks past the 32-entry ring stopped the game) | X-Wing runtime | not yet here: check WC2's longest tick hold before P7.5 |

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
