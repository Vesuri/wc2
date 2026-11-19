#!/usr/bin/env python3
"""Run the WHDLoad slave in FS-UAE in an isolated tmp/whdload-test-* fixture.
From Secret Weapons of the Luftwaffe's tools/test_whdload.py (docs/upstream.md).

    python3 tools/test_whdload.py --mode smoke     # Smoke.slave: harness only
    python3 tools/test_whdload.py --mode boot      # BootTest.slave: Kickstart 3.1 kickemu boots
    python3 tools/test_whdload.py --mode load      # LoadTest.slave: load + PROGDIR; its relocated block checked
    python3 tools/test_whdload.py --mode run [--analog] [--slave build/whdload/MemFree.slave]
    python3 tools/test_whdload.py --mode run --installed DIR [--setup a1200-040]
    python3 tools/test_whdload.py --mode run --setup a1200-030 [--whdload-mmu]

`run` starts the game under the release slave; WHDLoad TIMEOUT (needs the moved VBR of
a 68020) ends it with COREDUMP and the dump is judged:
  - the reason is the timeout ("DEBUG caused" at the CIA-A event count), not a fault;
  - the game is running: most 64-byte blocks of the original WC2.EXE's load image lie in
    guest RAM, which holds guest bytes in reverse order (overlays come and go; relocated
    and patched blocks differ);
  - the dump's CACR matches the slave's cache policy (docs/whdload.md, Caches): data
    cache on where WHDLoad uses the MMU (68040/060, 68030 with MMU), otherwise the
    instruction cache alone.
The MemFree slave's low-water marks (Chip, Fast) are read from its $100 slot.
--installed runs an installed WC2 drawer as it is (slave, data/Wc2, data).
--setup a1200-040: full 68040 with its MMU and FPU, JIT off, on $FSUAE_MMU; the report
must show TC=8000 (translation on; AmigaXDev whdload-mmu.md). The default --setup a1200 is a
68030 (D1's minimum) without MMU emulation, 8 MiB Zorro II and 8 MiB Zorro III Fast.
--setup a1200-030: full 68030 with its MMU on $FSUAE_MMU; WHDLoad uses the MMU only with its MMU option
(--whdload-mmu). --setup a1200-060: as the 68040. These setups emulate the data cache.

Inputs are local, never shipped: Kickstart 3.1 A1200 + RTB, WHDLoad, the Workbench
floppy, the installed game files (ref/WING2). Source amiga/env.sh first. The emulator
is the one this script started; it is stopped by its own PID only.
"""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
AMIGA = Path.home() / '.local/share/amiga'
KICKSTARTS = AMIGA / 'Kickstarts'
WHDLOAD = Path(os.environ.get('WHDLOAD', AMIGA / 'WHDLoad')) / 'C/WHDLoad'
WORKBENCH = Path(os.environ.get('WORKBENCH_ADF', AMIGA / 'Workbenchv2.04rev37.67Workbench.adf'))
KICK31 = Path(os.environ.get('KICKSTART_A1200', KICKSTARTS / 'kick40068.A1200'))
SETUPS = ('a1200', 'a1200-030', 'a1200-040', 'a1200-060')
SLAVES = {'smoke': 'Smoke.slave', 'boot': 'BootTest.slave', 'load': 'LoadTest.slave', 'run': 'Wc2.slave'}
DOS_ONLY = ('INSTALL.DAT', 'INSTALL.EXE', 'README.EXE')


def blocks(data, size=64):
    return [data[a:a + size] for a in range(0, len(data) - size + 1, size)
            if len(set(data[a:a + size])) > 8]


def load_image(exe):
    """The MZ load module, as the runtime's EXEC reads it (machine.c exec_root)."""
    w = lambda o: int.from_bytes(exe[o:o + 2], 'little')
    return exe[w(8) * 16:w(4) * 512]


