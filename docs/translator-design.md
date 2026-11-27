# Translator design

> Copied from Secret Weapons of Luftwaffe `658fc60` ([upstream.md](upstream.md)). Its rules
> and methods apply here; its addresses, measurements, step history and decisions are
> SWOTL's, kept for reference until a WC2 phase re-derives them.

The translator, runtime and test contract as built. Decisions D1–D16 are
settled where this file states them (D1 memory and calls, D2 overlays, D4
registers, D6 flags, D7 indirect transfers, D8 interrupts, D9 display, D11
strings, D15 memory, D16 self-modified code, D10 sound at the end); speed-plan
§8's decisions are cited as "speed-plan Dn". Speed forms are indexed in
[speed-plan.md](speed-plan.md) §7. Overview and guardrails:
[architecture.md](architecture.md).

## Fixed

### Components

| Module | Role |
|---|---|
| `translator/image.py` | proved root/overlay images (`tools/swotl_model.py`), annotations, run-time bytes of self-modified regions |
| `translator/decode.py` | own table-driven 8086 decoder; 186+/FPU opcodes raise (none in SWOTL) |
| `translator/cfg.py` | recursive descent from `annotations/` seeds over a scope of modules; CS along flow; self-modified regions recorded, not decoded, each listed form's successors followed. WC2 (port-plan P3): code ranges root, overlays and driver entries, stub entries as seeds and as far targets, `noreturn.csv`; `image.X86_SCOPE` is decoded and lifted, `image.SCOPE` generated |
| `translator/ir.py`, `sem.py` | IR ops; lifting of every decoded instruction |
| `translator/interp.py` | host IR interpreter (the semantics under test) |
| `translator/gen.py` | `make gen`: `build/gen/<module>.ir` with hash header; coverage report (G6); sizes the R8 alignment pads by assembling the program (vasm) |
| `translator/check.py` | G1 header/digest/regeneration check, G2 lint |
| `translator/lower.py` | one decoded instruction -> 68020 text under the register contract (templates per op family; the IR stays the semantic reference) |
| `translator/flags.py` | flag demand: per-instruction store set and CCR fusion with the next reader, or one past plain instructions |
| `translator/region.py` | BP-stable components, their direct-access range and guards (speed-plan R6) |
| `translator/reuse.py`, `compact.py`, `reglive.py` | run-local rewrites: repeated index/base formations (R13), folded displacements (R14f), native BP (R25), push/pop runs (R31); word-mask compaction within an instruction (R4); DX liveness within a block (word MUL/DIV store DX only where live) |
| `translator/smc.py` | self-modified region as a run-time cell walk with cell cache (D16, below) |
| `translator/compute.py` | admission and emission of `kind=compute` HLE rows ([native-compute.md](native-compute.md)) |
| `translator/emit.py` | program mode: global flag liveness, per-function return sets, leaders, labels, transfers, `build/gen/<module>.s`, `program.s` (assembly root, dispatch table) |
| `translator/support.py` | state-block equates, flag/BCD helpers (`build/gen/support.s`) |
| `src/runtime/` | runtime (C + `rt_entry.s`): machine model of the reference (PSP, environment, MCBs, IVT values), EXEC of `SWOTL.EXE`, INT 21h/10h/16h/33h/67h services, `rt_*` entries, dispatch lookup with PLINK residency; platform interface `platform.h` |
| `src/platform/host/`, `src/platform/amiga/` | `platform.h` for Unicorn (harness-served stubs) and AmigaOS (dos.library, private native stack) |
| `tests/` | `host_run.py` (generated program + runtime on Unicorn 68020 to a milestone vs the reference; `--amiga` capture; `--sabotage`), `test_decode.py` (Capstone), `x86_diff.py` + `x86_sabotage.py` (Unicorn x86-16), `m68k_diff.py` (instructions/short blocks, test mode) + `m68k_blocks.py` (generated program, traced blocks) + `m68k_sabotage.py` (Unicorn 68020), `test_guards.py` (G1/G2 plants), `audit.csv` (audit expectations), `uc.py` (ctypes binding) |

Language: Python 3.11 (sibling tooling, Capstone binding present). Offline,
so translator speed is irrelevant.

### IR

Specification in `translator/ir.py`. Per instruction: an op list over
width-typed temporaries with local labels (REP loops, CL-count guards,
divide checks), explicit stack traffic, and one exit (`jump`, `call`,
`ret`, far forms, `int`, `fault`) or fall-through. Flags: `flags kind w a b
r` defines the status flags of `kind` and marks the undefined ones
(`FLAG_KINDS`; count-dependent for shifts/rotates); reading an undefined
flag is an error, never a value. Guest registers 16-bit with explicit
8-bit halves; segment registers separate; FLAGS bits 12–15 as `flagsx`.
Listings in `build/gen` carry `(module, offset, CS:IP)` per instruction.

### Generated code contract

Registers (D4, fixed program-wide; spill audit 0):

| 68k | Guest | Rule |
|---|---|---|
| d0 d1 d2 d3 d4 d5 | AX CX DX BX SP BP | low word; upper word undefined (speed-plan R4); SP and BP mirrored: offset ^ 7FFFh |
| a4 a5 | SI DI | same (not mirrored); `movea.w` loads, dead-flag add/sub/inc/dec in place |
| a1 a2 a3 | ES SS DS base | a6 − seg*16 − 7FFFh, recomputed on every segment write |
| a6 | guest RAM | TOP = linear 0, byte-exact and reversed (linear L at TOP − L); state block above |
| d6 d7 a0 | scratch | a0 also CS base (`lea (-cs*16-7FFFh,a6)`); CS is static per instruction |
| a7 | native stack | `jsr`/`rts` only |

