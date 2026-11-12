# Upstream: Secret Weapons of Luftwaffe

Where the translator, runtime, Amiga layer, tests, tools and contract docs came from, and
every local change since, so fixes can move between the two ports (D5,
[port-plan.md](port-plan.md) P0). Source: Secret Weapons of Luftwaffe (SWOTL) at `658fc60`
(release 0.93, 2026-10-31). Paths are the same in both repositories unless a row says
otherwise.

## Imported at 658fc60

| Path | Treatment |
|---|---|
| `translator/*.py` | copied as is |
| `annotations/*.csv` | header line only; every row is re-derived for WC2 |
| `src/main.cpp`, `src/runtime/{dos,ems,input,machine,pointer,ports,video}.c`, `rt_entry.s`, `runtime.h`, `platform.h` | copied as is |
| `src/platform/host/` | copied as is |
| `src/platform/amiga/` except `tfh_paula.*` | copied as is; `framework/` too (its README says why) |
| `tests/` generic harnesses and unit tests (`git log --stat` of the import commit lists them) | copied as is |
| `tools/` generic tools and `tools/patches/` | copied as is |
| `amiga/` launchers, probes and `Makefile` | copied as is; `amiga/env.sh` was already here |
| `Makefile` | targets merged into the existing one |
| `docs/`: `translator-design`, `translation-lessons`, `x86-notes`, `amiga-arch`, `amiga-lessons`, `native-compute`, `irq-plan`, `sound-plan`, `speed-plan`, `pointer-plan`, `perf-method`, `headless-fsuae`, `toolchain`, `phases`, `method-lessons` | copied with a banner: the rules apply, the facts are SWOTL's until re-derived |

## From X-Wing

X-Wing took the same SWOTL commit through its own P3–P6 for Borland 80186 code. Port-plan P3
brings its x86 front end here (owner's direction, 2026-11-09); its 68020 lowering
(`ec4a238`) is P4's. Rows name X-Wing's commit; a fix to these files can move to both.

| Path | From X-Wing | Treatment |
|---|---|---|
| `translator/decode.py`, `translator/sem.py` | `3dea12a` | the 80186 forms (`push imm`, `imul r16,r/m16,imm`, shifts and rotates by an immediate, `enter`, `leave`); header text says where they came from |
| `tests/x86_diff.py` | `3dea12a` | `i186_cases` in the boundary corpus; `UNSUPPORTED` without the new opcodes |
| `tests/x86_sabotage.py` | `3dea12a` | five plants: `imul imm8 not sign-extended`, `push imm8 not sign-extended`, `shift imm count read as 1`, `enter level ignored`, `leave keeps BP` |
| `tests/test_decode.py` | `3dea12a` | `UNSUPPORTED` without the new opcodes; Capstone's sign-extended `enter` level |
| `translator/lower.py`, `flags.py`, `reglive.py` | `ec4a238` | the 80186 lowerings: shift and rotate immediates masked to 5 bits (0: no-op, up to 8 `#n`, else `moveq`), OF undefined unless the count is 1, `imul r,rm,imm`, `push imm` with its relocation check, `enter`/`leave` on the mirrored SP/BP; `writes()` of a masked count 0 is no flags |
| `tests/m68k_sabotage.py` | `ec4a238` | `only`; plants `imul r,rm,imm flags of the unsigned product`, `enter copies one frame pointer`, `leave keeps BP`, `push imm pushes 0`, `shift by an immediate counts 1` |
| `tests/m68k_blocks.py` | `ec4a238` | X-Wing's version as the base (per-module segments, no SWOTL-pinned regressions or native-routine cases) |
| `tests/host_run.py`, `tests/rep_replay.py` | `49b792b` | P5: X-Wing's lockstep (poll-point interrupts, REP slices through the diagnostic image, VGA status replay, launch and key handling) merged by three-way merge against SWOTL `658fc60`; WC2: host references `tmp/pc-runs/host-<m>`, the PIT reads replayed beside 3DAh (`port_runs`, `trace/replay-ports.csv`), the overlay probe (each overlay alone at a buffer CS) and sabotage `overlay` for SWOTL's resident check, `pit`; `rep_replay`'s cache split (generation keyed by translator, annotations and labels; the link also by the runtime objects) |
| `tests/amiga_replay.{py,c}` | `49b792b`, `2de0225` | P5: X-Wing's replay (REP stream, service-hash checkpoints, early-return stop, the replay machine's Zorro III board, 32 MB for WC2) merged; WC2: 3DAh and PIT streams, drivers at their load paragraphs, an overlay point's CS from its stub's word 10h, `fresh_run_directory` kept for `test_replay_run_isolation` |

