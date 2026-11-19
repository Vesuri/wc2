# Release

From SWOTL's pipeline (SWOTL `docs/release.md` holds the sibling rules and their
provenance; [upstream.md](upstream.md) the imports). Slave: [whdload.md](whdload.md).

## No original bytes

- Members come from an allowlist (`tools/package_release.py` `members`), never a directory
  sweep. The packager refuses a member whose SHA-256 is an original's
  (`reference/archives.sha256`, `disk-images.sha256`, `disk-files.sha256`,
  `install.sha256`); `tools/check_release.py` repeats it on the decoded archives.
- The checker also refuses any 64-byte block (more than 8 distinct bytes) of the original
  installed files (`ref/WING2`: `WC2.EXE`, the drivers, every `GAMEDAT` file), forward or
  reversed (guest RAM order), at any offset of any member, and member names with the
  original files' extensions. Positive control (2026-11-19): a planted block at an odd
  offset is found forward and reversed; 63 bytes of it are not.
- The installer helper's tables are names and hashes only
  (`tools/install-data/hashes.py`).

## Version

`VERSION` (`0.1`) and the date 19.11.2026 appear literally in: `Wc2` `$VER`
(`src/platform/amiga/version.s`), the slave's `slv_info` and `$VER`, `WC2InstallData`
`$VER` (`tools/install-data/install_config.h`), `Install` (`$VER`, `#exe-version`,
`#exe-revision`), the ReadMe's History, the archive names and the LHA date stamp. The
checker asserts each; nothing is stamped at build time.

## Executable

`make amiga-release` builds `build/amiga-release` with `RELEASE=1` (`WC2_RELEASE`: the
Shell template and tool types take `ANALOGJOYSTICK` only; `MUSIC`, `BENCH`, `KEYS` are
refused), strips it with `elf2hunk -s` to `amiga/out/Wc2-release.exe`, and
`tools/hunk_size.py --release-of` checks that no symbol or debug record remains and every
loadable record equals the unstripped build. The slave loads it as `data/Wc2`.

## Archives

`tools/package_release.py amiga/out/Wc2-release.exe DIR` (AmigaXDev `amigaxdev.release`:
level-0 LH5, fixed DOS stamp, sorted members after the drawer icon):

| File | Contents |
|---|---|
| `WC2-<version>.lha` | the full release (GitHub) |
| `WC2-<version>-whdload.lha` | for whdload.de: without `Wc2`; Install asks for it |
| `Wc2` | the executable, published beside the full archive |

```text
WC2 Install.info
WC2 Install/
  Wc2  Wc2.slave  Wc2.inf  WC2InstallData  Install  Install.info
  ReadMe  ReadMe.info  LICENSE.LGPL.txt
```

Installed: `WC2/{Wc2.slave, Wc2.info, ReadMe, ReadMe.info, data/{Wc2, the game files}}`.
Icons: `release/icons/` (base64, provenance in its README). The checker decodes every member
with Lhasa (`lha pq`), checks header and payload CRCs, the exact member set, byte identity
with the build outputs, HUNK and icon magic, the versions, the ReadMe's headings and the
slave header (flags, Chip, ExpMem, quit key, `ws_DontCache`, Custom1).

## Install

`release/Install` (Installer 43, SWOTL's and the WHDLoad template's conventions): ReadMe
first (MultiView, else More), WHDLoad on the path, a Kickstart 3.1 and RTB warning, the
executable beside the script or asked for (`getversion` must equal `#exe-version.#exe-revision`),
the parent drawer (`WHDLInstPath`), Remove or Keep an existing drawer, Use existing or Replace
installed game files, then the seven disks as images or copied files in a drawer, or the PC
floppies one by one in `PC0:` (copied into `InstallDisks`). `WC2InstallData`
([tools/install-data/README.md](../tools/install-data/README.md)) checks every disk file and
every file it writes by SHA-256 into `InstallStaging`; `data/` changes only after it succeeds,
so a refused source leaves an install as it was. Space: the game takes 17 MB; the install
needs 32 MB free while it runs, 42 MB from floppies (staging beside `data/`, plus the disk
copies; MEASURED from the trees, 14,342,888 bytes installed, 9,639,984 on the disks).

`tools/test_release_installer.py` runs real Installer 43 and the 68020 helper on an emulated
68030 with scripted answers: `fresh` (images), `files`, `floppies` (each disk request
answered by assigning `PC0:` to that disk's files), `keep`, `replace` (over a damaged file),
`remove`, `bad-disks` (refused, install unchanged), `no-exe` and `wrong-exe` (asked for).
The installed tree must equal the original installer's without the DOS programs, saved
games must survive Keep and Replace. `--archive LHA` installs from a release archive.
