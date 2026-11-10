"""Replay launch isolation: retained failed game files cannot change inputs."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import amiga_replay as R


class IsolationMismatch(AssertionError):
    pass


def check():
    with tempfile.TemporaryDirectory(prefix='replay-isolation-', dir=R.ROOT / 'tmp') as tmp:
        out = Path(tmp)
        (out / 'expected.json').write_text(json.dumps(dict(services=7, interrupts=3, steps=2)))
        old = out / 'run/dh1'
        old.mkdir(parents=True)
        (old / 'A.CBA').write_bytes(b'old failed run')
        used = []
        calls = []
        result = [1]

        def launch(command, *, env, stdout, stderr, start_new_session):
            directory = (R.ROOT / 'amiga' / env['FSUAE_RUN']).resolve()
            if directory in used or (directory / 'dh1/A.CBA').exists():
                raise IsolationMismatch('replay reused previous game data')
            used.append(directory)
            (directory / 'dh1').mkdir(parents=True, exist_ok=True)
            (directory / 'dh1/A.CBA').write_bytes(b'new game write')
            assert start_new_session and stderr == subprocess.STDOUT
            assert env['WC2_ARGS'] == '' and env['FSUAE_CLAIM_STRICT'] == '1'
            fixture = Path(command[2]).read_text()
            for value in ('replay_services != 7', 'replay_interrupts != 3', 'replay_steps != 2',
                          'WC2_MILESTONE_WRONG_HANDOFF'):
                assert value in fixture
            stdout.write('WC2_REGS ax=0000\nWC2_MILESTONE_OK\n')

            class Process:
                def wait(self, timeout):
                    assert timeout == R.TIMEOUT
                    return result[0]
            return Process()

        def compare(name, timeout, capture, extra, trace):
            calls.append((name, timeout, capture, extra, trace))
            assert name == 'test-isolation' and timeout == R.TIMEOUT and extra is None
            assert trace == out / 'original-trace'
            return []

        with patch.object(R.subprocess, 'Popen', launch), patch.object(R.H, 'check', compare):
            try:
                R.run('test-isolation', out, out / 'original-trace', out / 'amiga')
            except SystemExit as error:
                assert 'no capture (exit 1)' in str(error), error
            else:
                raise AssertionError('failed emulator accepted')
            assert not calls
            result[0] = 0
            R.run('test-isolation', out, out / 'original-trace', out / 'amiga')
            R.run('test-isolation', out, out / 'original-trace', out / 'amiga')
        assert len(used) == 3 and len(calls) == 2
        assert (old / 'A.CBA').read_bytes() == b'old failed run'
        assert all((p / 'dh1/A.CBA').read_bytes() == b'new game write' for p in used)
    print('replay isolation: failed run plus two reruns; prior data retained; all comparison hooks retained')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sabotage', action='store_true')
    args = parser.parse_args()
    check()
    if args.sabotage:
        def reused(out):
            return out / 'run'
        with patch.object(R, 'fresh_run_directory', reused):
            try:
                check()
            except IsolationMismatch:
                print('caught: reused game directory')
            else:
                raise AssertionError('reused-directory plant escaped')


if __name__ == '__main__':
    main()
