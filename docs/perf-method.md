# Performance method

P7's instruments and how their numbers are made. The method itself is AmigaXDev's
`docs/reference/measurement-method.md`: units, A/B discipline, pricing, budgets and the
traps that made measurements lie. The 68020 cost facts are in its
`docs/reference/m68k-optimisation.md`. The instruments come from X-Wing `0d20bcd`, which
copied them from Secret Weapons of Luftwaffe ([upstream.md](upstream.md)); SWOTL's
[speed-plan.md](speed-plan.md) holds the reasons behind them. The steps and their gate are
in the [port plan](port-plan.md#p7-performance-gate-7).

## Machine

- **Measurement model:** the shared cycle-exact preset `a1200-030` (50 MHz 68030, data
  cache) without its MMU (`--uae_mmu_model=0`). FS-UAE's profiler records no instruction on
  the 68030 MMU core (X-Wing, MEASURED); the game uses no MMU.
- **Emulator:** the native arm64 FS-UAE, pinned in `manifest/perf-tools.sha256` (relative to
  `~/.local/share/amiga`, the same build as X-Wing's) and checked before every run. Numbers
  from another build do not compare.
- Emulated fields, never wall time. No warp.

## Instruments

- **Meter** (`tools/cost_meter.py MILESTONE --out A.json`): the per-step acceptance. It is
  deterministic and layout-blind.
  - **Run:** `tests/host_run.py`'s lockstep check of the milestone from boot, so every meter
    run is also a fidelity check. Any lockstep problem refuses the result.
  - **Window:** the milestone's first snapshot trigger to its last
    (`reference/milestones.csv`): m4, 49 visits of the flight frame label `WC2.EXE+813C`
    after the first (the launch); m5f, 49 visits inside the Nav 1 fight. m2 and m3 have one
    snapshot: their windows are its last 600 timer ticks (`cost_meter.TAIL`), the intro's
    animation and the pilot-file screen. A C block hook (`tests/host_meter.c`) counts every
    translated block and taken transfer in it, in the milestone's own host only (the
    lockstep check's controls build others).
  - **Model:** per executed 68k instruction its code bytes, inside or outside a cached loop
    of at most 256 bytes; its data reads and writes; its taken transfers; and its mul/div,
    weighted by `tools/cost_model.json` into model cycles.
  - **What it measures:** the host image is the sync image, so its poll tests (which
    production does not have) are reported apart. Its REP instructions that an interrupt
    split in the reference run `tests/rep_replay.py`'s diagnostic lowering. Interrupts
    arrive at the reference's poll visits, so a guest wait loop runs the reference's
    iteration count: its cost is the reference's waiting, not work.
  - **Usage:** `--compare A.json B.json` for the deltas per class and x86 form.
    `--plant-check BASE.json --label L [--nops N]` is the meter's control: N NOPs at one
    generated label must add exactly their instructions, bytes and cost, in a run whose
    lockstep passes.
- **Frames fixtures** (`tools/perf_flight.py OUT --scene quiet|fight`,
  `amiga/perf_flight.gdb`): the non-release Amiga image, the frame time the owner sees.
  - **Route:** a `KEYS` script (`src/platform/amiga/amiga_platform.c`), `play_walk.sh`'s
    route through the opening, the pilot file and the briefing's Esc into the first flight.
    From there its steps count published frames (`nN`, `amiga_presents`), so the window
    starts at the same point of the flight in every build. quiet: 200 frames after the Esc.
    fight: the autopilot held 30 fields 301 frames after the Esc, which drops out at Nav 1
    into the Sartha attack, and the mark 100 frames later. The Amiga start has no command
    tail, so the fixtures fly the plain game, not the references' `WC2 Origin -k`.
  - **Output:** at each of the next 60 visits to `R_0813C`, the field and the scaled objects
    drawn since the previous one (`STM_0153E`, `SUPERTM.DRV`'s entry 2); the intervals, and
    those between visits that drew; then a 100-field profile reported by
    `tools/profile_report.py` and deleted (`--keep-capture` for `--calibrate`).
  - **Paired runs:** `tools/ab_runs.py freeze ARM`, then `flight SESSION ARM... --scene S`:
    interleaved runs, tool fingerprints checked, results never overwritten. A frame-time
    claim needs arm ranges of run medians that do not overlap.
- **Profile report** (`tools/profile_report.py CAPTURE ELF`): class, module, guest routine
  and instruction, and runtime shares of a `monitor profile` capture; up to 2% of a field
  without a record is reported as unattributed (SWOTL's rule), more refuses the capture.
- **Lowering cost** (`tools/lowering_cost.py`) and **call tree** (`tools/profile_tree.py`):
  per x86 form and per routine, inclusive. **Counts:** `tools/host_census.py`;
  `amiga/perf_slice.gdb` (P5.4's intro window).

## Cost model

`tools/cost_model.json` is fit on the measurement model (`--calibrate`, the fight fixture's
100-field capture, 38,118 generated PCs): per instruction 0.777, per code byte 0.951 (0.659
inside a cached loop), read 0.191, write 3.715, taken transfer 5.217 (0.280 inside a cached
loop), mul/div 20.128; unsigned register long arithmetic keeps SWOTL's probed 4.125. R²
0.882, the model 4.35% under the measured generated cycles. Before it the weights were
SWOTL's 68020 fit. Recalibrate after a change to the measurement model or when the meter and
a capture disagree, then rerun `--plant-check`.

## Baseline (2026-11-24, the image at `377426a` plus the instruments)

MEASURED. Per frame without poll tests is the production estimate. Each meter gave equal
counts in two runs, each frames scene equal medians in two.

| Window | Instrument | Figure |
|---|---|---|
| m4, 49 frames of the launch | meter | 424.9 M model cycles (generated 287.6 M, runtime 136.9 M); poll tests 17.65%; 8.67 M a frame, 7.14 M without poll tests |
| m5f, 49 frames of the fight | meter | 446.0 M (generated 299.8 M, runtime 146.0 M); poll tests 15.67%; 9.10 M a frame, 7.68 M without poll tests |
| m2, the intro's last 600 ticks | meter | 1,602.9 M; poll tests 7.60% |
| m3, the pilot-file screen's last 600 ticks | meter | 2,043.6 M; poll tests 2.56% |
| quiet flight, 60 frames | frames, 2 runs | a visit to the frame label every 160 ms (median); drawn frames 280 ms apart (median of both runs; means 284.8, 285.5); 4 objects or none |
| the fight, 60 frames | frames, 2 runs | 160 ms a visit; drawn frames 300 ms apart (means 300.0, 303.6); 11–13 objects or none |
| the fight, 99 fields | profile | runtime/platform 54.8% (`copy` 20.9%, `plat_pit_count` 4.3%, `rt_video_frame` 3.7%), generated 31.7% (WC2.EXE 21.2%, TM.DRV 3.6%, SUPERTM.DRV 3.6%, STRAX.DRV 3.2%), outside the first hunk 10.9%; quiet flight 54.7%, 30.4%, 12.3% |
| controls | plants | meter: 8 NOPs at `R_12C07` on m1b add exactly 50,432 instructions, 100,864 bytes, 92,025 model cycles; on m5f at `STM_0153E` (622 calls) +4,976 instructions, +9,952 bytes, +13,326 model cycles; profile: 64 NOPs at `R_0E9B4` raise its cost a call from 2,861–2,870 to 3,057 cycle units (+6.6%) |

On the 68030 model only every other visit to the frame label draws (in the fight 11–13
scaled objects, then none; in quiet flight 4, then none). In the reference every visit
draws, one 66.7 ms frame each (`tools/pc_run.py` probes on m5f's route, MEASURED). The
picture rate is the drawn frames'. That the game skips the drawing of a late frame is
INFERRED.
