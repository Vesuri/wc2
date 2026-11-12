# Wing Commander II — DOS to Amiga port investigation

Investigate porting Wing Commander II: Vengeance of the Kilrathi (Origin, 1991, DOS,
7 × 1.44 MB disks) to the Amiga. Target and approach (owner decisions,
[docs/design.md](docs/design.md)): AGA, 68030 minimum, 68040 or better recommended, by
offline translation of the x86 code to 68020 assembly as in Secret Weapons of Luftwaffe.
Scope: VGA, FM music and effects on Paula, the digitised intro speech. The original
running under DOSBox-X is the ground truth. Start with [docs/open-work.md](docs/open-work.md).

## Standing rules

- Commits: author `Vesa Halttunen <vesuri@jormas.com>`, unsigned
  (`commit.gpgsign=false`, `tag.gpgsign=false` local), `core.hooksPath=/dev/null`, no
  Co-Authored-By or other trailers, directly on `main`, one verified coherent change per
  commit. Never change global git settings.
- Be concise. Docs hold rules, facts and pointers. This file holds rules and pointers only.
- Never commit original or byte-derived material: archives, disk images, game files,
  unpacked or installed data, disassembly, generated code that embeds original tables,
  captures, screenshots, audio, traces, emulator state, saves. They stay in ignored
  `ref-originals/`, `ref/`, `tmp/`, `build/`, `disasm/` (except `symbols.csv`). Run
  `git status --ignored` before `git add` of new files. Names and hashes may be committed.
- `tmp/` is local scratch; reusable scripts go in `tools/`, decisions in `docs/`, and the
  method behind every committed number in a committed tool or commit message.
- The original is the ground truth. The host build and the Amiga build are never compared
  only with each other or with themselves.
- Preserve the original's decisions: implement the services it calls; never replace game
  logic with screen-specific guesses. Unknown calls, control flow, code writes, ports and
  interrupts are loud stops until deliberately supported.
- Guest code reaches the Amiga only as translator output. Never hand-port a guest routine
  to C or asm, never edit generated files (`build/gen/`), never fix output by hand: fix the
  translator or `annotations/` and regenerate.
- Hand-written code is the runtime and platform layer only, named by surface item, never by
  guest address (`make lint`). Native replacement of a guest routine needs the owner's
  per-routine authorization and an `annotations/hle.csv` row with reason and oracle.
- Phase gates (`docs/port-plan.md`, `docs/phases.md`) are hard: do not commit a phase's work
  before the previous gate passes. A milestone counts only if its pixels come from
  generated code.
- Tests settle correctness. A timeout or an unreached probe is never a pass; every check
  needs a positive completion signal, and a negative observation needs a positive control.
- No performance claim without a measurement on matched workloads.
- Never `pkill` fs-uae, gdb, dosbox-x or dosbox-staging: projects share the host. Scripts
  record and kill only their own pid.
