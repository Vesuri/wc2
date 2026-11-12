"""IRQ footprint proof (docs/irq-plan.md I2, translator/irq.py) for WC2's handlers.

The proof holds on the program, matches build/gen/irq-footprint.csv and keeps the
facts the later steps rest on (every handler in irq.HANDLERS proved, the ports,
the INT 08h handler's tick counts as handler-written, the sound-state poll at
WC2.EXE+4565A a sync access), the sync instructions that meet handler-written
memory in more than one 68k access (LES of the sequencer's far pointers, ADC to
memory) are held (irq-hold.csv) and bracketed by `st`/`sf rt_irq_hold` in the
generated text, and the host monitor's buffer rule holds per byte
(tests/irq_monitor.py buffer_races). --sabotage: each plant edits one decoded
instruction of the INT 0Fh handler (the smallest) and must fail its analysis with
its message; each buffer-rule and hold plant must fail its check."""
from pathlib import Path
import argparse
import dataclasses
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from translator import cfg, emit, irq
sys.path.insert(0, str(ROOT / 'tests'))
import irq_monitor

EXE = 'WC2.EXE'
SB = (EXE, 0x06F3F)        # the INT 0Fh handler
TICKS = (0xD130, 0xD137)   # WC2.EXE+0FD70..+0FD7C: two tick dwords
HELD = {(EXE, 0x12A0A), (EXE, 0x12A2A), (EXE, 0x12B6F)}   # LES, LES, ADC (make gen)


def edit(prog, node, **change):
    u = prog.units[node[0]]
    u.insns[node[1]] = dataclasses.replace(u.insns[node[1]], **change)


def operand(prog, node, k, **change):
    i = prog.node_insn(node)
    ops = list(i.operands)
    ops[k] = dataclasses.replace(ops[k], **change)
    edit(prog, node, operands=tuple(ops))


def unsaved_register(prog):
    # push bx -> push cx: bx is popped from a slot that never held it
    operand(prog, (EXE, 0x06F40), 0, name='cx')
    return 'bx'


def undeclared_port(prog):
    # add ax,0Eh -> 0Fh: the DSP status read at 22Fh
    operand(prog, (EXE, 0x06F5A), 1, value=0xF)
    return 'not in PORTS'


def far_return(prog):
    # the handler's IRET -> RETF: the frame's flags word is left behind
    edit(prog, (EXE, 0x070FD), op='retf')
    return 'return'


PLANTS = {'unsaved-register': unsaved_register, 'undeclared-port': undeclared_port,
          'far-return': far_return}


def check(proof):
    proof.raise_errors()
    assert set(proof.fps) == set(irq.HANDLERS), sorted(proof.fps)
    for e, fp in proof.fps.items():
        assert not fp.errors and fp.nodes, (irq.site(e), fp.errors[:3])
    ports = {p for p, _ in proof.fp.ports}
    assert {0x20, 0x388, 0x389, 0x22C, 0x22E} <= ports <= set(irq.PORTS), sorted(ports)
    written = [(lo, hi) for (cls, lo, hi, kind) in proof.fp.mem if cls == '1976' and kind == 'w']
    missing = [a for a in range(TICKS[0], TICKS[1] + 1) if not any(lo <= a <= hi for lo, hi in written)]
    assert not missing, f'tick bytes not handler-written: {[hex(a) for a in missing]}'
    sync = {(n, cls, lo) for n, cls, lo, *_ in proof.sync}
    assert ((EXE, 0x4565A), '1976', 0xA530) in sync     # irq-sync.csv
    assert HELD <= proof.held <= {n for n, *_ in proof.sync}, sorted(proof.held)
    csv = ROOT / 'build/gen/irq-footprint.csv'
    if csv.exists():
        want = csv.read_text().splitlines()[1:]
        assert proof.rows() == want, 'build/gen/irq-footprint.csv is stale: run make gen'
        assert emit.held_points() == proof.held, 'build/gen/irq-hold.csv is stale: run make gen'
        texts = {m: (ROOT / f'build/gen/{m}.s').read_text() for m in {n[0] for n in proof.held}}
        held_text(texts, proof.held)
    return len(proof.sync)