State block (`G_*` equates at a6+1..a6+16): `G_FL` low byte = CCR image of
CF (C), OF (V), ZF (Z), SF (N), X not guest state; PF = even parity of
`G_PF`; AF = bit 4 of `G_AF`; `G_DF`/`G_IF`/`G_TF` bytes; `G_FX` = FLAGS
bits 12–15; `G_ES`/`G_SS`/`G_DS` segment values. Run-time CS =
`LOADSEG+link`, `LOADSEG` = 0822h (the reference load segment, so guest RAM
diffs directly); relocated words in instructions are emitted as
`LOADSEG+value`.

- Upper words (speed-plan R4): a lowering that reads a guest register's 32
  bits zero-extends it first (`read_zx`: segment loads, the cell walk's entry
  IP from an indirect call); the REP fast path converts SI/DI from their low
  words; the runtime masks what it takes.
- Segment loads in `annotations/seg-repeat.csv` (R30) compare the new value
  with `G_xS` first; only a change stores it, checks the cell caches and
  rebuilds the base, out of line (`lower.putseg_repeat`).
- Memory (D1, speed-plan R1): a little-endian word at linear L is the native
  word at TOP − L − 1 (68020 allows odd addresses), no byte swaps. The byte
  at offset o is `(7FFFh−o,aS)`, the word `(7FFEh−o,aS)`; a computed offset
  is mirrored into d7 (`move.w #7FFFh−disp` / `sub.w Rn`, or from a mirrored
  register `move.w Rn` / `sub.w #disp`) and indexes as `(0,aS,d7.w)` /
  `(−1,aS,d7.w)`, keeping the 16-bit wrap; SP/BP alone index directly. A word
  at offset FFFFh is two consecutive linear bytes. Push is `addq.w #2,d4` +
  `move.w v,(−1,a2,d4.w)`. A run of four or more pushes (pops) with no leader
  between steps SP once in its first instruction, `bvs` (only that step can
  overflow d4.w: the run wraps SS:0) to the exact lines out of line; the rest
  address from the final SP (`reuse.stack_runs`, R31; R29 for CALLF's long
  push). SP/BP as values convert with `eori.w #$7fff`
  (dead-flag add/sub/inc/dec, NOT and `or/and/test r,r` stay in place).
  Byte and word memory operands fold into the 68k op (source, read-modify-
  write destination, INC/DEC/NEG/NOT, CMP with an immediate) where AF and
  PF are dead.
- BP regions (speed-plan D2 and R6, `region.py`): a BP-stable component (the
  code after a BP write up to the next, calls continuing at their return
  site) chosen in `annotations/bp-regions.csv` (`tools/bp_regions.py`, from
  a meter run) gets a guarded copy (`<label>_bp`) in which `[bp+d]` and far
  pointers at `[bp+d]` are `(−d,aS,d5.w)` / `(−d−1,aS,d5.w)`: d5.w
  sign-extends to 32767 − BP, so this is exact while 0 ≤ BP + d ≤ FFFFh.
  One range check on d5.w covers every displacement of the component: at
  its entry after the BP write (`<S>_bpg`) and after each call or software
  interrupt in it (`<S>_bpr`); a failure continues in the exact code, as do
  exits, BP writes, poll stubs and divide-error retries. Entries, those
  return points and where a copy run falls into the exact code are leaders (a
  guard clobbers the CCR; the run passes start afresh there). Tools that hook an
  instruction's label (host run) hook its copy too.
