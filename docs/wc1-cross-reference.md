# WC1 cross-reference (P7.10)

P7.3's hot routines ([speed-plan.md](speed-plan.md) §9) matched to PC WC1 and to the Amiga
CD32 WC1 (sibling project "Wing Commander"), with the CD32 routine's cost on the 68030
model where that project measured it. This is evidence only. No WC1 code, PC or CD32,
enters the port. WC2's x86 stays the oracle: its constants, rounding, branch order and
tables. Names describe what the code was seen to do; they are not recovered symbols and
do not authorize a native routine (port-plan P7.11, [native-compute.md](native-compute.md)).

## Inputs and addresses

- WC2: `ref/WING2/WC2.EXE` and the installed drivers ([source-inventory.md](source-inventory.md)).
  `WC2.EXE+x` is a load-image offset, `R:seg:off` the original's numbering (`make compare`).
  Driver offsets are file offsets ([drivers.md](drivers.md)).
- PC WC1: `WC.EXE` from the supplied disk 1 (`tmp/wc1/disk01/`, `make compare`), with the
  same numbering.
- CD32 WC1: the English executable that the Wing Commander project pins (`data/wing.english`,
  SHA-256 `0935…e657`, its `inputs.sha256`). `E:x` is an offset in hunk 0, which starts at
  file offset 2Ch. The addresses cited from that project come from its `docs/internals.md`;
  the others were found by reading a local Capstone 68020 decode of hunk 0. That decode is
  not committed.
- WC2 costs: speed-plan §9, the Nav 1 fight on the 50 MHz 68030 model (12 visits, 1.01 M
  cycle units in a 20 ms field). Milliseconds are calls × inclusive cost per call × 20 ms /
  1.01 M (DERIVED); a frame that draws is two visits.
