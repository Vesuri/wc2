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
| `src/platform/amiga/` except `framework/` and `tfh_paula.*` | copied as is |
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
| `src/platform/amiga/framework/` | taken from AmigaXDev instead (P0.2) |
| `tests/audit.csv` and the tests of SWOTL routines: `test_compute_*`, `test_point_*`, `test_polygon_classify*`, `test_rasterize`, `test_edge_submit`, `test_terrain_*`, `test_ground_vertices`, `test_scenery`, `test_sprite_packet`, `test_line_pixels`, `test_priority_search`, `test_opl_delay`, `test_tfh`, `test_sfx_*`, `test_sound_hooks`, `test_pointer_static`, `test_gameport`, `test_machine_vectors`, `test_amiga_file_sharing`, `test_mouse_scale` | SWOTL routines, fixtures or scenes |
| `tools/`: `swotl_model`, `plink_check`, `load_image`, `ovl_info`, `sweep`, `code_writes`, `compute_oracle`, `native_entries`, `sound_reference`, `sfx_levels`, `pointer_static`, `tfh_*`, `ghidra_import`, `m68k_cost_probe`, `fm_effect_check.cpp`, `fsuae-input-lua.patch`, `install-data/`, release tools (`originals`, `pack_preinstalled`, `package_release`, `check_release`, `test_release_installer`, `test_whdload`) | game-specific: rewritten or adapted in their phase (P1, P2, P8) |
| `whdload/`, `release/` | P8 |
| other docs | SWOTL facts and history |

## Local changes

One line per change to an imported file, newest last: commit subject, files, and whether
it applies upstream (`up`), is WC2 only (`wc2`) or is a rename (`ren`).

| Change | Files | Kind |
|---|---|---|
| Rename `SWOTL_` → `WC2_`, `Swotl` → `Wc2`, `swotl-gen` → `wc2-gen`; `Swotl.{cpp,h}` → `Wc2.{cpp,h}` | 65 imported files | ren |
