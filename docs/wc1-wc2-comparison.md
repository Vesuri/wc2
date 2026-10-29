# PC Wing Commander I vs II

How much of WC2 (`ref/WING2/WC2.EXE`, installed) is WC1 (`WC.EXE` from the supplied WC1
disk 1, not packed). Purpose: the owner's plan to map WC2 code shared with PC WC1 onto the
native 68k routines of the Amiga CD32 WC1 (sibling project "Wing Commander"). All numbers
come from `make compare`: static, linear decode, no run-time profile yet.

## Build and structure (MEASURED)

| | WC1 `WC.EXE` | WC2 `WC2.EXE` |
|---|---|---|
| Compiler | Turbo C++ 1990 | Borland C++ 1991 |
| Instruction set | 8086 (`mov ax,#; push ax`) | 80186+ (`push #`, `shl r,#`); no 386 code found |
| File / MZ image | 304,976 / 129,472 B | 363,696 / 161,760 B |
| Overlays | Borland VROOMM (`FBOV`), 40 overlays, 162,253 B code | VROOMM, 124 overlays, 184,673 B code |
| Code (resident + overlays) | 230,861 B, 1,256 functions | 279,857 B, 1,426 functions |
| Startup | `mov dx,DGROUP` at `0000:0000`, DGROUP `1231h` | same, DGROUP `1976h` |

Both are large-model Borland C with almost no hand-written assembly (frameless modules:
WC1 2.5 KB, WC2 2.6 KB, the WC2 ones mostly matching WC1). There is no graphics driver
file: the renderer is compiled C in the EXE. Shared driver files are sound: `SUPERTM.DRV`
is identical (both entries), `STRAX.DRV` shares 1 of 3 entries, `TM.DRV` none.

## Code similarity (MEASURED, `tools/wc_compare.py`)

Functions are split at Borland prologues and normalised to be compiler-invariant
(`--norm canon`, see the tool). Shares are of WC2 function bytes (266,729 B):

| Band | WC2 functions | Bytes | Share |
|---|---|---|---|
| identical bytes | 30 | 1,216 | 0.5% |
| same normalised code | 224 | 12,849 | 4.8% |
| similar ≥ 0.95 | 118 | 24,949 | 9.4% |
| similar ≥ 0.85 | 253 | 39,429 | 14.8% |
| similar ≥ 0.70 | 180 | 38,078 | 14.3% |
| no counterpart | 562 | 149,765 | 56.1% |
| tiny (< 6 instructions) | 59 | 443 | 0.2% |

So 29.5% of WC2's code is WC1 code nearly unchanged (≥ 0.85) and another 14.3% is
recognisably a modified WC1 function; from WC1's side, 35.9% of its code has a ≥ 0.85
counterpart in WC2.

Controls: matching WC2 against the unrelated installer (`INSTALL.EXE`, Turbo C++) puts
0.9% of WC2 in the 0.70–0.85 band, and its ≥ 0.85 matches are the shared Borland runtime,
so the bands above are not chance. Without the normalisation (`--norm loose`) the ≥ 0.85
share drops to 16.5%: the compiler change, not the source, hides half the sharing.
Function boundaries are approximate (frameless code joins the preceding function; linear
decode covers 93–95% of the code bytes, the rest being data in code).

## Where (INFERRED: modules labelled by the strings their code references)

| WC2 module | Bytes | ≥ 0.85 / 0.70–0.85 | WC1 module | Reading |
|---|---|---|---|---|
| `O:1858`, `O:1864` | 24,684 | 0% / 0.4% | none | new sprite/plane/sequence/script engine (cinematics) |
| `O:17A4` | 3,899 | 0% / 0% | none | new pilot-file menu (`savegame.wc2`, WC1/SM1/SM2 transfer) |
| `R:073C` | 18,862 | 31% / 17% | `O:10C8` | flight HUD, navigation, messages |
| `O:1764` | 18,325 | 16% / 25% | `O:1135` | weapons and damage |
| `O:1850` | 11,819 | 21% / 49% | `O:112A` | game setup, memory, music loading |
| `R:0BD7` | 10,703 | 64% / 27% | `O:110B` | ship loading, frame timing |
| `R:1207` | 6,975 | 96% / 5% | `R:09C5` | music (MIDI `MThd`/`MTrk`, `strax.drv`) |
| `R:15AD` | 3,231 | 100% / 0% | `R:0E62` | span/sprite drawing ("SPACE BUFFER"), a renderer candidate |
| `R:0000` | 15,519 | 56% / 7% | `R:0000` | Borland runtime and startup |

Full per-module tables: `make compare` (`tmp/compare/`).

## Data (MEASURED, `tools/origin_pak.py`)

- Same container format and the same LZW in both games: a shared file's packed payloads
  are byte-identical; only the flag byte differs (WC1 `01`, WC2 `20`). The decoder
  rebuilds 133 of WC2's installed files byte-exactly; the installer leaves 47 packed;
  `SPEECH.S00` uses another codec.
- 27 file names are common, but the content is mostly new: 40 container entries
  (258,330 of 13,711,477 unpacked bytes) are identical, chiefly 26 Roland tracks of WC1's
  `MUSIC.MID` reused in `MUSIC.R00`, plus `ARROW.VGA`, `CAMP.000`, parts of `FONTS.FNT`,
  `COCKPIT.VGA`, `OBJECTS.VGA`, `TITLE.VGA`. All ship art is new, in the same formats.

## For the reuse plan

- The sharing is real but partial: about 30–44% of WC2's code descends from WC1, unevenly.
  Core flight systems, music and the runtime are largely shared; the cinematics, menus and
  much of the HUD/weapons logic are new or rewritten.
- The hot-path question is still open: `R:15AD` (100% shared) is a renderer candidate, but
  only a profile of the PC reference in flight can say where the time goes.
- The data formats are shared, so WC1's loaders and decoders (container, LZW, sprite
  formats) are the most reliably reusable layer.
