"""Image proof (tools/load_image.py): DOS read provenance (overwritten files must use
bytes captured at the read) and the WC2 loader model on synthetic snapshots built
from ref/ (make install): the model's own image passes; a byte changed without a
writer, or an overlay left unrelocated, fails; a changed byte with a writer passes."""
import argparse
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import load_image as L
import wc2_model as M

LOAD = 0x0824


def snapshot(root: Path, ram: bytearray, rows, writes=()):
    """A snapshot directory: RAM, residency rows (linear, module, offset, bytes)."""
    trace = root / 'trace'
    snap = trace / 'snap-t'
    snap.mkdir(parents=True)
    (trace / 'events.csv').write_text('icount,kind,module,offset,detail\n')
    (snap / 'ram.bin').write_bytes(bytes(ram))
    (snap / 'regs.txt').write_text(f'icount=1 hits=1\nload_seg={LOAD:04x} vga_mode=13\n')
    with (snap / 'residency.csv').open('w') as f:
        f.write('first_para,last_para,module,module_offset\n')
        for lin, mod, off, n in rows:
            f.write(f'0x{lin >> 4:05x},0x{(lin + n - 1) >> 4:05x},{mod},0x{off:05x}\n')
    with (snap / 'writes.csv').open('w') as f:
        f.write('first_linear,last_linear,writer_module,writer_offset\n')
        for a in writes:
            f.write(f'0x{a:05x},0x{a:05x},WC2.EXE,0x00100\n')
    return snap


class LoaderModel(unittest.TestCase):
    """Needs ref/ (make install); a missing ref/ fails, it never skips."""

    @classmethod
    def setUpClass(cls):
        if not (M.REF / M.ROOT).exists():
            raise AssertionError(f'{M.REF / M.ROOT} missing: run make install')
        cls.root = M.root_image(LOAD)
        cls.ovl = max((o for o in M.overlays() if o.relocs), key=lambda o: len(o.relocs))
        cls.code = M.overlay_code(cls.ovl, LOAD)

    def prove(self, change=None, writes=(), raw_overlay=False):
        ram = bytearray(0x100000)
        base, buf = LOAD * 16, 0x60000
        ram[base:base + len(self.root)] = self.root
        code = M.image_file()[self.ovl.code:self.ovl.code + self.ovl.size] if raw_overlay else self.code
        ram[buf:buf + len(code)] = code
        if change is not None:
            ram[change] ^= 0xFF
        size = (self.ovl.size + 15) & ~15
        with tempfile.TemporaryDirectory() as tmp:
            snap = snapshot(Path(tmp), ram, [(base, M.ROOT, 0, len(self.root)),
                                             (buf, M.ROOT, self.ovl.code, size)], writes)
            argv = sys.argv
            sys.argv = ['load_image.py', str(snap)]
            try:
                with patch('sys.stdout', new=io.StringIO()):
                    return L.main()
            finally:
                sys.argv = argv

    def test_model_image_passes(self):
        self.assertEqual(self.prove(), 0)

    def test_changed_root_byte_fails(self):
        self.assertEqual(self.prove(change=LOAD * 16 + 0x1000), 1)

    def test_changed_overlay_byte_fails(self):
        self.assertEqual(self.prove(change=0x60000 + self.ovl.size // 2), 1)

    def test_written_byte_passes(self):
        a = LOAD * 16 + 0x1000
        self.assertEqual(self.prove(change=a, writes=[a]), 0)

    def test_unrelocated_overlay_fails(self):
        self.assertEqual(self.prove(raw_overlay=True), 1)


class ReadData(unittest.TestCase):
    def check_reads(self, lines, payload=b'X', captured=b'ABCDE'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'trace').mkdir()
            if captured is not None:
                (root / 'trace/reads.bin').write_bytes(captured)
            (root / 'root').mkdir()
            (root / 'ref').mkdir()
            (root / 'root/RP2.TMP').write_bytes(payload)
            events = root / 'trace/events.csv'
            events.write_text('icount,kind,module,offset,detail\n' + lines)
            return L.dos_reads(events, 20, root / 'ref')

    def test_rewrite_overlap_and_cutoff(self):
        self.assertEqual(self.check_reads(
            '1,read,-,0,RP2.TMP linear=0x100 pos=0x20 got=3 data=0\n'
            '2,read,-,0,RP2.TMP linear=0x101 pos=0 got=1 data=3\n'
            '21,read,-,0,RP2.TMP linear=0x100 pos=0 got=1 data=4\n'),
            {0x100: 65, 0x101: 68, 0x102: 67})

    def test_empty_read(self):
        self.assertEqual(self.check_reads(
            '1,read,-,0,RP2.TMP linear=0x100 pos=0xffff got=0 data=5\n'), {})

    def test_malformed_payload_fails(self):
        for data in ('-1', '4', 'bad'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.check_reads(f'1,read,-,0,RP2.TMP linear=0x100 pos=0 got=2 data={data}\n')

    def test_new_capture_missing_offset_fails(self):
        with self.assertRaises(ValueError):
            self.check_reads('1,read,-,0,RP2.TMP linear=0x100 pos=0 got=1\n')

    def test_legacy_capture(self):
        self.assertEqual(self.check_reads(
            '1,read,-,0,RP2.TMP linear=0x100 pos=0x1 got=2\n', b'ABC', captured=None),
            {0x100: 66, 0x101: 67})

    def test_legacy_short_file_fails(self):
        with self.assertRaises(ValueError):
            self.check_reads('1,read,-,0,RP2.TMP linear=0x100 pos=0 got=2\n', captured=None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    if args.sabotage:
        original = L.dos_reads
        def broken(*args):
            result = original(*args)
            return {address: 0 for address in result}
        with patch.object(L, 'dos_reads', broken):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.TestSuite([ReadData('test_rewrite_overlap_and_cutoff')]))
        assert len(result.failures) == 1 and not result.errors, 'lost DOS read bytes escaped detection'
        print('sabotage: corrupted DOS read payload caught')
        # the proof expects raw FBOV bytes for overlay code (relocation ignored)
        real_init = L.Expected.__init__
        def unrelocated(self, ref, load):
            real_init(self, ref, load)
            self.code = {o.code: self.file[o.code:o.code + o.size] for o in self.ovls}
        with patch.object(L.Expected, '__init__', unrelocated):
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                unittest.TestSuite([LoaderModel('test_model_image_passes')]))
        assert len(result.failures) == 1 and not result.errors, 'unrelocated overlay model escaped detection'
        print('sabotage: overlay relocation dropped from the model caught')
    else:
        unittest.main(argv=[sys.argv[0]])
