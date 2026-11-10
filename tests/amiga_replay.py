#!/usr/bin/env python3
"""Build and run a diagnostic Amiga image against the existing DOSBox-X reference.

Secret Weapons of Luftwaffe's tests/amiga_replay.py with X-Wing's P5 changes, adapted
to WC2: no joystick, no real-video capture (the shown bitplanes are compared), and the
reference's VGA status (3DAh) and PIT counter (40h) reads are replayed in their service
intervals (trace/replay-ports.csv), as by the host run. Drivers run at their load
paragraphs (emit.DRIVER_SEG); an interrupt at a point in overlay code takes the CS its
stub's word 10h holds then (docs/translator-design.md, VROOMM). The image replays the
reference's hardware interrupts at their recorded poll points, its REP slices and its
calendar inputs; the guest code is the translator's, with diagnostic hooks only. At the
milestone's last snapshot the image holds, the fixture captures registers, state block,
guest RAM, DAC and bitplanes, and tests/host_run.py compares them with the reference
after its own host run. Generated hooks, tables and captures stay in tmp/; no reference
is re-recorded.
"""
import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import host_run as H  # noqa: E402
import rep_replay  # noqa: E402
from translator import cfg, emit, gen  # noqa: E402
from translator.lower import LOADSEG  # noqa: E402

ROOT = H.REPO
TIMEOUT = 3600   # seconds of emulation for the whole run (the 68030 model at max speed)
HASH_STEP = 256  # service-history checkpoints: the hash is cumulative (amiga_replay.c)


def varint(value):
    assert value >= 0
    out = bytearray()
    while True:
        out.append(value & 127 | (128 if value > 127 else 0))
        value >>= 7
        if not value:
            return out


def delta(value, base):
    d = (value - base) & 0xffff
    d = d - 0x10000 if d & 0x8000 else d
    return varint(d << 1 if d >= 0 else (~d) << 1 | 1)


def rep_stream(records, ids):
    """The compacted REP slices as the byte stream amiga_replay.c rep_next reads:
    service difference, hits, point, start against the previous record's end,
    end against start (zigzag 16-bit), repeat << 1 | restart."""
    out, service, end = bytearray(), 0, (0, 0, 0)
    for c, n in records:
        assert c.service >= service and 0 < n < 0x8000
        out += varint(c.service - service) + varint(c.hits) + varint(ids[c.label])
        for k in range(3):
            out += delta(c.start[k], end[k])
        for k in range(3):
            out += delta(c.end[k], c.start[k])
        out += varint(n << 1 | int(c.restart))
        service, end = c.service, c.end
    return bytes(out)


