#!/usr/bin/env bash
# The game's own exit: Alt+X on the title (milestone mx1's route, its 2400 timer ticks);
# no forced guest exit.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p tmp
run=$(mktemp -d "$PWD/tmp/restore-check.XXXXXX")
export FSUAE_RUN="../tmp/${run##*/}" FSUAE_CLAIM_STRICT=1
export AMIGA_CPU="${AMIGA_CPU:-68030}" JOY0=none JOY1=none
export WC2_ARGS='KEYS=t2400:alt+x,d1500:shot'
printf 'Diagnostic logs: %s\n' "$run"
bash amiga/debug.sh "" "$PWD/amiga/restore_check.gdb" > "$run/check.log" 2>&1
cat "$run/check.log"
# A disconnected debugger or an exhausted command file is not a pass.
grep -q '^WC2_RESTORE_OK$' "$run/check.log"