- Flags (D6): a setter stores the defined flags live after it (`flags.py`,
  global liveness in `emit.py`). The next instruction reads the CCR directly
  when it is not a leader, reads only flags the setter's 68k op holds with
  x86 meaning (`CCR_OK`), and the setter's tail leaves the CCR intact; else
  readers load `G_FL`. Plain instructions (no flags, no transfer) may stand
  between the two (speed-plan R3b). Their 68k lines keep the CCR, or the
  last one that changes it moves the setter's result register at its width
  (unchanged since), which leaves N and Z equal to SF and ZF. PF/AF are
  stored as result / `a^b^r` bytes only when live. adc/sbb/rcl/rcr take CF
  from X when the instruction before (not across a leader: add, sub, adc,
  sbb, neg, shifts) leaves X = CF, else from `G_FL`; an adc/sbb operand
  setup that changes X keeps it in d6 (`subx.b d6,d6` first, `add.b d6,d6`
  before the setup's load into d6, R28). Z is preset for `addx`/`subx`.
- Strings (D11): per-element loops, one body per DF; the backward body is
  out of line and rejoins the forward body's continuation (R21). REP with DF = 0,
  CX ≠ 0 and SI/DI + size × CX < 10000h takes a fast path with host pointers
  descending: `move -(a4),-(a5)`, `move d,-(a5)`, `move -(a4),d6` + `cmp
  -(a5),d6` or `cmp -(a5),d` with `db<cc>`, the last pair's flags
  recomputed. REP STOSW and REPE CMPSW move or compare two words per
  `move.l`/`cmp.l` (speed-plan R12: an odd element alone, a mismatching
  long's guest-first word first), eight longs per pass (R24: STOSW stores
  a first word to long-align; R26). Checked by the boundary corpus (guard and
  stop edges, overlap) and sabotage plants.
- Calls (D1): the guest stack stays byte-exact; a guest call is `jsr` and
  returns with `rts`. Near returns carry IP in d7.w; RETF and IRET carry
  CS:IP in d7.l (R33). RETF pops one long after a word SP step guarded by
  overflow; a wrap pops the two words out of line, wrapping SP between
  them. IRET pops flags and words separately, then packs the pair.
  Return sites compare the near word or far long and branch to a module-local
  `<tag>_rm<n>` trampoline after a run that cannot fall through. Far failure
  normalizes CS into d6 before the fail-loud diagnostic. A PLINK
  manager call's return site is 2 bytes later (the manager advances the IP).
- Indirect transfers (D7): compare chain over the known targets
  (`annotations/indirect.csv`); a proved switch table falls back to
  `rt_stop_unknown`, other sites to `rt_dispatch_near`/`rt_dispatch_far`
  (target in d7, CS in d6). The first walk call falls through to its return
  check; its remaining targets and fallback are out of line, with both walk
  range checks retained (R22). Table rows (`program.s`): the cfg seeds (MZ
  entry, PLINK thunks, `runtime.csv`, `indirect.csv` targets) as (CS, IP,
  overlay id, far, label); overlays sharing an area share CS:IP, so the row whose
  overlay is resident (PLINK record bit 15) wins; anything else stops.
  `far` = 0 for a row seeded only as a target of indirect near `jmp`/`call`
  sites: `rt_dispatch_far` (and interrupt delivery, the guest entry) stops
  there (R14e).
- Layout: runs in offset order, stubs (poll, cold paths) after a run that
  cannot fall through. A forward jcc listed in `annotations/outline.csv`
  (R27) branches, inverted, to its fall-through range, which goes first among
  the stubs after the next closing transfer and ends with `bra` to the target
  unless it ends in a transfer; every instruction keeps its lowering.
  `build/gen/outline-sites.csv` lists every eligible site and where its range
  would go.
- Runtime entries (`jsr`, contract in registers): `rt_int` (d7 next IP, d6
  CS << 16 | vector; the runtime writes the CPU's IRET frame below SS:SP;
  services read no guest flags and leave undefined-by-them flags in the
  state block; a vector pointing into the program's memory runs the guest
  handler on that frame), `rt_fault` (same d6/d7; returns to re-execute),
  `rt_in8/16`, `rt_out8/16` (d7 port, d6 value), `rt_halt`,
  `rt_stop_unknown` (prints and halts; never resumes).
- Returns: a `ret` continues at the return sites of the calls whose targets
  reach it without entering a call (the divide-error edge is not flow); an
  indirect near `jmp` in `annotations/jump-returns.csv` (a routine that pops
  its return IP into memory and leaves through it, Borland's `_setargv`) is such
  a return: `rts` with the target in d7, checked at the caller's return site. A
  direct near call in `annotations/push-calls.csv` pushes a continuation its
  callee consumes (`pop cx; add cx,3; jmp cx`, or a drop): push and jump, no
  native frame, no return site;
  calls through the dispatcher return from any `ret` a table row reaches
  (far calls: a far row, R14e).
- Generated files: `build/gen/<module>.s`, `support.s` and `program.s`
  (equates, runtime xrefs, includes, dispatch table, `load_segment`,
  `overlay_table`), header = SHA-256 of translator sources, annotations and
  input image (`make gen-check`). One assembly unit (`vasm -Felf`), linked
  with the runtime: `make host` (`build/host/wc2.elf`), `make amiga`.
- Overlays (D2 = a): every translated module resident in native code; the
  guest's own PLINK manager runs translated and loads the overlay bytes into
  guest RAM (data, CS-relative reads, RAM equal to the reference).
- WC2: VROOMM overlays and dynamic CS (port-plan P4.2, P4.3; [vroomm.md](vroomm.md)).
  `LOADSEG` = 0824h (the milestone load segment). Drivers (`TM.DRV`, `SUPERTM.DRV`,
  `STRAX.DRV`) are modules at static CS `LOADSEG + DRIVER_SEG` (`emit.DRIVER_SEG`, the
  reference's load paragraphs, [drivers.md](drivers.md)); a driver loaded elsewhere
  reaches no row and stops. Each of the 124 overlays is translated once at link CS =
  the paragraph of its image offset; its run-time CS is the word at offset 10h of its
  stub, the manager's own residency record (0: out), read in guest RAM
  (`emit.cs_slot`): `push cs`, far pushes, far return checks, `cs:` bases (d7 and the
  CCR saved around the base), dispatch d6, interrupt and fault d6 and poll stubs.
  The plan's state-block slot is not used: the manager rewrites the record on every
  load, and reading it keeps the original's decision exact.
  - Stub cells (`emit.stub_cells_text`, label `R_<off>_cell`): a far call to stub
    entry k jumps to its cell, which reads the entry's bytes: `EA off seg` with `off`
    the entry's own offset and `seg` the stub's word 10h branches to the overlay
    entry's native label; `CD 3F off 00`, and the header's `CD 3F`, are
    `jsr rt_int` (vector 3Fh, d7 the IP after it); anything else stops. A cell's
    flags are its continuations': the INT 3Fh handler (WC2.EXE+F606) swaps the FLAGS
    word with BP around the loader and IRETs, so the overlay entries join the
    dispatcher's live union.
  - Rows: an overlay row is (stub CS, IP, overlay id = 1 + file order); the runtime
    takes the overlay whose stub word 10h equals the CS (`machine.c overlay_row`).
    Return sites of far calls in overlay code (trap sites) are far rows. A RETF or
    IRET return mismatch re-dispatches far (`rt_ret_far_mismatch`): the INT 3Fh
    IRET returns to the entry or to a return address the manager redirected. A near
    mismatch and hardware interrupt delivery still stop.
  - `push cs; call near` is a far call (P4.3): its return check is far and the callee
    must reach only RETF (checked at generation).
  - Self-modified start-up code (`annotations/self-modifying.csv`): a region whose
    forms are whole instructions (+1ED, `ja`/`jb`) is a switch comparing guest bytes
    with each form, then that form's lowering (a leader, every flag live after it);
    no match stops. An operand region (+1DC, the `imm8` of `mov ah` at +1DB) is
    lowered as a load of those bytes through CS.
  - Checked by `tests/m68k_blocks.py` (overlay blocks at a random buffer CS held in
    the stub word, cells in every form, both start-up regions) and the 68020
    differential's `cs-slot` variants (a run whose lowering reads CS, again with CS
    from guest RAM).
- WC2 EMS model (port-plan P4.5, C3). WC2 maps 4 physical pages of a 164-page handle
  with INT 67h AH=44h, about 5–15 maps per timer tick, 218,641 maps to m6
  ([external-surface.md](external-surface.md) "EMS", MEASURED). To m1b generated code
  reads the frame 5,455 times (10,910 bytes), all through ES = E000h, page 0, in the
  EMS heap routines (+15183..+159CF); copying every mapped page in and out moved
  82 MB (MEASURED, `tools/ems_frame_profile.py`). Built (lazy pages, store access):
  the logical pages' storage after the state block (reversed, as guest RAM) is the
  truth and a frame page holds its mapped page's bytes only while it is live
  (`ems.c`). A map writes a live page back and leaves the new one in the store:
  - before every instruction that accesses memory through ES (`lower.py ems_guard`):
    `cmp.w #$d001,G_ES(a6)` / `bcc` out of line to `rt_ems_es` (d7 offset, d6
    bytes; 0 for a string instruction: the whole ES window), which sets a1 for the
    access: an access within one frame page whose page is in the store only (not
    live, no live alias) gets the ES base displaced onto the store page and runs
    there without a copy; anything else (a string, a wrap at FFFFh, a live page)
    gets the plain base with the pages copied in. So a1 is the plain ES base only
    while ES is below D001h; the access follows its guard's return label, which no
    register formation crosses (`reuse.py`). X kept, the CCR saved where flags
    enter in it. An access within one frame page, or two with one displacement,
    decides in `rt_entry.s` `EMS_GUARD` from `rt_ems_fast` (`ems.c refresh`, after
    every change of a mapping or a live page: the displacement, 0 for the frame, 1
    for the C path), the rest in `ems.c guard` (X-Wing `5f720a2`). A one-entry cache
    per segment register (`rt_ems_cache_es/ds`: the segment, the offsets of the frame
    page the last displaced access lay in, the base; X-Wing `4c50051`) answers a
    repeat; every refresh empties it, and an interrupt's handler puts it back with
    the frame pages (`rt_ems_irq_leave`), or leaves it empty after a changed mapping;
  - a string instruction passes the lowest of its operands through the segment and
    the bytes to the last one's end (size times CX, plus the SI-DI distance; 0 with DF
    set: the whole window), and lods/xlat with ES: are guarded; an access across frame
    pages runs on the store when their pages lie as the frame pages do (the store is
    reversed, as guest RAM: `ems.c store()`); from X-Wing `5f720a2`;
  - listed code (`annotations/ems-ds.csv`, D17) guards its DS accesses the same way
    (`rt_ems_ds`, a3), its DS loads copy nothing, and before every transfer that may
    leave it (RETF, IRET, INT, INTO, a far CALL or JMP not into listed code) and after a
    range's last instruction a DS still at D001h or above has its pages copied in
    (`rt_ems_ds_leave`, counted in `rt_ems_ds_exits`). `emit.py` refuses a near call
    into a range, a direct near transfer out of one and an indirect near one inside
    one, but in a range that covers its whole module (TM.DRV, SUPERTM.DRV: their near
    transfers stay in their own CS);
  - a restore row (`ems-ds.csv` kind `restore`: X-Wing `5f720a2`'s kind, with a runtime
    condition, as WC2's INT 08h handler maps) is a POP DS outside listed code whose
    straight-line run to its far exit (IRET, JMPF, RETF) or the next DS load accesses
    nothing through DS (`emit.py ems_restore_problem`, controls in
    `tests/test_ems_restore_rows.py`); its load of D001h or above calls `rt_ems_restore`,
    which copies nothing inside an interrupt's handler reloading the DS the handler
    interrupted (the handler's return then gives the interrupted code its pages, below)
    and anywhere else copies in as any DS load (counted in `rt_ems_restore_falls`).
    The rows are the INT 08h chain's restores of the interrupted DS (WC2.EXE+0FD87,
    STRAX.DRV+1468): with listed code interrupted at DS in the frame they cost 16 page
    copies an interrupt (MEASURED, P7.6 E5 in speed-plan.md);
  - elsewhere DS and SS accesses are not guarded: a load of D001h or above (`putseg`), a
    service's return (`rt_ems_segments`) copy in the pages their windows meet, and a
    map copies in at once a page DS or SS addresses;
  - an interrupt's handler, which production runs at any instruction (also between a
    guard and its access), leaves the frame pages as it found them when the mapping is
    the same (`rt_ems_irq_enter`/`rt_ems_irq_leave`: a page it left live is written back
    and hidden, one it hid copied in again); a changed mapping is the guest's, DS and SS
    then get their pages (`rt_ems_irq_remaps`, 0 at m4 and m5, MEASURED);
    `host_run.ems_irq_problems` checks it on the run's image (plant `ems-irq`);
  - the runtime's accessors copy in (`runtime.h` `rt_frame`: DOS reads into the frame).
  Captures show a page not yet copied in from its store page (`host_run.frame_view`).
  To m1b (MEASURED, same tool, copies by cause): lazy pages alone copied 20.7 MB (ES
  copy-in 8.2 MB, write-back at maps 10.4 MB, DS/SS copy-in 2.2 MB); with store
  access 5,389 of the 5,455 generated accesses run on a store page and the model
  copies 5.7 MB, all from DS/SS loads (copy-in 2.8 MB, their write-back at maps
  2.9 MB); runtime accessors copy nothing. The lockstep passes. The 68020
  differential runs every one-instruction case that accesses through ES or loads DS
  or SS a second time with the guards (`ems` variant), ES (or the loaded register)
  at one of the compare's edges (D000h, D001h, DFFFh, E000h, EFFFh, F000h, FFFFh) on
  both sides, and checks the runtime calls (`m68k_diff.ems_diffs`); its `rt_ems_es`
  stub moves each non-string access's bytes to a shadow and inverts the guest
  bytes, so an access that does not use the a1 it leaves fails. Plants "EMS guard
  misses ES D001h", "EMS access ignores the base rt_ems_es gives", "EMS DS/SS load
  check misses D001h"; dropping the displacement in `rt_entry.s` fails the m1b
  lockstep. The stubbed guard itself is checked on the run's image before every
  lockstep run (`host_run.ems_guard_problems`, plants `ems-fast`, `ems-cache`,
  `ems-cache-irq`). Whether the DS/SS copies matter is the first target profile's (P5.4).
- Memory (D15 = b): Fast RAM required (1.36 MB code at R34 + 1.06 MiB guest RAM);
  the A1200 model runs with 8 MiB Fast; development runs set `--cpu=68030`
  (`AMIGA_CPU`, ~3× the 68020: logo at 80 vs 252 frames); timing runs
  leave it unset (68020).

### Annotations (`annotations/`, CSV)

`entries.csv`, `indirect.csv` (site -> targets; written by `make map`),
`jump-returns.csv` and `push-calls.csv` (Returns, above),
`tables.csv` (cs: word tables sized by evidence other than an MS C bounds
check, read by the sweep), `runtime.csv` (runtime entries: name, `seg_ip` the CS a seed without one takes,
class, evidence), `self-modifying.csv` (D16 regions and cell forms),
`flags.csv` (PUSHF/POPF pairs that only save and restore FLAGS: the save keeps the
status flags live after its POPF; a row whose save is no PUSHF or restore no POPF, or
a second row for one save, is a translation error; the program block test compares
the saved word's other status bits as dead, as host lockstep's dead stack),
`hle.csv` (guest range, service, reason, oracle; below), `align.csv`
(R8 pads; `tools/align_targets.py`), `bp-regions.csv` (BP writes whose
component gets a guarded copy; a profile choice, `tools/bp_regions.py`),
`outline.csv` (forward jcc whose fall-through range goes out of line, R27;
a profile choice, `tools/outline_sites.py` from `build/gen/outline-sites.csv`),
`seg-repeat.csv` (segment loads that compare first, R30; a profile choice,
`tools/seg_repeat.py`), `irq-bounds.csv` (value bounds of variables that index
the IRQ0 handler's accesses, and class extents, I2), `irq-ds.csv` (entries that return the
caller's DS where the I2 analysis cannot see it; host runs check, I3) and `irq-sync.csv`
(monitored accesses the I3 monitor found meeting the footprint: sync for the declared span).

### Tests

- Instruction differential (`make test-m68k`): the x86 corpora (forms,
  space, boundary, blocks) lowered in test mode (every exit through a stub,
  all flags live at the end), Unicorn x86-16 vs Unicorn 68020 on the same
  guest-memory layout; registers, segments, CS:IP, defined flags, FLAGS
  12–14, memory, OUT sequence, interrupt/fault. A case with a direct
  `[bp+d]` form also runs behind a region guard (copy, exact fallback).
- Block differential (`make test-blocks`, in `--shard` parts): the generated program as emitted,
  run from executed leaders to the first transfer with random states. Every
  branch to an instruction's label targets a leader (copy exits, divide-error
  retries: `lower.exit_fault` re-executes the instruction), except exact code
  branching to its own fall-through (R27). Guest CFG
  exits remain stopping boundaries when a zero-code jump aliases its target;
  direct zero-code entries stop without executing the target. Each outlined
  jcc (R27) runs from the leader that falls into it, and its fall-through
  range as paths from there (registers and the words a path loads at edge
  values or its immediates; cases taking a jump on the way are skipped). Flags
  compared where live at the successor reached (at a cell walk: live at the
  transfer; the walk reads no flags); calls also run the return protocol
  (right IP/CS reaches the return site, wrong IP or CS reaches the mismatch
  handler; near IP’s upper word random, far CS:IP packed). Register calls and jumps that
  can enter a self-modified region also run with the target in each region.
  Every executed block of a guarded copy runs with BP at both ends of the
  range its guard admits and inside it; every guard runs just inside and
  outside that range. Every `annotations/tables.csv` row also runs from
  its call site to the target read from the original table, then every
  reachable block runs against x86, including untraced targets.
- File dates (`tests/test_file_dates.py`): live DOSBox-X find-first/next
  over synthetic files verifies Amiga DateStamp conversion and runtime
  DTA time/date, including leap centuries, pre-1980 wrapping and odd seconds.
- Host run (`make test-host`, gate 5): `build/host/wc2.elf` on Unicorn
  68020 from the MZ entry to milestones m1–m3 (`make test-host-all`: m1–m7,
  the Makefile's `HOST_COVERAGE` scenarios and `t-hle-music-skip`; files the
  guest writes are kept in memory); every software
  INT's registers at entry and return vs the tracer's service log; registers
  and RAM (environment MCB to A0000h) vs the snapshot, dead stack masked
  (below SS:SP at a service, and the FLAGS image of an `annotations/flags.csv`
  PUSHF, until the guest rewrites it); at m1b-logo the A0000h window and the
  DAC; machine bytes the guest read hold reference values; every guest
  access against the IRQ footprint (`tests/irq_monitor.py`, irq-plan I3:
  handler accesses inside it, runtime classes placed from their words at entry and
  as the handler stores them, the irq-bounds.csv bounds at entry and return, main
  accesses meeting it only from sync instructions, IF clear or services, no
  generated write into a buffer byte between two handler reads of it; record
  `tmp/test/irq-monitor-<run>.json`; sabotage `irq-footprint`, `irq-sync`,
  `irq-bounds`).
  `make test-amiga`: the same at m1b-logo on the A1200 model (FS-UAE,
  `amiga/milestone.gdb.in`), plus the shown screen (bitplanes, colour
  table) decoded against the reference framebuffer and DAC.
- Amiga replay (`make test-amiga-replay`, also in `make gates`): separate
  diagnostic images for m2-choose-side, m5-player-flight, c9-mouse-menu,
  c66-flight-calibration and c85-joystick-calibration.
  Translator hooks preserve native registers/CCR and split diagnostic
  entries at block boundaries; the normal generated bodies are unchanged.
  `tests/amiga_replay.*` replays DOSBox input and interrupt groups at their
  recorded sync visits/service counts through the production IRQ glue.
  Every service prefix checks registers, segments, vector, IF and DF;
  final counts, guest state, DAC and shown bitplanes must match the original.
  The final guest state is held while its queued frame reaches the VBI.
  Only diagnostic builds disable physical input and the CIA timer; normal
  hardware, smoke and restoration gates remain mandatory. No reference,
  sync point, normal interrupt order or PIT rate changes.
- Display (D9 slice): only the graphics driver (`emit.GRAPHICS_DRIVER`,
  RTSVGA) writes video memory. Before each of its memory stores the
  lowering checks the segment for A000h and calls `rt_vram_mark` (offset,
  bytes; `rep stos/movs` once for the whole run), which widens per-row
  changed columns; a store with no driver call in progress stops. The `jmp
  far` of each PLINK thunk into the driver is a `jsr` counted in
  `rt_vdrv_depth` (WC2: each `call far [mem]` whose traced targets are in
  `TM.DRV` or `SUPERTM.DRV`, every `call far [V]` through a pointer slot such a
  call reads, and every one through a slot the game's driver loader fills
  (`annotations/driver-slots.csv`), `emit.driver_calls`: 323 brackets in the output, 179 by traced targets alone, MEASURED; a dispatch into a driver from
  another site stops at its first VRAM store); the outermost return publishes the frame
  (`rt_vdrv_return`). The game's mouse poll (INT 33h AX=3, after all of a
  frame's drawing) ends a frame (`rt_video_frame`): its changed rows go to
  `plat_present` as 32-pixel-aligned rectangles there if a vertical blank is
  due, otherwise at the next one (`rt_present_due`; Amiga: the field task,
  host: always due) while no driver call and no main-thread present or video
  BIOS call runs; publications between polls are not presented, so an erase
  and its redraw (PANEL gauges) are never shown apart (user 2026-10-28).
  Before the first poll, or after one second of IRQ0 deliveries without one,
  each publication presents as before. Frame cap (production Amiga,
  `rt_frame_cap`; user 2026-10-29): a poll that ends a drawn frame (a
  publication since the previous poll) returns at most once per field
  (`rt_fields`), waiting with the service's tick hold lifted so IRQ0 runs; a
  poll with nothing drawn since the previous one returns at once (user
  2026-11-27: each flight frame polls twice, the pointer hook `WC2.EXE+10851`
  ending the frame and the empty event queue's position read `+108B8` in the
  same field, MEASURED on the 68030 model; capped, the second waited a field); the
  game's loop never reads the retrace, so on a fast CPU it would outpace the
  display, and each frame takes at least a field of mouse motion (AX=0Bh, the
  flight stick). Sync builds and the host leave it off. Flight mouse scaling
  (production Amiga, `rt_mouse_scale`; user 2026-10-29): AX=0Bh returns the
  motion times `MOUSE_FRAME_MS` (input.c, 300 ms, the tweakable sensitivity)
  over the game-clock time since the last AX=0Bh, remainders carried, so the
  stick's deflection follows mouse speed alone at any frame rate; off while the
  guest's pointer was shown at the last present or within 25 fields (menus,
  film room). Vertical mickeys (`rt_mickeys_y`): 2 per count as DOSBox-X
  (host pixels), 1 on the production Amiga, as a real PC mouse's equal counts
  per inch (user 2026-10-29). Mode set marks the whole
  frame; DAC block sets go to `plat_palette` at once. No frame is read to
  find changes. Amiga (machine taken over, `Swotl.cpp`): an 8-plane copper
  display (framework `CopperList`/`Bitmap`), Kalms `c2p1x1_8_c5_bm` per
  rectangle (one call per full-width band, per row otherwise) into the
  inactive bitmap. Both bitmaps retain dirty rows since their own last
  conversion. A pending frame is withdrawn before reuse; updates can
  coalesce without waiting. Each bitmap has a complete
  copper list and palette. VERTB switches lists before input, only at beam
  lines below 8; a late VBI defers the handoff. `amiga_bitmap` and
  `amiga_colours` describe the handed-off frame. Checked by the host run
  (every guest A0000h store lies in the next present's rectangles; sabotage
  `vram`), `tests/test_display_queue.py` (inheritance and queue races; production
  `video.c` with the field task interrupting driver calls, presents and video BIOS
  calls, the cap's once-per-field return of drawn frames, its lifted hold and
  undrawn polls' return at once, plants), and
  `amiga/display_audit.sh` (40 handoffs against published guest snapshots
  and DAC, no conversion into the shown bitmap, zero late handoffs).
- Interrupts (D8; [irq-plan](irq-plan.md)): poll points (`build/gen/poll-points.csv`,
  `module,offset,kind`, all block leaders, so live flags are in the state block) are the
  I8 sync points (`irq.Proof.sync_points`: `access` footprint accesses and `int` sites
  with IF possibly set, `clear` CLI/POPF/IRET, `if` the instruction after an IF 0→1) and
  the loop heads (`loop`, targets of backward branches outside native rows; user
  2026-10-26: they keep the reference on the original's timing). A native row is atomic
  to the interrupt (irq-plan RC5): loop heads in its body, callees and re-entries
  included, are not in the set. Only sync builds
  (`SWOTL_SYNC`: host runs, replays, `make amiga-sync` for the bench) test at `access`,
  `int`, `clear` and `loop` points; every build tests at `if` points. Production takes
  IRQ0 at the CIA-B tick (below). A test is `tst.b G_IRQ(a6)`
  and `bne` to the poll's stub `X_irq`, placed after the next run that cannot
  fall through: d6 = CS << 16, d7 = IP, `jsr rt_irq`, back past the test to
  `X_np` (the tools fold `X_np` into `X`; the block differential also runs
  every poll block with an interrupt posted). The platform raises `G_IRQ` and
  `rt_irq_pending` together (`RT_RAISE_IRQ`); with IF clear `rt_irq` clears
  `G_IRQ` only, and `sti`, `__set_flags` (POPF, IRET) and
  `rt_set_flags_word` re-arm it from `rt_irq_pending` when they set IF
  (checked in the 68020 differential and `host_run.py rearm_problems`;
  sabotage plants). With guest IF set posted interrupts run in order: IRQ0's guest
  handler (`annotations/entries.csv`) through `rt_irq_async` on the private guest
  stack `B000:8000` down (frame with the sentinel CS:IP `B000:8000` its IRET must pop;
  68k registers, state block and `rt_r` restored after it; nothing posted is taken
  until it returns, the PIC's in-service IRQ0, irq-plan I4; on the Amiga the CIA-B
  tick runs it at once through `rt_irq_interrupt` when `rt_irq0_ready`: IF set, none
  running, no runtime service (`rt_irq_mask`) or main-thread OPL index/data pair
  (`rt_opl_pair`) or held sync access (`rt_irq_hold`), nothing posted, not `BENCH`; a stop raised in it unwinds through
  `rt_irq_abort` and is raised at the next poll; a tick posted while it could not run
  is taken by the next CIA tick before its own, `rt_irq0_take`; host runs inject recorded ticks
  the same way with `host_run.py --stress SEED`, `tests/irq_stress.py`, I6), another
  guest handler on a pushed frame, else the BIOS one (INT 08h ticks; INT 09h, posted in
  sync builds only, takes the next `rt_key_ring` event; production drains the ring at
  service entry with IF set, `rt_keyboard_drain`: a set 1 scan code with break bit and E0 flag, as
  DOSBox-X's IRQ1 handler does: its scan-code table, shift and lock flags,
  words like `48E0`/`xxF0` in the buffer, which DOS AH=08h converts as its
  CON device over INT 16h AH=10h);
  a guest handler's `jmp far` to F000:FEA5 is the BIOS tick plus IRET
  (`rt_bios_int08`). INT 33h is DOSBox-X's driver with the mouse captured
  (8/16 mickeys per 8 pixels, 640x200, mode 13h X even) over `plat_mouse`
  counts, the Amiga's JOY0DAT deltas taken at each vertical blank. Recorded
  IRQ12 (74h) at the exact DOSBox-X external vector F000:D020 drains no
  guest callback: the supported INT 33h surface installs none and never
  shows the DOS driver cursor. Guest-installed vectors still dispatch;
  other external targets stop. `c9-mouse-menu` checks motion, buttons and
  these recorded interrupts; `test_mouse_irq.py` checks the IVT/IF edges.
  The platform posts vectors to `rt_irq_ring` (08h tick,
  09h/89h key make/break in sync builds): Amiga a CIA-B timer per PIT period
  (`plat_timer_rate`) and the CIA-A keyboard read at the vertical blank (`Input.cpp`: raw
  key -> scan code, PC typematic repeat from the vertical blank; diagnostic
  argument `KEYS=when:key,...` feeds keys, `lmb`/`rmb` and `mx±N`/`my±N`
  into the same paths at a frame or `pN`, N
  guest mouse reads after the previous step (host load moves frame
  timings), and `shot`/`quit` call `amiga_script_mark` for a gdb fixture;
  `SWOTL_ARGS` in `amiga/debug.sh`); host run the reference's `irq` events, replayed at the
  same visit of the same sync point after the same service event, one of a
  same-visit group per return of the guest handler to that point (the
  reference takes interrupts only at sync points, `build/gen/poll-points.csv`, IRQ0
  edges only the gate held raised again in order, `dosbox-x-swotl-irq0-backlog.patch`;
  references are re-recorded when the sync set changes, irq-plan RC3).
- IRQ footprint (irq-plan I2, `translator/irq.py`, run by `make gen`, `gen.IRQ_PROOF`):
  every handler WC2 installs (INT 08h at WC2.EXE+0FD10 and +148E0, INT 0Fh at +06F3F;
  the INT 08h handler calls STRAX.DRV and the EMS pointer resolver): its memory,
  ports, IF changes, runtime calls (INT 67h's map, save and restore), register
  transparency proved over the lifted IR. Classes: link paragraphs, `abs:` paragraphs,
  runtime classes `[C:a-b]` (segments read from those words, placed at run time);
  segment 0, the EMS resolver's null result on its failure paths, is no class: a
  store through it fails the proof, a read is a runtime row the monitor fails.
  Every main-code access classified masked, disjoint, sync (may meet a fixed class of
  the footprint) or monitored, with segment registers per (entry, DS, SS) context; the
  sync accesses and IF edges are the poll points (`build/gen/poll-points.csv`). A sync
  access to a handler-written byte lowers to one memory-touching 68k instruction, or
  to straight-line code bracketed by `st`/`sf rt_irq_hold` (the CIA tick waits across
  it, as an x86 instruction is never interrupted: LES of a far pointer, ADC to memory;
  `build/gen/irq-hold.csv`); no compute row holds a sync access, else generation fails. Assumptions the handlers
  rest on are `annotations/irq-bounds.csv` rows (checked at every handler entry and
  return in host runs); monitored accesses the host runs found meeting the footprint
  are `annotations/irq-sync.csv` rows. Output `build/gen/irq-footprint.csv`;
  `t-unit-test_irq_footprint` and `t-sab-irq`.
- HLE (`annotations/hle.csv`, G3): at a range's first instruction
  `jsr rt_hle_<service>`; NE skips to the instruction after `last`, EQ runs
  the guest code. `args`: up to two guest word registers (not SP, BP), in d7
  and d6. Both ends are leaders, the first's live-in includes the
  resume's, and a hook where the CCR holds live flags fails `make gen`. The
  block differential runs the guest path. Entries: `sfx_start` (observe
  only: SPAZ's effect start, BX = slot·6, DI = id·4 → `rt_sfx_id`,
  `rt_sfx_starts`; oracle `check_sfx` in every host run: each report equals
  the guest's store of DI after the hook; sabotage `sfx_start` on c6);
  `pointer_tracked` (observe only: the pointer tracker's exit, DS = DGROUP →
  `rt_pointer_ds`; oracle `check_pointer` in every host run, sabotage
  `pointer-ds` on c9; [pointer-plan.md](pointer-plan.md));
  `music_skip` (SPAZ song
  start, [sound-plan.md](sound-plan.md)): `rt_music_skip`, 0 by default
  (music enabled, user 2026-10-15; 1 skips) and 0 with the argument
  `MUSIC`; `amiga/debug.sh` passes `MUSIC` and host runs
  clear it, since the references hold the music. Oracle `make
  t-hle-music-skip` (in `test-host-all`): m2 with the skip on; the interrupt
  the reference took in the song code is posted at the next sync point;
  services and interrupts equal the reference, RAM too outside SPAZ's state
  (its data segment, its effect counts at DS:6564, dead stack below SP).
  Optional `kind=compute` uses the complete generated register ABI and a d7.l
  handled result; admission proves the reachable flow (`compute.validate`: loops,
  callees, several returns, continuation `exits`, re-entry hooks `entries`). It
  leaves the guest return and check generated. A row is atomic to the interrupt
  (irq-plan RC5): its body's loop heads leave the sync set in both arms. U8: REP,
  the divide-fault edge as a decline edge, every root return a resume
  (d7 dispatch), `end` for code past the return. Contract, oracle and the
  enabled rows: [native-compute.md](native-compute.md).
- Self-modified code (D16, `translator/smc.py`): the root block
  `+6A4D..+8E2C` is one generated cell walk (the whole template block: the
  [2581]=0 variant fills it at 190 cells per run). The setup (+E50E) writes opcodes
  as well as operands, and the shape (cell counts [2587]/[2591], reload position) varies,
  so cells are matched at run time against the forms the writers produce
  (`annotations/self-modifying.csv` kind `form`: `mov [bx+w],al`, the
  `bx`/`ds` reload, the planted `ret`), each checked against the decoder,
  operand words read from guest RAM; anything else stops. Mov cells run
  counted (R7): the cells that fit before the bound are counted once, each
  still matched when it runs (one long read: opcode and operand). That
  exact walk (`_walk_x`) serves a cell cache (speed-plan D3, R20): a cell is
  matched once, when a walk first reaches it, and its bytes are covered; a
  mov cell records its operand and the end of its run of consecutive
  destinations, which the walk stores AL to a long at a time (under 8 bytes
  one by one, offsets wrapping at 16 bits one by one). Every store that may
  change a covered byte is seen: a CS store that may reach a region calls its
  hook after storing (`lower.code_store`; byte `mov`s plant or restore inline):
  a RET at a covered cell start is the walk's stop (one at a time), its first
  byte back ends it, anything else drops the cache. A DS, ES or SS value whose
  window reaches a region drops every cache where it is loaded
  (`lower.putseg`, the reload cells, the runtime's `load_regs`; reloading the
  value a segment holds changes nothing, R30), and so does a
  runtime store into a region (`rt_wrote`; bounds and segment limit from the
  program). A dropped cache is cleared at the next walk with no segment
  reaching a region; until then walks are exact, and so is the rest of a walk
  whose reload loads such a DS. Bytes not covered are read when reached: a
  RET returns, other cells are decoded or walked exactly. Unresolved
  near indirect transfers range-check every walk in their module and CS,
  regardless of traced targets; proved tables retain their closed target set.
  The graph includes the walk edge. If every decoded cell instruction preserves
  arithmetic flags, a call propagates its return site's live flags through the
  walk; otherwise all flags are live. Return checks remain in place. The EGA/Tandy and/or variant ([2581]=0) is out
  of scope. Checked by `make test-blocks` (walks over every snapshot image
  vs x86, through a dropped cache and exactly; per entry, mov cells to the
  bound and past it, a RET at the bound, unknown cells; warm walks between
  RET plants, restores and operand patches made by the hooks or by the
  lowered stores, and cells rewritten after a lowered segment load or
  `smc_expose`; RETs inside and at the ends of runs, 16-bit wraps, a DS
  reaching the region at the entry and from a reload, entries inside a cached
  cell) and `make t-cell-cache` (the runtime's notifications).
- Trap flag: the game never sets TF (its four POPF/IRET sites pop PUSHF or
  interrupt-frame images; no INT 1 and no TF in any reference). A popped
  image with TF set stops (IR exit `trap`, `rt_trap`; `rt_set_flags_word`
  likewise); no single-step delivery. Checked by the TF cases of
  `flag_extract_cases` (x86, 68k) and `flag_helper_entries` (POPF, IRET).
- Audits (`make gen`): spills, full-flag materializations, PF/AF stores,
  dispatcher exits, `stop_unknown` sites against `tests/audit.csv` (above
  expected fails), plus flag stores/merges/loads and return checks; HLE count.

## Sound (D10)

SPAZ runs translated; its OPL2 writes reach `rt_out8` (register file in
`src/runtime/ports.c`). The FM re-hoster produces Paula voices for music,
which stays enabled in both FM and TFH modes; see
[sound-plan.md](sound-plan.md).
