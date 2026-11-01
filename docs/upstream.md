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

## Not imported

| SWOTL path | Why |
|---|---|
| `src/runtime/compute_*.s`, `sfx.c` | SWOTL native routines and SPAZ effect capture |
| `src/platform/amiga/tfh_paula.*` | Their Finest Hour samples |
| `tests/audit.csv` and the tests of SWOTL routines: `test_compute_*`, `test_point_*`, `test_polygon_classify*`, `test_rasterize`, `test_edge_submit`, `test_terrain_*`, `test_ground_vertices`, `test_scenery`, `test_sprite_packet`, `test_line_pixels`, `test_priority_search`, `test_opl_delay`, `test_tfh`, `test_sfx_*`, `test_sound_hooks`, `test_pointer_static`, `test_gameport`, `test_machine_vectors`, `test_amiga_file_sharing`, `test_mouse_scale` | SWOTL routines, fixtures or scenes |
| `tools/`: `swotl_model`, `plink_check`, `load_image`, `ovl_info`, `sweep`, `code_writes`, `compute_oracle`, `native_entries`, `sound_reference`, `sfx_levels`, `pointer_static`, `tfh_*`, `ghidra_import`, `m68k_cost_probe`, `fm_effect_check.cpp`, `fsuae-input-lua.patch`, `install-data/`, release tools (`originals`, `pack_preinstalled`, `package_release`, `check_release`, `test_release_installer`, `test_whdload`) | game-specific: rewritten or adapted in their phase (P1, P2, P8) |
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
| `test_load_image` | `tools/load_image.py` (not imported) | P1.4 |
| `m68k_sabotage` plants on `program` and `walk` (37): `tests/m68k_blocks.py` needs generated blocks, and it imports SWOTL's compute and scene predecessor tests (`test_compute_contract` and others, not imported): drop those for WC2's | a module in scope | P1.4 |
| `test_audio`, `test_fm_effect_asm` | TFH and SWOTL's effect capture: rewritten for WC2's effects | P6b.2 |
| `test_display_palette` | its C++ extract does not compile: fails in SWOTL `658fc60` too (`Pointer` undeclared), an upstream fix | P6b.1 |

## Local changes

One line per change to an imported file, newest last: commit subject, files, and whether
it applies upstream (`up`), is WC2 only (`wc2`) or is a rename (`ren`).

| Change | Files | Kind |
|---|---|---|
| Rename `SWOTL_` → `WC2_`, `Swotl` → `Wc2`, `swotl-gen` → `wc2-gen`; `Swotl.{cpp,h}` → `Wc2.{cpp,h}` | 65 imported files | ren |
| Empty scope before P1.4: `tools/wc2_model.py` from `swotl_model.py` (generic parts; no modules, no PLINK); `cfg.build` returns no unit; `gen` skips the IRQ0 proof without units; `pointer_guest` zeros without rows; `lint` names the root; `test_decode` passes on the opcode space alone | `tools/wc2_model.py`, `translator/{image,gen,cfg,emit,check}.py`, `tools/surface.py`, `tests/test_decode.py` | wc2 |
| `tests/audit.csv`: header only | `tests/audit.csv` | wc2 |
| TFH and SPAZ effect capture removed: sample loading, the effect cache and prerender in `Audio`, the `TFH` option, `rt_sfx_*`, the HLE `sfx_start`/`sfx_prerender` entries, the OPL capture path, the `compute_transform.s` include. `plat_sfx_*` stay as host stubs until P6b.2 | `src/platform/amiga/{Audio.cpp,Audio.h,amiga_platform.c}`, `src/runtime/{rt_entry.s,runtime.h,ports.c}` | wc2 |
| Amiga link without TFH and the compute objects | `amiga/Makefile` | wc2 |
| Empty image: with no dispatch rows the platform logs it, keeps the takeover for 200 fields and hands back; the smoke requires that hand-back after 100 live fields | `src/platform/amiga/amiga_platform.c`, `amiga/diag_smoke.gdb` | wc2 |
| DOSBox-X tree `~/.local/src/wc2-dosbox-x` (the renamed patches differ from SWOTL's) | `tools/build_dosbox_x.sh` | wc2 |
| `host_run.Host` hooks the effect capture only when the image has it | `tests/host_run.py` | wc2 |
| Guard plants: two `.s` files while no IR listing exists; planted module names use the root's | `tests/test_guards.py` | wc2 |
| Sabotage plants aimed at `forms` alone run on `forms,boundary` (`forms` is empty until P2; `boundary` catches each, MEASURED): x86 `sub OF = CF`, `disp8 not sign-extended`; 68020 `RMW word at its byte address` | `tests/{x86,m68k}_sabotage.py` | wc2 |
| 68020 sabotage: plants on the `program` and `walk` corpora (the generated program's blocks) print `deferred` while no module is in scope and count neither as caught nor as passed | `tests/m68k_sabotage.py` | wc2 |
