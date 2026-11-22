#!/usr/bin/env python3
"""The prerendered effects at the game's sound init and their cache (make
test-amiga-sfx-cache; owner decision D15): the production image on the 68030
model, started from the Shell, three times in one run directory (the game
drawer dh1 keeps sfx.cache), each to the first frame the game presents
(plat_present). Checks, each with its control:

- before the first scene: the sound init's hook (HLE sfx_init) ran and the
  samples are in Chip before the first frame is presented
  (amiga_sfx_init_frame set, amiga_audio_effect_cached not 0).
- no cache: one capture, every id rendered, sfx.cache written (cached 2).
- the cache kept: no capture (rt_sfx_captures 0; the control is the first
  run's and the third's 1 under the same fixture), loaded (cached 1), the same
  samples, release ticks and volumes as the first run rendered.
- another key (the file's key word changed): refused, captured and rendered
  again, the cache rewritten, the same samples.

Exit 0 on PASS. Usage: tests/amiga_sfx_cache.py [--keep]
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 900               # wall seconds a run; a timeout fails
IDS = 56                    # runtime.h RT_SFX_IDS

FIXTURE = r'''set pagination off
set confirm off
break plat_exit
commands
  silent
  printf "WC2_SFX_EXIT\n"
  quit 1
end
break *rt_stop
commands
  silent
  x/s *(char **)($sp+4)
  printf "WC2_SFX_STOP a=%x b=%x\n", *(unsigned *)($sp+8), *(unsigned *)($sp+12)
  quit 1
end
break amiga_start_return
commands
  silent
  printf "WC2_PROGRAM_RETURNED %d\n", *(int *)($sp+4)
  quit 1
end
break plat_present
continue
printf "WC2_SFX frame=%u init=%u captures=%u capture_fields=%u fields=%u cached=%u bytes=%u key=%x\n", amiga_frames, amiga_sfx_init_frame, rt_sfx_captures, amiga_sfx_capture_fields, amiga_audio_effect_fields, amiga_audio_effect_cached, amiga_audio_effect_bytes, rt_sfx_key
set $i = 0
while $i < @IDS@
  if 'Audio.cpp'::effectChip[$i] != 0
    eval "dump binary memory @OUT@/fx-%u.bin %lu %lu", $i, (unsigned long)'Audio.cpp'::effectChip[$i], (unsigned long)('Audio.cpp'::effectChip[$i] + 'Audio.cpp'::effectBytes[$i])
  end
  set $i = $i + 1
end
dump binary memory @OUT@/ticks.bin &'Audio.cpp'::effectTicks[0] &'Audio.cpp'::effectTicks[@IDS@]
dump binary memory @OUT@/volume.bin &'Audio.cpp'::effectVolume[0] &'Audio.cpp'::effectVolume[@IDS@]
printf "WC2_SFX_DONE\n"
quit 0
'''

REPORT = re.compile(r'^WC2_SFX frame=(\d+) init=(\d+) captures=(\d+) capture_fields=(\d+) fields=(\d+) '
                    r'cached=(\d+) bytes=(\d+) key=([0-9a-f]+)$', re.M)
FIELDS = ('frame', 'init', 'captures', 'capture_fields', 'fields', 'cached', 'bytes')


def boot(run: Path, n: int) -> tuple[dict | None, str]:
    """One start to the first presented frame: its report and the samples."""
    out = run / f'out{n}'
    out.mkdir()
    fixture = run / f'sfx{n}.gdb'
    # gdb runs in amiga/ (debug.sh); a relative path keeps the project's spaces out
    fixture.write_text(FIXTURE.replace('@OUT@', os.path.relpath(out, ROOT / 'amiga')).replace('@IDS@', str(IDS)))
    fast = ('--uae_cpu_speed=max --uae_cpu_cycle_exact=false --uae_cpu_memory_cycle_exact=false '
            '--uae_blitter_cycle_exact=false')
    env = dict(os.environ, FSUAE_RUN=os.path.relpath(run, ROOT / 'amiga'), FSUAE_CLAIM_STRICT='1',
               AMIGA_CPU=os.environ.get('AMIGA_CPU', '68030'), AMIGA_SETUP='a1200-030',
               JOY0='none', JOY1='none', EXTRA_ARGS=os.environ.get('EXTRA_ARGS', fast))
    log_path = run / f'gdb{n}.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(['bash', str(ROOT / 'amiga/debug.sh'), '', str(fixture)], env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 15)
            process.wait()
            return None, f'run {n}: no report within {TIMEOUT} s'
    log = log_path.read_text(errors='replace')
    m = REPORT.search(log)
    if not m or 'WC2_SFX_DONE' not in log:
        return None, f'run {n}: no report: ' + ' | '.join(log.splitlines()[-12:])
    print(f'run {n}: {m.group(0)}', flush=True)
    r = {k: int(m.group(i + 1)) for i, k in enumerate(FIELDS)}
    r['key'] = int(m.group(8), 16)
    r['fx'] = {int(p.stem[3:]): p.read_bytes() for p in out.glob('fx-*.bin')}
    r['ticks'], r['volume'] = (out / 'ticks.bin').read_bytes(), (out / 'volume.bin').read_bytes()
    return r, ''


def problems(n: int, r: dict, want_captures: int, want_cached: int, first: dict | None) -> list[str]:
    out = []
    if not r['init'] or not r['cached']:
        out.append(f'run {n}: the first frame was presented before the effects were ready '
                   f'(init field {r["init"]}, cached {r["cached"]})')
    if r['captures'] != want_captures or r['cached'] != want_cached:
        out.append(f'run {n}: captures {r["captures"]}, cached {r["cached"]}; want {want_captures}, {want_cached}')
    if not r['fx'] or r['bytes'] != sum(len(b) for b in r['fx'].values()):
        out.append(f'run {n}: {len(r["fx"])} samples, {sum(len(b) for b in r["fx"].values())} bytes; '
                   f'Audio counted {r["bytes"]}')
    if first is not None:
        if r['key'] != first['key']:
            out.append(f'run {n}: input key {r["key"]:x}, the first run\'s {first["key"]:x}')
        diff = sorted(i for i in set(r['fx']) | set(first['fx']) if r['fx'].get(i) != first['fx'].get(i))
        if diff:
            out.append(f'run {n}: samples of ids {diff} differ from the first run\'s')
        if r['ticks'] != first['ticks'] or r['volume'] != first['volume']:
            out.append(f'run {n}: release ticks or volumes differ from the first run\'s')
    return out


def main() -> int:
    tmp = ROOT / 'tmp'
    tmp.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='sfx-cache-', dir=tmp))
    print(f'Diagnostic logs: {run}', flush=True)
    cache = run / 'dh1/sfx.cache'
    found: list[str] = []
    first, err = boot(run, 1)
    if first is None:
        found.append(err)
    else:
        found += problems(1, first, 1, 2, None)
    if not found:
        if not cache.exists():
            found.append('run 1: no sfx.cache written')
        else:
            written = cache.read_bytes()
            second, err = boot(run, 2)
            found += [err] if second is None else problems(2, second, 0, 1, first)
            if not found and cache.read_bytes() != written:
                found.append('run 2: sfx.cache rewritten although it held the key')
            if not found:
                data = bytearray(cache.read_bytes())
                data[8] ^= 0x01                 # the key word (Audio.cpp: magic, version, key, count)
                cache.write_bytes(bytes(data))
                third, err = boot(run, 3)
                found += [err] if third is None else problems(3, third, 1, 2, first)
                if not found and cache.read_bytes() != written:
                    found.append('run 3: sfx.cache not rewritten as the first run wrote it')
    for p in found:
        print('FAIL:', p)
    if found:
        return 1
    print(f'PASS: the effects are ready before the first frame; captured and cached on the first start '
          f'({first["capture_fields"]} + {first["fields"]} fields), loaded without a capture on the next '
          f'({second["fields"]} fields), the same {len(first["fx"])} samples; another key captured again')
    if '--keep' not in sys.argv:
        shutil.rmtree(run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