## Not imported

| SWOTL path | Why |
|---|---|
| `src/runtime/compute_*.s`, `sfx.c` | SWOTL native routines and SPAZ effect capture |
| `src/platform/amiga/tfh_paula.*` | Their Finest Hour samples |
| `tests/audit.csv` and the tests of SWOTL routines: `test_compute_*`, `test_point_*`, `test_polygon_classify*`, `test_rasterize`, `test_edge_submit`, `test_terrain_*`, `test_ground_vertices`, `test_scenery`, `test_sprite_packet`, `test_line_pixels`, `test_priority_search`, `test_opl_delay`, `test_tfh`, `test_sfx_*`, `test_sound_hooks`, `test_pointer_static`, `test_gameport`, `test_machine_vectors`, `test_amiga_file_sharing`, `test_mouse_scale` | SWOTL routines, fixtures or scenes |
| `tools/`: `swotl_model`, `plink_check`, `load_image` (adapted at P1.4, below), `ovl_info`, `sweep`, `code_writes`, `compute_oracle`, `native_entries`, `sound_reference`, `sfx_levels`, `pointer_static`, `tfh_*`, `ghidra_import`, `m68k_cost_probe`, `fm_effect_check.cpp`, `fsuae-input-lua.patch`, `install-data/`, release tools (`originals`, `pack_preinstalled`, `package_release`, `check_release`, `test_release_installer`, `test_whdload`) | game-specific: rewritten or adapted in their phase (P1, P2, P8) |
| `whdload/`, `release/` | P8 |
| other docs | SWOTL facts and history |

## Imported tests not yet in `make test`

Copied because their harness is generic; each needs what the named phase brings (MEASURED at
P0: every one fails before it for the reason given). Enter each into `make test` in that phase.

| Tests | Need | Phase |
|---|---|---|
| `test_pointer_model` | WC2's pointer rows in `annotations/pointer.csv` (`pointer.c` is inactive without them) | P6 |
| `test_cell_cache` | none applies: WC2's self-modified regions are switches and operand reads, with no cell cache (no `_walk_plant` in `build/gen`, MEASURED at P5) | — |
| `test_profile_tools` | generated guest call targets | P4 |
| `m68k_sabotage` plants on `program` and `walk` (37): `tests/m68k_blocks.py` needs generated blocks, and it imports SWOTL's compute and scene predecessor tests (`test_compute_contract` and others, not imported): drop those for WC2's | a module in scope (P1.4 brings the loader model only) | P2 |
| `test_audio`, `test_fm_effect_asm` | TFH and SWOTL's effect capture: rewritten for WC2's effects | P6b.2 |
| `test_display_palette` | its C++ extract does not compile: fails in SWOTL `658fc60` too (`Pointer` undeclared), an upstream fix | P6b.1 |

## Local changes

One line per change to an imported file, newest last: commit subject, files, and whether
it applies upstream (`up`), is WC2 only (`wc2`) or is a rename (`ren`).

