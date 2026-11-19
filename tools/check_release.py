#!/usr/bin/env python3
"""Audit the exact minimal LHA releases, their checksums and their members.
From Secret Weapons of the Luftwaffe's tools/check_release.py (docs/upstream.md).

    python3 tools/check_release.py dist [--exe amiga/out/Wc2-release.exe]
    python3 tools/check_release.py --notes   # the newest ReadMe entry, for GitHub

Both archives (package_release.archive_names): the full one with the Wc2 executable,
the whdload.de one without it; dist/Wc2 must equal the executable. Every member is
decoded independently with Lhasa (`lha pq`) and must equal its build output. No member
may equal an original (package_release.ORIGINAL_HASHES) or hold any 64-byte block of the
original installed files (ref/WING2, local: WC2.EXE, the drivers and every GAMEDAT file),
forward or byte-reversed (guest RAM order).
"""
import argparse
import hashlib
import re
import struct
import subprocess
from pathlib import Path
from package_release import ORIGINAL_HASHES, PREFIX, ROOT, archive_names, crc16, members

DATE = '19.11.2026'
STAMP = (((2026 - 1980) << 9) | (11 << 5) | 19) << 16
CHIP, EXP = 0xC0000, 0x700000 + 0x80000     # the slave's BaseMem; ExpMem: game plus Kickstart


def original_blocks(size=64):
    out = set()
    files = sorted(p for p in (ROOT / 'ref/WING2').rglob('*') if p.is_file() and p.suffix.lower() != '.pdf')
    for p in files:
        d = p.read_bytes()
        for a in range(0, len(d) - size + 1, size):
            b = d[a:a + size]
            if len(set(b)) > 8:
                out.update((b, b[::-1]))
    assert len(out) > 100000, 'original installed files missing (ref/WING2)'
    return out


def contains_block(data, blocks, size=64):
    # Any aligned original block occurs whole in data, so slide by one over data.
    return any(data[i:i + size] in blocks for i in range(len(data) - size + 1))