def held_text(texts, held):
    """Each held instruction's code starts with `st rt_irq_hold` and has its one
    `sf rt_irq_hold` where irq.hold_span puts it: after its last line before the
    next label, or after a far call's pointer loads (then only stack pushes)."""
    for mod, off in sorted(held):
        lines = texts[mod].split('\n')
        at = next((k for k, x in enumerate(lines) if x.startswith(emit.label(mod, off) + ':')), None)
        assert at is not None, f'{irq.site((mod, off))}: no label in the generated text'
        np = emit.label(mod, off) + '_np:'     # a sync point: its poll test comes first
        if any(x.startswith(np) for x in lines[at + 1:at + 8]):
            at = next(k for k in range(at + 1, at + 8) if lines[k].startswith(np))
        body = []
        for x in lines[at + 1:]:
            if x and not x[0].isspace():
                break
            body.append(x.strip())
        inner = [x for x in body if x not in ('st rt_irq_hold', 'sf rt_irq_hold')]
        k = irq.hold_span(['\t' + x for x in inner])
        assert k is not None and body == ['st rt_irq_hold', *inner[:k], 'sf rt_irq_hold', *inner[k:]], \
            f'{irq.site((mod, off))} is not held: {body[:3]}'


def buffer_rule(races=irq_monitor.buffer_races):
    """Buffer bytes 100-103 read in ticks 10-20, byte 200 in ticks 10-500: a
    generated write of a byte inside its own read window races; after its last
    read (a reload of played bytes), before its first, or from a service, not."""
    reads = {a: [10, 20, 'b'] for a in range(100, 104)}
    reads[200] = [10, 500, 'b']
    w = lambda lin, tick, generated=True: (lin, 2, 'site', generated, tick)
    assert len(races(reads, [w(102, 15)])) == 1, 'write inside a byte\'s read window passed'
    assert len(races(reads, [w(199, 300)])) == 1, 'write reaching a byte still read passed'
    for quiet in (w(100, 300), w(100, 5), w(102, 15, False)):
        assert not races(reads, [quiet]), f'no race flagged: {quiet}'
    return 5


def hold_plants():
    """Each held instruction's generated text with its st or its sf dropped."""
    held = emit.held_points()
    texts = {m: (ROOT / f'build/gen/{m}.s').read_text() for m in {n[0] for n in held}}
    n = sorted(held)[0]
    lines = texts[n[0]].split('\n')
    at = next(k for k, x in enumerate(lines) if x.startswith(emit.label(*n) + ':'))
    for name, drop in (('hold: no st', '\tst rt_irq_hold'), ('hold: no sf', '\tsf rt_irq_hold')):
        k = lines.index(drop, at)
        yield name, {**texts, n[0]: '\n'.join(lines[:k] + lines[k + 1:])}, held


BUFFER_PLANTS = {
    'buffer rule: first read only': lambda reads, writes: [
        w for w in writes if w[3] and any(a in reads and reads[a][0] <= w[4] for a in range(w[0], w[0] + w[1]))],
    'buffer rule: no races': lambda reads, writes: [],
}


def plant(units, name):
    prog = emit.Program(units, sync={})
    expect = PLANTS[name](prog)
    fp = irq.Handler(prog, SB).run()
    hit = [e for e in fp.errors if expect in e]
    if not hit:
        raise AssertionError(f'{name} escaped ({len(fp.errors)} errors: {fp.errors[:3]})')
    return hit[0][:160]


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    if args.sabotage:
        for name in PLANTS:
            print('caught', name, plant(cfg.build(), name), flush=True)
        for name, races in BUFFER_PLANTS.items():
            try:
                buffer_rule(races)
            except AssertionError as error:
                print('caught', name, error, flush=True)
            else:
                raise AssertionError(f'{name} escaped')
        for name, texts, held in hold_plants():
            try:
                held_text(texts, held)
            except AssertionError as error:
                print('caught', name, error, flush=True)
            else:
                raise AssertionError(f'{name} escaped')
        print('all plants caught')
    else:
        clean = irq.Handler(emit.Program(cfg.build(), sync={}), SB).run()
        assert not clean.errors, clean.errors[:3]     # the plants' control
        n = check(irq.Proof(emit.Program(cfg.build(), sync={})))
        print(f'irq footprint: {n} sync accesses, buffer rule {buffer_rule()} cases: ok')
