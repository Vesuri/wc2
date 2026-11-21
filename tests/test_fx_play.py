#!/usr/bin/env python3
"""Prerendered effect playback (src/platform/amiga/fx_play.c) with synthetic
samples and effect-slot states, no game bytes. Adapted from X-Wing's
tests/test_fx_play.py (its commit 0eda68f's successors, docs/upstream.md).

  python3 tests/test_fx_play.py [--sabotage]

A slot that starts an effect with a sample at full volume (7Fh), once its start
is counted (before, its channels muted and no play): the OPL
channels its voices play muted while it plays, a Paula voice reserved and
restarted on the sample's first chunk at the effect period and the sample's
volume, the next chunk (or silence) latched a field after the latched one
starts, the voice given back once the last has played. After the slot's
release the channels stay muted while the sample sounds, each until a key-on
edge there. A sample over one Paula loop splits into equal chunks. Two slots
of one id play on two voices; a start the game made on a slot that plays the
same id restarts it; a stop before the game's release fades over
FX_FADE_FIELDS, one at its release plays out; a fourth play takes the
oldest's voice, so the music keeps one. An id with no sample, or a slot at
another volume, stays on FM. PAL and NTSC periods; volume from fm_effect's
peak.
"""
import ctypes as C
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from test_fm_quality import Voice  # noqa: E402

SRC = ROOT / 'src/platform/amiga'
PERIOD = {0: 214, 1: 216}           # FM_EFFECT_RATE on PAL, NTSC
FIELD = {0: 71051 / 214, 1: 119665 / 2 / 216}   # samples a field
FIELD8 = 256 * 71051 // 214         # fx_play.c's 24.8 samples a PAL field
IDS, SLOTS, PLAYS, FADE, FULL = 56, 32, 3, 3, 0x7f


def RESERVE(v):
    return 1 << (12 + v)            # fm_paula.h FM_RESERVE


class Driver(C.Structure):
    _fields_ = [('active', C.c_uint8 * SLOTS), ('id', C.c_uint8 * SLOTS),
                ('volume', C.c_uint8 * SLOTS), ('owner', C.c_uint8 * 9)]


class Rig:
    def __init__(self, lib):
        self.lib = lib
        lib.fx_field.argtypes = [C.c_void_p] * 4
        lib.fx_field.restype = C.c_uint16
        lib.fx_effect.argtypes = [C.c_uint8, C.c_void_p, C.c_uint32, C.c_uint8, C.c_uint32, C.c_void_p]
        lib.fx_effect_volume.argtypes = [C.c_uint32]
        lib.fx_effect_volume.restype = C.c_uint8
        self.d = Driver()
        self.d.id[:] = [0xff] * SLOTS
        self.d.owner[:] = [0xff] * 9
        self.starts = (C.c_uint8 * IDS)()
        self.keyon = (C.c_uint8 * 9)()
        self.v = (Voice * 4)()

    def play(self, slot, sid, channels, volume=FULL, start=True):
        self.d.active[slot], self.d.id[slot], self.d.volume[slot] = 1, sid, volume
        for c in channels:
            self.d.owner[c] = slot
            self.keyon[c] = (self.keyon[c] + 1) & 255
        if start:
            self.starts[sid] = (self.starts[sid] + 1) & 255

    def stop(self, slot):
        self.d.active[slot] = 0
        for c in range(9):
            if self.d.owner[c] == slot:
                self.d.owner[c] = 0xff

    def field(self):
        m = self.lib.fx_field(C.byref(self.d), self.starts, self.keyon, self.v)
        held = [i for i in range(4) if m & RESERVE(i)]
        return m & 0x1ff, held

    def addr(self, i):
        return C.addressof(self.v[i].loop.contents) if self.v[i].loop else 0


