#!/usr/bin/env python3
"""Host test of WC2InstallData against the original installer's tree.

    python3 tools/install-data/test_install.py build/install-data/WC2InstallData

Local inputs (never committed), defaults from make extract and make install:
  WC2_DISK_FILES   the files of all 7 disks (tmp/union)
  WC2_DISK_IMAGES  disk1.img..disk7.img (tmp/extract/001639_wing_commander_2)
  WC2_INSTALLED    the original installer's WING2 tree (ref/WING2)
Cases: files and images install byte-identical to WC2_INSTALLED (every file but the
DOS programs, compared byte by byte here, not by the helper's own hashes); refusals of an
existing destination, a damaged disk file, a missing file and a missing image, each
leaving no destination behind.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = Path(os.environ.get('WC2_DISK_FILES', ROOT / 'tmp/union'))
IMAGES = Path(os.environ.get('WC2_DISK_IMAGES', ROOT / 'tmp/extract/001639_wing_commander_2'))
INSTALLED = Path(os.environ.get('WC2_INSTALLED', ROOT / 'ref/WING2'))
DOS_ONLY = {'INSTALL.DAT', 'INSTALL.EXE', 'README.EXE'}


def run(helper, source, dest):
    p = subprocess.run([helper, str(source), str(dest)], capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout


def tree(d):
    return {str(p.relative_to(d)): p for p in sorted(d.rglob('*')) if p.is_file()}


def same_as_installed(dest):
    got, want = tree(dest), {k: v for k, v in tree(INSTALLED).items() if k not in DOS_ONLY}
    if set(got) != set(want):
        return f'files differ: {sorted(set(got) ^ set(want))[:5]}'
    for k in want:
        if got[k].read_bytes() != want[k].read_bytes():
            return f'{k} differs'
    return None


def main():
    helper = Path(sys.argv[1]).resolve()
    for need in (FILES, IMAGES, INSTALLED):
        if not need.is_dir():
            sys.exit(f'missing local input {need}: run make extract and make install')
    fails = 0
    with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as t:
        t = Path(t)

        def case(name, ok):
            nonlocal fails
            print(f'{"ok  " if ok is True else "FAIL"} {name}' + ('' if ok is True else f': {ok}'))
            fails += ok is not True

        for name, source in (('files', FILES), ('images', IMAGES)):
            dest = t / name
            rc, out = run(helper, source, dest)
            diff = same_as_installed(dest) if rc == 0 else out
            case(f'install from {name}', diff is None or f'rc={rc} {diff}')
        rc, _ = run(helper, FILES, t / 'files')
        case('existing destination refused', rc == 20 and same_as_installed(t / 'files') is None or f'rc={rc}')

        damaged = t / 'damaged'
        shutil.copytree(FILES, damaged)
        b = bytearray((damaged / 'WC2LOGO.VGA').read_bytes())
        b[len(b) // 2] ^= 1
        (damaged / 'WC2LOGO.VGA').write_bytes(b)
        rc, out = run(helper, damaged, t / 'd1')
        case('damaged disk file refused', (rc == 20 and not (t / 'd1').exists() and 'WC2LOGO.VGA' in out) or f'rc={rc}')
        (damaged / 'WC2LOGO.VGA').unlink()
        rc, _ = run(helper, damaged, t / 'd2')
        case('missing disk file refused', (rc == 20 and not (t / 'd2').exists()) or f'rc={rc}')

        partial = t / 'partial'
        partial.mkdir()
        for n in range(1, 7):
            os.symlink(IMAGES / f'disk{n}.img', partial / f'disk{n}.img')
        rc, _ = run(helper, partial, t / 'd3')
        case('missing image refused', (rc == 20 and not (t / 'd3').exists()) or f'rc={rc}')
    print('INSTALL_TEST_OK' if not fails else f'{fails} failed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
