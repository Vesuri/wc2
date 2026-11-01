# Wing Commander II — Amiga port investigation

An investigation into porting the 1991 DOS space combat game **Wing Commander II:
Vengeance of the Kilrathi** by Origin Systems to the Amiga. Nothing playable exists yet.

The target is an AGA Amiga with a 68030 or better (68040 recommended), with the original
x86 code translated offline to 68020 assembly by the translator of the Secret Weapons of the
Luftwaffe Amiga port, copied here with its runtime and Amiga layer
([docs/upstream.md](docs/upstream.md)). The
original game running under DOSBox-X is the ground truth for every test.

## Originals

No original game files are in this repository. The work uses the 7-disk DOS release
(`001639_wing_commander_2.7z`, seven 1.44 MB images) and, as a cross-reference, the
3-disk DOS Wing Commander (`001690_wing_commander.7z`). Put both in `ref-originals/`;
checksums are in [reference/archives.sha256](reference/archives.sha256) and
[docs/source-inventory.md](docs/source-inventory.md).

```sh
make extract    # unpack and hash-check the disks into tmp/
make install    # run the original installer headless; the installed game lands in ref/
make reference-staging   # play a disposable copy under DOSBox Staging
```

The environment (DOSBox-X, DOSBox Staging, 7zz, the Amiga toolchain) comes from
AmigaXDev's `make setup`. Plans and open work: [docs/design.md](docs/design.md),
[docs/open-work.md](docs/open-work.md).

## Credits

Wing Commander II and its assets belong to their copyright holders. This is an unofficial
fan project, not affiliated with or endorsed by them. By Vesa Halttunen (Vesuri).
