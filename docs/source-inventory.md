# Source inventory

What the user supplied, in ignored `ref-originals/`. Hashes are committed in `reference/`
and checked by `make extract` (`tools/extract_originals.sh`).

## Archives

| File | SHA-256 | Content |
|---|---|---|
| `001639_wing_commander_2.7z` | `097130c32273598c2641243d4da2152aea359d130e48cd5e17952e1e3ff82b60` | WC2 DOS, 7 × 1.44 MB FAT12 images `disk1.img`–`disk7.img` |
| `001690_wing_commander.7z` | `e03edd637705d9b81b5ac28f3536e41cf3f1eeae52a7b8e7f41f1707e8dd55b5` | WC1 DOS, 3 × 1.44 MB images `disk01.img`–`disk03.img` (cross-reference only) |

Full hashes: `reference/archives.sha256`, images `reference/disk-images.sha256`, the 185 WC2
disk files `reference/disk-files.sha256`.

## WC2 disks (MEASURED, 7zz FAT listing)

All seven volumes have the label `WC2 VF4_00`; volume dates 1991-08-19 21:38–21:52, files
dated 1991-08-19 16:00. No file name appears on two disks, so one flat directory
(`tmp/union`) serves as the installer's A: without disk swaps.

| Disk | Files | Bytes | Notable |
|---|---|---|---|
| 1 | 8 | 1,454,913 | `INSTALL.EXE`, `INSTALL.DAT`, `WC2PAL` |
| 2 | 8 | 1,454,968 | `WC2.LZC` (238,668 B, packed game executable, INFERRED), `MUSIC.A00`/`.R00`, `SPEECH.S00`, `TM.DRV` |
| 3 | 10 | 1,454,551 | `OBJECTS.VGA`, `STARTGLB.000` |
| 4 | 13 | 1,454,233 | |
| 5 | 19 | 1,452,889 | |
| 6 | 27 | 1,449,887 | `SUPERTM.DRV`, `TITLE.VGA`, `WC2LOGO.VGA` |
| 7 | 100 | 918,543 | `STRAX.DRV`, `README.DOC`, `README.LZC`, `WING2.TIM`, `FONTS.FNT` |

## Installer

| Fact | Value |
|---|---|
| `INSTALL.EXE` | SHA-256 `ba2891fdd12154e77da6d62107acfc3e5fdfc186bd7b1ebfd182dbe238392292`, 67,178 B, MZ, header 4,096 B, 894 relocations, entry `0000:0000`, stack `0FCE:0080` (`amigaxdev.dos.mz_info`) |
| Compiler | Borland Turbo C++ 1990 (string) |
| Catalogue | `INSTALL.DAT` (3,720 B) lists every file per disk; strings name up to 15 disks and `WC2.CFG` |
| Options | destination, unpack ("Save Time") or keep packed, graphics, sound, speech; says music needs EMS |
| End message | "Type WC2 to play the game." |

## Memory (from `README.DOC`, the publisher's statement)

- Minimum 583,000 bytes free conventional memory gives the basic game; more memory adds
  speech (4,000 B), music without EMS (20,000 B), then extra space-flight graphics
  (planets, jump flash, larger explosions, debris, cockpit damage), loaded per mission.
- EMS enables further features; with ≤ 100 KB free EMS, speech or instant replay but not
  both. Speech needs 64 KB EMS plus 4 KB base memory.
- Without the Speech Accessory Pack, speech exists only in the first intro scene.
- Playtested under MS-DOS 5.0.

## Installed tree (`ref/`, MEASURED)

`make install` with the fixed answers ([pc-reference-loop.md](pc-reference-loop.md)); two
independent runs gave identical SHA-256 for all 186 files (`reference/install.sha256`).

| Path | Fact |
|---|---|
| `WING2/WC2.EXE` | 363,696 B, SHA-256 `0eb4e54e97a29266b31ec73a149aa5f4a1a32e6b1a1aea74d287f0bfd890393f`; unpacked from `WC2.LZC`, whose header holds the packed size (238,668) at byte 0 and the unpacked size (363,696) at byte 8 (DERIVED) |
| `WC2.EXE` MZ | declared 168,416 B, header 6,656 B, load image 161,760 B, 1,597 relocations, entry `0000:0000`, stack `2776:0080`, min alloc 0; 195,280 B follow the MZ image (overlays, INFERRED) |
| `WC2.EXE` compiler | Borland C++ 1991 (string); EMS diagnostics strings ("Not enough EMS for expanded ships.") |
| `WING2/WC2.CFG` | 12 B, text `v a904 c27`: the installer's answers (VGA, Sound Blaster, speech IRQ 7; encoding INFERRED) |
| `WING2/README.EXE` | 21,280 B, from `README.LZC` |
| `WING2/GAMEDAT/` | 181 files: every disk data file, each unpacked (all differ from the disk copies) |
| `WING2/INSTALL.EXE`, `INSTALL.DAT` | copies from disk 1 |