def prepare(name, out, trace):
    script = H.milestone_script(name)
    irqs, releases = H.reference_inputs(trace)
    _, exact = H.reference_inputs(trace, exact_releases=True)
    if any(not isinstance(r, int) for r in exact):
        raise ValueError('key releases with visit counts: the replay counts service events only')
    reps = rep_replay.read(trace, required=True)
    summary = dict(x.split('=', 1) for x in (trace / 'summary.txt').read_text().split())
    assert int(summary['polls'], 16) == H.fnv(H.POLLS.read_bytes()), 'reference poll points differ'
    services = H.reference_services(trace)
    retrace = H.port_runs(trace, (0x3DA,))
    pit = H.port_runs(trace, (0x40,))
    points = sorted({t[0] for t, _ in script['keys']} |
                    {t[0] for t in script['snapshots']} | {lab for _, lab, _, _ in irqs} | {c.label for c in reps})
    ids = {lab: i for i, lab in enumerate(points)}
    units = cfg.build()
    nodes = {emit.label(mod, off): (mod, off) for mod, u in units.items() for off in u.insns}
    hooks = {nodes[lab]: ids[lab] for lab in points}
    rep_hooks = {nodes[c.label]: ids[c.label] for c in reps}
    program = emit.Program(units, diagnostic_hooks=hooks, diagnostic_reps=rep_hooks)
    assert all(nodes[lab] in program.loop_heads for _, lab, _, _ in irqs)
    out.mkdir(parents=True, exist_ok=True)
    gen.generate(out / 'gen', program=program)
    hashes, digest = [], 2166136261
    for kind, r in services:
        values = [r[n] for n in H.REGS + ('es', 'ss', 'ds', 'vector')]
        values += [r['flags'] & 0x600, int(kind == 'svc_ret')]
        for byte in struct.pack('>' + 'H' * len(values), *values):
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        hashes.append(digest)
    steps = []
    release = iter(releases)
    for (lab, _, hits), key in script['keys']:
        if isinstance(key, str):
            kind, value, end = {'x': 2, 'y': 3, 'b': 4}[key[1]], int(key[2:]), 0
        else:
            base = key & 0xffff
            kind, value, end = (1, base >> 8 | (0x100 if base in H.GREY else 0) |
                                ((key >> 7) & 0xe00), next(release))
        steps.append((ids[lab], hits, kind, value, end))
    assert next(release, None) is None
    steps += [(ids[lab], hits, 0, 0, 0) for lab, _, hits in script['snapshots']]
    locations = []
    for lab in points:
        mod, off = nodes[lab]
        o = program.overlay(mod, off)
        # overlay code: CS = the word at offset 10h of its stub, read at delivery
        slot = (LOADSEG << 4) + o.stub + 0x10 if o is not None else 0
        locations.append((LOADSEG + units[mod].cs[off] + emit.DRIVER_SEG.get(mod, 0),
                          units[mod].ip_of(off), slot))

    def array(ctype, name, rows):
        return f'static const {ctype} {name}[] = {{\n' + ''.join(
            '{' + ','.join(map(str, row)) + '},\n' for row in rows) + '};\n'
    reads = sum(n for _, _, n in retrace)
    pit_reads = sum(n for _, _, n in pit)
    text = ('/* Generated from the existing original reference; local only. */\n'
            'struct replay_point_info { uint32_t cs, ip, slot; };\n'
            'struct replay_irq { uint32_t service, point, hits, vector; };\n'
            'struct replay_step { uint32_t point, hits, kind; int32_t value; uint32_t release; };\n'
            'struct replay_retrace { uint32_t service, value, repeat; };\n'
            f'#define REPLAY_POINTS {len(points)}u\n#define REPLAY_IRQS {len(irqs)}u\n'
            f'#define REPLAY_SERVICES {len(services)}u\n#define REPLAY_STEPS {len(steps)}u\n'
            f'#define REPLAY_RETRACE {len(retrace)}u\n#define REPLAY_VGA_READS {reads}u\n'
            f'#define REPLAY_PIT {len(pit)}u\n#define REPLAY_PIT_READS {pit_reads}u\n')
    stream = rep_stream(rep_replay.compact(reps), ids)
    text += ('struct replay_rep { uint32_t service, hits; uint16_t point, cx, si, di, end_cx, end_si, end_di, restart, repeat; };\n'
             f'#define REPLAY_REPS {len(reps)}u\n'
             'static const uint8_t replay_rep_stream[] = {\n')
    text += ''.join(','.join(map(str, stream[k:k + 32])) + ',\n' for k in range(0, len(stream), 32)) + '};\n'
    text += array('struct replay_point_info', 'replay_points', locations)
    text += array('struct replay_irq', 'replay_irqs', [(s, ids[lab], h, v) for s, lab, h, v in irqs])
    text += array('struct replay_step', 'replay_script', steps)
    text += array('struct replay_retrace', 'replay_retrace', retrace)
    text += array('struct replay_retrace', 'replay_pit', pit)
    text += (f'#define REPLAY_HASH_STEP {HASH_STEP}u\n#define REPLAY_FINAL_HASH {hashes[-1]}u\n'
             'static const uint32_t replay_service_hashes[] = {\n' +
             ','.join(map(str, hashes[HASH_STEP - 1::HASH_STEP])) + '};\n')
    (out / 'replay_data.h').write_text(text)
    calendar, clock = H.reference_clocks(trace)
    stamp = H.dos_file_stamp(clock) if clock is not None else (0, 0)
    (out / 'replay_clocks.h').write_text(
        '/* Recorded external calendar inputs, diagnostic build only. */\n'
        f'#define REPLAY_CALENDAR_DATE {calendar or 0}u\n'
        f'#define REPLAY_FILE_TIME {stamp[0]}u\n'
        f'#define REPLAY_FILE_DATE {stamp[1]}u\n')
    (out / 'expected.json').write_text(json.dumps(dict(
        services=len(services), interrupts=len(irqs), steps=len(steps), vga_reads=reads,
        pit_reads=pit_reads)))
    print(f'{name}: {len(points)} diagnostic points, {len(irqs)} interrupts, {len(services)} service events, '
          f'{len(reps)} REP slices, {reads} VGA status reads, {pit_reads} PIT reads', flush=True)


def build(out):
    work = out / 'amiga'
    work.mkdir(exist_ok=True)
    makefile = work / 'Makefile'
    if not makefile.exists():
        makefile.symlink_to(ROOT / 'amiga/Makefile')
    subprocess.run(['make', '-s', '-C', str(work), f'REPO={os.path.relpath(ROOT, work)}',
                    'GEN=../gen', 'REPLAY=..'], check=True)
    return work


def fresh_run_directory(out):
    # debug.sh copies the original data but does not delete game writes: a fresh
    # run directory, so a replay inherits no file from an earlier attempt.
    return Path(tempfile.mkdtemp(prefix='run-', dir=out))