def hunks(exe):
    """The executable's hunks as dos.LoadSeg loads them: (longs, data,
    [(target hunk, offset)...]) each; data is the file's bytes, shorter than
    longs*4 for BSS and uninitialised tails."""
    w = lambda o: int.from_bytes(exe[o:o + 4], 'big')
    assert w(0) == 0x3f3 and w(4) == 0, 'HUNK_HEADER without resident libraries'
    first, last = w(12), w(16)
    sizes = [w(20 + 4 * k) for k in range(last - first + 1)]
    assert not any(s & 0xc0000000 for s in sizes), 'no memory flags'
    out, o, cur = [], 20 + 4 * len(sizes), None
    while o < len(exe):
        t = w(o) & 0x3fffffff
        o += 4
        if t in (0x3e9, 0x3ea, 0x3eb):         # CODE, DATA, BSS
            n = w(o)
            cur = [sizes[len(out)], exe[o + 4:o + 4 + 4 * n] if t != 0x3eb else b'', []]
            out.append(cur)
            o += 4 if t == 0x3eb else 4 + 4 * n
        elif t == 0x3ec:                         # RELOC32
            while w(o):
                n, target = w(o), w(o + 4)
                cur[2] += [(target, w(o + 8 + 4 * k)) for k in range(n)]
                o += 8 + 4 * n
            o += 4
        elif t == 0x3f0:                         # SYMBOL
            while w(o):
                o += 4 + 4 * w(o) + 4
            o += 4
        elif t == 0x3f1:                         # DEBUG
            o += 4 + 4 * w(o)
        elif t == 0x3f2:                         # END
            pass
        else:
            raise SystemExit(f'FAIL: hunk type {t:X} at {o - 4} not checked')
    assert len(out) == len(sizes)
    return out


