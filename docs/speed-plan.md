# Speed plan (phase 7)

> Copied from Secret Weapons of Luftwaffe `658fc60` ([upstream.md](upstream.md)). Its rules
> and methods apply here; §1 and §9 are WC2's (P7.3); the other sections' addresses,
> measurements, step history and decisions are SWOTL's, kept for reference until a WC2
> phase re-derives them.

Rules, measurement and work order for all speed work on the A1200 build.
An implementing agent follows it literally, one step at a time. Step
details (prices, coverage, plants, FS-UAE checks) are in the step's commit
message (`git log --grep '^R[0-9]'`); round 1 (T1–T15) at `781975e`, the
sections of R16–R34 in this file at `e2cedc6`.
Method background: [perf-method.md](perf-method.md). Open-work item: 14b.

## 1. Target and state

WC2's own (P7.3, 2026-11-25, MEASURED unless marked); SWOTL's §1 history is at its
`658fc60`. Method and instruments: [perf-method.md](perf-method.md); the numbers' files are
`tools/perf_flight.py` runs on the image at `1367440` plus P7.3's tool fixes.

- **Bar** ([design.md](design.md) D16, B1): a drawn frame every 66.7 ms in quiet flight and
  at the median Nav 1 fight frame on the 50 MHz 68030 model. 66.7 ms is the original's
  default frame duration: `WC2.EXE+10642` sets a minimum of `DS:00B6` ticks of its 60 Hz
  timer at each frame start, which `+10636` waits out at the end; `DS:00B6` starts at 4
  and Alt+keypad +/− changes it from 1 to 19 ("%d/60th SEC FRAME DURATION." with
  `DS:00B6`+1, so the default reads 5/60; MEASURED by reading, 4 ticks a frame MEASURED). At
  12000 cycles every flight frame waits in it ([feasibility.md](feasibility.md)
  "Combat frame cost"). Below the setting the game runs as fast as the machine allows.