def check_archive(archive, expected, blocks):
    raw = archive.read_bytes()
    pos, payloads = 0, {}
    while pos < len(raw) and raw[pos]:
        size = raw[pos]
        header = raw[pos + 2:pos + 2 + size]
        assert len(header) == size and sum(header) & 255 == raw[pos + 1], 'bad header checksum'
        assert header[:5] == b'-lh5-' and header[18] == 0, 'expected level-zero LH5'
        packed, unpacked = struct.unpack_from('<II', header, 5)
        assert struct.unpack_from('<I', header, 13)[0] == STAMP, 'wrong release date'
        n = header[19]
        assert size == 22 + n
        archive_name = header[20:20 + n].decode('ascii').replace('\\', '/')
        if archive_name == PREFIX + '.info':
            name = '@drawer'
        else:
            assert archive_name.startswith(PREFIX + '/'), 'wrong installation drawer'
            name = archive_name[len(PREFIX) + 1:]
        assert name in set(expected) | {'@drawer'} and name not in payloads, 'unexpected or duplicate file: ' + name
        pos += size + 2
        assert len(raw[pos:pos + packed]) == packed, 'truncated payload'
        data = subprocess.run(['lha', 'pq', str(archive.resolve()), archive_name],
                              check=True, capture_output=True).stdout
        assert len(data) == unpacked and crc16(data) == struct.unpack_from('<H', header, 20 + n)[0], 'bad payload CRC'
        payloads[name] = data
        pos += packed
    assert raw[pos:] == b'\0' and set(payloads) == set(expected) | {'@drawer'}, 'wrong archive contents'
    for name, data in expected.items():
        assert payloads[name] == data, 'member differs from build output: ' + name
    for name, data in payloads.items():
        assert hashlib.sha256(data).hexdigest() not in ORIGINAL_HASHES, 'original file: ' + name
        assert not contains_block(data, blocks), 'original bytes in ' + name
    for name in ('Wc2', 'Wc2.slave', 'WC2InstallData'):
        assert name not in expected or payloads[name][:4] == b'\0\0\3\xf3', 'not an Amiga HUNK executable: ' + name
    for name, kind in (('Wc2.inf', 4), ('ReadMe.info', 4), ('Install.info', 4), ('@drawer', 2)):
        assert payloads[name][:4] == b'\xe3\x10\0\1' and payloads[name][48] == kind, 'bad icon: ' + name
    version = (ROOT / 'VERSION').read_text().strip().encode()
    for name in ('Wc2', 'Wc2.slave', 'WC2InstallData'):
        assert name not in expected or \
            b'$VER: ' + name.encode() + b' ' + version + b' (' + DATE.encode() + b')' in payloads[name], 'version: ' + name
    assert b'$VER: Install ' + version + b' (' + DATE.encode() + b')' in payloads['Install']
    # Install accepts only this release's executable (Version VERSION.REVISION, not the next).
    major, minor = version.decode().split('.')
    for field, value in (('exe-version', major), ('exe-revision', minor)):
        assert re.search(rf'^\(set #{field} {value}\)'.encode(), payloads['Install'], re.M), 'Install #' + field
    assert b'version ' + version + b' (' + DATE.encode() + b'):' in payloads['ReadMe']
    for heading in (b'Requirements:', b'Installation:', b'Playing:', b'History:', b'Contact:', b'Credits:',
                    b'https://github.com/Vesuri/wc2'):
        assert heading in payloads['ReadMe'], heading
    assert b'TODO' not in payloads['ReadMe'], 'ReadMe placeholder left'
    # WHDLoadSlave header, whdload.i: flags +14, BaseMem +16, keyexit +31, ExpMem +32.
    slave = payloads['Wc2.slave']
    signature = b'\x70\xff\x4e\x75WHDLOADS'
    assert slave.count(signature) == 1, 'ambiguous WHDLoad header'
    header = slave.index(signature)
    flags = struct.unpack_from('>H', slave, header + 14)[0]
    assert flags & 0x32 == 0x32, 'Wc2.slave must set NoError, Req68020 and ReqAGA'
    assert struct.unpack_from('>I', slave, header + 16)[0] == CHIP, f'expected {CHIP >> 10} KiB Chip'
    assert struct.unpack_from('>I', slave, header + 32)[0] == EXP, f'expected ExpMem {EXP:#x}'
    assert slave[header + 31] == 0x5f, 'Help must be the quit key'
    # ws_DontCache (+28, relative to the header): the executable stays out of the file cache.
    dont = struct.unpack_from('>h', slave, header + 28)[0]
    pattern = b'(Wc2)\0'
    assert dont and slave[header + dont:header + dont + len(pattern)] == pattern, 'ws_DontCache pattern'
    assert b'C1:B:Analog joystick in port 2;' in slave, 'Custom1 analog joystick'
    assert b'APPNAME=Wing Commander II\0' in payloads['Install.info']
    assert not any(n.lower().endswith(('.wc2', '.cfg', '.dat', '.img', '.exe', '.drv', '.lzc')) for n in payloads)
    print(f'PASS: {archive.name}: {len(payloads)} allowlisted LH5 members; independent decompression, CRCs, '
          'build identity, no original files or blocks, versions, slave header and icons')


def release_notes(readme):
    """The ReadMe's newest History entry as Markdown bullets."""
    entry = readme[readme.index('\n version ') + 1:].split('\n\n', 1)[0].splitlines()[1:]
    notes = []
    for line in entry:
        if line.startswith(' - '):
            notes.append('- ' + line[3:])
        else:
            notes[-1] += ' ' + line.strip()
    return '\n'.join(notes) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dist', type=Path, nargs='?', default=ROOT / 'dist')
    parser.add_argument('--exe', type=Path, default=ROOT / 'amiga/out/Wc2-release.exe')
    parser.add_argument('--notes', action='store_true')
    args = parser.parse_args()
    if args.notes:
        print(release_notes((ROOT / 'release/ReadMe').read_text('latin-1')), end='')
        return
    full = members(args.exe)
    version = (ROOT / 'VERSION').read_text().strip()
    assert b'$VER: Wc2 ' + version.encode() + b' (' + DATE.encode() + b')' in full['Wc2'], 'version: Wc2'
    assert (args.dist / 'Wc2').read_bytes() == full['Wc2'], 'dist/Wc2 differs from the release executable'
    blocks = original_blocks()
    for name, omitted in archive_names(version):
        check_archive(args.dist / name, {k: v for k, v in full.items() if k not in omitted}, blocks)
    print('PASS: dist/Wc2 is the release executable')


if __name__ == '__main__':
    main()
