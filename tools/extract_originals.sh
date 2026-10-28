#!/usr/bin/env bash
# Extract the user's archives and check every stage against the committed hashes.
#   tools/extract_originals.sh [ORIGINALS] [OUT]
# ORIGINALS (default ref-originals) holds the two .7z archives, never written.
# OUT (default tmp) receives:
#   extract/<archive>/*.img   the disk images
#   disks/diskN/              the FAT contents of each WC2 disk
#   union/                    all WC2 disk files in one directory (the installer's A:)
#   wc1/diskNN/               the FAT contents of each WC1 disk (cross-reference)
# Stops on any hash mismatch or duplicate file name.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
orig="$(cd "${1:-$root/ref-originals}" && pwd)"
out="${2:-$root/tmp}"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
ref="$root/reference"

(cd "$orig" && shasum -a 256 -c --quiet "$ref/archives.sha256")

rm -rf "$out/extract" "$out/disks" "$out/union" "$out/wc1"
mkdir -p "$out/extract" "$out/union"
for a in "$orig"/*.7z; do
	7zz x -bd -y -o"$out/extract" "$a" > /dev/null
done
(cd "$out/extract" && shasum -a 256 -c --quiet "$ref/disk-images.sha256")

for i in 1 2 3 4 5 6 7; do
	d="$out/disks/disk$i"
	7zz x -bd -y -o"$d" "$out/extract/001639_wing_commander_2/disk$i.img" > /dev/null
	for f in "$d"/*; do
		n="$(basename "$f")"
		if [ -e "$out/union/$n" ]; then
			echo "duplicate file name across disks: $n" >&2
			exit 1
		fi
		cp -p "$f" "$out/union/$n"
	done
done
(cd "$out/union" && shasum -a 256 -c --quiet "$ref/disk-files.sha256")
have="$(ls "$out/union" | wc -l | tr -d ' ')"
want="$(wc -l < "$ref/disk-files.sha256" | tr -d ' ')"
if [ "$have" != "$want" ]; then
	echo "union has $have files, reference/disk-files.sha256 lists $want" >&2
	exit 1
fi

for i in 01 02 03; do
	7zz x -bd -y -o"$out/wc1/disk$i" "$out/extract/001690_wing_commander/disk$i.img" > /dev/null
done
echo "EXTRACT_OK $want WC2 files in $out/union"