- **World rate:** the world moves one fixed step a frame, WC1's units, so game speed is the
  frame rate. At m4 (SET 200, KPS 199 on the reference's screen) the player's velocity is
  (2940, 0, 4200) a visit of `R_0813C`, magnitude 5126.75 in 1/256 km (the nav range is
  that distance >> 8, `WC2.EXE+092D8`): 20.03 km a frame. Each visit's position change is
  the previous visit's velocity, at 4 ticks a visit throughout (MEASURED, DGROUP at 50
  visits of the m4 window). No reader of the tick counters `DS:D130`/`D134` in the motion
  path (INFERRED from the readers' list: input repeat, timed callbacks, the limiter). So
  200 kps is true at 10 frames a second (100 ms, `DS:00B6` = 6, read as 7/60), as in WC1 (the Wing Commander
  project's `docs/internals.md`, "PC speed calibration": 5120 at 200 kps). The default 15
  fps runs the world 1.5× fast. The nav range readout uses the 3D maths module's
  approximate magnitude (`0E9B:040D`, WC1 `R:077E:0461`). With Nav 1 31° off the nose it
  fell 23.33 km a frame, so it calibrates only when flying straight at the point.
- **Where it stands** (50 MHz 68030 model, the frames fixtures, 60 visits of the flight
  frame label `R_0813C`, P7.2's two runs and P7.3's third, each with a 100-field profile):

  | Scene | A visit to `R_0813C` | Between frames that drew | Objects a drawn frame |
  |---|---|---|---|
  | quiet flight | 160 ms median (mean 143.7) | 280 ms median (means 284.8, 285.5, 285.5) | 4 |
  | the Nav 1 fight | 160 ms median (mean 153.6) | 300 ms median (means 300.0, 303.6, 306.2) | 11–13 |

  Every other visit draws no object on the model, every visit in the reference: the
  picture rate is the drawn frames' (3.3–3.6 a second against 15). That the game drops a
  late frame's drawing is INFERRED.
- **Meter** (the host lockstep windows, model cycles; perf-method "Baseline"): m4 424.9 M
  over 49 frames (7.14 M a frame without poll tests), m5f 446.0 M (7.68 M).

Where a visit's time goes (the profiles' cycle shares over the window's visits: fight 12
visits in 99 fields, 166.7 ms each; quiet 13, 153.8 ms; `tools/profile_tree.py` self
costs unless inclusive is said):

| Cost | Fight | Quiet | What |
|---|---:|---:|---|
| EMS page copies and mapping | 40.9 ms (24.5%) | 36.8 ms (23.9%) | `copy` 21.2%, 48 16 KB page copies a visit (0.51 ms each), from INT 67h maps (`rt_int67` 5.7% inclusive) and segment loads that expose a page (`rt_ems_seg` 10.7% inclusive, 188 a visit); `src/runtime/ems.c` |
| generated guest code | 48.8 ms (29.3%) | 48.5 ms (31.5%) | 226 K x86 instructions a visit, 10.8 cycle units each (2.5 68k instructions): `WC2.EXE` 9.0, `STRAX.DRV` 11.7, `TM.DRV` 21.9, `SUPERTM.DRV` 22.6 (`lowering_cost.py`, `profile_report.py`) |
| present (inclusive) | 23.8 ms (14.3%) | 23.8 ms (15.5%) | the palette 11.6 ms (`plat_palette`: the DAC is written every frame, so every present rebuilds 256 colours and the copper list), the copy and c2p call 9.6 ms (`plat_present`), `present` itself 2.6 ms |
| other hunks: the c2p | 17.6 ms (10.5%) | 18.7 ms (12.2%) | the c2p (`c2p1x1_8_c5_bm`, the only code in its own section, MEASURED by the map) and OS calls; that it is mostly the c2p is INFERRED. The game writes 178–192 of the 200 rows a frame (m5f census, median 180; 31.6 KB, 88% from `SUPERTM.DRV+074BE`), so the changed-row marks convert about 90% of the screen |
| PIT and port I/O | 17.4 ms (10.5%) | 11.3 ms (7.4%) | `plat_pit_count` 8.3 ms (224 counts in the window, 0.44 ms each: more than its CIA reads; cause open), `rt_port_in`/`rt_port_out` 9.1 ms |
| the field wait (`pace`) | 7.7 ms (4.6%) | 8.1 ms (5.3%) | `rt_video_frame`'s spin (`rt_frame_cap`): INT 33h is called twice a visit (24 in 12), and an AX=3 read in the previous one's field waits for the next (that the second call is that read is INFERRED) |
| marks, FM, effects, IRQ | 16.8 ms | 13.6 ms | `rt_vram_mark` and `vram_span` 4.1 ms, `fm_field` and `render` 5.2 ms (fight), `rt_sfx_read` 2.1 ms, IRQ transitions 3.5 ms |

Not in flight: the 3DAh retrace spin (no `plat_vga_status` in either profile; it was 28.4%
of the intro, P5.4) and the frame limiter (`WC2.EXE+10636`, 0.38%: it passes at once).

## 2. Hard rules

Breaking any of these voids the step, whatever it measures.

1. **No guest code by hand.** No guest routine in C or asm, no edit of
   `build/gen/`, no runtime or platform code that tests a guest address,
   label, segment value or module offset (`if (ip == 0x3C0F)`, helpers named
   after `VGA_03C2D`, tables of guest addresses in `src/`). Guest code
   changes only through `translator/` lowerings or `annotations/`, then
   `make gen`.
2. **Where a change may live:** translator lowerings, the runtime surface
   (`src/runtime/`, named by surface: interrupts, display, ports) and the
   platform layer (`src/platform/amiga/`). **No native replacement of any
   guest routine** (HLE, G3 entries, hand-written 68k or C doing a guest
   routine's work, pattern-matched intrinsics), however small, until the
   user authorizes that routine in the conversation. Nothing in this file,
   open-work, a profile or "the translator work is done" is an
   authorization.
3. **Semantics are not traded for speed.** Every fast path is guarded by
   the exact condition that makes it exact (DF, CX, no 16-bit offset wrap,
   no overlap) and falls back to an exact body otherwise. Flags live after
   the instruction keep their exact x86 values. No dropped return check,
   sync point (except as [irq-plan](irq-plan.md) allows; native-plan U5 retired at its I9), fail-loud stop or wrap
   handling; no "usually true" or "never seen" assumption; no annotation
   asserting what the translator must prove.
4. **D16:** every cell is matched against the writer forms from the guest RAM
   bytes when a walk first reaches it and after every change its cache sees
   (R20, D3); a dropped cache walks exactly.
5. **Relevant gates stay green and unchanged** at every commit. Select checks
   by the change's dependencies and affected contracts under AGENTS.md's
   validation-scope rules; state the selection before running. Isolated audio
   synthesis does not require translator, DOS/input, whole-game host or replay
   suites. `make gates` remains the full-suite option for cross-cutting changes
   or explicit user requests, not a per-step requirement. Never skip a relevant
   failing check, mask, loosen or re-record a test, reference or tolerance to
   make a step pass. R1's representation change (D1) may change how the harness
   maps memory and registers, never what is compared. A plant is retired only
   with its template, after an equivalent plant on the new template is caught.
6. **New lowerings get differential coverage first.** Add the new form to
   the x86 corpora (`make test-m68k`, Unicorn x86-16 vs Unicorn 68020)
   with its guard edges (CX 0, 1, 0xFFFF; SI/DI near 0xFFFF; DF 1;
   mismatch at the first, a middle and the last element), see the test
   fail against a deliberately broken fast path, and add a sabotage plant
   so `make test-sabotage` fails if the guard is removed.
7. **Never compare the port with itself as correctness evidence.** Oracles:
   Unicorn x86, the host run against DOSBox references, the reference
   framebuffer. The display checks (host run: guest stores to A0000h vs the
   present's rectangles; `amiga/display_audit.gdb`: shown bitplanes vs guest
   A0000h) check the presentation, not the game; run the audit after any
   display change.
8. **No unmeasured claims.** Numbers in commits and docs come from runs in
   the same session, measured as §4 says.
9. **Out of bounds** (ask the user first): changing the frame fixture (CPU
   model, Fast RAM, FS-UAE options, fixture, game data and settings, warp
   and speed); presenting a frame before the game publishes it (D9: the
   outermost graphics driver call returns), reading the frame to find
   changes, or skipping published frames other than those between two
   mouse polls (D9 frame boundary, user 2026-10-28); changing the PIT or timer rate
   or the order of interrupt delivery; removing or thinning sync points or
   return checks (exceptions: [irq-plan](irq-plan.md)'s sync points, loop heads in
   native rows and asynchronous IRQ0, user 2026-10-24, RC2/RC3/RC5; native-plan U5
   retired at its I9); shortening the guest's own delay loops
   (SPAZ OPL waits are guest semantics; exception, user 2026-10-24: F9's
   delay loops in O(1) with an exact final state once irq-plan I9 has landed);
   a double buffer or copper display;
   Chip-only memory (19). Exception: the deterministic frame bench (§4,
   user 2026-10-08) posts PIT ticks on a fixed schedule in its own runtime
   mode, as an instrument only.
10. **One step, one commit**, before/after numbers in the message; §1, the §7
    row and `docs/open-work.md` 14b updated in the same commit. Do not start the
    next step on an unproven one.

## 3. Acceptance (D0, user 2026-10-08: any speed or size improvement is welcome)

- Gates green (§2.5).
- **Meter (§4) on the m4 window:** model cycles lower; or equal
  (|Δ| < 0.001%) with a smaller code payload. Report Δ model cycles,
  Δ executed code bytes, Δ data reads/writes, Δ code payload. No minimum gain.
- **Layout and Amiga platform work outside the host meter (D5):** accept
  lower fixed-work 68020 bench cycles, with identical final guest RAM, all relevant
  fidelity gates green and no slowdown. Report the unchanged meter and
  actual code payload; do not infer a frames-fixture gain from the bench.
- **Bench noise (D8):** a bench median at most +0.25% above the base
  (layout-scale; F4's code move gave +0.20%) is noise, not a slowdown,
  when the step is generally faster (meter lower, or the flyby lowers the
  changed work per call) and final guest RAM is identical. Report it; ask
  only above +0.25% or when nothing general improves.
- **Code growth** only with lower model cycles (D2), or lower bench cycles
  for work covered by D5. Stop and ask before
  the payload exceeds 1,325,164 bytes by more than 25% (slave ExpMem margin, [whdload.md](whdload.md) Memory).
- **FS-UAE check** after every third kept step and after any memory-model,
  cell-walk or layout step: a bench run (§4) per arm with a capture; the meter's Δ must have the
  sign of `ab_labels.py`'s mix-adjusted Δ over the changed labels. D5 exempts
  effects the host meter does not represent, not contradictory measurements
  of represented work. If they
  disagree, stop: fix the meter, never tune lowerings to FS-UAE noise.
  Report the bench's frames 4–11 cycles (they include layout effects).
- **Frame-rate claims:** the bench (§4) for build-to-build progress; the
  target itself is the frames fixture (§4, with the interval lists),
  measured at each re-profile. Neither is a per-step gate.

**Stop and ask the user** when: a gate fails for a reason that is not a
plain bug; a step needs any of §2 beyond what was approved; references
need re-recording or an interrupt delivery moves (beyond a U5 row's approved
re-recording); two consecutive steps
are rejected by the meter; meter and FS-UAE disagree on represented work; a step is ambiguous.

**Per step:** price from meter counts (D5: fresh target capture and census);
write the price in a §7 step section before coding (at the commit its
details move to the commit message; the §7 row stays);
coverage first (§2.6; cases appended at the end of corpora, `m68k_blocks`
cases for multi-block changes); implement in `translator/` or
`src/runtime/` or `src/platform/amiga/`; `make gen` if translation inputs changed;
selected gates; meter (D5: bench); keep or revert (revert keeps the
passing new tests; one line in §10); one commit (§2.10); report in a few
lines.

## 4. Measurement

- **Emulator.** `$FSUAE` (`amiga/env.sh`: the shared arm64 `$FSUAE_ARM`
  since 2026-10-24; x86_64 before). Compare FS-UAE numbers from one binary
  only; `ab_runs.py` fingerprints it. Its captures hold absolute PCs
  (`profile_report.hunk_relative`).
- **Frame period (P).** `amiga/perf_frames.gdb` under `amiga/debug.sh`
  (68020, 8 MB Fast): field at each of the first 12 drawn frames of the
  attract demo flight (one gdb stop per frame at the frame loop `R_044E2`).
  P = median of the frame-4…11 intervals × 20 ms. Emulated fields, never
  wall time; the 68020 model (`AMIGA_CPU` unset), never the 68030 for a
  claim; no warp, no `cpu_speed=max`; control = the parent commit, built
  and run in the same session with the same fixture; three runs per arm;
  quote ms per drawn frame. The start field varies run to run (4299, 4334,
  5274 seen: the hard-drive folder completes I/O on host time). Claim a
  frame-rate gain only when the arms' ranges do not overlap; frame times
  fall into trajectory modes (§5.1).
- **Shares.** The same fixture then captures 100 fields
  (`monitor profile` stops at 100) into `tmp/prof/frames.bin`;
  `tools/profile_report.py tmp/prof/frames.bin amiga/out/Swotl.elf
  --objdump m68k-amiga-elf-objdump --count rt_irq --count deliver --count
  plat_present`; per x86 form `tools/lowering_cost.py`. A capture is
  1.1 GB: delete it after the report. Use `lowering_cost.py` semantic guest
  counts for ratios: it excludes helpers
  and recovers zero-code entries using incoming guest control flow. Supply the
  exact generated assembly/IR with `--gen`. Unknown or ambiguous edges fail
  loudly. Older ratios include helper hits and omit zero-code entries;
  `profile_report.py` still reports label-derived counts.
- **Counts.** `tools/host_census.py MILESTONE --strops --vram --labels …`
  (host run, exact, free; never timing) before pricing a loop. Per drawn
  frame (m4): `repe cmpsw` `VGA_03BE9` 19,290 words (the whole view vs the
  previous frame), `rep stosw` `R_0C1CA` 16,075 words, `rep movsw`
  `VGA_03C2D` 151 words to A0000h (median 6 rows).
- **Reference cadence** (DOSBox-X `cycles=fixed 12000`, m4): a drawn frame
  every 9 PIT ticks ≈ 36 ms, ≈ 408K x86 instructions per frame.
- **Meter** (`tools/cost_meter.py`, deterministic): `--out tmp/meter/ARM.json`
  per arm, `--compare A B` for the §3 deltas; also poll tests per class (irq-plan I1); the JSON's `runtime` holds model cycles per runtime symbol (natives against the generated cycles they replace). Weights `tools/cost_model.json`,
  fit at A4 on the `e891ace` bench capture: per code byte 1.038 (0.912 inside
  a loop of ≤ 256 bytes whose back branch was taken in the workload), read
  1.795, write 3.219, taken transfer 5.113 outside such a loop and 1.712 inside,
  word/general mul/div 23.317. Unsigned register long arithmetic uses a separately
  probed total of 4.125025 cycles (no additional fetch/muldiv charge;
  `m68k-optimisation.md`, B3 calibration). R² 0.9224, model −2.25% of measured. U1 selects executed
  back edges; this remains a workload-level cache approximation. The doubling
  plant is caught (419,726 extra instructions, 839,452 extra bytes). The
  per-instruction weight still fits to 0. Recalibrate (`--calibrate CAPTURE
  ELF --write`, then `--plant-check`) at the next re-profile or when the FS-UAE
  check disagrees. `tools/ab_labels.py` serves the FS-UAE check.
- **Bench** (`SWOTL_ARGS=BENCH ./debug.sh "" bench_frames.gdb`, same model, on the
  sync image `make amiga-sync` since irq-plan I8: production has no poll checks and
  refuses `BENCH`; `ab_runs.py` freezes and runs it; runtime.h `rt_bench`): no CIA timer; 9 PIT ticks per 4 runtime services
  (the flight makes 4 per frame, m4 draws a frame every 9 ticks), plus one
  per 8,956 consecutive visits to a poll point in a spin (SPAZ's rate
  calibration gets the reference count 8,956; the demo waits for a tick
  after loading its replay). Every build does the same guest work: demo
  after 1,628 services (reference 261,320), the guest's elapsed ticks 9 per
  frame, frames 0–56 the static opening view (rendered, compared, not
  blitted; the reference's 27 frames at 18 ticks), about 830K guest
  instructions each. Output: field and beam line at frames 0–12, the guest
  RAM at frame 12 (`shasum tmp/bench/ram.bin`; equal to the host run's at
  that frame), a 100-field capture. Two runs: equal RAM hash, frames 4–11
  sums within 2 lines (single frames within 16), window guest
  instructions within 0.02% (measured at its introduction). Not comparable to P
  (different frames and tick rate); compare arms by the frames 4–11 sum.
  Its window (the static opening view) runs no cell walk: the FS-UAE check
  of a walk change uses a frames-fixture capture per arm (cycles per mov
  cell, `move.b d0` executions in the walk).
- **Flyby** (F0, user 2026-10-23): `amiga/perf_flyby.gdb`, five consecutive
  100-field captures from drawn frame 12 of the attract demo (fighters to close
  B-17s); `tools/profile_tree.py` over all five. Supplements the frames fixture
  and bench; runs: `tools/ab_runs.py flyby`.
- **Palette bench (D6).** `SWOTL_ARGS=BENCH ./debug.sh ""
  bench_palette.gdb`, same model and runtime schedule. Measure intervals
  60–67, dump guest RAM at frame 68, then capture 100 fields. Require equal
  final RAM between arms and display publications in the profile. This
  supplements the opening bench and normal frames fixture; neither changes.
- **Stops are free (S0).** Fields from `rt_run_guest` to m1b-logo
  (`VGA_039AD`), 68020: 99–100 with no stop between (3 runs), 99–100 with
  110, 364 and 731 stops (5 runs). `amiga_io_frames` counts the fields
  inside I/O windows (host-timed disk I/O, 7–17 here); the total does not
  move because the guest waits on the PIT.

## 5. Why round 1 stalled (do not repeat)

1. **The per-step measurement could not resolve the steps.** Frame
   intervals fall into trajectory modes (23, 29, 23, 30, … / 28, 24, 34,
   25, … / 30, 26, 36, 27, …); one executable gave run medians 24.5 and
   28.5. Cycles/guest follows the window's instruction mix (14.64–15.45 on
   unchanged or near-unchanged code). T7 and T10–T15 were priced at
   0.0007–0.07% of P, T8 at 0.28%: 10–10,000× below that noise. S5 (cell
   walk 14.1% → 12.0% of CPU) was rejected on the same unresolvable frame time.
2. **Layout noise of the same size.** Moving code changes the cost of
   untouched forms (T8: `jne near` 6.07 → 6.87 cycles; T12: `loop`,
   `shl`). Mix-adjusted per-form A/B from the saved reports (same weights
   for both arms): T3 −0.94%, T4-local −6.24%, T6 −2.19% are real; T7
   +0.26%, T8 +0.51%, T10 +0.23%, T11 −0.14%, T12 +0.72%, T13 +0.50%,
   T4 cross-block −0.63% lie inside ±0.7% layout noise. Their keep/revert
   verdicts were noise, and keeping lucky layouts biased later parents.
3. **Prizes shrank by narrowing.** Each step was confined to block-local
   sites under the unchanged register contract (little-endian memory,
   zero-extended registers, SI/DI in address registers, flags in a memory
   image). That contract is where the cost is (§6): a 19.9% group yielded a
   1.19% candidate, and T10–T15 0.0007–0.07% each.
4. **The 1% threshold** deferred T3/T5 and drove the narrowing. Removed by
   the user (2026-10-08): every speed or size improvement is welcome.
5. **Wrong cost unit.** Steps were priced in 68k instructions; on this
   model the cost is code bytes and data accesses (§6).

## 6. Cost model

Per-PC fit on the replan capture (13,608 non-branch PCs, 5.5M executions):
**cycles ≈ 1.09 × code bytes + 2.27 × data reads + 3.07 × data writes**
(R² 0.83). Outside the 256-byte i-cache a 2-byte register op costs ≈ 2
cycles, 4 bytes ≈ 4, `and.l #$ffff` (6 bytes) ≈ 6. Inside cached loops
bytes are nearly free. Price and accept in executed bytes, data accesses
and taken branches, never in instruction counts. FS-UAE is the user's
instrument; a real 68020 may weigh these differently. The meter's current
weights: §4.

The meter's runtime is the host run's (the reference's interrupts
replayed); the frames capture adds the CIA timer at its own rate.

## 7. Step index

Kept steps, one row each (names cited in code comments; M1 is the meter and label A/B,
M2 the frame bench, §4). The generated-code
contract they produce is in [translator-design.md](translator-design.md);
details in each commit. Δ is the meter's at the step (weights of its time).

| Step | Change | Where | Meter Δ |
|---|---|---|---:|
| T3, T4-local, T6, T10, T11 | round 1: block-local byte order, carry in X, masks, byte copies | `lower.py`, `flags.py` | (frames) |
| T8 | AH-class register writes as one `bfins` | `lower.py` | −0.242% |
| T7 | word MUL/DIV high results only where live | `lower.py` | −0.005% |
| R1a | runtime guest-memory accessors | `src/runtime/` | −0.0001% |
| R1b | reversed guest memory, biased segment bases, mirrored SP/BP (D1) | `lower.py`, runtime, harness | −1.916% |
| R1d | word memory operands folded into the 68k op | `lower.py` | −1.231% |
| R2 | poll point falls through; call in an out-of-line stub | `emit.py` | −1.029% |
| R3a | adc/sbb skip the Z preset where ZF is dead | `lower.py` | −0.991% |
| R3b | flags reach a reader across plain instructions | `flags.py` | −0.188% |
| R4 | guest registers' upper words undefined; zero-extend where consumed | `lower.py`, `compact.py` | −2.646% |
| R5 | return checks to local trampolines; ret pops keep upper words; `rt_lookup` cache per CS:IP | `emit.py`, `lower.py`, runtime | −2.036% |
| R6 | guarded copies address `[bp+d]` directly (D2) | `region.py`, `tools/bp_regions.py` | −1.213% |
| R7 | cell walk runs mov cells as a counted run (matching kept) | `smc.py` | −9.037% |
| R8 | hot branch targets aligned by pads that never run | `tools/align_targets.py`, `gen.pad` | 0 (bench −0.30%) |
| R9 | mul/div without DX masks; operands straight into `mulu` | `lower.py` | −1.615% |
| R10 | runtime: table flag helpers, one-move guest words, OPL/EOI in `rt_out8` | `support.py`, `src/runtime/` | −0.299% |
| R11 | re-profile, meter recalibrated | `tools/cost_model.json` | — |
| R12 | REPE CMPSW and REP STOSW two words per iteration | `lower.py` | −5.207% |
| R13 | repeated index formation or CS base in a run dropped | `reuse.py` | −0.354% |
| R14a–d, g, i | high-byte idioms, CCR through jump chains, memory compares without `lea`, SI/DI self-test, cold divide errors | `lower.py`, `flags.py`, `emit.py` | −2.600% |
| R14e | dispatch rows say near-only or far; returns per row kind | `emit.py`, runtime | −0.140% |
| R14f | displacements folded into d8 under no-wrap guards | `reuse.py` | −0.288% |
| R15 | interrupt delivery in one runtime round trip | `src/runtime/` | −0.092% |
| R16 | alignment convergence, fresh targets and profiler/meter repair | translator, tools | 0 (bench −1.18%, D5) |
| R17 | palette validity per physical back buffer | Amiga platform | outside meter (later bench −2.81–3.61%, D5/D6) |
| R18 | TF/IF/DF extraction with register bitfields; meter operand and A/B selection fixes | `support.py`, tools | −0.0126% |
| R20 | cell cache: cells matched once, runs of destinations stored by longs, exact invalidation (D3) | `smc.py`, `lower.py`, runtime | −15.3114% (bench +0.9424%, user-approved tradeoff) |
| R21 | backward string bodies outlined; forward path falls through | `lower.py` | −0.1080% |
| R22 | first matched walk call returns into its check; fallback outlined | `lower.py` | −0.0246% |
| R24 | REP STOSW: eight longs per pass, long-aligned stores, odd word last | `lower.py` | −1.1239% |
| R25 | native BP kept in a run, dead mirror stores dropped | `reuse.py` | −1.1354% |
| R26 | REPE CMPSW: eight long compares per pass, remainder pairs first | `lower.py` | −0.8031% |
| R27 | cold sides of hot forward jcc out of line, profile-chosen | `emit.py`, `tools/outline_sites.py` | −0.6278% (bench −0.481%) |
| R28 | carry in X kept across an adc/sbb operand setup in d6 | `lower.py` | −0.4796% |
| R29 | CALLF pushes CS:IP as one long; SP wrap out of line | `lower.py` | −0.4660% |
| R30 | segment loads that mostly repeat compare first; store, check and base out of line | `lower.py`, `tools/seg_repeat.py` | −0.5926% (bench −1.816%) |
| R31 | push (pop) runs step SP once; SP wrap out of line | `reuse.py` | −0.0821% |
| R32 | invert conditional over a lone jump; preserve jump entry aliases | `emit.py` | −0.1766% |
| R33 | guarded packed far-return pop and full CS:IP check | `lower.py`, `emit.py`, `rt_entry.s` | −0.7089% (bench −2.318%) |
| R34 | canonical FM phase, 0.75 dB envelopes, stable four-voice allocation | `fm_paula.c` | meter unchanged; bench +0.0453%, user-approved quality tradeoff |
| A2 | semantic guest-entry accounting, helper exclusion and zero-code aliases | `lowering_cost.py` | tooling only |
| A3 | HEAD frame, bench and native-candidate baseline | docs | measurement only |
| A4 | executed-back-edge loop classification and recalibration (U1) | cost meter/model | tooling only |
| B3-cal | separately probed unsigned register long-arithmetic cost | cost meter/model | 0 on saved A4 workload |
| B3 | native candidate prices under both U3 rules; unpriced rows retain ceilings | rendering map | pricing only |
| B4 | consolidate 14 candidates; record U0–U4, authorize only the transform pilot | docs | no code change |
| R35 / N1 | guarded native point transform from authorized xform20; complete byte-write history | runtime, compute oracle | −4.6800% (bench +0.0204%, user-approved tradeoff) |
| N3 | post-transform frames checkpoint: 370, 350, 340 ms; target unmet | docs | measurement only |
| R36 / N2 | guarded projection long path from authorized xproj20; complete byte-write history | runtime, compute tests | −0.2838% (bench +0.0423%; user accepts initial +0.0598% as noise) |
| R37 / N2 | perspective divide from authorized xdiv20; exact intermediate BP and all register results | runtime, compute tests | −0.6499% (bench −0.0219%) |
| R38 / N4 | counted normalization from authorized xpnorm20; proved continuation endpoint and U5 poll | runtime, compute contract/tests | −1.3373% (bench −0.0044%) |
| R40 / N4 | guarded scenery clears from clr_scenery; proved BP continuation guard and U5 endpoint poll | runtime, translator, compute tests | −0.150466% (bench +0.030708%, user accepts as noise) |
| R42 / N4 | guarded sprite packet loop; exact original polls and handler-state re-entry | runtime, translator, compute/replay tests | −0.131085% (bench −0.007312%) |
| R44 / N4 | guarded line pixel loops; exact original polls and handler-state re-entry | runtime, compute tests | −0.040939% (bench −0.016083%) |
| R46 / N4 | priority searches deferred; generated oracle coverage and optional short poll macro retained | tests, translator tooling | No shipped speed change |
| R48 / N4 | guarded edge ordering/merging; wrapping index reuse and exact original polls | runtime, compute tests | −0.100064% (bench +0.001462%, user accepts as noise) |
| Z1 | post-N4 frames checkpoint: 340, 340, 350 ms; target unmet; user paused speed work (U7) | docs | measurement only |
| F1 | EMS map: long-word page copy, exact identical-remap skip | runtime, EMS oracle | c12 meter −27.72% (m4 unchanged) |
| F2 | REP MOVSW by longs; element order kept for CX < 4 and DI 1–3 bytes above SI | `lower.py` | −0.0067% (flyby `rep movsw` −29%) |
| F3a | projection `B017` whole with divide `B4E2`, four returns; folds R36/R37 rows; merged long stores | runtime, compute tests | −1.4854% (bench −0.0921%) |
| F3b | transform `B52D` whole with `B54B`; wrapper pushes stored, SI/DI/BP restored | runtime, compute tests | −1.5848% (bench +0.025%, user accepts as noise) |
| F4 | FM loop cache: split key/stamp arrays, first-free hint, freed-range refit; render loop per feedback/connection | Amiga platform, FM tests | outside meter (flyby `fm_field` −24.4%/call; bench +0.20%, user accepts as noise) |
| ZF3 | post-F3/F4 frames checkpoint: 330, 300, 300 ms against pre-F3 360, 350, 360 (no overlap); target unmet | docs | measurement only |
| F5 | `BFD1` whole, exact polls, guest calls as exits; folds R48. Price (S2, flyby `130bd18`): 575,524 inclusive cycles/call, self 260,523 + ordering 86,293; clear 0.80% of the clip stays (long stores, U3); replaceable ~300K/call; estimate −45–60% of it, 1.5–2.5% of the clip | runtime, translator, compute tests | −0.0167% (bench −0.044%, flyby `BFD1` −2.1%/call) |
| F9 | SPAZ OPL delay loops as exact-poll rows, every iteration, poll and store kept | runtime, annotations, `test_opl_delay` | −1.4996% (bench +0.056%, D8; flyby `0CEE` −36.4%/call) |
| I10 | native rows re-opened poll-free (irq-plan I10), one batch, references re-recorded once; per row below: generated cycles saved and native cost on the same m4 run (`cost_meter.py` `runtime` per symbol) | runtime, translator, compute tests | −4.9158% (bench −0.48%) |
| I10 / BB70 | polygon classify whole up to its RETF, R39's admission guard | runtime, compute tests | generated −3.13M, native 1.47M: −1.66M |
| I10 / BFD1 | rasterizer re-entered after each guest call (`hle.csv` entries); guards once per scanline | runtime, translator, compute tests | −1.18M against the I9 arm (native 9.79M → 13.11M, generated 5.74M → 1.25M) |
| I10 / F290 | tile and scenery selection whole; object calls as exits with re-entries; far-ring sprite objects skipped by their type byte | runtime, compute tests | generated −2.90M, native 2.06M: −0.84M |
| I10 / 109D6 | ground-object vertex loops 10C08–10F5F; B52D/D5A6 calls and their 9C20h sync writes as exits | runtime, translator (`irq.check_rows`), compute tests | generated −3.46M, native 2.80M: −0.66M |
| I10 / FDE0 | terrain polygons whole; transform and classify natives called directly (exit only on decline), other calls as exits | runtime, compute tests | generated −3.96M, native 3.37M: −0.59M |
| I10 / BD68 | edge submission; C962/CD00 calls as exits with re-entries; hook and dispatch overhead leaves little | runtime, compute tests | generated −1.11M, native 1.05M: −0.06M |
| F8 | sprite walk loop 4FD3..5032 in `sprite_row` (user 2026-10-27: code writes through the cell cache's bookkeeping, the generated cell walk called directly); sync set −1 (4FD3), references re-recorded; generated −10.70M, native +8.97M | runtime, translator, compute tests | −1.2038% (bench +0.025%, user accepts as noise) |
| ZI | post-irq-plan frames checkpoint (irq-plan I11): 300, 290, 300 ms against pre-irq-plan 330, 330, 320 (no overlap); target unmet | docs | measurement only |
| I10 / rest | D5A6 prefix and suffix to the projection call; F9 delay loops O(1) (§2.9 exception); D69C BP once; 4DAE packet loop widened to the span setup (`sprite_row`) | runtime, compute tests | −2.43M together (no per-row I9 runtime baseline) |

No priced translator candidate remains. Unchanged (§2): sync points outside native rows
(`(a6)` is guest byte 0; no thinning; no poll checks in production since irq-plan I8), `mulu`/`divu` themselves. The translator helpers
`__set_flags` (POPF/IRET) and `__flags_word` are the largest runtime-side
items left.

## 8. User decisions (D0–D4 2026-10-08)

- **D0.** Per-step acceptance by the meter (§3), instead of FS-UAE frame A/B.
- **D1.** R1's memory model, with the harness converting memory and
  registers. Plants whose templates R1/R4 remove are replaced first, then
  retired: "word loads not byte-swapped", "ror for ror.w on memory dest",
  "native word store skips byte swap", "native byte-order restoration
  omitted", "address word not restored", "stack pointer not restored",
  "address restoration copies stale scratch", "SP not 16-bit", "RETF CS
  pop uses linear SP", "mask trusts dirty upper word".
- **D2.** R6 may grow the code beyond +5% when each guarded copy lowers
  model cycles; the +25% stop in §3 remains.
- **D3.** Cell cache (R7b) with exact invalidation. Re-price approved 2026-10-17:
  RET-aware, consecutive destinations a long at a time; priced −17.2% of the
  meter, built as R20 (−15.31%, §7).
- **D4.** Deterministic frame bench (§4).
- **D5 (2026-10-14).** Bench-based acceptance for layout and Amiga platform
  work outside the host meter; all fidelity gates and no slowdown remain.
- **D6 (2026-10-14).** Add a separate frames-60–67 fixed-work palette bench,
  with equal final guest RAM, exercised palette calls and all fidelity gates.
  Keep the existing bench and normal frame-rate fixture unchanged.
- **D7 (2026-10-14).** R19 flag-word packing rejected (§10). Trap flag:
  TF = 1 stops loudly at POPF/IRET, no single-step delivery
  (translator-design.md).
- **D8 (2026-10-24).** The bench stays frames 4–11 (static opening view).
  Tiny bench regressions count as noise when general performance improves (§3).
- Native replacement: [native-plan.md](native-plan.md); each routine needs the user's
  authorization (§2.2).

## 9. Gap

WC2's own (P7.3, 2026-11-25, MEASURED); SWOTL's §9 is at its `658fc60`. Against the
original's 66.7 ms a drawn frame the model draws one every 280 ms (quiet) and 300 ms
(fight): 4.2× and 4.5×. A visit costs 154–167 ms of work and every second one draws,
so the gap to 66.7 ms a visit is 2.3–2.5× (§1).

The runtime, the platform and the c2p carry about two thirds of a visit (§1 table: EMS
37–41 ms, present 24 ms, c2p 18 ms, I/O 11–17 ms, the field wait 8 ms); generated code
29–32%. No translator step
alone reaches the bar: generated code twice as fast saves about 24 ms a visit (15%).

Hot guest routines in the fight (`tools/profile_tree.py` on the 100-field capture, 12
visits; cycle units, 1.01 M a field; WC1 counterpart from `tools/wc1_counterparts.py` on
`make compare`, similarity of normalised code; drivers are not compared, `SUPERTM.DRV`'s
entries are byte-identical in PC WC1, [wc1-wc2-comparison.md](wc1-wc2-comparison.md)).
Inclusive rows overlap; do not add them.

| Routine | Own | Inclusive | Calls a visit | Own a call | Inclusive a call | PC WC1 |
|---|---:|---:|---:|---:|---:|---|
| `WC2.EXE+0E9B4` (3D maths module R:0E9B) | 4.00% | 4.00% | 118 | 2,851 | 2,851 | R:077E:0000, 0.930 |
| `WC2.EXE+0EA42` | 1.81% | 1.81% | 382 | 398 | 398 | R:077E:009A, identical bytes |
| `WC2.EXE+0ECEE` | 1.41% | 1.41% | 160 | 739 | 739 | R:077E:0330, 0.944 |
| `WC2.EXE+0EBF8` | 0.77% | 0.77% | 10 | 6,453 | 6,453 | none (best 0.661) |
| `WC2.EXE+0EDBD` | 0.53% | 2.37% | 80 | 561 | 2,488 | R:077E:0461, identical bytes |
| `WC2.EXE+0ED8E` | 0.43% | 0.43% | 160 | 225 | 225 | R:077E:0330, 0.944 |
| `WC2.EXE+0C5F2` | 0.52% | 1.54% | 73 | 594 | 1,776 | WC1 overlay O:110B+0924, same code |
| `WC2.EXE+0C35F` | 0.38% | 0.38% | 76 | 422 | 422 | O:110B+0568, 0.923 |
| `WC2.EXE+0E7E1`, `+0E902` (R:0E78) | 0.46% | 3.25% | 0.5 | 77,377 | 545,795 | R:0758:0041, 0.961 |
| `WC2.EXE+0DE57` | 0.29% | 4.75% | 0.5 | 48,613 | 798,810 | O:110B+22AB, 0.749 |
| `SUPERTM.DRV+07460` (scaled sprites) | 2.01% | 2.99% | 0.5 | 337,905 | 501,800 | PC WC1's `SUPERTM.DRV`, identical |
| `SUPERTM.DRV+015F5` | — | 2.88% | 6.5 | — | 37,297 | identical |
| `TM.DRV+00E93` (sprite blit) | 1.73% | 9.32% | 16.7 | 8,702 | 47,014 | no shared entry |
| `TM.DRV+02C07` | 0.91% | 1.69% | 13 | 5,861 | 10,950 | no shared entry |
| `STRAX.DRV+0129B`, `+00714`, `+00B82`, `+00747` (FM) | 3.44% | — | 2–9 | 8–54 K | — | 1 of 3 entries shared |
| `WC2.EXE+0364A` | 0.47% | 3.21% | 61 | 648 | 4,416 | none |
| `WC2.EXE+15831` | 0.42% | 6.59% | 45 | 798 | 12,390 | none (its inclusive cost is EMS maps) |
| `WC2.EXE+04C58`, `+04846`, `+05739`, `+106CD`, `+10851` (the frame) | ≤ 0.01% | 14–19% | 1 | — | 1.2–1.6 M | none |

Quiet flight ranks the same routines (`WC2.EXE+0E9B4` 4.05%, 117 a visit, 2,684 a call;
`SUPERTM.DRV+01A5B` 1.32%, 78 a visit). The 3D maths module (R:0E9B, WC1 R:077E) is the
largest guest code, about 8% of a visit, and is WC1's nearly unchanged: the CD32
counterpart (port-plan P7.10, open-work 8) prices its native version. The frame's own
routines (R:03CA, R:073C, R:106C) have no WC1 counterpart.

The x86 forms with the most cycles (fight, `lowering_cost.py`): `rep movsw` 1.66% (289
units a run), `push r16` 1.45%, `rcl r16, imm` 1.28% (139 K runs, the maths module's long
shifts), `callf` 0.94%, `pop r16` 0.85%, `mul r16` 0.80%, `rep movsb` 0.79%: no single
form is more than 2% of a visit.

## 10. Rejected and not built

(One line each: step, change, measured Δ, reason. Round 1 is in git
history at `781975e` and §5.)

- S1 shape "compare each present against a shadow copy to find changed
  rows": rejected by the user before building; every present would read
  the whole 64000-byte frame. Replaced by marks at the driver's stores
  (D9, translator-design Display).
- S5 "cell walk: mov cells four at a time under one bound check, opcode
  of each still compared": walk 14.1% → 12.0% of CPU, rejected only
  because frame times (trajectory noise) did not separate. Revisited as
  R7 under the meter.
- R1c "SI/DI mirrored like SP/BP": census −1.0% (SI/DI serve as data
  registers far more than as lone indexes); not built.
- R14h "mul with DX dead": DX is live after every hot `mul` (≤ 10K
  executions with DX possibly dead, ≈ 0.01%). Not built.
- R15 shape "per-vector `rt_lookup` cache on interrupt delivery": +≈ 10K
  model cycles (the timer handler's row is an overlay row, so the row search
  still runs per delivery); reverted.
- R19 flag-word packing: priced at 18,726–29,266 model cycles
  (0.0086–0.0135%) and ten code bytes on `25dd32c`; too small (D7).
- R23 loop-tail placement: model −0.1361%, changed-code target −11.3304%,
  code +12 bytes; six opening benches per arm give median +0.0042%, mean
  +0.0326% (overlapping ranges, five pairs slower). No-slowdown acceptance
  not established; placement reverted. Approved alias-boundary and timing-tool
  fixes plus oracle coverage retained; all seven gates passed. Evidence: `tmp/item31-r23/`.
- X1 REP STOSB long fill: not built; zero executions at all 17 emitted entries
  in A3’s three captures and the fresh 49-frame m4 census; zero priced saving
  in the acceptance window. Startup executes four sites (319,670 bytes); no
  startup timing or unreachability claim. Evidence: `tmp/native/X1/`.

- R39 / BB70: deferred by user 2026-10-22; whole-body prototype skipped kept syncs. Repair budget 4,363,049 versus 3,198,000 generated model cycles; no positive price. Generated differential and skipped-sync sabotage retained; evidence `tmp/native/N4-classify/`.

- R41 / F290: user deferred 2026-10-23; narrow tile-selection design estimated at 1,633,529 versus 1,147,792 generated model cycles (JSR/RTS model accesses corrected after 7744ce5). No implementation built; guards and frequent handoffs outweigh the priced arithmetic folds. Evidence: `tmp/native/N4-terrain/`.

- R43 / BD68: user deferred 2026-10-23; approved exact-poll edge scopes budget 843,635 versus 667,905 generated model cycles even with optimistic credits. Frequent external-call handoffs outweigh address reuse; no implementation built. Evidence: `tmp/native/N4-edges/`.

- R45 / FDE0: user deferred 2026-10-23; approved cache-loop design budgets 476,194 versus 434,107 generated model cycles, even with optimistic credits. Frequent cache-miss exits outweigh address reuse; no implementation built. Evidence: `tmp/native/N4-polygons/`.

- R46 / BFD1 priority searches: user deferred 2026-10-23; meter −0.087648%, target mix −3.777903%, but four bench pairs give median +0.049732% with overlapping ranges. No-slowdown acceptance unproved; native hooks removed, generated coverage retained. Evidence: `tmp/native/N4-raster/`.

- R47 / BFD1 expiry and advance: user deferred 2026-10-23; address-reuse budgets 1,304,535 versus 1,048,049 and 1,769,291 versus 1,676,612 model cycles. No implementation built; evidence `tmp/native/N4-raster-remaining/`.
