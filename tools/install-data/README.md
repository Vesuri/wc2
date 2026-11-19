# WC2InstallData

Standalone C99 installer helper (port-plan P8.2, D7). Installs the Wing Commander II
game files from the user's seven 1.44 MB floppies, given as a drawer with `Disk1.img` to
`Disk7.img` (FAT12 images) or with the files copied from all seven disks.

- It installs as the original `INSTALL.EXE` does with "Save Time", by the original's
  own file table `INSTALL.DAT` (a method per file): copy, unpack the resource container,
  the speech (`SPEECH.S00`) or the program (`WC2.LZC` → `WC2.EXE`). Formats and their
  derivation: `tools/origin_pak.py`, the Python twin (`make inspect`).
- Checks: every disk file by SHA-256 before use, and every file written by SHA-256
  against the original installer's tree. The tables are generated from
  `reference/disk-files.sha256` and `reference/install.sha256` (`hashes.py`). No game
  bytes in the helper.
- Writes `WC2.EXE`, `WC2.CFG` (the configuration the port runs: VGA, Sound Blaster,
  speech) and `GAMEDAT/`; not the DOS installer or `README.EXE`.
- Destination must be new; on failure or Ctrl-C the files and drawers it created are
  removed. Exit 0 or 20. Needs 2 MB and a 16 KiB stack.
- `io*`, `sha256*`, `start.s`, `COPYING.LIB`: AmigaXDev install-data
  (LGPL-2.1-or-later), vendored unchanged and pinned in `vendored.sha256`. `install.c`:
  LGPL-2.1-or-later.

`make install-data` builds the host helper and the 68020 one (freestanding, no
unresolved symbols); `make test-install-data` runs `test_install.py` (host: both sources
byte-identical to the original installer's tree, refusals, cleanup) and `test_amiga.py`
(the 68020 helper in FS-UAE on the images). Test inputs are local: `WC2_DISK_FILES`,
`WC2_DISK_IMAGES`, `WC2_INSTALLED` (defaults from `make extract` and `make install`).
