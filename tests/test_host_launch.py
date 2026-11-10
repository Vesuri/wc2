"""DOS shell launch inputs, checked before executing the first guest instruction.

WC2's reference launch is `WC2` with no argument (tools/pc_run.py); machine.c
builds that PSP (FCBs, command tail), compared at the MZ entry with gate 1's
m0 snapshot (run a), taken there."""
import argparse
from pathlib import Path
import host_run as H


def check(sabotage=False):
    root = Path(__file__).resolve().parents[1]
    h = H.Host(H.image.M.REF)
    script = {'keys': [], 'snapshots': [H.trigger('WC2.EXE+0')], 'irqs': [], 'releases': []}
    h.run(script, 30)
    assert h.stopped_at == 'R_00000', h.stopped_at
    psp = (h.u32(h.syms['load_segment']) - 0x10) * 16
    actual = h.gmem(psp, 256)
    expected = (root / 'tmp/pc-runs/ref-m0-a/trace/snap-m0-0/ram.bin').read_bytes()[psp:psp + 256]
    if sabotage:
        actual = actual[:0x80] + bytes([14]) + actual[0x81:]
    assert actual[0x5c:0x7c] == expected[0x5c:0x7c], 'FCBs'
    assert actual[0x80:] == expected[0x80:], 'command tail'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--sabotage', action='store_true')
    args = ap.parse_args()
    if args.sabotage:
        check()
        try:
            check(True)
        except AssertionError as exc:
            assert exc.args == ('command tail',), exc
        else:
            raise AssertionError('wrong command-tail length escaped')
        print('sabotage: wrong command-tail length caught')
    else:
        check()
        print('host launch: the no-argument PSP inputs match DOSBox-X')
