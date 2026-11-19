#!/usr/bin/env bash
# The flight smoke (port-plan P6b.1, P6b.3): m4's route by the game's file opens,
# then flight with the keyboard, WC2's joystick calibration (Ctrl+J) and the
# proportional stick (ANALOGJOYSTICK). Pass: WC2_PLAY_OK from play_walk.gdb.
# - Esc held 10 fields skips the opening, each intro scene and the briefing,
#   repeated until the next screen's file opens (uNAME): scene loads vary. The
#   opening stops at the title's BUTTONS.V00, since Esc on the title menu quits.
# - Each click repeats until the game opens CAMPAIGN.S00, its answer to both
#   (the reference), so no Esc reaches a menu whose click did not take.
# - Shift+C for Create, where m4 taps C; the names 150 ticks later, once the
#   prompt takes keys. The personnel menu drops scripted input in about half the
#   runs (Create missed, then an Enter there quits): open-work 23.
# At the emulator's maximum speed, the default here; EXTRA_ARGS replaces it.
# AMIGA_CPU=68030 or 68040. Started from its icon (debug.sh WC2_WORKBENCH): the
# tool types carry the script, with no Shell line limit and no ReadArgs quoting.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/play-walk.XXXXXX")
export FSUAE_RUN="../tmp/${run##*/}" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" AMIGA_SETUP="${AMIGA_SETUP:-a1200-030}" JOY0=none JOY1=none
fast='--uae_cpu_speed=max --uae_cpu_cycle_exact=false --uae_cpu_memory_cycle_exact=false --uae_blitter_cycle_exact=false'
export EXTRA_ARGS="${EXTRA_ARGS-$fast}"
# The pots centred first: an off-centre stick moves the menu pointer. The title
# sets the pointer to (318,159) (MEASURED); my-20 is on "Start New Game".
keys='d1:ax=128,d1:ay=128,uBUTTONS.V00:esc*10,fTEMPGLOB.000:shot,d300:my-20,uCAMPAIGN.S00:lmb,uOPTIONS.V00:esc*10'
keys+=',t1000:shift+c,t150:a,t50:enter,t100:b,t50:enter,t100:d,t50:enter'
keys+=',fMUSIC.A00:shot,uCAMPAIGN.S00:lmb,uMESSAGE.V00:esc*10'
keys+=',d300:left*99,d9:right*99,d50:ctrl+j*40,d99:shot'
keys+=',d1:ax=128,d1:ay=128,d50:jf,d99:ax=0,d1:ay=0,d50:jf,d99:ax=255,d1:ay=255,d50:jf,d99:shot'
keys+=',d1:ay=128,d50:jf,d1:ax=0,d1500:shot,d1:quit'
export WC2_WORKBENCH=1 WC2_TOOLTYPES="ANALOGJOYSTICK MUSIC KEYS=$keys"
printf 'Diagnostic logs: %s\n' "$run"
exec bash amiga/debug.sh "" "$PWD/amiga/play_walk.gdb"
