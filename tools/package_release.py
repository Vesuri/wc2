#!/usr/bin/env python3
"""Create the minimal deterministic Amiga LHA distributions (LH5).
From Secret Weapons of the Luftwaffe's tools/package_release.py (docs/upstream.md).

    python3 tools/package_release.py amiga/out/Wc2-release.exe dist

  dist/WC2-<version>.lha          full release (GitHub), with the Wc2 executable
  dist/WC2-<version>-whdload.lha  for whdload.de: no Wc2 executable; Install asks for it
  dist/Wc2                        the executable, published beside the full archive

Members are refused when their SHA-256 is an original's: every hash in
reference/archives.sha256, disk-images.sha256, disk-files.sha256 and install.sha256.
"""
import argparse
from pathlib import Path
import _amigaxdev  # noqa: F401
from amigaxdev import release
from amigaxdev.release import crc16  # noqa: F401  (check_release.py imports it from here)

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_HASHES = {line.split()[0] for name in ('archives', 'disk-images', 'disk-files', 'install')
                   for line in (ROOT / f'reference/{name}.sha256').read_text().splitlines() if line.strip()}
PREFIX = 'WC2 Install'
STAMP = release.dos_stamp(2026, 11, 19)
ICONS = ROOT / 'release/icons'
WHDLOAD_DE_OMITS = ('Wc2',)


def archive_names(version):
    """(archive name, omitted members) for the full and the whdload.de archive."""
    return ((f'WC2-{version}.lha', ()), (f'WC2-{version}-whdload.lha', WHDLOAD_DE_OMITS))


def installer_icon(game=False):
    # Wc2.inf is distributed as is, renamed and configured by Installer, exactly
    # as RoF.inf in the reference package. No synthetic replacement artwork.
    return release.installer_icon(ICONS, 'Wing Commander II', game=game)


def members(executable):
    return {
        'Wc2': executable.read_bytes(),
        'Wc2.slave': (ROOT / 'build/whdload/Wc2.slave').read_bytes(),
        'Wc2.inf': installer_icon(game=True),
        'WC2InstallData': (ROOT / 'build/install-data/WC2InstallData.exe').read_bytes(),
        'Install': (ROOT / 'release/Install').read_bytes(),
        'Install.info': installer_icon(),
        'ReadMe': (ROOT / 'release/ReadMe').read_bytes(),
        'ReadMe.info': release.template_icon(ICONS, 'readme.info.b64'),
        'LICENSE.LGPL.txt': (ROOT / 'tools/install-data/COPYING.LIB').read_bytes(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('executable', type=Path)
    parser.add_argument('output_directory', type=Path)
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    files = members(args.executable)
    release.refuse_originals(files, ORIGINAL_HASHES)
    for name, omitted in archive_names(version):
        contents = {k: v for k, v in files.items() if k not in omitted}
        archive = release.write(args.output_directory / name,
                                release.archive(PREFIX, contents, release.template_icon(ICONS, 'drawer.info.b64'), STAMP))
        print(f'{archive}: {len(contents)} drawer contents plus drawer icon, {archive.stat().st_size} bytes')
    executable = args.output_directory / 'Wc2'
    executable.write_bytes(files['Wc2'])
    print(f'{executable}: the release executable, {executable.stat().st_size} bytes')


if __name__ == '__main__':
    main()
