#!/usr/bin/env bash
# Source this for the shared Amiga environment that AmigaXDev installs (~/.local/share/amiga):
# the cross-toolchain and FS-UAE on PATH, the Kickstart, SetPatch and the FS-UAE helpers.
# Every variable can be overridden from the environment.
#   . amiga/env.sh
# or, from amiga/:
#   . env.sh
. "${AMIGA_ENV:-$HOME/.local/share/amiga/env.sh}"
# Emulator: the shared native arm64 FS-UAE. Measurements compare one binary only.
export FSUAE="${FSUAE:-$FSUAE_ARM}"
# The machine (docs/headless-fsuae.md, Machine settings): AMIGA_CPU=68030, 68040 or 68060 is
# the shared preset a1200-030, a1200-040 or a1200-060 (fsuae_common.sh fsuae_setup), which
# also emulates the data cache; an explicit AMIGA_SETUP wins. Unset: the launchers' 68020.
wc2_machine() {
  case "${AMIGA_CPU:-}" in
    '') ;;
    68030|68040|68060) AMIGA_SETUP="${AMIGA_SETUP:-a1200-0${AMIGA_CPU#680}}" ;;
    *) echo "AMIGA_CPU must be 68030, 68040 or 68060, or unset for the 68020" >&2; return 1 ;;
  esac
  [ -n "${AMIGA_SETUP:-}" ] || return 0
  export AMIGA_SETUP
  # A preset sets its own Fast RAM; an explicit FAST_KB/FAST_MEMORY (the D1 measurement,
  # docs/feasibility.md) still wins through EXTRA_ARGS, whose options come first.
  local fast="${FAST_KB:-${FAST_MEMORY:-}}"
  [ -z "$fast" ] || export EXTRA_ARGS="--fast_memory=$fast ${EXTRA_ARGS:-}"
}
