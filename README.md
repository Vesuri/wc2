# Wing Commander II — Amiga

An unofficial Amiga port of the 1991 PC space combat game **Wing Commander II:
Vengeance of the Kilrathi** by Origin Systems: fly the Confederation's fighters against
the Kilrathi, with the story told between missions aboard the carrier.

The port runs the original game code, translated offline from 16-bit x86 to 68020 by
this repository's static translator (from the Secret Weapons of the Luftwaffe Amiga
port); there is no x86 emulator. The game runs as the original's VGA version (320×200,
256 colours) on AGA, and its AdLib music and effects are resynthesised on Paula.

Current Amiga release: **0.1 (19.11.2026), an early alpha**.

## What to expect from 0.1

0.1 runs the game with its AdLib music and effects, but it is **not optimized** and has
**no digitised speech** yet. It is for people who
want to try the port early and report what they find.

- **Checked against the original:** the translated game code was run in a test build and
  compared step by step with the PC original under DOSBox-X. At every step of these
  routes the screen, the memory and every call the game made matched:
  - the start and the title;
  - a new game and its intro;
  - the pilot's file and the first flight;
  - a mission flown to its end (with the game's debug keys and autopilot) and landed;
  - saving and loading a game in the quarters;
  - both ways out to DOS: Alt+X on the title menu, and the window in the quarters.

  The Amiga build itself was compared the same way on an emulated A1200 with a 68030 at
  the title, the intro and the first flight frame.
- **Sound:** the AdLib music and sound effects play on Paula, resynthesised from the FM
  chip the game drives. Their sound has not been measured against the PC yet, and some
  instruments may not sound as on the PC. The Sound Blaster's digitised speech is silent;
  it is the next step of the port.
- **Speed:** not optimized. In the one scene measured on an emulated 50 MHz 68030, the
  opening animation, the Amiga draws one frame for every eight the PC does. Flight is
  estimated, not measured, at about half the PC's frame rate on that 68030 and close to
  it on a 40 MHz 68040. Expect it to be slow. Speed work comes after the speech.
- **Unsupported paths stop the game:** where the game does something the port does not
  support yet, it stops rather than guessing. The tests cover the routes above, not
  every mission, cinematic or menu choice, nor the ending.
  - Under WHDLoad the requester says "Wing Commander II stopped".
  - From a Shell, a line starting with `WC2_STOP` appears.
  - Please [report it](https://github.com/Vesuri/wc2/issues) with that line and what you
    were doing.
- **Saving:** saving and loading matched the original in the test build, but have not
  been tested under WHDLoad yet. Keep copies of saved games you care about.
- **Testing:** only on emulated A1200s (68030, 68040 and 68060, with and without
  WHDLoad's `MMU` option, PAL and NTSC); not yet on real hardware. The start from a
  Shell without WHDLoad was not tested for this release.

## Requirements and installation

- An AGA Amiga (A1200 or A4000) with a **68030 or better**; a 68040 or 68060 is
  recommended.
- **8 MB Fast RAM**. On a 68030 the data cache needs WHDLoad's `MMU` option (the `MMU`
  tooltype).
- WHDLoad 17+, Installer 43+, and an installed Kickstart 3.1 image
  (`kick40068.A1200` or `kick40068.A4000` with its `.RTB`) in `Devs:Kickstarts`.
- The seven 1.44 MB PC floppies of **Wing Commander II** (Origin, 1991), as `Disk1.img`
  to `Disk7.img`, as the files of all seven disks in one drawer, or the floppies
  themselves in `PC0:` (CrossDOS, a high-density drive). Other releases are not
  supported.

Extract `WC2-0.1.lha` from the [releases](https://github.com/Vesuri/wc2/releases), open
its **WC2 Install** drawer and run **Install**. Every file is checked, and damaged or
other disks are refused. The installed game takes 17 MB. Updating keeps saved games.
Start the installed **Wc2** icon.

No original game code or data, Kickstart image or WHDLoad binary is distributed. See
[the release ReadMe](release/ReadMe) for the full instructions.

## Controls

Keyboard and mouse work as in the PC original, with keys at their US keyboard
positions; see the original manual. Esc skips the cinematics. A joystick in port 2 works
as the cursor keys and its buttons as the mouse buttons; set the `Custom1` tooltype to 1
for an analog joystick, calibrated with Ctrl+J in flight. Quit with Alt+X on the title
menu, or click the window in your quarters (Exit to DOS). The WHDLoad QuitKey (**Help**)
quits immediately, without saving.

## Building

The game uses `m68k-amiga-elf-gcc`, `elf2hunk` and vasm; the WHDLoad slave also needs the
WHDLoad SDK includes. The environment (also DOSBox-X, DOSBox Staging and 7zz for the
reference) comes from AmigaXDev's `make setup` (`~/.local/share/amiga/env.sh`).

```sh
make release    # dist/WC2-$(cat VERSION).lha and its check; clean tree only
make amiga      # the standalone executable amiga/out/Wc2.exe
make help       # every target: reference, translator gates, host and Amiga runs
```

The tests compare the port with the original running under a scripted DOSBox-X. They
need the 7-disk DOS release (`001639_wing_commander_2.7z`) and, as a cross-reference,
the 3-disk DOS Wing Commander (`001690_wing_commander.7z`), which you supply yourself in
`ref-originals/`. Git ignores them;
[reference/archives.sha256](reference/archives.sha256) pins their SHA-256.

```sh
make extract             # unpack and hash-check the disks into tmp/
make install             # run the original installer headless; the game lands in ref/
make reference-staging   # play a disposable copy under DOSBox Staging
```

How the port works, its gates and what comes next are in the
[port plan](docs/port-plan.md) and [design](docs/design.md). Remaining work is in
[open-work.md](docs/open-work.md), and [AGENTS.md](AGENTS.md) indexes the other docs.

## Credits and licensing

Wing Commander II and its original assets belong to their copyright holders. This is an
unofficial fan port, not affiliated with or endorsed by them. Amiga port by Vesa
Halttunen (Vesuri). WHDLoad by Wepl.

The install helper uses the AmigaXDev installer helpers (LGPL-2.1-or-later; see
[COPYING.LIB](tools/install-data/COPYING.LIB)). That licence applies to the helper only,
not to the original game.
