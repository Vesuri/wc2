#!/usr/bin/env python3
"""The intro's speech on Paula (make test-amiga-speech): the
production image on the 68030 model, started from the Shell as the replay, with
amiga/play_walk.sh's route (Esc through the opening to the title's BUTTONS.V00, then once the title has
set the pointer, TEMPGLOB.000 opened, a click on "Start New Game" repeated until
CAMPAIGN.S00 opens), runs into the intro's speech until the
game's IRQ 7 handler (WC2.EXE+6F3F) is entered for the (ENDS + 1)th time: ENDS
blocks have ended (X-Wing's speech fixture stops with an ignore count too). Checks, each with its control:

- blocks: every block the DSP model started (amiga_sb_blocks, timed for its
  IRQ 7) was handed to the player (sb_started), at least MIN_BLOCKS; all but
  the one playing have ended (sb_ended): each block followed the last without
  a cut (sb_play.c). Controls: a player not called gives started 0; a restart
  for each block ended 6 of 41 (MEASURED, before the follow-on).
- speaker: on (rt_sb_speaker; the game sends D1h at its detection), so the
  voice is heard (sb_play.c volume).
- samples: the Chip block the player plays (Audio.cpp) holds the last block's
  guest bytes (amiga_audio_sb_linear, _bytes) with the sign flipped; the same
  comparison against the unflipped bytes must fail.

Exit 0 on PASS. Usage: tests/amiga_speech.py [--keep]
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
ENDS = int(os.environ.get('SPEECH_ENDS', '40'))   # 4000 bytes at 10752 Hz: 0.37 s a block (docs/pc-reference-loop.md)
MIN_BLOCKS = ENDS + 1
TIMEOUT = 1200              # wall seconds; a timeout fails
SB_BLOCK_BYTES = 65536      # sb_play.h

FIXTURE = r'''set pagination off
set confirm off
break plat_exit
commands
  silent
  printf "WC2_SPEECH_EXIT\n"
  quit 1
end
break *rt_stop
commands
  silent
  x/s *(char **)($sp+4)
  printf "WC2_SPEECH_STOP a=%x b=%x started=%u ended=%u\n", *(unsigned *)($sp+8), *(unsigned *)($sp+12), sb_started, sb_ended
  quit 1
end
break amiga_start_return
commands
  silent
  printf "WC2_PROGRAM_RETURNED %d\n", *(int *)($sp+4)
  quit 1
end
# the guest's IRQ 7 handler (WC2.EXE+6F3F) at each block's end: stop at entry
# ENDS + 1, so ENDS blocks have ended
break *R_06F3F
ignore $bpnum @ENDS@
continue
set $g = *(unsigned char **)&rt_guest
set $chip = *(signed char **)&'Audio.cpp'::sbChip + (*(unsigned char *)&'Audio.cpp'::sbNext ^ 1) * @BLOCK@
set $lin = amiga_audio_sb_linear
set $len = amiga_audio_sb_bytes
printf "WC2_SPEECH blocks=%u started=%u ended=%u restarts=%u speaker=%u linear=%x bytes=%u\n", amiga_sb_blocks, sb_started, sb_ended, amiga_audio_restarts, rt_sb_speaker, $lin, $len
printf "WC2_CHIP free=%u largest=%u\n", amiga_chip_free, amiga_chip_largest
if $len > 0
  eval "dump binary memory @OUT@/chip.bin %lu %lu", (unsigned long)$chip, (unsigned long)($chip + $len)
  eval "dump binary memory @OUT@/guest.bin %lu %lu", (unsigned long)($g - $lin - $len + 1), (unsigned long)($g - $lin + 1)
end
printf "WC2_SPEECH_DONE\n"
quit 0
'''


def problems(log: str, out: Path) -> list[str]:
    m = re.search(r'^WC2_SPEECH blocks=(\d+) started=(\d+) ended=(\d+) restarts=(\d+) speaker=(\d+) '
                  r'linear=([0-9a-f]+) bytes=(\d+)$', log, re.M)
    if not m or 'WC2_SPEECH_DONE' not in log:
        return ['no speech report: ' + ' | '.join(log.splitlines()[-12:])]
    blocks, started, ended, restarts, speaker, _, length = (int(m.group(k), 16 if k == 6 else 10)
                                                             for k in range(1, 8))
    print(m.group(0))
    chip_free = re.search(r'^WC2_CHIP .*$', log, re.M)
    if chip_free:
        print(chip_free.group(0))
    out_ = []
    if started != blocks or started < MIN_BLOCKS:
        out_.append(f'blocks: {started} played of {blocks} timed (at least {MIN_BLOCKS})')
    if not started - 1 <= ended <= started:
        out_.append(f'blocks: {ended} ended of {started} started')
    if speaker != 1:
        out_.append(f'speaker {speaker}')
    chip, guest = (out / 'chip.bin').read_bytes(), (out / 'guest.bin').read_bytes()[::-1]
    if len(chip) != length or len(guest) != length:
        return out_ + [f'samples: dumps {len(chip)}, {len(guest)} bytes, not {length}']
    flipped = bytes(b ^ 0x80 for b in guest)
    if chip != flipped:
        k = next(i for i in range(length) if chip[i] != flipped[i])
        out_.append(f'samples: Chip byte {k} {chip[k]:02x}, guest {guest[k]:02x}')
    if chip == guest:
        out_.append('samples: control failed, the unconverted bytes compare equal')
    return out_


def main() -> int:
    tmp = ROOT / 'tmp'
    tmp.mkdir(exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='speech-', dir=tmp))
    out = run / 'out'
    out.mkdir()
    fixture = run / 'speech.gdb'
    # gdb runs in amiga/ (debug.sh); a relative path keeps the project's spaces out
    fixture.write_text(FIXTURE.replace('@OUT@', os.path.relpath(out, ROOT / 'amiga')).replace('@BLOCK@', str(SB_BLOCK_BYTES))
                       .replace('@ENDS@', str(ENDS)))
    keys = 'uBUTTONS.V00:esc*10,fTEMPGLOB.000:shot,d300:my-20,uCAMPAIGN.S00:lmb'
    fast = ('--uae_cpu_speed=max --uae_cpu_cycle_exact=false --uae_cpu_memory_cycle_exact=false '
            '--uae_blitter_cycle_exact=false')
    env = dict(os.environ, FSUAE_RUN=os.path.relpath(run, ROOT / 'amiga'), FSUAE_CLAIM_STRICT='1',
               AMIGA_CPU=os.environ.get('AMIGA_CPU', '68030'), AMIGA_SETUP='a1200-030',
               JOY0='none', JOY1='none', EXTRA_ARGS=os.environ.get('EXTRA_ARGS', fast),
               WC2_ARGS=f'KEYS={keys}')
    print(f'Diagnostic logs: {run}', flush=True)
    with (run / 'gdb.log').open('w') as log:
        process = subprocess.Popen(['bash', str(ROOT / 'amiga/debug.sh'), '', str(fixture)], env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 15)
            process.wait()
            print(f'FAIL: no report within {TIMEOUT} s')
            return 1
    found = problems((run / 'gdb.log').read_text(errors='replace'), out)
    for p in found:
        print('FAIL:', p)
    if found:
        return 1
    print('PASS: the intro speech plays on Paula: every block timed was played, its samples '
          'converted in Chip, the speaker on')
    if '--keep' not in sys.argv:
        shutil.rmtree(run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
