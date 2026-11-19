#!/usr/bin/env python3
"""WC2InstallData on the emulated Amiga (FS-UAE, A1200, Kickstart 3.1).

    python3 tools/install-data/test_amiga.py build/install-data/WC2InstallData.exe [--cpu 68030]

Boots the Workbench floppy's C: and runs the helper from a Shell with a 16 KiB stack on
the 7 disk images (as Disk1.img..Disk7.img), then compares the installed drawer on the
host with the original installer's tree, byte by byte (test_install.py's comparison).
Inputs are local, as test_install.py's; Kickstart 3.1 and the Workbench floppy from
AmigaXDev. The emulator is stopped by its own PID.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_install import IMAGES, ROOT, same_as_installed  # noqa: E402

AMIGA = Path.home() / '.local/share/amiga'
WORKBENCH = Path(os.environ.get('WORKBENCH_ADF', AMIGA / 'Workbenchv2.04rev37.67Workbench.adf'))
KICK = Path(os.environ.get('KICKSTART_A1200', AMIGA / 'Kickstarts/kick40068.A1200'))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('helper', type=Path)
    p.add_argument('--cpu', default='68020')
    p.add_argument('--seconds', type=int, default=900)
    args = p.parse_args()
    base = Path(tempfile.mkdtemp(prefix='install-amiga-', dir=ROOT / 'tmp'))
    print('Fixture:', base, flush=True)
    boot, work = base / 'boot', base / 'work'
    for d in (boot / 's', work / 'disks', base / 'state'):
        d.mkdir(parents=True)
    shutil.copyfile(args.helper, boot / 'WC2InstallData')
    for n in range(1, 8):
        shutil.copyfile(IMAGES / f'disk{n}.img', work / f'disks/Disk{n}.img')
    (boot / 's/startup-sequence').write_text(
        'DF0:C/Assign C: DF0:C\nStack 16384\nFailAt 999\n'
        'DH0:WC2InstallData DH1:disks DH1:WC2 >DH1:output\n'
        'If WARN\nEcho failed >DH1:failed\nElse\nEcho passed >DH1:passed\nEndIf\n')
    with (base / 'emulator.log').open('w') as log:
        emu = subprocess.Popen([os.environ.get('FSUAE', 'fs-uae'), '--amiga_model=A1200', '--cpu=' + args.cpu,
            '--uae_cpu_model=' + args.cpu, '--jit_compiler=0', '--chip_memory=2048', '--fast_memory=8192',
            '--kickstart_file=' + str(KICK), '--hard_drive_0=' + str(boot), '--hard_drive_0_priority=10',
            '--hard_drive_1=' + str(work), '--floppy_drive_0=' + str(WORKBENCH), '--audio_driver=dummy',
            '--warp_mode=1', '--fullscreen=0', '--automatic_input_grab=0',
            '--base_dir=' + str(base / 'fsuae'), '--state_dir=' + str(base / 'state')],
            stdout=log, stderr=log, env=dict(os.environ, SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline and not any((work / n).exists() for n in ('passed', 'failed')):
                if emu.poll() is not None:
                    sys.exit(f'FAIL: FS-UAE exited unexpectedly ({base})')
                time.sleep(.5)
            time.sleep(1)
        finally:
            emu.terminate()
            try:
                emu.wait(timeout=5)
            except subprocess.TimeoutExpired:
                emu.kill()
                emu.wait()
    output = (work / 'output').read_text(errors='replace') if (work / 'output').exists() else ''
    print(output.strip())
    if not (work / 'passed').exists():
        sys.exit(f'FAIL: the helper did not succeed within {args.seconds} s ({base})')
    for sidecar in (work / 'WC2').rglob('*.uaem'):
        sidecar.unlink()
    diff = same_as_installed(work / 'WC2')
    if diff:
        sys.exit(f'FAIL: {diff} ({base})')
    print(f'PASS: WC2InstallData on the {args.cpu} installs the original installer\'s tree')
    shutil.rmtree(base)


if __name__ == '__main__':
    main()
