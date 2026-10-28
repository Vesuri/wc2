#!/usr/bin/env bash
# Run the original INSTALL.EXE headless under DOSBox-X from a disposable copy of the disk
# files and leave the installed tree in OUT/c/WING2.
#   tools/pc_install.sh [UNION] [OUT] [SECONDS]
# UNION (default tmp/union, from tools/extract_originals.sh): all disk files, mounted as A:.
# OUT (default tmp/pc-install) is recreated. SECONDS is the wall-clock limit (default 1800).
# Answers: C:\WING2, unpacked ("Save Time"), VGA, Sound Blaster, speech Yes (IRQ 7), confirm.
# Success needs a positive signal: the batch line after INSTALL.EXE writes C:\INSTDONE.TXT,
# and DOSBox-X must exit before the limit. OUT/last.png is the last captured frame.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
union="$(cd "${1:-$root/tmp/union}" && pwd)"
out="${2:-$root/tmp/pc-install}"
secs="${3:-1800}"
keys="enter enter enter enter s enter enter y enter"

rm -rf "$out"
mkdir -p "$out/a" "$out/c" "$out/cap"
out="$(cd "$out" && pwd)"
cp -p "$union"/* "$out/a/"
cp "$root/reference/dosbox-x-install.conf" "$out/dx.conf"

# DOSBox paths are relative: the project path has spaces.
cd "$out"
start=$(date +%s)
env SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy dosbox-x -conf dx.conf -nogui -nomenu \
	-fastlaunch -time-limit "$secs" -c "mount a a" -c "mount c c" -c "a:" \
	-c "autotype -w 2 -p 0.5 $keys" -c "dx-capture /v install.exe" \
	-c "echo done> c:\\instdone.txt" -c "exit" > dosbox-x.out 2>&1 &
pid=$!
echo $pid > dosbox-x.pid
wait $pid || true
rm -f dosbox-x.pid
took=$(( $(date +%s) - start ))
ffmpeg -loglevel error -sseof -0.5 -i cap/*.avi -frames:v 1 -update 1 -y last.png || true

done_file="$(find c -maxdepth 1 -iname instdone.txt | head -1)"
if [ -z "$done_file" ]; then
	echo "INSTALL_FAIL no completion marker after ${took}s (limit $secs s); see $out/last.png" >&2
	exit 1
fi
if [ "$took" -ge "$secs" ]; then
	echo "INSTALL_FAIL reached the time limit (${took}s)" >&2
	exit 1
fi
echo "INSTALL_OK in ${took}s: $out/c/WING2"