def checks(lib):
    for level, vol in [(0, 1), (32, 1), (4095, 64), (2048, 32), (9000, 64), (64, 1), (96, 2)]:
        assert lib.fx_effect_volume(level) == vol, f'volume of {level}'
    r = Rig(lib)
    ntsc = C.c_uint8.in_dll(lib, 'fm_ntsc')
    silence = (C.c_int8 * 4)()
    small = (C.c_int8 * 1000)(*[5] * 1000)
    big_bytes = 72184
    big = (C.c_int8 * big_bytes)()
    # Unregistered: FM keeps every channel and voice.
    r.play(0, 9, (0, 1))
    assert r.field() == (0, []), 'an id with no sample taken'
    r.stop(0)
    r.field()
    for sid in (5, 7, 8, 10):
        lib.fx_effect(sid, small, 1000, 40, 1000, silence)
    lib.fx_effect(6, big, big_bytes, 64, big_bytes, silence)
    lib.fx_effect(11, small, 131070, 64, 1000, silence)     # over two loops: refused
    r.play(0, 11, (0,))
    assert r.field() == (0, []), 'a refused sample taken'
    r.stop(0)
    r.field()
    # Another slot volume than the capture's: FM.
    r.play(30, 5, (2,), volume=FULL - 1)
    assert r.field() == (0, []), 'a slot below full volume taken'
    r.stop(30)
    r.field()
    # A slot seen before its start is counted (the start fills it, keys the
    # note on, then returns): muted, no play; the count a field later starts
    # one play, not a restart after it.
    r.play(7, 5, (2,), start=False)
    assert r.field() == (1 << 2, []), 'a play before its start was counted'
    r.starts[5] += 1
    m = r.field()
    assert m == (1 << 2, [0]) and r.v[0].restart, f'the counted start not played {m}'
    m = r.field()
    assert m == (1 << 2, [0]) and not r.v[0].restart, f'the count taken as a restart {m}'
    r.stop(7)
    for _ in range(FADE + 2):
        r.field()
    base, sil = C.addressof(small), C.addressof(silence)
    for mode in (0, 1):
        ntsc.value = mode
        for slot, channels in ((2, (0, 1, 8)), (31, (4,))):
            r.play(slot, 5, channels)
            out = []
            for _ in range(12):
                out.append((r.field(), r.v[0].restart, r.addr(0), r.v[0].bytes, r.v[0].period, r.v[0].volume))
            want_mask = sum(1 << c for c in channels)
            assert all(f[0][0] == want_mask for f in out), f'slot {slot}: mask {out}'
            assert out[0][0][1] == [0] and out[0][1:] == (1, base, 1000, PERIOD[mode], 40), f'start {out[0]}'
            assert out[1][1:3] == (0, sil) and out[1][3] == 4 and out[1][5] == 40, f'latch {out[1]}'
            playing = [f for f in out if f[0][1]]
            want = -(-(1000 + FIELD[mode]) // FIELD[mode])
            assert abs(len(playing) - want) <= 1, f'slot {slot}: {len(playing)} fields, not {want}'
            assert not out[-1][0][1], 'voice kept after the sample'
            r.stop(slot)
            assert r.field() == (0, []), 'channels kept after the stop'
    ntsc.value = 0
    # Two chunks: equal halves, the second latched at field 1, silence a field
    # after the second starts, then the voice back.
    r.play(1, 6, (3,))
    f = []
    while True:
        m = r.field()
        f.append((m, r.v[0].restart, r.addr(0), r.v[0].bytes))
        if not m[1]:
            break
    half, b = big_bytes // 2, C.addressof(big)
    assert f[0][1:] == (1, b, half), f'chunk 0 {f[0]}'
    assert f[1][1:] == (0, b + half, half), f'chunk 1 {f[1]}'
    k = next(n for n, x in enumerate(f) if x[2] == sil)
    want = next(n for n in range(1, 1000) if n * FIELD8 >> 8 >= half + (FIELD8 >> 8))
    assert k == want, f'silence latched at field {k}, not {want}'
    assert f[-1][0] == (1 << 3, []), 'the slot still plays it: its channel stays muted'
    r.stop(1)
    r.field()
    # Two slots of one id: two voices.
    r.play(0, 5, (0,))
    r.play(3, 5, (1,))
    assert r.field() == (3, [0, 1]) and r.v[0].restart and r.v[1].restart, 'two instances'
    # A start the game made on a slot that plays the id: a restart, no new voice.
    r.field()
    r.starts[5] += 1
    assert r.field() == (3, [0, 1]), 'restart took a voice'
    assert sum(r.v[i].restart for i in (0, 1)) == 1, 'restart not seen'
    assert r.field()[1] == [0, 1] and not r.v[0].restart and not r.v[1].restart
    r.stop(0)
    r.stop(3)
    # An early stop fades; the voice is back after it; its channel stays muted
    # through the fade until a key-on there.
    vols = []
    for _ in range(6):
        r.field()
    r.play(4, 7, (5,))
    r.field()
    r.stop(4)
    for n in range(FADE + 1):
        m = r.field()
        vols.append(r.v[0].volume if m[1] else None)
        assert m[0] == (1 << 5 if n < FADE else 0), f'fade field {n}: mask {m}'
    assert vols == [40 * n // (FADE + 1) for n in range(FADE, 0, -1)] + [None], f'fade {vols}'
    # A stop at the game's release: the tail plays out, the channel muted until
    # a key-on there, the play's voice kept.
    lib.fx_effect(8, small, 1000, 40, 300, silence)
    r.play(4, 8, (5, 6))
    r.field()
    r.field()
    r.stop(4)
    m = r.field()
    assert m == ((1 << 5) | (1 << 6), [0]) and r.v[0].volume == 40, f'tail cut {m} {r.v[0].volume}'
    r.keyon[6] += 1                 # the music keys channel 6 on
    m = r.field()
    assert m == (1 << 5, [0]), f'a key-on left its channel muted {m}'
    for _ in range(4):
        m = r.field()
    assert m == (0, []), f'the tail outlived its sample {m}'
    # Four at once: three play, the fourth on the oldest's voice; one voice
    # stays the music's.
    for p, sid in enumerate((5, 7, 8)):
        r.play(p, sid, (p,))
        assert len(r.field()[1]) == p + 1
    r.play(5, 10, (6,))
    m = r.field()
    assert m == (0b1000111, [0, 1, 2]), f'fourth play {m}'
    assert r.v[0].restart and not r.v[1].restart and not r.v[2].restart, 'not the oldest voice'
    lib.fx_clear()
    for p in (0, 1, 2, 5):
        r.stop(p)
    assert r.field() == (0, []), 'cleared samples still play'
    print('effect play: masks, full volume, counted start, chunks, latch, instances, restart, fade, '
          'tail and key-on, voice cap, PAL/NTSC: ok')


def main():
    plants = {'latch': ('* e->chunk + (field >> 8)', '* e->chunk'),
              'chunk': ('(bytes + EFFECT_LOOP_BYTES - 1) / EFFECT_LOOP_BYTES', '1'),
              'full': ('d->volume[k] == FX_FULL', '1'),
              'mask': ('mask = (uint16_t)(mask | 1u << k);', ';'),
              'reserve': ('mask = (uint16_t)(mask | FM_RESERVE(p->voice));', ';'),
              'restart': ('fresh[tracked[k]]) {', '0) {'),
              'fade': ('p->phase = FADE;', 'p->phase = IDLE;'),
              'tail': ('(p->elapsed >> 8) + 2 * (field >> 8) < p->e->end', 'field'),
              'release': ('mask = (uint16_t)(mask | p->channels);', ';'),
              'keyon': ('keyon[c] != p->keys[c]', '0'),
              'cap': ('if (plays[k].phase == IDLE) {\n                if (!p)', 'if (1) {\n                if (!p)'),
              'ntsc': ('fm_ntsc ? EFFECT_PERIOD_NTSC', '0 ? EFFECT_PERIOD_NTSC'),
              'count': ('appeared[k] = fresh[id] != 0;', 'appeared[k] = 1;'),
              'wait': ('now[d->owner[k]] != FX_NONE', 'tracked[d->owner[k]] != FX_NONE')}
    cases = plants.items() if '--sabotage' in sys.argv else [('normal', None)]
    missed = []
    for name, plant in cases:
        with tempfile.TemporaryDirectory(prefix='fx-play-', dir=ROOT / 'tmp') as tmp:
            paths = []
            for filename in ('fm_paula.c', 'fx_play.c'):
                text = (SRC / filename).read_text()
                if plant and filename == 'fx_play.c':
                    assert plant[0] in text, name
                    text = text.replace(plant[0], plant[1])
                path = Path(tmp) / filename
                path.write_text(text)
                paths.append(str(path))
            dll = Path(tmp) / 'fx.so'
            subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-parameter', '-I', str(SRC), *paths, '-o', str(dll)], check=True)
            try:
                checks(C.CDLL(str(dll)))
            except AssertionError as e:
                if not plant:
                    raise
                print(f'plant {name}: caught ({e})')
            else:
                if plant:
                    print(f'plant {name}: MISSED')
                    missed.append(name)
    if missed:
        print('FAIL: plants missed:', ', '.join(missed))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
