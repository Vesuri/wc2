# VROOMM overlays

Borland's VROOMM overlay manager as linked into `WC2.EXE`. `seg:off` values are link
(unrelocated) values; `WC2.EXE+x` is an image offset (the root's load image, then the
FBOV area at file offset − 6656). Evidence: the disassembly of segment 0F12h (MEASURED
by reading); the model holds over every milestone trace (`tools/vroomm_check.py`: 3102
traps, 208 of them return traps, 1806 reads, 4092 moves, 18 snapshots; 0 violations).
Overlay code bytes after a load are proved by `tools/load_image.py` (gate 1).

## Pieces

| Piece | Where | Fact |
|---|---|---|
| Manager code | `0F12:0000` = `WC2.EXE+F120..FA5A` | init, the INT 3Fh handler, load, eviction, compaction |
| Manager data | `16B8:0000` = `WC2.EXE+16B80` | `[02]`/`[04]` the INT 3Fh vector saved; `[10]` the eviction hook (near: `0F12:0938`, a RET); `[12]`, `[14]` init/exit hooks (RETF); `[16]` far debugger hook (`0000:0274`, a RETF); `[1C]` the file name; `[A0]` the word CD3Fh; `[A4]` the FBOV data position in the file; `[A8]` a quarter of the buffer; `[AA]` the largest overlay + 2 (paragraphs); `[B0]` the allocation point; `[B4]`, `[B6]` the buffer; `[B8]` the file handle; `[BC]` the queue head |
| Segment table | `16B8:00C0..0840` = `WC2.EXE+16C40` | 240 records of 8 bytes: link segment, size, flags (1 root code, 3 overlay stub, 0 data, 4 group), 0. The MZ relocations make word 0 absolute |
| Stubs | `173D:0000..1975` = `WC2.EXE+173D0..1975F` | 124, one paragraph-aligned segment each, in file order |
| Pseudo stub | `16C2:0000` = manager data + A0h | its words 10h, 12h, 1Ch are `[B0]`, `[B2]`, `[BC]`: the heads of the lists |
| Buffer size | `1976:00AC` = `WC2.EXE+19800` | 1370h paragraphs (`_ovrbuffer`); the buffer is max(this, 2 × `[AA]`) |
| Start-up | `_INIT_` record `WC2.EXE+244DC` → `0F12:08DD` | builds the list, allocates the buffer, opens the file, hooks INT 3Fh, preloads |
| Exit | `_EXIT_` record `WC2.EXE+244F4` → `0F12:018C` | restores INT 3Fh, closes the file (never reached in the traces) |

### Stub