| Change | Files | Kind |
|---|---|---|
| Rename `SWOTL_` → `WC2_`, `Swotl` → `Wc2`, `swotl-gen` → `wc2-gen`; `Swotl.{cpp,h}` → `Wc2.{cpp,h}` | 65 imported files | ren |
| Empty scope before P2: `tools/wc2_model.py` from `swotl_model.py` (generic parts; no modules, no PLINK); `cfg.build` returns no unit; `gen` skips the IRQ0 proof without units; `pointer_guest` zeros without rows; `lint` names the root; `test_decode` passes on the opcode space alone | `tools/wc2_model.py`, `translator/{image,gen,cfg,emit,check}.py`, `tools/surface.py`, `tests/test_decode.py` | wc2 |
| `tests/audit.csv`: header only | `tests/audit.csv` | wc2 |
| TFH and SPAZ effect capture removed: sample loading, the effect cache and prerender in `Audio`, the `TFH` option, `rt_sfx_*`, the HLE `sfx_start`/`sfx_prerender` entries, the OPL capture path, the `compute_transform.s` include. `plat_sfx_*` stay as host stubs until P6b.2 | `src/platform/amiga/{Audio.cpp,Audio.h,amiga_platform.c}`, `src/runtime/{rt_entry.s,runtime.h,ports.c}` | wc2 |
| Amiga link without TFH and the compute objects | `amiga/Makefile` | wc2 |
| Empty image: with no dispatch rows the platform logs it, keeps the takeover for 200 fields and hands back; the smoke requires that hand-back after 100 live fields | `src/platform/amiga/amiga_platform.c`, `amiga/diag_smoke.gdb` | wc2 |
| DOSBox-X tree `~/.local/src/wc2-dosbox-x` (the renamed patches differ from SWOTL's) | `tools/build_dosbox_x.sh` | wc2 |
| `host_run.Host` hooks the effect capture only when the image has it | `tests/host_run.py` | wc2 |
| Guard plants: two `.s` files while no IR listing exists; planted module names use the root's | `tests/test_guards.py` | wc2 |
| Sabotage plants aimed at `forms` alone run on `forms,boundary` (`forms` is empty until P2; `boundary` catches each, MEASURED): x86 `sub OF = CF`, `disp8 not sign-extended`; 68020 `RMW word at its byte address` | `tests/{x86,m68k}_sabotage.py` | wc2 |
| 68020 sabotage: plants on the `program` and `walk` corpora (the generated program's blocks) print `deferred` while no module is in scope and count neither as caught nor as passed | `tests/m68k_sabotage.py` | wc2 |
| WC2 trace patch on top of the imported one: root `WC2.EXE` (entry `0000:0000`, 6656-byte header), stub scan, `vroomm.csv` (INT 3Fh traps, overlay reads, entries, stub and frame writes, buffer moves with ownership), `.DRV` code files, code reads own their trailing partial paragraph, OPL at the SB aliases and `sound.csv`, `WC2_REPLAY_PORTS`; generic: per-key hold `key*N`, the caller's return address in `probe.csv`, key names `backslash`, `kpminus`, `kpplus`, `kpenter`, `insert`, `delete` | `tools/patches/{dosbox-x-wc2-trace.patch,ORDER}` | wc2; per-key hold and probe caller up |
| `reference/dosbox-x.conf`: the Staging machine (`vgaonly`, SB 2.0 with OPL2) | `reference/dosbox-x.conf` | wc2 |
| `quit warning = false`: a signal to stop a run while the game runs opened a native macOS confirmation dialog | `reference/dosbox-x.conf`, `reference/dosbox-x-install.conf` | up |
| `pc_run`: launch `WC2` in `WING2`, writable root copy, `--replay-ports`; `-exit` replaces `-silent`, which also sets the Sound Blaster type to none; `mount c root` relative to the run directory, since DOSBox echoes the command into text VRAM and an absolute path made the entry snapshots of two runs differ | `tools/pc_run.py` | wc2; `-silent` and the mount up |
| `reference`: each milestone twice in parallel, RAM, VRAM and DAC compared between the runs, image proof on every snapshot, `opened` and `irqs` columns, poll points passed only when the file has rows | `tools/reference.py` | wc2; poll-point guard up |
| Loader model (root with DOSBox-X's EXEC entry frame below the initial SS:SP, VROOMM overlays relocated through the root segment table, drivers) in `wc2_model`; `load_image` adapted to it, with the overlay-tail and read-tail rules; `test_load_image` rewritten on synthetic snapshots of the model and entered into `make test` (it needs `ref/`) | `tools/{wc2_model,load_image}.py`, `tests/test_load_image.py`, `Makefile` | wc2 |
| `make reference` | `Makefile` | wc2 |
| Trace patch for P2: `stub_write` and `frame_write` carry the value written (logged at the next instruction); a trap ends at the first instruction in the overlay area, not at the first root instruction (the timer handler calls `STRAX.DRV` inside a trap); `code-writes.csv` names the target's module and offset at write time; `create`, `write` and `delete` events (AH=3Ch, 40h, 41h; `dos.cpp` hooks) | `tools/patches/dosbox-x-wc2-trace.patch` | wc2; code-write targets and the file events up |
| `surface.py` rewritten for WC2's external surface: EMS per run, vectors, VGA, DOS files from the traced file events, the drivers, static sites from the sweep (stub cells as INT 3Fh), the decoder's fit | `tools/surface.py` | wc2 |
| VROOMM model in `wc2_model`: manager data and segment table constants, overlay entries and paragraph needs, relocation by `w & FFF8h` and the far-pointer form (`far_pointer_form`) | `tools/wc2_model.py` | wc2 |
| `make map` (gate 2: `vroomm_check` with its sabotage, `sweep`, `code_writes`, `surface`); `sweep.py` and `code_writes.py` are WC2's own (SWOTL's not imported) | `Makefile` | wc2 |
| The self-modified forms are checked and lowered, and their run-time bytes read, only for modules in scope (WC2's start-up forms are in `self-modifying.csv` before `WC2.EXE` is) | `translator/{emit,image}.py` | up |
| P3: x86 semantics over WC2's code. Two scopes: `X86_SCOPE` (decode and IR) and `SCOPE` (68020 generation, empty until P4); `cfg.build` and `image.runtime_bytes` take a scope. `cfg.py` rewritten for WC2's code ranges (root segment rule, overlays at their image paragraph, driver entries at CS 0), seeds from the stub entries and `entries.csv`, stub far targets to overlay entries, `noreturn.csv` calls, the successors of each listed self-modified form | `translator/{cfg,image}.py` | wc2; the form successors up |
| `test_decode`: the decoded starts equal the sweep's (`tmp/sweep/*.cls`); executed VROOMM stub cells decode in both forms; every count must be nonzero | `tests/test_decode.py` | wc2 |
| `x86_diff` forms and blocks over `X86_SCOPE`; `make test` runs them in shards (forms 8, blocks 2) | `tests/x86_diff.py`, `Makefile` | wc2 |
| Model: `load_modules` (WC2.EXE with its overlays relocated at load segment 0, the drivers), `code_ranges`, `program_image`, `records`, `root_code_segs`, `driver_entry` and the driver constants moved from `sweep.py`; `STUBS` from `code_writes.py` | `tools/{wc2_model,sweep,code_writes}.py` | wc2 |
| `sweep.py --annotations` writes `annotations/entries.csv` (the seeds `cfg.py` cannot derive); an indirect far jump (`ljmp [mem]`) ends a flow, as in X-Wing's sweep (it fell through into 148 bytes after `WC2.EXE+FE09`, never executed) | `tools/sweep.py` | wc2 |
| `m68k_diff`: a case with an 80186 form is skipped and counted (`not compared`) until P4 lowers the forms; SWOTL's lowering takes some of them silently and wrongly (`C1 E0 10` as a shift by one, MEASURED in the boundary corpus's `compact-dirty` cases) | `tests/m68k_diff.py` | wc2 |
| P4: `LOADSEG` 0824h; dynamic CS for VROOMM overlay code (`Ctx.cs_slot`: the stub's word 10h for `push cs`, far pushes, far return checks, `cs:` bases, dispatch, interrupt and fault d6, poll stubs); `push cs; call near` as a far call (`Ctx.far_return`) | `translator/lower.py` | wc2 |
| P4: overlays, stub cells, trap sites, drivers at `DRIVER_SEG`, overlay dispatch rows (`overlay_count`/`overlay_stubs` replace `overlay_table`), the start-up switch and operand regions, `ZeroDivision` as the INT 00h handler, stub-cell liveness from their continuations; `cfg.Unit.stub_calls` | `translator/{emit,cfg}.py`, `annotations/runtime.csv` | wc2 |
| P4: version `wc2-gen 3`; IRQ footprint proof off (`IRQ_PROOF`, P5); drivers read from `GAMEDAT` (`wc2_model.module_path`); stub-cell starts counted as self-modified in the coverage | `translator/gen.py`, `tools/wc2_model.py` | wc2 |
| P4: `rt_lookup` takes a static row, then the overlay whose stub word 10h is the CS; a RETF/IRET return mismatch re-dispatches far (`rt_ret_far_mismatch`, also after a guest INT handler: `deliver_int`), hardware delivery still stops (`rt_ret_far_stop`) | `src/runtime/{machine.c,rt_entry.s,runtime.h}` | wc2; the far re-dispatch up |
| P4: `m68k_diff` takes the 80186 forms (the skip removed) and a `cs-slot` variant of every run whose lowering reads CS; x86 sides replayed and recorded per case (`side`) | `tests/m68k_diff.py` | wc2 |
| P4: `m68k_blocks`: drivers at `DRIVER_SEG`, overlay blocks at a random buffer CS held in the stub word, stub-cell exits and the far return protocol of `push cs; call`, cases for every stub cell and the start-up regions; `make test` runs the 68020 forms and blocks corpora and the block test | `tests/m68k_blocks.py`, `Makefile` | wc2 |
| P4: plants for the `cs-slot` variant, stub cells, the overlay CS, the start-up switch and the `push cs; call` return | `tests/m68k_sabotage.py` | wc2 |
| P4: `tests/audit.csv` with WC2's measured counts and reasons | `tests/audit.csv` | wc2 |
| P4: an `indirect.csv` target marked `(isr)` (an interrupt handler the trace entered) is no target of the site; duplicate targets dropped from compare chains; a near target translated at another link CS goes to the dispatcher (counted) instead of a label resolved in the site's CS | `translator/emit.py` | up |
| P4: the `lower_case` stand-ins take `m68k_diff`'s Ctx extras | `tests/{cross_flags_cases,test_carry_entries}.py` | wc2 |
| P4: synthetic module name `WC2.EXE` for `SWOTL.EXE`; the REP stand-in takes the Ctx extras; `Program.ovls` defaults to none (a bare `Program`) | `tests/{test_block_boundary,test_key_release,test_rep_replay,test_rep_lowering}.py`, `translator/emit.py` | wc2 |
| P4: a program or walk plant that leaves the generated text unchanged is deferred, not caught (WC2: the cell-walk and cache plants, the outline plants, the BP-exit plant); `SABOTAGE_JOBS` caps the workers | `tests/m68k_sabotage.py` | up |
| P4: `m68k_blocks` checks every proved switch table (the `indirect.csv` rows with switch targets) from its jump, each target and the stop; fixture memory may depend on the case's CS | `tests/m68k_blocks.py` | up |
| P4: `m68k_blocks --shard k/n`: the sampled blocks and the per-block and per-instruction sections split by index, the other sections in part 0; `make test` and `make test-blocks` run `BLOCK_SHARDS` (8) parts, `test-blocks` at most `BLOCK_JOBS` at once | `tests/m68k_blocks.py`, `Makefile` | up |
| P5: an indirect near `jmp` that is a near return (`annotations/jump-returns.csv`) lowers as `rts` with its target in d7, the caller's return check applying; `is_ret` for the return analysis and the IRQ walk | `translator/emit.py`, `lower.py`, `irq.py` | up |
| P5: a direct near call that pushes a continuation its callee consumes (`annotations/push-calls.csv`) lowers as push and jump, with no native frame and no return site | `translator/emit.py`, `lower.py` | up |
| P5: a CFG seed without a CS takes its `runtime.csv` row's `seg_ip` CS | `translator/cfg.py` | up |
| P5: a `call far` whose traced targets are in `VRAM_MODULES` is a graphics driver call (`rt_vdrv_depth`, `rt_vdrv_return` after it) | `translator/emit.py`, `lower.py`, `src/runtime/rt_entry.s` (comment) | wc2 |
| P5: WC2's machine (MEASURED, host-m0): environment, PSP and MCB names, IVT, BIOS data, the INT 15h AH=C0h configuration table; INT 1Ah AH=00h; the loader reads whole pages as DOSBox-X does | `src/runtime/machine.c` | wc2 |
| P5: the path model (game directory C:\WING2, AH=3Bh current directory, letter-only upper case); AH=4Ah growth into a following free block; AH=33h BREAK flag | `src/runtime/dos.c` | wc2 (path), up (resize, 33h) |
| P5: EMS 46h, 47h, 48h (DOSBox-X's save and restore of the frame mappings) | `src/runtime/ems.c` | up |
| P5: INT 33h AX=4 | `src/runtime/input.c` | up |
| P5: the PIT counter latch (channel 0, `plat_pit_count`), the SB DSP probe, the DAC ports 3C7h-3C9h, 3DAh (`plat_vga_status`); INT 10h AH=08h and AH=12h BL=10h | `src/runtime/ports.c`, `video.c`, `runtime.h`, `platform.h`, `src/platform/host/host.s`, `src/platform/amiga/amiga_platform.c` | up |
| P5: services and captures inside IRQ0's handler compare SS:SP:BP relocated from the private stack (design D8); sabotage `irq-offset` | `tests/host_run.py`, `tests/amiga_replay.c` | up |
| P5: the replay and debug launchers copy the game directory `ref/WING2/`; the early-return stop | `amiga/debug.sh`, `amiga/run.sh`, `amiga/milestone.gdb.in` | wc2 (path), up (stop) |
| P5: unit tests re-pointed at WC2: the mouse IRQ vector F000:CFA0 and m2's mouse surface, the oracle's PSP as the machine's, the MZ entry and +00275 as labels, a fixture BP region, `run()` with its work directory | `tests/test_mouse_irq.py`, `test_dos_sda.py`, `test_host_launch.py`, `test_interrupt_frame_mask.py`, `test_replay_hooks.py`, `test_replay_run_isolation.py` | wc2 |
| P5: `swotl.elf` → `wc2.elf` | `Makefile`, `docs/translator-design.md`, `tests/test_pointer_model.py`, `tools/{ab_runs,align_targets,cost_meter,outline_sites}.py` | ren |
| P5: `make test-host` (m1, m1b) and `make test-amiga` (m1b) | `Makefile` | wc2 |
| P5: lint skips the Amiga build's outputs (`amiga/out`, `amiga/obj`: listings of generated code) | `translator/check.py` | up |
| P5: `m68k_blocks` probes no return protocol after a push-call (no native frame) | `tests/m68k_blocks.py` | up |
| P5: the replay harness stubs carry the merged replay data (point slot, VGA and PIT intervals, hash step, REP stream) and the IRQ-state symbols; the REP test builds its records with `rep_stream`; the joystick-step test checks a loud stop (WC2 records none); hash plant on both compares | `tests/{test_replay_events,test_rep_replay,test_joystick_events}.py` | wc2 (joystick), up |
| P5: the VGA and PIT interval counts compare as objects (a fixture without reads builds under `-Wtype-limits`) | `tests/amiga_replay.c` | up |
| P5: the Amiga build's log, interrupt names and fault prefix say WC2, `$VER` Wing Commander 2 | `src/platform/amiga/{Wc2.cpp,amiga_platform.c,version.s}` | ren |
| P5: VROOMM's INT 3Fh opens no service level in the replay (it never returns after the INT; MEASURED, the m1 and m1b references) | `tests/amiga_replay.c` | wc2 |
| P5: the capture prints no sound-effect cache (WC2 has no SFX path) | `amiga/milestone.gdb.in` | wc2 |
| P5: EMS model with lazy frame pages: a map is a table update and a write-back of a live page; first access copies in (`rt_ems_touch`, `rt_ems_es`, `rt_ems_segments`, `rt_ems_sync`); the runtime's accessors report frame accesses (`rt_frame`) | `src/runtime/{ems.c,runtime.h,machine.c,rt_entry.s}` | wc2 |
| P5: `Ctx.ems`: a guard before every ES access, a check at DS and SS loads (`ems_guard`, `putseg`) | `translator/lower.py`, `translator/emit.py` | wc2 |
| P5: the `ems` variant of the one-instruction cases at the guard's edges, the runtime calls checked; plants for both compares | `tests/{m68k_diff,m68k_sabotage}.py` | wc2 |
| P5: captures show a frame page not yet copied in from its store page | `tests/host_run.py`, `amiga/milestone.gdb.in` | wc2 |
| P5: the EMS test's guest reports each frame access to the model first (`rt_ems_touch`); an alias's writes reach a page mapped again (`map_slot`) | `tests/test_ems.py`, `src/runtime/ems.c` | wc2 |
| P5: the REP test's lowering takes the harness's Ctx fields (`ems`) | `tests/test_rep_lowering.py` | wc2 |
| P5: the replay harness stops on a frame access (`rt_ems_touch` stub) | `tests/test_replay_events.py` | wc2 |
| P5: EMS store access: `rt_ems_es` sets a1 to the ES base displaced onto a non-live page's store page (`rt_ems_es_c` returns the displacement) | `src/runtime/{ems.c,rt_entry.s}`, `translator/lower.py` (docstring) | wc2 |
| P5: the differential's `rt_ems_es` stub moves the access to a shadow and inverts the guest bytes; a1 may end displaced; plant "EMS access ignores the base rt_ems_es gives" | `tests/{m68k_diff,m68k_sabotage}.py` | wc2 |
| P5: the EMS profile counts generated accesses on store pages | `tools/ems_frame_profile.py` | wc2 |
| P5: the profile report takes WC2's label prefixes (`emit.TAG`), leaves out partial first and last fields, and reports field cycles no record carries (up to 2% a field) | `tools/profile_report.py` | wc2 |
| P5: the call tree counts `plat_present` as drawn frames by default | `tools/profile_tree.py` | wc2 |
| P5: the IRQ footprint proof for WC2's handlers (`HANDLERS`: INT 08h +0FD10 and +148E0, INT 0Fh +06F3F): Borland C contexts keyed by constant argument words, leaf-loop unrolling, REP MOVS/STOS as one access, the byte-pair value, narrowing by bounded operands and the slot a register was loaded from, `or`/`and r,r` keeping r, the remainder of a constant divisor, an FFh widening step, facts kept across INT 67h and strongly updated by a store through their form; `irq-bounds.csv` tables; `abs:` classes placed; segment 0 (a null far pointer) no class; `Main.ret_words` for jump-returns; declared sync rows for unreached or implicit accesses | `translator/irq.py`, `annotations/irq-bounds.csv`, `annotations/irq-sync.csv` | wc2 (handlers, rows), up (analysis) |
| P5: a sync access to handler-written memory that lowers to more than one 68k access in straight-line code runs under `rt_irq_hold` (`st`/`sf`; `irq.Proof.held`, `build/gen/irq-hold.csv`); `rt_irq0_ready` and `rt_irq0_take` wait for it | `translator/{irq,emit,gen}.py`, `src/runtime/{machine.c,runtime.h}`, `tests/{m68k_blocks,irq_stress}.py` | up |
| P5: `IRQ_PROOF` on | `translator/gen.py` | wc2 |
| P5: the host-run monitor for WC2: runtime classes placed from their words at entry and as the handler stores them, irq-bounds.csv bounds at entry and return, the buffer rule outside the EMS frame, no delivery a problem; sabotages `irq-footprint`, `irq-sync`, `irq-bounds`; `deliver_int` pops the pending service (VROOMM's INT 3Fh never returns through `rt_exit`) | `tests/irq_monitor.py`, `tests/host_run.py` | wc2 (rows, INT 3Fh), up (checks) |
| P5: `test_irq_footprint` re-pointed at WC2 (the INT 0Fh plants, the ports, the tick write, the sound-state sync row, the held instructions and their plants); in `make test` and `t-sab-irq` | `tests/test_irq_footprint.py`, `Makefile` | wc2 |
| P5: the BIOS model byte F000:FFFE = FCh (AT; MEASURED, the reference) | `src/runtime/machine.c` | wc2 |
| P5: AH=2Fh (get DTA) returns the current DTA in ES:BX (the intro, host-m2); `test_dos_sda` checks it after every AH=1Ah step against DOSBox-X, with a planted wrong BX per step | `src/runtime/dos.c`, `tests/test_dos_sda.py` | up |
| P5: the smoke back to SWOTL's form: pass at 100 live fields, a hand-back before them fails (the translated game runs on; the empty-image form passed only on a loud stop) | `amiga/diag_smoke.gdb` | wc2 (back to up) |
| P6: the Sound Blaster DSP (commands 14h, 40h, D1h) and DMA channel 1 in the port model; `plat_dsp_status` (the device's status timing) and `plat_sb_block` (a block to play, IRQ 7 at its end; the Amiga's stops until open-work 19); an IRQ 7 without a playing block stops | `src/runtime/{ports.c,machine.c,runtime.h,platform.h}`, `src/platform/host/host.s`, `src/platform/amiga/amiga_platform.c` | up |
| P6: host lockstep with the Sound Blaster: DSP status reads replayed (22Ch, 22Eh), blocks checked against the reference's `sound.csv`, INT 0Fh runs from `rt_irq` checked by the monitor on the interrupted stack; sabotages `sb-block`, `sb-irq`, `dsp-status`, `--plants` to run some | `tests/host_run.py`, `tests/irq_monitor.py` | up |
| P6: the replay image answers DSP status reads from the reference | `tests/amiga_replay.{py,c}`, `tests/test_replay_events.py` | up |
| P6: the trace's replay ports take 22Ch and 22Eh; host references log the DSP and DMA ports (`--opl`) | `tools/patches/dosbox-x-wc2-trace.patch`, `tools/pc_run.py`, `tools/reference.py` | wc2 |
| P6: a sync access whose lowering has control flow is held over its straight-line memory prefix when only stack pushes follow (`irq.hold_span`: a far call through a handler-written pointer, WC2.EXE+13F77); `check_atomic` and the emitter share it; `held_text` checks the sf where it puts it | `translator/{irq,emit}.py`, `tests/test_irq_footprint.py` | up |
| P6: the monitor reports each distinct problem once; frame bytes `ems.c`'s `copy` moves inside a handler are the EMS model's (counted); at a hardware interrupt the dead stack is the footprint's stack depth and frame below SS:SP (the reference's IRQ0 handler pushes there) | `tests/irq_monitor.py`, `tests/host_run.py` | up |
| P6: the reference's INT 07h, 11h and 12h vectors (read through null far pointers in the intro, host-m2) | `src/runtime/machine.c` | wc2 |
