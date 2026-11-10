"""Replay joystick steps: WC2's reference replay records none (the merged
amiga_replay.c has no joystick case), so a joystick step (kind 5) is a loud
stop, not a silent no-op. The control: the same script without it completes."""
from pathlib import Path
import sys

import test_replay_events as C
p=Path(__file__).resolve().parent
source=(p/'amiga_replay.c').read_text()
base=C.DATA.replace('#define REPLAY_IRQS 3u','#define REPLAY_IRQS 0u').replace('#define REPLAY_SERVICES 1u','#define REPLAY_SERVICES 0u')
control=base
joystick=base.replace('#define REPLAY_STEPS 1u','#define REPLAY_STEPS 2u').replace('{{2,1,0,0,0}}','{{2,1,5,3,0},{2,1,0,0,0}}')
harness=C.HARNESS[:C.HARNESS.index('int main(void)')]+r'''
int main(void) {
    G_IF=1;
    if (replay_point(2)==-1 && replay_steps==1) return 0;
    for (;;) if (replay_point(2)==-1) return 0;
}
'''
C.check(source,False,control,harness,(0,),(0,))
C.check(source,False,joystick,harness,(0,),(2,))
if '--sabotage' in sys.argv:
    old='default: fail("replay step kind", step->kind, point);'
    assert old in source
    C.check(source.replace(old,'default: break;'),True,joystick,harness,(0,),(2,))
print('Joystick replay step: loud stop, control completes' + ('; silent plant caught' if '--sabotage' in sys.argv else ''))