A stub is a 32-byte header and `n` 5-byte entries. The file holds the header with
words 10h–1Fh zero, and each entry as `CD 3F off 00` (INT 3Fh, the entry's code offset).

| Offset | Field |
|---|---|
| `+0` | `CD 3F`: the return trap |
| `+2` | the saved return offset (written when frames are redirected) |
| `+4` | file offset of the code, from the FBOV data (dword; init adds `[A4]`) |
| `+8` | code size (bytes) |
| `+0A` | relocation size (bytes) |
| `+0C` | entry count |
| `+0E` | previous stub (unused here) |
| `+10` | buffer segment of the code; 0 when not in memory |
| `+12` | next stub in record order (init list) |
| `+18` | loader (near; `04B8h`, the file reader, for every stub) |
| `+1A` | flags: bit 2 called while in memory but trapped; bit 3 set while it is being loaded |
| `+1B` | probation |
| `+1C` | next in the queue (kept when evicted) |
| `+20 + 5k` | entry k: `CD 3F off 00` while trapped, `EA off seg` (far jump to `seg:off`) while in the buffer |

In the buffer, the code is at the stub's segment `[10]`, IP 0 = its first byte, and the
word at offset 0Eh of the paragraph before it is the stub's segment. An overlay takes
`(size + 11h) >> 4` paragraphs (code and that word); a load needs that plus
`(relocation size + 0Fh) >> 4` free, since the relocation records are read after the code.

## Relocation

The relocation records are words: code offsets of segment words. Each segment word w
becomes the load segment plus word 0 of segment record `w & FFF8h` (`WC2.EXE+F533`).
If bit 0 of w is set, and the bytes around the word are `mov r,seg; push r; mov r,off;
push r` with one register r, an `off` equal to one of the target stub's entry offsets
becomes that entry's stub offset (20h + 5k), so the far pointer goes through the stub
(`WC2.EXE+F578`). One word of the 4579 has bit 0 set (`WC2.EXE+556D0+C0`); its bytes are
not that form. Root code reaches an overlay only through its stub (the MZ relocations
make the stub segment absolute; the offset is the entry's).

## Start-up (`0F12:000B`, `0F12:028D`, `0F12:030D`)

1. The list: the segment records with flag bit 1 and a nonzero size, in record order,
   linked through stub word 12h (a stub with flags FFh would be skipped; none is). Each
   gets the file loader and the FBOV data position added to its file offset.
2. The buffer: `_ovrbuffer` + 1 paragraphs from `farmalloc` (`0000:3228`, INFERRED name,
   `annotations/runtime.csv`); `[B4]` = its segment + 2,
   `[B6]` = `[B4]` + 1370h; `[A8]` = 1370h / 4. The buffer is at 319Ch–450Ch with the
   reference load segment 0824h.
3. INT 3Fh is hooked (`0F12:013B`, AH=35h/25h).
4. Preload: from the first stub in record order, each overlay is placed at the next
   paragraph by the distance of its file offset to the next one's, while the next one
   still starts inside the buffer. They are read in one pass (chunks of FFF0h bytes:
   65,520 and 13,360 bytes in every trace), relocated and queued in order, entries
   patched to far jumps.

## Trap (`0F12:04E6`, the INT 3Fh handler)

INT 3Fh comes from a stub entry (a call of an overlay function, IP after the INT = 22h
+ 5k) or from the stub header (a return into an evicted overlay, IP = 2). The handler
checks that BP is even (else `0000:0257`, "Runtime overlay error"), saves the registers,
and calls the load routine (`0F12:0596`). For an entry, it first moves the saved BP over
the FLAGS word so that the caller's frame heads the BP chain; for a return, the INT's own
frame heads it. After the load it calls the debugger hook and returns with IRET to the
stub, whose entry or header now jumps into the buffer.

Load (`0F12:0596`), for stub S:
1. If S's code is still in the buffer (its entries were reset by the probation sweep
   below): probation 1, flags bit 2.
2. Else: make room for S's need; S goes at `[B0]`; its back pointer; the loader reads
   code and relocation records from the file into the buffer (one DOS read) and
   relocates; S is queued at the tail and `[B0]` advances by its paragraphs.
3. The entries become far jumps to the buffer (`0F12:0664`). If S has a saved return
   offset, the frames that return into S's stub get its buffer segment back, and the
   innermost one the saved offset.
4. Probation sweep: from the queue head, while the free space plus what it has counted
   is under a quarter of the buffer and the element is not the tail, an overlay with
   probation 0 has its entries reset to INT 3Fh and its paragraphs counted; one on
   probation counts nothing.

Make room (`0F12:054C`), for n paragraphs: while the free space is short of n:
- The free space is from `[B0]` to the queue head's segment, or, when there is no head
  or the head is below `[B0]`, to the buffer's end. In that second case the buffer
  wraps first (`0F12:0629`): every queued overlay moves, in queue order, to the top of
  the buffer, and `[B0]` goes back to its start.
- The head leaves the queue. With probation 0 it is evicted: its entries reset to INT
  3Fh, the eviction hook (a RET), segment 0. Otherwise its probation drops by one and it
  moves to `[B0]` and is queued again (a second chance).

Move (`0F12:06D6`): `(size + 1) >> 1` words by `rep movsw` (`WC2.EXE+F81F`, the trace's
`move`), downward or upward as the addresses need; the back pointer; if its entries are
far jumps, the frames returning into it and the jumps get the new segment.

## Return trapping

Resetting an overlay's entries (`0F12:06A3`) walks the BP chain from the current BP.
Every frame whose saved BP is even and whose return segment is the overlay's buffer
segment gets the stub's segment instead; the innermost of them also gets return offset
0, and its old offset goes to stub word 2. That return lands on the stub's INT 3Fh at
offset 0, the return trap, which reloads the overlay and puts its buffer segment and
the saved offset back. Frames with an odd saved BP are passed over. The check sees this
through the 208 return traps: each one enters its overlay at the new buffer segment
and the saved offset.

## EMS and other entries

- EMS caching is off: the eviction hook `[10]` is the RET at `0F12:0938` and every
  stub's loader is the file reader at every snapshot (MEASURED, `tools/vroomm_check.py`).
  The game's own EMS use is separate (docs/external-surface.md).
- The far routines at `0F12:07B7` (buffer segment to stub), `0F12:07ED` (a frame walk
  for longjmp) and `0F12:0885` (load the overlay of a far pointer) have no caller in the
  code and never ran in any trace.
- Overlays install no interrupt handler: every handler the traces took is root code.

## Names

The manager's routines are in `annotations/runtime.csv` (class `overlay manager`) with
the C runtime's, except the three uncalled ones above, which the sweep does not reach.

## Tracer events and the check

The trace patch (`tools/patches/dosbox-x-wc2-trace.patch`) writes `vroomm.csv`:
- `trap` (stub, entry = IP after the INT − stub offset) and `enter`, the first
  instruction in the overlay area after it; interrupt handlers (the timer calls the
  music driver) and DOS do not end a trap;
- `read` (buffer linear, image offset, bytes; inside a trap or not);
- `move` (destination, source, bytes, at `WC2.EXE+F81F`);
- `stub_write` (field, width, the value written) and `frame_write` (writes above the
  trap's SP).

`tools/vroomm_check.py` runs the manager's algorithm on the traced traps and checks
every read and move, the entered address, every stub's state after each trap (rebuilt
from the stub writes), and at every snapshot the stubs, `[B0]`, `[BC]`, the eviction
hook and the loaders in RAM. `--sabotage` breaks one rule and must then fail in every
trace where the rule decides: `second-chance` (6 traces), `wrap`, `sweep`, `position`
(14 traces each; m0's snapshot is the MZ entry, before the manager).