def run(name, out, trace, work):
    capture = out / 'capture'
    capture.mkdir(exist_ok=True)
    template = (ROOT / 'amiga/milestone.gdb.in').read_text()
    # inside IRQ0's handler the interrupted SS:SP (host_run.amiga_irq, design D8)
    dump = 'dump binary memory @OUT@/ram.bin'
    assert dump in template
    template = template.replace(dump, 'dump binary memory @OUT@/irq.bin &rt_irq0_running (char *)&rt_irq0_running+1\n'
                                'append binary memory @OUT@/irq.bin &rt_irq_saved (char *)&rt_irq_saved+32\n' + dump, 1)
    template = template.replace('@LABEL@', 'rt_replay_done').replace(
        '@OUT@', os.path.relpath(capture, ROOT / 'amiga'))
    expected = json.loads((out / 'expected.json').read_text())
    check = '\n'.join(f'if replay_{key} != {value}\n  printf "WC2_REPLAY_INCOMPLETE {key}\\n"\n  quit 1\nend'
                      for key, value in expected.items())
    assert 'set $bm = &amiga_bitmap' in template
    stop = '  x/s *(char **)($sp+4)\n'
    assert stop in template
    template = template.replace(stop, stop + (
        '  printf "WC2_REPLAY_STATE a=%u b=%u services=%u interrupts=%u steps=%u reps=%u vga=%u pit=%u\\n", '
        '*(unsigned *)($sp+8), *(unsigned *)($sp+12), replay_services, replay_interrupts, replay_steps, '
        'replay_rep_index, replay_vga_reads, replay_pit_reads\n'
        '  printf "WC2_REPLAY_REP service=%u hits=%u point=%u cx=%x end_cx=%x restart=%u repeat=%u offset=%u\\n", '
        'rep_record.service, rep_record.hits, rep_record.point, rep_record.cx, rep_record.end_cx, '
        'rep_record.restart, rep_record.repeat, replay_rep_offset\n'
        '  printf "WC2_REPLAY_VISITS %u epoch=%u\\n", visits[*(unsigned *)($sp+8)], epochs[*(unsigned *)($sp+8)]\n'))
    template = template.replace('set $bm = &amiga_bitmap', check + '\nset $bm = &amiga_bitmap')
    (capture / 'fixture.gdb').write_text(template)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    run_dir = fresh_run_directory(out)
    env = dict(os.environ, DEBUG_PORT=str(port), FSUAE_PORT_PINNED='1',
               AMIGA_CPU=os.environ.get('AMIGA_CPU', '68030'),
               WC2_ELF=str(work / 'out/Wc2.elf'), FSUAE_RUN=os.path.relpath(run_dir, ROOT / 'amiga'),
               FSUAE_CLAIM_STRICT='1', WC2_ARGS='',
               # The diagnostic image carries the reference (replay_data.h: the 3DAh
               # and PIT runs, 544,298 rows to m1b) beside the code, 11.4 MB at m1b:
               # with the target's 8 MB of Fast RAM it does not load ("not enough
               # memory", return code 20). The replay machine gets a 32 MB Zorro III
               # board (owner, 2026-11-10); the production image keeps the 8 MB target.
               EXTRA_ARGS='--zorro_iii_memory=32768')
    with (capture / 'gdb.log').open('w') as log:
        command = [str(ROOT / 'amiga/debug.sh'), '', str(capture / 'fixture.gdb'), str(work / 'out/Wc2.exe')]
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            result = process.wait(timeout=TIMEOUT)
        except BaseException:
            # Only the process group created above belongs to this capture.
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    lines = (capture / 'gdb.log').read_text().splitlines()
    if result or 'WC2_MILESTONE_OK' not in lines:
        raise SystemExit(f'Amiga diagnostic replay {name}: no capture (exit {result})\n' + '\n'.join(lines[-20:]))
    regs = [line.removeprefix('WC2_REGS ') for line in lines if line.startswith('WC2_REGS ')]
    assert len(regs) == 1, regs
    (capture / 'regs.txt').write_text(regs[0])
    problems = H.check(name, TIMEOUT, capture, None, trace=trace)
    if problems:
        raise SystemExit('\n'.join(problems))
    print(f'Amiga diagnostic replay {name}: registers, state, RAM, DAC, shown pixels and '
          f'service history match DOSBox-X', flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--milestone', required=True)
    args = ap.parse_args()
    out = ROOT / 'tmp/amiga-replay' / args.milestone
    trace = H.host_reference(args.milestone)
    prepare(args.milestone, out, trace)
    work = build(out)
    run(args.milestone, out, trace, work)