- No local paths in the repo (home directories, usernames, `/tmp`, other projects' paths).
  Name another project by name. DOSBox command paths are relative (the project path has
  spaces).
- Validation scope: run the gates relevant to the changed code and its callers, consumers
  and shared contracts; say which and why before running them. Translator or shared runtime
  changes: the affected differential, guard and sabotage tests, then host or replay
  fixtures. Audio synthesis only: the FM checks and their sabotage, plus build and smoke.
  Docs only: consistency and diff checks. Scope by dependency, never by whether a test
  passes; never weaken a check, oracle or tolerance.
- Fixes to files imported from Secret Weapons of Luftwaffe are logged in
  `docs/upstream.md` (one row each) so they can move between the ports.
- Before building a runtime surface, harness feature or translator feature, check the
  sibling tables (`docs/port-plan.md` "Sibling: X-Wing" and X-Wing's mirror) and start
  from the other port's commit; add a row when either port lands shared work.
- `docs/open-work.md` is the only work queue: open items with acceptance checks, removed
  in the commit that completes them; measured dead ends stay. History belongs in git.
- Names have one source of truth (`disasm/symbols.csv`, once it exists). Addresses use the
  original's own numbering, never an Amiga load address. Mark evidence MEASURED, DERIVED or
  INFERRED.
- Owner decisions are in the table in `docs/design.md` and change only by the owner. Ask
  at genuine decision points; proceed on documented defaults otherwise.
- Do not edit a shell launcher while it runs.
- The sibling project "Wing Commander" (Amiga WC1 WHDLoad work) is separate; do not touch
  its working tree.

## Docs

| Doc | Read when |
|---|---|
| [docs/open-work.md](docs/open-work.md) | always first: the work queue |
| [docs/design.md](docs/design.md) | choosing target, scope or approach; owner decisions |
| [docs/port-plan.md](docs/port-plan.md) | starting a phase; what to copy from Secret Weapons of Luftwaffe and why; what X-Wing has built |
| [docs/upstream.md](docs/upstream.md) | changing a file imported from Secret Weapons of Luftwaffe |
| [docs/translator-design.md](docs/translator-design.md), [docs/translation-lessons.md](docs/translation-lessons.md), [docs/x86-notes.md](docs/x86-notes.md) | translator work (SWOTL's contracts; facts SWOTL's until re-derived) |
| [docs/amiga-arch.md](docs/amiga-arch.md), [docs/amiga-lessons.md](docs/amiga-lessons.md), `src/platform/amiga/framework/README.md` | Amiga platform work |
| [docs/irq-plan.md](docs/irq-plan.md), [docs/sound-plan.md](docs/sound-plan.md), [docs/speed-plan.md](docs/speed-plan.md), [docs/native-compute.md](docs/native-compute.md) | interrupts, sound, speed, native routines (SWOTL's methods) |
| [docs/source-inventory.md](docs/source-inventory.md) | facts and hashes of the original files |
| [docs/pc-reference-loop.md](docs/pc-reference-loop.md) | running the installer or the game under DOSBox |
| [docs/wc1-wc2-comparison.md](docs/wc1-wc2-comparison.md) | WC1/WC2 code and data sharing; the WC1 reuse plan |
| [docs/vroomm.md](docs/vroomm.md), [docs/drivers.md](docs/drivers.md), [docs/external-surface.md](docs/external-surface.md) | the overlay manager, the drivers, the game's DOS, BIOS, EMS and port use (the P2 map) |

## Shared environment and knowledge

Shared guidance starts at `~/.local/share/amiga/docs/index.md`: read the rows that match the
task. It routes to the playbooks, references and shared tools (`docs/environment.md`,
"Shared tools"); this project follows `docs/playbooks/new-port-playbook.md` there. The
environment comes from AmigaXDev's `make setup`, and `amiga/env.sh` sources
`~/.local/share/amiga/env.sh`. Generic lessons go into AmigaXDev's docs (edit them there and
run `make share`); this repository keeps what is specific to this game. Secret Weapons of
Luftwaffe is the model for the translator, reference loop and Makefile.

## Commands

`make extract` (archives → `tmp/union`, hash-checked), `make install` (original installer,
headless → `ref/`, hash-checked), `make hash` / `make check-ref`, `make prepare-reference`
(`ref/` → disposable `tmp/pc-root`), `make reference-staging` (play it), `make compare`
(PC WC1 vs WC2), `make reference-emulator` (instrumented DOSBox-X), `make reference`
(gate 1), `make map` (gate 2: VROOMM check, sweep, code writes, surface).
Translator and Amiga: `make gen`, `make gen-check`, `make lint`, `make test` (gate 3
with `make test-sabotage`: lint, decoder against the sweep and Capstone, the x86
differential on WC2's code and the synthetic corpora; the 68020 differential on the
synthetic corpora, guards, unit tests; needs `make map`'s `tmp/sweep/`),
`make test-sabotage`, `make host`, `make amiga`, `make smoke`, `make size`.