- CD32 costs: the Wing Commander project's `docs/internals.md`, "Phase 11b rendering costs:
  D1". That is the 50 MHz 68030 model with MMU and `CACHE DCACHE`, running its C3
  diagnostic release build (the owner's patches), over one steady Nav 1 window of 639
  pictures. Figures are mean / p95 ms of inclusive elapsed time per picture.
  The 14 MHz 68020 figures are from its "Representative flight costs": the original slave,
  with PC buckets by address range.
- Tools: `tools/wc1_counterparts.py` matches functions; `tools/wc1_span.py` (new) compares
  a frameless helper span with `wc_compare.py`'s normalisation; `tools/cd32_tables.py` (new)
  compares the maths tables in all three games.
- Marks: MEASURED (a tool's output), DERIVED (by reading the code), INFERRED.

## Summary

The 3D maths module and `SUPERTM.DRV` come first, then the rest in §9's order. WC2's cost is
per visit (fight); the CD32 cost is per picture (68030, steady flight).

| WC2 routine (what it does) | PC WC1 | CD32 | WC2 cost | CD32 cost on the 68030 |
|---|---|---|---|---|
| `+0E9B4` `R:0E9B:0004` signed 24.8 divide | `R:077E:000C`, identical bytes (MEASURED) | `E:2bbce` (DERIVED) | 6.66 ms | not measured per routine |
| `+0EA42` `R:0E9B:0092` signed 24.8 multiply | `R:077E:009A`, identical bytes (MEASURED) | `E:2bd42` (DERIVED) | 3.01 ms | not measured per routine |
| `+0ECEE` `R:0E9B:033E` hypotenuse ratio and table lookup (near) | `R:077E:0392`, exact (MEASURED) | ratio part of `E:2c648`; a different table form (DERIVED) | 2.34 ms | not measured per routine |
| `+0EBF8` `R:0E9B:0248` 64-bit integer square root (near) | `R:077E:023A`, exact (MEASURED) | integer square roots at `E:2c0b4`–`2c624`, no call site found (DERIVED / unresolved) | 1.28 ms | — |
| `+0EDBD` `R:0E9B:040D` approximate 3D length | `R:077E:0461`, identical bytes (MEASURED) | `E:2c8bc` (DERIVED) | 3.94 ms incl. | not measured per routine |
| `+0ED8E` `R:0E9B:03DE` unsigned 24.8 multiply (near) | `R:077E:0432`, identical bytes (MEASURED) | inline in `E:2c648` (`2c686`–`2c69c`) (DERIVED) | 0.71 ms | — |
| `SUPERTM.DRV+07460` entry 4: span-list copy (composition) | PC WC1's `SUPERTM.DRV`, identical (MEASURED) | cockpit/view composition `E:2cf0a` (INFERRED) | 4.97 ms incl., 9.94 ms a drawn frame | 3.800 / 3.854 |
| `SUPERTM.DRV+015F5` entry 1: draw one object's image | identical (MEASURED) | scaled `E:2ec98` and rotated `E:2d746` (INFERRED) | 4.80 ms incl. | 0 / 0 in steady flight (68040 model, held turn: 0.187, 0.901) |
| `+0E7E1` `R:0E78:0061` draw list build | `R:0758:0098`, exact (MEASURED) | `E:2c9b6` (DERIVED) | together 5.40 ms incl. | in object dispatch |
| `+0E902` `R:0E78:0182` object draw pass | `R:0758:01B9`, exact (MEASURED) | object dispatch `E:2ca3e` (DERIVED) | (above) | 0.167 / 0.190 incl. |
| `+0DE57` `R:0BD7:20E7` per-slot geometry, once a drawn frame | `O:110B+22AB`, 0.749 (MEASURED) | geometry `E:2a086` (INFERRED) | 7.91 ms incl., 15.8 ms a call | 1.895 / 4.836, all calls |
| `+0C5F2` `R:0BD7:0882` dot product | `O:110B+0924`, exact (MEASURED) | `E:2b8d8` (DERIVED) | 2.57 ms incl. | not measured |
| `+0C35F` `R:0BD7:05EF` vector difference | `O:110B+0568`, 0.923 (MEASURED) | `E:2b7d6` (DERIVED) | 0.64 ms | not measured |
| `TM.DRV+00E93` sprite blit | not compared (drivers) | plain image `E:2efe8`, for draw classes 2 and 4 only (INFERRED) | 15.55 ms incl. | object bitmap 0.144 / 0.165 |
| `TM.DRV+02C07` entry 1: glyph by character code, two-colour remap | not compared | glyphs `E:2fd6a` (INFERRED) | 2.82 ms incl. | 0 / 0 in steady flight |
| `STRAX.DRV` FM entries | 1 of 3 entries shared (MEASURED) | none: the CD32 plays Paula music | 3.44% own | — |
| `+0364A` far block copy (`rep movsw`) | none (best 0.135) | not sought (library copy) | 3.21% incl. | — |
| `+15831` the drivers' memory callback | none | none (no EMS on the CD32) | 6.59% incl. | — |
| the frame (`R:03CA`, `R:073C`, `R:106C`) | none | not matched | 14–19% incl. | — |

## The 3D maths module (WC2 `R:0E9B`, WC1 `R:077E`, CD32 `E:2a9d4`–`2cbd8`)

- **Module.** The CD32 range is the Wing Commander project's "math" PC bucket. In WC1 and
  WC2 the module is resident and frameless, so it is hand-written assembly; the CD32 one
  is 68k assembly too (register save in address registers, unrolled loops). WC2's module
  is WC1's module: each hot routine is identical bytes or the same normalised code
  (MEASURED, `tools/wc1_span.py`):
  - divide `R:0E9B:0004-0092` = `R:077E:000C-009A`;
  - multiply `0092-0101` = `009A-0109`;
  - 32-bit square root `020A-0232` = `0212-023A`;
  - 64-bit square root `0248-02A5` ~ `023A-0297`;
  - square `02D2-02FF` = `02C4-02F1`;
  - exact hypotenuse `02FF-033E` ~ `02F1-0330`;
  - ratio lookup `033E-03DE` ~ `0392-0432`;
  - near multiply `03DE-040D` = `0432-0461`;
  - 3D length `040D-04AC` = `0461-0500`.

  The negative controls, unrelated pairs, score 0.083 and 0.180. WC2 adds a far wrapper,
  `R:0E9B:0232`, and drops WC1's exact 3D length.
- **Tables (MEASURED, `tools/cd32_tables.py`).** The three games' tables agree value for
  value, with a shifted-offset negative control. The 91-entry Q8 cosine table is at WC2
  DS:0BD4, WC1 DS:3C92 and CD32 `E:2bdc2`. The 257-entry arccosine table, in degrees by
  256ths, is at WC2 DS:0C8A, WC1 DS:3D48 and CD32 `E:2be78` (bytes on the CD32). The CD32
  module is therefore WC1's maths carried over with its tables. The trigonometry around
  them matches by reading (DERIVED). WC2 sin `R:0E9B:0101` corresponds to CD32 `E:2bf7a`,
  cos `015D` to `E:2bfe4`, arcsin `01B9` to `E:2c04a` and arccos `01E3` to `E:2c07e`. Each
  pair has the same quadrant arms at 90/180/270/360 and the same ±256 ratio limit.
- **Divide** (`+0E9B4`). WC2 computes the sign-magnitude quotient of a·256 / b by a
  40-step restoring loop (`rcl`: the "long shifts" of §9's x86 forms). CD32 `E:2bbce`
  computes the same quotient in two ways: `divu` when the divisor fits 16 bits, otherwise
  an unrolled 24+8-step loop (DERIVED). The CD32 version returns 0 for a zero dividend
  and 7FFFFFFFh for a zero divisor and for overflow. WC2 has no such case, so the two
  agree only for quotients in range (DERIVED).
- **Multiply** (`+0EA42`). Both take the sign-magnitude 32×32 product and keep bits 8–39
  (WC2: bytes 1–4; CD32 `E:2bd42`: `ror.l #8`). The CD32 version skips two partial
  products when the smaller magnitude fits 16 bits (DERIVED). The Wing Commander
  project's OCS build patched its copy of this routine (`O:2adb6`, "exact signed 24.8
  multiply"). The CD32 address is OCS + F8Ch, as in that project's verified pairs
  (`2acb2`/`29d26`, `2c8dc`/`2b950`, `2a086`/`290fa`).
- **Approximate 3D length** (`+0EDBD`, with `+0ECEE` and `+0ED8E`). WC2 takes a pointer to
  three longs, makes them absolute, and orders them. It then applies a 2D approximate
  hypotenuse twice. Each pass finds the ratio of the smaller to the larger component,
  searches a table for a correction factor, and multiplies the larger component by it
  (`:03DE`). CD32 `E:2c8bc` has the same interface (a pointer to three longs, absolute
  values) and the same two passes through `E:2c648` (DERIVED). `E:2c648` makes an 8-bit
  ratio, by `divu` or by an 8-step loop, indexes a 257-word table directly (`E:2c6a4`),
  and returns max + max·g / 65536, rounded. So the method matches but the table and the
  arithmetic do not. Equal results are not established. `E:2c8dc` is the same length
  compared with a radius·256: the "radius predicate" of the Wing Commander project, whose
  OCS build patched the ratio loop (`O:2b6d4`, CD32 `E:2c660`).
- **64-bit square root** (`+0EBF8`). WC2 uses it through the exact hypotenuse
  √(a² + b²) (`:02FF`) and `:02A5`. The CD32 hunk holds unrolled bit-pair integer square
  roots at `E:2c0b4`–`2c624` and a 32→64 square at `E:2c626` (DERIVED). No call site for
  them was found. The file has no absolute reference to their entries, and the linear
  decode has no branch into the range, while the same search finds 31 absolute
  references to `E:2c8bc`. A computed call is not ruled out, so whether the CD32 uses an
  exact hypotenuse in flight is unresolved. `wc1_counterparts.py` reports "none (best
  0.661)" because the frameless helper is joined to `R:0E9B:0232`.

## Object drawing (`R:0E78`, `SUPERTM.DRV`, `TM.DRV`)

- **Draw list** (`+0E7E1`). WC2 walks the slots and skips the following: class 0, a
  screen x of 7D00h (WC2's off-screen mark), and class 5 or above whose word at
  `[slot+4C0Eh]` is not above 4. It sorts the rest by depth (`[4C9Ah]`, selection sort)
  into a list ended by FFFFh. CD32 `E:2c9b6` applies the same class filter, including the
  ≥ 5 threshold on a per-slot word. It ends its list with FFFFh but sorts through
  `E:2d2c2`. Its culled mark is 8001h, and WC2's geometry writes that mark too (below)
  (DERIVED). WC1 clears 40h list words, WC2 46h (DERIVED). The CD32 starts its slot walk
  from 40h.
- **Draw pass** (`+0E902`). Classes 2 and 4 call `TM.DRV` entry 7 (`+00E93`) through
  DS:DED6. Every other class calls `SUPERTM.DRV` entry 1 (`+015F5`) through DS:DF16, with
  the slot's screen position, image, scale word `[4C0Eh]` and angles (DERIVED;
  `annotations/indirect.csv`). The pass `+0E8C8`/`+0E8F4` before it does the same with
  `SUPERTM.DRV` entry 2 and `TM.DRV` entry 10. CD32 `E:2ca3e` dispatches on the slot's
  class through a 14-entry table. Class 2, the stars, goes to the plain image `E:2efe8`.
  The other classes go to scaled `E:2ec98` (size ≥ 5, clamped to 2000h) or to rotated
  `E:2d746` (DERIVED). The match of draw pass to `E:2ca3e` rests on structure. That
  `SUPERTM.DRV` entry 1 is the scaled/rotated pair, and `TM.DRV+00E93` the plain image,
  is INFERRED. `TM.DRV+00E93` has 76 listed call sites in `annotations/indirect.csv`, mostly outside the object pass (cockpit, HUD, menus), so only
  part of its 15.55 ms is object drawing.
- **`SUPERTM.DRV` entries** (MEASURED from the entry table; DERIVED by reading). Entry 1 is
  `+015F5`, entry 2 `+0153E`, entry 3 `+014F8` and entry 4 `+07460`. Entry 4 is not a
  sprite routine. It walks a list of spans (destination offset, row, length; FFFFh ends
  it) and copies each from a source buffer to a destination buffer through row-offset
  tables, using `rep movsw` at `+074BE` (88% of flight's VRAM bytes, P7.3). It is called
  once per drawn frame, from `WC2.EXE+040E8` in the frame code. That is the CD32's cockpit
  and view composition `E:2cf0a`, which copies the view's spans through the cockpit
  aperture map built by `E:2cc36` (INFERRED: WC2's span list was not traced to the
  cockpit). WC2's entry 4 costs 6.69 ms own and 9.94 ms inclusive per drawn frame. The
  CD32 composition costs 3.800 ms per picture (steady 68030), and 2.9 ms on the 68040
  model.
- PC WC1's `SUPERTM.DRV` holds WC2's two entries byte-identically (SHA-256,
  [wc1-wc2-comparison.md](wc1-wc2-comparison.md)), so every entry above is PC WC1's code.

## Geometry and vector helpers (`R:0BD7`)

- **Per-slot geometry** (`+0DE57`, once per drawn frame). This routine walks the slots and
  skips class 0, class 7 and the view's own slot. It clears the depth `[4C9Ah]` and writes
  8001h to the screen x of class 1. For the rest it forms the relative vector (`:05EF`),
  its length (`R:0E9B:040D`), dot products (`:0882`), perspective divides and multiplies
  (`R:0E9B:0004`, `0092`) and an arccosine (`R:0E9B:01E3`) (DERIVED). CD32 `E:2a086` does
  per slot: 8001h for a culled slot, the vector difference `E:2b7d6`, the length
  `E:2c8bc`, the transform `E:2bb86` (three dot products), divides `E:2bbce`, the arcsine
  and arccosine, and multiplies `E:2bd42` (DERIVED). The match is INFERRED from the same
  recipe and the shared 8001h mark; the per-slot fields were not mapped one to one. The
  CD32 figure, 1.895 / 4.836 ms per picture, counts every call, including the slave's
  own extra rebuilds (1,020 calls over 639 steady pictures in that project's note).
- **Dot product** (`+0C5F2`). Three 24.8 multiplies, summed, in WC2 `:0882` and CD32
  `E:2b8d8` (DERIVED).
- **Vector difference** (`+0C35F`). WC2 `:05EF(a, b, out)` computes out = b − a over three
  longs. CD32 `E:2b7d6(a, b, out)` does the same in the same operand order (DERIVED). The
  CD32 module also has vector add, a − b, negate, clear, test and compare (`E:2b75e`–`2b7d4`),
  scale `E:2b7f0` (WC2 `R:0BD7:0636`) and divide-by-scalar `E:2b820`.

## What the costs can say

The CD32 figures come from a different workload: steady flight in WC1 with the owner's
patches. The WC2 figures come from the WC2 fight on the unpatched translation. So no
saving is claimed here; the price of each native routine is P7.11's W5. These cost facts
stand:

- On the 14 MHz 68020, the CD32's maths range takes 12.15–13.38% and drawing 7.93–8.27% of
  a 98 ms frame. That is about 12–13 ms and 8 ms (DERIVED). For the 68030 the Wing Commander
  project has no maths figure apart from geometry's inclusive 1.895 ms.
- WC2's maths module is 8.95% own of a fight visit, about 14.9 ms, or 30 ms a drawn frame
  (DERIVED from §9). The geometry routine alone is 15.8 ms a drawn frame. Both include the
  translation's overhead (10.8 cycle units an x86 instruction, §1).
- The only per-call cost the Wing Commander project measured for a maths routine is on
  the A500: the OCS radius predicate, 0.223 ms (its "Measured cause and changes"). It
  does not transfer to the 68030.

## Unresolved

- `+0EBF8`'s CD32 counterpart: the square-root code has no call site found (above).
- Equal results for the approximate length: the CD32 table and rounding differ from WC2's.
  A differential test would settle it, but none was run (desk work).
- `SUPERTM.DRV` entry 1 as scaled and rotated, `TM.DRV+00E93` as the plain image, entry 4
  as the composition, and `TM.DRV+02C07` as the glyphs: matched by role (INFERRED). The
  CD32 drawing routines were not read.
- `+0DE57` ↔ `E:2a086`: the per-slot fields were not mapped.
- The CD32's costs for the scaled and rotated images and the glyphs exist only on the
  68040 model in a held turn. The 68030 steady window did not run them.
- `STRAX.DRV` and the frame routines have no CD32 counterpart by design. `+0364A` was not
  sought.
