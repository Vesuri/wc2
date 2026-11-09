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
| `test_cell_cache`, `test_dos_sda`, `test_dos_search`, `test_ems`, `test_far_return_protocol`, `test_file_dates`, `test_host_launch`, `test_irq_in_service`, `test_mouse_irq`, `test_pointer_model`, `test_interrupt_frame_mask`, `test_key_chords`, `test_keyboard_prefix`, `test_host_replay_visits`, `test_replay_hooks`, `test_replay_run_isolation` | generated labels of SWOTL's guest code (`R_03E64` and others): re-pointed at WC2's | P5 |
| `test_irq_footprint` | an INT 08h handler row in `entries.csv` | P4.4 |
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