def check_block(exe, data, base):
    """The slave's resload_Relocate block (LoadTest.slave: test-block and its
    address, size and resload_Relocate's size in test-blockadr) against the
    executable relocated here: every segment linked in order inside the block,
    its bytes the hunk's, relocated to the segments' addresses, BSS zero."""
    adr = (data / 'test-blockadr').read_bytes() if (data / 'test-blockadr').exists() else b''
    if len(adr) != 12:
        raise SystemExit(f'FAIL: load: no relocated block saved: dos.LoadSeg loaded Wc2 ({base})')
    at, size, used = (int.from_bytes(adr[k:k + 4], 'big') for k in (0, 4, 8))
    block = (data / 'test-block').read_bytes()
    assert len(block) == size and used <= size, (size, used, len(block))
    hs, segs, link = hunks(exe), [], at + 4
    while link:
        o = link - at
        assert 4 <= o < size and len(segs) < len(hs), f'segment link {link:X} outside the block'
        segs.append(link + 4)
        link = int.from_bytes(block[o:o + 4], 'big') * 4
    if len(segs) != len(hs):
        raise SystemExit(f'FAIL: load: {len(segs)} segments, the executable has {len(hs)} hunks')
    for k, (longs, raw, relocs) in enumerate(hs):
        want = bytearray(raw.ljust(4 * longs, b'\0'))
        for target, off in relocs:
            v = int.from_bytes(want[off:off + 4], 'big') + segs[target]
            want[off:off + 4] = (v & 0xffffffff).to_bytes(4, 'big')
        o = segs[k] - at
        if block[o:o + len(want)] != want:
            bad = next(i for i in range(len(want)) if block[o + i] != want[i])
            raise SystemExit(f'FAIL: load: hunk {k} differs at +{bad:X} ({base})')
    print(f'relocated block: {len(hs)} hunks at {at:X}, {used:,} of {size:,} bytes, matches the executable')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mode', choices=tuple(SLAVES), default='run')
    p.add_argument('--analog', action='store_true', help='set Custom1 (analog joystick)')
    p.add_argument('--slave', type=Path, help='slave override (default: build/whdload/ per mode)')
    p.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/Wc2-release.exe',
                   help='stripped (make amiga-release): LoadSeg reads symbol hunks in small pieces')
    p.add_argument('--data', type=Path, default=ROOT / 'ref/WING2')
    p.add_argument('--installed', type=Path, help='installed WC2 drawer, used unchanged')
    p.add_argument('--setup', choices=SETUPS, default='a1200')
    p.add_argument('--whdload-mmu', action='store_true', help="WHDLoad's MMU option (68030)")
    p.add_argument('--fast', type=int, default=16384, help='host Fast RAM in KiB: 8 MiB Zorro II, the rest Zorro III')
    p.add_argument('--cpu', default='68030', help='D1: 68030 minimum (a 68EC020 has no room for Zorro III)')
    p.add_argument('--ticks', type=int, default=3000, help='WHDLoad TIMEOUT in PAL fields (run)')
    p.add_argument('--no-preload', action='store_true')
    p.add_argument('--ntsc', action='store_true', help='NTSC machine (--ticks stays in CIA-A events)')
    p.add_argument('--option', action='append', default=[], help='extra WHDLoad option, e.g. FILELOG')
    p.add_argument('--seconds', type=int, default=900, help='host safety ceiling')
    args = p.parse_args()
    if args.installed:
        assert args.mode == 'run' and not args.slave, '--installed runs its own slave'
        args.data = args.installed / 'data'
    mmu = args.setup != 'a1200'
    if mmu:
        args.cpu = '68' + args.setup[-3:]
    assert not args.whdload_mmu or args.cpu == '68030', '--whdload-mmu is for --setup a1200-030'
    dcache = args.cpu in ('68040', '68060') or args.whdload_mmu

    (ROOT / 'tmp').mkdir(exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix='whdload-test-', dir=ROOT / 'tmp'))
    print('Fixture:', base, flush=True)
    boot, game = base / 'boot', base / 'game'
    data = game / 'data'
    if args.installed:
        shutil.copytree(args.installed, game)
    for d in (boot / 's', boot / 'devs/Kickstarts', data, base / 'state'):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(WHDLOAD, game / 'WHDLoad')
    if not args.installed:
        shutil.copyfile(args.slave or ROOT / 'build/whdload' / SLAVES[args.mode], game / 'Wc2.slave')
    if args.mode != 'smoke':
        shutil.copyfile(KICK31, boot / 'devs/Kickstarts' / KICK31.name)
        shutil.copyfile(KICK31.with_name(KICK31.name + '.RTB'), boot / 'devs/Kickstarts' / (KICK31.name + '.RTB'))
    if args.mode in ('load', 'run') and not args.installed:
        shutil.copyfile(args.exe, data / 'Wc2')
    if args.mode == 'run' and not args.installed:
        shutil.copytree(args.data, data, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.pdf', *DOS_ONLY))
        # copytree copies the read-only modes of ref/ to the drawer itself too.
        for f in (data, *data.rglob('*')):
            f.chmod(0o644 if f.is_file() else 0o755)
    options = ['SPLASHDELAY=0', 'NOREQ']
    if not args.no_preload:
        options.append('PRELOAD')
    if args.mode == 'run':
        # The game creates files (TEMPGLOB.000, ...): with PreLoad on 8 MiB, WHDLoad
        # 20.1's write cache hangs at exit (SWOTL docs/whdload.md, Common failures).
        options += ['COREDUMP', f'TIMEOUT={args.ticks}', 'NOWRITECACHE']
        if args.analog:
            options.append('CUSTOM1=1')
    if args.mode == 'load':
        options.append('NOWRITECACHE')      # LoadTest.slave writes test-block (exit hang, as above)
    if args.whdload_mmu:
        options.append('MMU')
    options += args.option
    command = 'WHDLoad Wc2.slave ' + ' '.join(options)
    print('Command:', command, flush=True)
    (boot / 's/WHDLoad.prefs').write_text('Expert\nReadDelay=0\n')
    (boot / 's/startup-sequence').write_text(
        'DF0:C/Assign C: DF0:C\nDF0:C/Assign LIBS: DF0:Libs\n'
        'DF0:C/Assign DEVS: DH0:devs\nStack 16384\nFailAt 999\n'
        f'CD DH1:\n{command} >DH0:result\n'
        'If WARN\nEcho failed >DH0:failed\nElse\nEcho passed >DH0:passed\nEndIf\n')

    fsuae = os.environ.get('FSUAE_MMU' if mmu else 'FSUAE', 'fs-uae')
    # Data-cache emulation needs the compatible core and, with directory drives, the
    # indirect UAE board (AmigaXDev headless-fsuae.md); otherwise FS-UAE drops it.
    cpu = {'68030': ['--uae_mmu_model=68030'],
           '68040': ['--uae_mmu_model=68040', '--uae_fpu_model=68040'],
           '68060': ['--uae_mmu_model=68060', '--uae_fpu_model=68060']}.get(args.cpu, []) if mmu else []
    if mmu:
        cpu += ['--uae_cpu_compatible=true', '--uae_cpu_data_cache=true', '--uae_uaeboard=full+indirect']
    if mmu or args.fast > 8192:
        cpu += ['--uae_cpu_24bit_addressing=false']
    with (base / 'emulator.log').open('w') as log:
        emu = subprocess.Popen([fsuae, '--amiga_model=A1200', '--uae_chipset=aga', '--cpu=' + args.cpu,
            '--uae_cpu_model=' + args.cpu, *cpu, '--jit_compiler=0',
            *(['--ntsc_mode=1'] if args.ntsc else []),
            '--chip_memory=2048', '--slow_memory=0', '--fast_memory=' + str(min(args.fast, 8192)),
            *(['--zorro_iii_memory=' + str(args.fast - 8192)] if args.fast > 8192 else []),
            '--kickstart_file=' + str(KICK31),
            '--hard_drive_0=' + str(boot), '--hard_drive_0_priority=10', '--hard_drive_1=' + str(game),
            '--floppy_drive_0=' + str(WORKBENCH), '--audio_driver=dummy',
            '--joystick_port_0=mouse', '--joystick_port_1=nothing', '--warp_mode=1', '--fullscreen=0',
            '--automatic_input_grab=0', '--window_width=720', '--window_height=568',
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')],
            stdout=log, stderr=log, env=dict(os.environ, SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline and not any((boot / n).exists() for n in ('passed', 'failed')):
                if emu.poll() is not None:
                    raise SystemExit(f'FAIL: FS-UAE exited unexpectedly ({base})')
                time.sleep(.25)
            time.sleep(1)
        finally:
            emu.terminate()
            try:
                emu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emu.kill()
                emu.wait()

    output = (boot / 'result').read_text(errors='replace') if (boot / 'result').exists() else ''
    fsuae_log = base / 'fsuae/Cache/Logs/fs-uae.log.txt'
    if mmu and 'Data cache emulation' in (fsuae_log.read_text(errors='replace') if fsuae_log.exists() else 'Data cache emulation'):
        raise SystemExit(f'FAIL: FS-UAE did not keep data-cache emulation ({fsuae_log})')
    report = (game / '.whdl_register').read_text(encoding='latin1') if (game / '.whdl_register').exists() else ''
    if not any((boot / n).exists() for n in ('passed', 'failed')):
        raise SystemExit(f'FAIL: WHDLoad did not return within {args.seconds} s ({base})\n{output}')
    if args.mode != 'run':
        if not (boot / 'passed').exists():
            raise SystemExit(f'FAIL: {args.mode} ({base})\n{report[:2000]}{output}')
        if args.mode == 'smoke':
            assert (game / 'smoke-passed').read_bytes() == b'PASS'
        if args.mode == 'load':
            check_block(args.exe.read_bytes(), data, base)
        print(f'PASS: {args.mode} slave returned normally')
        return

    if not report:
        raise SystemExit(f'FAIL: no WHDLoad core dump ({base})\n{output}')
    first = next((l for l in report.splitlines() if l.strip()), '')
    print('WHDLoad:', first.strip())
    chip = (game / '.whdl_memory').read_bytes()
    exp = (game / '.whdl_expmem').read_bytes() if (game / '.whdl_expmem').exists() else b''
    # TIMEOUT reports as "DEBUG caused" once the CIA-A TOD event count passes it.
    event = re.search(r'event=([0-9A-F]+)', report)
    if 'DEBUG caused' not in report or not event or int(event[1], 16) < args.ticks:
        raise SystemExit(f'FAIL: the run did not end by TIMEOUT ({base})\n' + report[:2000])
    if args.cpu in ('68040', '68060') and 'TC=8000' not in report:
        raise SystemExit(f'FAIL: {args.cpu} MMU translation was not enabled (no TC=8000)\n' + report[:2000])
    # CACR alone does not show the policy: with the MMU, WHDLoad enables both
    # caches whatever the slave asks; setcpu= holds the slave's request.
    cacr = int(re.search(r'CACR=([0-9A-F]+)', report)[1], 16)
    setcpu = re.search(r'setcpu=\S+', report)[0]
    ic, dc = (0x8000, 0x80000000) if args.cpu in ('68040', '68060') else (0x1, 0x100)
    print(f'CACR={cacr:X}', setcpu)
    if not cacr & ic or bool(cacr & dc) != dcache or (',DC,' in setcpu) != dcache:
        raise SystemExit(f'FAIL: CACR={cacr:X}: expected the instruction cache'
                         + (' and the data cache' if dcache else ' without the data cache'))
    memory = chip + exp
    image = blocks(load_image((args.data / 'WC2.EXE').read_bytes()))
    found = sum(1 for b in image if b[::-1] in memory)
    print(f'WC2.EXE load image in guest RAM: {found} of {len(image)} blocks')
    if args.slave and args.slave.name.startswith('MemFree'):
        print('MemFree low water: Chip {:,} Fast {:,} bytes'.format(
            int.from_bytes(chip[0x100:0x104], 'big'), int.from_bytes(chip[0x104:0x108], 'big')))
    if found < len(image) // 2:
        raise SystemExit(f'FAIL: the game is not resident in guest RAM ({base})')
    print(f'PASS: game runs under WHDLoad on {args.setup}'
          + (', analog joystick' if args.analog else '')
          + (f', {args.cpu} MMU' + (' in use' if dcache else ' unused') if mmu else '')
          + f', CACR={cacr:X}')
    shutil.rmtree(base)


if __name__ == '__main__':
    main()
