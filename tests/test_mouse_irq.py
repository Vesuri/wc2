#!/usr/bin/env python3
"""Mouse IRQ12: recorded external handler, IVT guards, IF and guest ownership."""
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import host_run as H

U = H.U


def call(h, name, *args):
    stack = H.STACK_TOP - 4 * (len(args) + 1)
    stop = 0x00fe0000
    h.e.write(stack, struct.pack('>' + 'I' * (len(args) + 1), stop, *args))
    h.e.reg_write(U.M68K['sr'], 0x2700)
    h.e.reg_write(U.M68K['a7'], stack)
    error = h.e.start(h.syms[name], stop, timeout_us=10_000_000)
    assert not error, error
    assert h.halted or h.r('pc') == stop, f"{name} did not return before the limit"
    return h.r('d0')


def write_guest(h, addr, data):
    h.e.write(H.TOP - addr - len(data) + 1, data[::-1])


def machine():
    h = H.Host(H.image.M.REF)
    h.halted = False
    call(h, 'rt_start', H.BLOCK)
    h.e.write(h.syms['rt_present_due'], b'\0')
    h.e.write(H.TOP + 11, b'\1')  # G_IF
    return h


def check_irq():
    # WC2's reference vector F000:CFA0 (machine.c MOUSE_INT74_*, MEASURED: host-m0 IVT)
    for seg, off in [(0xf000, 0xcfa0), (0xf000, 0xcfa1), (0xf001, 0xcfa0)]:
        h = machine()
        write_guest(h, 0x74 * 4, struct.pack('<HH', off, seg))
        h.post(0x74)
        result = call(h, 'rt_irq_c', 0x08220000, 0x100)
        if (seg, off) == (0xf000, 0xcfa0):
            assert result == 0 and not h.halted and h.mem(H.G_IRQ, 1) == b'\0', (result, h.log)
        else:
            assert h.halted and any('hardware interrupt vector' in x for x in h.log), h.log
        print(f'{seg:04x}:{off:04x}: expected handling confirmed')

    # With IF clear the queued mouse interrupt must remain pending.
    h = machine()
    h.e.write(H.TOP + 11, b'\0')
    h.post(0x74)
    call(h, 'rt_irq_c', 0x08220000, 0x100)
    assert h.mem(h.syms['rt_irq_pending'], 1) == b'\1'
    h.e.write(H.TOP + 11, b'\1')
    call(h, 'rt_irq_c', 0x08220000, 0x100)
    assert h.mem(h.syms['rt_irq_pending'], 1) == b'\0'

    # A guest-installed vector must enter translated code, not be swallowed.
    h = machine()
    cs = int.from_bytes(h.mem(h.syms['rt_entry_cs'], 2), 'big')
    ip = int.from_bytes(h.mem(h.syms['rt_entry_ip'], 2), 'big')
    write_guest(h, 0x74 * 4, struct.pack('<HH', ip, cs))
    h.post(0x74)
    assert call(h, 'rt_irq_c', 0x08220000, 0x100) == 0x08220100
    assert not h.halted
    assert int.from_bytes(h.mem(h.syms['rt_deliver_cs'], 2), 'big') == cs
    assert int.from_bytes(h.mem(h.syms['rt_deliver_ip'], 2), 'big') == ip
    assert h.u32(h.syms['rt_deliver_code']) != 0
    assert h.mem(H.TOP + 11, 1) == b'\0'
    print('mouse IRQ: external guards, IF deferral and translated guest handler pass')


def check_reference():
    # Positive controls over WC2's mouse surface in the m2 reference (gate 1, run a):
    # reset, set position and the position poll with motion and both button states;
    # WC2 reads no motion counters (AX=0Bh) and takes no IRQ12 there (MEASURED).
    trace = H.REPO / 'tmp/pc-runs/ref-m2-a/trace'
    calls, positions, buttons, pending = set(), set(), set(), []
    for kind, regs in H.reference_services(trace):
        if kind == 'svc':
            pending.append(regs)
        else:
            entry = pending.pop()
            if entry['vector'] != 0x33:
                continue
            calls.add(entry['ax'])
            if entry['ax'] == 3:
                positions.add((regs['cx'], regs['dx']))
                buttons.add(regs['bx'])
    assert calls == {0, 3, 4}, calls
    assert len(positions) > 1 and buttons == {0, 1}, (positions, buttons)
    assert not any(v == 0x74 for _, _, _, v in H.reference_inputs(trace)[0])
    print('mouse reference: reset, set position, moved positions and both button states covered')


if __name__ == '__main__':
    check_irq()
    check_reference()
