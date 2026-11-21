## Wing Commander II — repository-level targets.

.PHONY: all help test-host test-amiga extract install inspect hash check-ref prepare-reference reference-staging compare \
	reference-emulator reference map gen gen-check lint test test-decode test-x86 test-m68k test-blocks test-sabotage \
	test-guards host amiga smoke size install-data test-install-data amiga-release amiga-diag whdload test-whdload release release-check \
	github-release test-release-installer gates-audio sound-fm sfx-price test-sfx-capture t-amiga-sfx clean

REFERENCE_ROOT ?= tmp/pc-root
INSTALL_OUT ?= tmp/pc-install
INSTALL_SECS ?= 1800
INSTALL_HASHES := reference/install.sha256
PYTHON ?= python3
# AmigaXDev's shared Python package.
AMIGA_PYLIB ?= $(HOME)/.local/share/amiga/pylib

all: help

help:
	@echo "Wing Commander II — DOS x86 -> Amiga port investigation"
	@echo
	@echo "  make extract            ref-originals/*.7z -> tmp/union (hash-checked)"
	@echo "  make install            run the original installer headless -> ref/ (hash-checked)"
	@echo "  make install-data       the installer helper, host and 68020 (tools/install-data)"
	@echo "  make test-install-data  its host test and its FS-UAE run against the installed tree"
	@echo "  make inspect            WC2.EXE's MZ header; every disk file unpacked (LZW, speech,"
	@echo "                          .LZC) equals the installer's copy (the P8.2 codecs)"
	@echo "  make hash               re-record $(INSTALL_HASHES) from ref/ (deliberate change only)"
	@echo "  make check-ref          verify ref/ against $(INSTALL_HASHES)"
	@echo "  make prepare-reference  copy ref/ to disposable $(REFERENCE_ROOT)"
	@echo "  make reference-staging  play the disposable copy in DOSBox Staging"
	@echo "  make compare            PC WC1 vs WC2 code and data comparison -> tmp/compare/"
	@echo "  make reference-emulator build instrumented DOSBox-X (tools/patches/ORDER)"
	@echo "  make reference          gate 1: every milestone twice, image proof, identical state"
	@echo "  make map                gate 2 over the traces: VROOMM model and sabotage, sweep,"
	@echo "                          code writes, annotations/indirect.csv, docs/external-surface.md"
	@echo
	@echo "  Translator and Amiga build (Secret Weapons of Luftwaffe's; docs/upstream.md):"
	@echo "  make gen                translate the in-scope modules -> build/gen (none before P1.4)"
	@echo "  make gen-check          G1: headers, digests and byte-identical regeneration of build/gen"
	@echo "  make lint               G2: no guest-address names in hand-written code"
	@echo "  make test               lint, decoder, x86 (forms, blocks, space, boundary) and 68020 (forms, blocks, space, boundary) differentials, the program block test, guards, gen-check"
	@echo "  make test-sabotage      planted faults must fail the x86 and 68020 differentials"
	@echo "  make host               link generated program + runtime for Unicorn 68020 -> build/host/wc2.elf"
	@echo "  make test-host          gate 5 host: lockstep from the MZ entry to m1, m1b, m2, m3, m4, m5 and m6 (tests/host_run.py)"
	@echo "  make test-amiga         gate 5: m1b replayed on the 68030 model (FS-UAE + GDB capture, AMIGA_CPU)"
	@echo "  make gates-audio        the FM re-hoster against Nuked OPL on the host references' OPL logs,"
	@echo "                          the FM unit checks, the effect render and player, and every plant (docs/sound-plan.md)"
	@echo "  make sound-fm           the re-hoster's Paula WAVs of those logs -> tmp/sound/"
	@echo "  make sfx-price          every FM effect captured from the original, played by the re-hoster"
	@echo "  make test-sfx-capture   the runtime's effect capture against the original's in host lockstep, and its plants"
	@echo "  make t-amiga-sfx        the effects on the 68030 model: capture, prerender and player in the replay, and its plants"
	@echo "  make amiga              build amiga/out/Wc2.exe"
	@echo "  make smoke              boot it under FS-UAE + GDB: takeover live, then hand-back"
	@echo "  make size               account for code, data, symbols and relocations in the executable"
	@echo "  Package (docs/whdload.md, docs/release.md):"
	@echo "  make amiga-release      the stripped release image amiga/out/Wc2-release.exe"
	@echo "  make whdload            the slave and its test variants"
	@echo "  make test-whdload       the slave's smoke, boot, load and run checks in FS-UAE"
	@echo "  make test-release-installer  Installer 43 and the helper in FS-UAE, every mode"
	@echo "  make release            from a clean tree: the archives in dist/ and their check"
	@echo "  make github-release     publish the tagged HEAD (the owner's step)"
	@echo "  make clean              remove Amiga build output"

extract:
	tools/extract_originals.sh ref-originals tmp

# ref/ mirrors the installed C: drive (ref/WING2/...), read-only.
install:
	tools/pc_install.sh tmp/union $(INSTALL_OUT) $(INSTALL_SECS)
	rm -f $(INSTALL_OUT)/c/instdone.txt $(INSTALL_OUT)/c/INSTDONE.TXT
	cd $(INSTALL_OUT)/c && shasum -a 256 -c --quiet "$(abspath $(INSTALL_HASHES))"
	test "$$(cd $(INSTALL_OUT)/c && find . -type f | wc -l)" -eq "$$(wc -l < $(INSTALL_HASHES))"
	if [ -d ref ]; then chmod -R u+w ref; fi
	rm -rf ref
	cp -Rp $(INSTALL_OUT)/c ref
	chmod -R a-w ref
	@echo "INSTALL_REF_OK ref/"

# Playbook §2's gate; needs make extract and make install.
inspect:
	PYTHONPATH='$(AMIGA_PYLIB)' $(PYTHON) -m amigaxdev.dos.mz_info ref/WING2/WC2.EXE
	$(PYTHON) tools/origin_pak.py verify tmp/union ref/WING2

hash:
	cd ref && find . -type f ! -name .DS_Store -print0 | LC_ALL=C sort -z | \
		xargs -0 shasum -a 256 > "$(abspath $(INSTALL_HASHES))"

check-ref:
	cd ref && shasum -a 256 -c --quiet "$(abspath $(INSTALL_HASHES))"
	test "$$(cd ref && find . -type f ! -name .DS_Store | wc -l)" -eq "$$(wc -l < $(INSTALL_HASHES))"

prepare-reference: check-ref
	@mkdir -p $(REFERENCE_ROOT)
	if [ -d $(REFERENCE_ROOT) ]; then chmod -R u+w $(REFERENCE_ROOT); fi
	rsync -a --delete ref/ $(REFERENCE_ROOT)/
	chmod -R u+w $(REFERENCE_ROOT)

reference-staging: prepare-reference
	dosbox-staging --noprimaryconf --nolocalconf -conf reference/dosbox-staging.conf
	$(MAKE) check-ref

# docs/wc1-wc2-comparison.md; needs make extract and make install.
compare:
	@mkdir -p tmp/compare
	. amiga/env.sh && python3 tools/bc_exe.py tmp/wc1/disk01/WC.EXE ref/WING2/WC2.EXE
	. amiga/env.sh && python3 tools/origin_pak.py verify tmp/union ref/WING2 || true
	. amiga/env.sh && python3 tools/wc_compare.py tmp/wc1/disk01/WC.EXE ref/WING2/WC2.EXE \
		--control ref/WING2/INSTALL.EXE --csv tmp/compare/funcs.csv | tee tmp/compare/report.txt

reference-emulator:
	tools/build_dosbox_x.sh

# Gate 1 (docs/pc-reference-loop.md): reference/milestones.csv, two runs each.
reference: check-ref
	. amiga/env.sh && $(PYTHON) tools/reference.py

# Gate 2 (docs/port-plan.md P2): the static and live map over the milestone traces.
MAP_SABOTAGE := second-chance wrap sweep position
map:
	cd tools && $(PYTHON) vroomm_check.py
	cd tools && for s in $(MAP_SABOTAGE); do \
		out=$$($(PYTHON) vroomm_check.py --sabotage $$s); rc=$$?; echo "$$out" | tail -1; \
		[ $$rc -eq 0 ] || exit 1; done
	cd tools && $(PYTHON) sweep.py --annotations
	cd tools && $(PYTHON) code_writes.py
	cd tools && $(PYTHON) surface.py --write ../docs/external-surface.md

# --- Translator, tests and builds (Secret Weapons of Luftwaffe 658fc60, docs/upstream.md) ---

gen:
	$(PYTHON) -m translator.gen

gen-check:
	$(PYTHON) -m translator.check gen --regen

lint:
	$(PYTHON) -m translator.check lint

test-decode:
	$(PYTHON) tests/test_decode.py

# The "forms" and "blocks" corpora come from the game's code (image.X86_SCOPE, gate 3;
# the 68020 side: the generated scope, gate 4); test-blocks runs the generated program.
X86_CORPORA ?= forms,space,boundary,blocks
CORPORA ?= forms,space,boundary,blocks
test-x86:
	$(PYTHON) tests/x86_diff.py --only $(X86_CORPORA)

test-m68k:
	$(PYTHON) tests/m68k_diff.py --only $(CORPORA)

test-blocks:
	@$(MAKE) -s -k -j$(BLOCK_JOBS) $(BLOCK_TESTS)

test-guards: gen
	$(PYTHON) tests/test_guards.py

# Checks run in parallel after the one writer of build/gen (gen-check); each logs
# to tmp/test/<name>.log and prints one status line.
# The host is shared (AGENTS.md): a quarter of the cores, at least 2, at nice 10. The
# Python pools take WC2_JOBS too (tests/*_sabotage.py, tools/reference.py).
JOBS ?= $(shell n=$$(sysctl -n hw.ncpu 2>/dev/null || nproc); echo $$(( n / 4 > 2 ? n / 4 : 2 )))
NICE ?= 10
export WC2_JOBS = $(JOBS)
RUN = @mkdir -p tmp/test; if nice -n $(NICE) $(2) > tmp/test/$(1).log 2>&1; then echo "ok    $(1)"; \
	else echo "FAIL  $(1) (tmp/test/$(1).log)"; tail -n 15 tmp/test/$(1).log; exit 1; fi
X86_SHARDS = forms.0/8 forms.1/8 forms.2/8 forms.3/8 forms.4/8 forms.5/8 forms.6/8 forms.7/8 \
	blocks.0/2 blocks.1/2 space.0/1 boundary.0/1
SHARDS = forms.0/8 forms.1/8 forms.2/8 forms.3/8 forms.4/8 forms.5/8 forms.6/8 forms.7/8 \
	blocks.0/2 blocks.1/2 space.0/1 boundary.0/1
# Unit tests (docs/upstream.md lists the deferred ones); test_load_image needs ref/.
UNIT_TESTS = test_align test_align_convergence test_amiga_input test_block_boundary \
	test_byteorder_entries test_carry_entries test_compact test_cost_meter \
	test_display_queue test_dosbox_retf test_fixture_inputs test_fm_allocation \
	test_fm_cache test_fm_envelope test_fm_phase test_fm_quality test_fm_render \
	test_gate_runner test_helper_branches test_hunk_size test_joystick_cli \
	test_joystick_events test_joystick_link test_load_image test_joystick_recorder test_joystick_replay \
	test_jump_fusion test_key_release test_m68k_assembly test_next_branch \
	test_oracle_boundary test_oracle_exception_writes test_reglive test_rep_lowering \
	test_rep_replay test_replay_chords test_replay_events test_smc_flow \
	test_dos_sda test_dos_search test_ems test_far_return_protocol test_file_dates \
	test_host_launch test_irq_footprint test_irq_in_service test_mouse_irq test_interrupt_frame_mask \
	test_key_chords test_keyboard_prefix test_host_replay_visits test_replay_hooks \
	test_replay_run_isolation test_undefined_flags
# The program block test in parts (tests/m68k_blocks.py --shard); BLOCK_JOBS bounds
# the parts run at once when test-blocks runs alone.
BLOCK_SHARDS ?= 8
BLOCK_JOBS ?= $(JOBS)
BLOCK_TESTS = $(foreach k,$(shell seq 0 $$(($(BLOCK_SHARDS)-1))),t-blocks.$(k)-of-$(BLOCK_SHARDS))
TESTS = t-lint t-decode t-guards $(BLOCK_TESTS) $(subst /,-of-,$(X86_SHARDS:%=t-x86-%)) $(subst /,-of-,$(SHARDS:%=t-m68k-%)) \
	$(UNIT_TESTS:%=t-unit-%)

test: gen-check
	@$(MAKE) -s -k -j$(JOBS) $(TESTS)

test-sabotage: gen-check
	@$(MAKE) -s -k -j$(JOBS) t-sab-x86 t-sab-m68k t-sab-irq

t-lint:
	$(call RUN,lint,$(PYTHON) -m translator.check lint)
t-decode:
	$(call RUN,decode,$(PYTHON) tests/test_decode.py)
t-blocks.%:
	$(call RUN,blocks.$*,$(PYTHON) tests/m68k_blocks.py --shard $(subst -of-,/,$*))
t-guards:
	$(call RUN,guards,$(PYTHON) tests/test_guards.py)
# t-x86-<corpus>.<k>-of-<n>: one shard of a differential corpus
CORPUS = $(word 1,$(subst ., ,$*))
SHARD = $(subst -of-,/,$(word 2,$(subst ., ,$*)))
t-x86-%:
	$(call RUN,x86-$*,$(PYTHON) tests/x86_diff.py --only $(CORPUS) --shard $(SHARD))
t-m68k-%:
	$(call RUN,m68k-$*,$(PYTHON) tests/m68k_diff.py --only $(CORPUS) --shard $(SHARD))
# its x86 side is reused by the sabotage plants (tests/m68k_sabotage.py)
t-m68k-boundary.0-of-1:
	$(call RUN,m68k-boundary.0-of-1,$(PYTHON) tests/m68k_diff.py --only boundary --shard 0/1 \
		--record tmp/test/x86-side-boundary.pkl)
t-unit-%:
	$(call RUN,$*,$(PYTHON) tests/$*.py)
t-sab-x86:
	$(call RUN,sabotage-x86,$(PYTHON) tests/x86_sabotage.py)
t-sab-m68k:
	$(call RUN,sabotage-m68k,$(PYTHON) tests/m68k_sabotage.py)
t-sab-irq:
	$(call RUN,sabotage-irq,$(PYTHON) tests/test_irq_footprint.py --sabotage)

# Host image: the generated program and the runtime for tests/host_run.py (P5).
AMIGA_TOOLCHAIN ?= $(HOME)/.local/opt
VASM     ?= $(HOME)/.local/vasmm68k_mot
CROSS    = $(AMIGA_TOOLCHAIN)/bin/m68k-amiga-elf-
VASMELF  = $(VASM) -quiet -m68020 -Felf -x -nowarn=62
RT_CFLAGS = -m68020 -O2 -ffreestanding -nostdlib -fomit-frame-pointer \
	-fno-tree-loop-distribute-patterns -Wall -Wextra -Werror -Isrc/runtime -DWC2_SYNC
RUNTIME_C = $(wildcard src/runtime/*.c)
HOST_OBJ = build/host/host_s.o build/host/host.o build/host/rt_entry.o \
	$(patsubst src/runtime/%.c,build/host/%.o,$(RUNTIME_C)) build/host/program.o

build/host/program.o: build/gen/program.s $(wildcard build/gen/*.s)
	@mkdir -p $(dir $@)
	cd build/gen && $(VASMELF) -DWC2_SYNC=1 -o ../host/program.o program.s

build/host/rt_entry.o: src/runtime/rt_entry.s
	@mkdir -p $(dir $@)
	$(VASMELF) -Isrc/runtime -o $@ $<

build/host/host_s.o: src/platform/host/host.s
	@mkdir -p $(dir $@)
	$(VASMELF) -o $@ $<

build/host/host.o: src/platform/host/host.c src/runtime/runtime.h src/runtime/platform.h
	@mkdir -p $(dir $@)
	$(CROSS)gcc $(RT_CFLAGS) -c -o $@ $<

build/host/%.o: src/runtime/%.c src/runtime/runtime.h src/runtime/platform.h
	@mkdir -p $(dir $@)
	$(CROSS)gcc $(RT_CFLAGS) -c -o $@ $<

build/host/wc2.elf: $(HOST_OBJ)
	$(CROSS)ld -Ttext=0x10000 -e _start -o $@ $(HOST_OBJ)

host: gen-check build/host/wc2.elf

# Gate 5 (docs/port-plan.md P5): lockstep against the host references
# (tools/reference.py --host), one run per milestone, in parallel.
HOST_MILESTONES = m1 m1b m2 m3 m4 m5 m6
t-host-%:
	$(call RUN,host-$*,$(PYTHON) tests/host_run.py --milestone $* --timeout 20000)
# The effect capture (src/runtime/sfx.c, HLE sfx_start) against tools/sfx_capture.py in
# host lockstep to the first milestone whose route starts an effect, and its plants.
SFX_MILESTONE ?= mx1
SFX_PLANTS = restore tick value end starts
t-sfx-capture: host
	$(call RUN,sfx-capture,$(PYTHON) tests/host_run.py --milestone $(SFX_MILESTONE) --timeout 20000 --sfx-capture)
t-sab-sfx-capture-%: host
	$(call RUN,sabotage-sfx-capture-$*,$(PYTHON) tests/host_run.py --milestone $(SFX_MILESTONE) --timeout 20000 --sfx-capture $*)
test-sfx-capture:
	@$(MAKE) -s -k -j$(JOBS) t-sfx-capture $(SFX_PLANTS:%=t-sab-sfx-capture-%)
test-host: host
	@$(MAKE) -s -k -j$(JOBS) $(HOST_MILESTONES:%=t-host-%)

# AdLib FM on Paula (P6b.2), from X-Wing's Makefile (ba28410): the re-hoster
# (src/platform/amiga/fm_paula.c) on the host references' OPL logs, checked against
# Nuked OPL from the DOSBox-X tree (tools/build_dosbox_x.sh links tools/vendor/dosbox-x).
# m6's log holds m1b-m5's (one route); mx1 and mx2 are the exit routes.
NUKED = tools/vendor/dosbox-x/src/hardware
FM_MILESTONES = m6 mx1 mx2
FM_OPL = tmp/pc-runs/host-$(1)/trace/opl.csv
build/tools/fm_check: tools/fm_check.cpp src/platform/amiga/fm_paula.c src/platform/amiga/fm_paula.h
	mkdir -p build/tools
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/fm_paula.o src/platform/amiga/fm_paula.c
	c++ -O2 -std=c++17 -Isrc/platform/amiga -I$(NUKED) -o $@ $< build/tools/fm_paula.o $(NUKED)/nukedopl.cpp
sound-fm: build/tools/fm_check
	mkdir -p tmp/sound
	-for m in $(FM_MILESTONES); do build/tools/fm_check $(call FM_OPL,$$m) tmp/sound/$$m-paula.wav; done
t-fm-paula-%: build/tools/fm_check
	@mkdir -p tmp/sound
	$(call RUN,fm-paula-$*,build/tools/fm_check $(call FM_OPL,$*) tmp/sound/$*-paula.wav)
t-sab-fm-paula: build/tools/fm_check
	$(call RUN,sabotage-fm-paula,sh -c 'for s in pitch level; do \
		! build/tools/fm_check $(call FM_OPL,m2) tmp/test/fm-sabotage.wav --sabotage $$s || exit 1; done')
FM_UNITS = quality render phase envelope allocation cache
t-sab-fm-%:
	$(call RUN,sabotage-fm-$*,$(PYTHON) tests/test_fm_$*.py --sabotage)
# The FM effects priced on the live re-hoster (open-work 19): each effect's OPL
# writes from the original game code and STRAX.DRV under Unicorn (tools/sfx_capture.py,
# the m4 host reference's flight snapshot), each through fm_check; a report, no gate
# (fm_check's pitch needs steady notes, and the driver moves every effect's pitch a tick).
sfx-price: build/tools/fm_check
	mkdir -p tmp/sound/sfx-paula
	nice -n $(NICE) $(PYTHON) tools/sfx_capture.py > tmp/sound/sfx-capture.txt
	for f in tmp/sound/sfx/*.csv; do n=$$(basename $$f .csv); \
		nice -n $(NICE) build/tools/fm_check $$f tmp/sound/sfx-paula/$$n.wav | sed "s|^|$$n |"; \
	done | sort -n > tmp/sound/sfx-price.txt; cat tmp/sound/sfx-price.txt
# Prerendered effects (D13) against Nuked OPL on the original's captures
# (tools/sfx_capture.py from the m4 flight snapshot); WAVs in tmp/sound/sfx-wav.
build/tools/fm_effect_check: tools/fm_effect_check.cpp src/platform/amiga/fm_paula.c src/platform/amiga/fm_paula.h src/platform/amiga/fx_play.h
	@mkdir -p build/tools
	cc -O2 -std=c99 -Wall -Wextra -Werror -c -o build/tools/fm_effect_paula.o src/platform/amiga/fm_paula.c
	c++ -O2 -std=c++17 -Isrc/platform/amiga -I$(NUKED) -o $@ $< build/tools/fm_effect_paula.o $(NUKED)/nukedopl.cpp
tmp/sound/sfx-writes.csv: tools/sfx_capture.py
	nice -n $(NICE) $(PYTHON) tools/sfx_capture.py > tmp/sound/sfx-capture.txt
t-fm-effect: build/tools/fm_effect_check tmp/sound/sfx-writes.csv
	$(call RUN,fm-effect,sh -c 'mkdir -p tmp/sound/sfx-wav && build/tools/fm_effect_check tmp/sound/sfx-writes.csv tmp/sound/sfx-wav')
t-sab-fm-effect: build/tools/fm_effect_check tmp/sound/sfx-writes.csv
	$(call RUN,sabotage-fm-effect,sh -c 'mkdir -p tmp/test/sfx-wav && for s in pitch level end fade live; do \
		! build/tools/fm_effect_check tmp/sound/sfx-writes.csv tmp/test/sfx-wav --sabotage $$s || exit 1; done')
# The prerender's assembly loop (fm_effect_run.s) on the 68020 core against the C loop.
t-fm-effect-asm: tmp/sound/sfx-writes.csv
	$(call RUN,fm-effect-asm,sh -c '. amiga/env.sh && $(PYTHON) tests/test_fm_effect_asm.py')
t-sab-fm-effect-asm: tmp/sound/sfx-writes.csv
	$(call RUN,sabotage-fm-effect-asm,sh -c '. amiga/env.sh && $(PYTHON) tests/test_fm_effect_asm.py --sabotage')
# The effect player (fx_play.c) on synthetic effect slots.
t-fx-play:
	$(call RUN,fx-play,$(PYTHON) tests/test_fx_play.py)
t-sab-fx-play:
	$(call RUN,sabotage-fx-play,$(PYTHON) tests/test_fx_play.py --sabotage)
# Isolated audio changes (AGENTS.md "Validation scope"): the sound checks and their plants.
gates-audio:
	@$(MAKE) -s -k -j$(JOBS) $(FM_MILESTONES:%=t-fm-paula-%) t-sab-fm-paula \
		$(FM_UNITS:%=t-unit-test_fm_%) $(FM_UNITS:%=t-sab-fm-%) \
		t-fm-effect t-sab-fm-effect t-fm-effect-asm t-sab-fm-effect-asm t-fx-play t-sab-fx-play

# test-amiga (gate 5): the diagnostic replay image (tests/amiga_replay.py) replays
# the host reference's interrupts, REP slices, 3DAh and PIT reads and clocks on the
# 68030 model; its capture at the milestone gets the host run's checks.
AMIGA_MILESTONE ?= m1b
AMIGA_CPU       ?= 68030
test-amiga: host
	. amiga/env.sh && AMIGA_CPU=$(AMIGA_CPU) $(PYTHON) tests/amiga_replay.py --milestone $(AMIGA_MILESTONE)
# The effects on the 68030 model (X-Wing's t-amiga-sfx, 269828b): the replay to
# SFX_MILESTONE with the capture, prerender and player running, each play against the
# game's slots in the guest RAM, the host check with the capture; then the check's
# plants on the saved run (each must fail).
AMIGA_SFX_PLANTS = starts mute reserve
t-amiga-sfx: host
	. amiga/env.sh && AMIGA_CPU=$(AMIGA_CPU) nice -n 10 $(PYTHON) tests/amiga_replay.py --milestone $(SFX_MILESTONE) --sfx
	for p in $(AMIGA_SFX_PLANTS); do $(PYTHON) tests/amiga_replay.py --milestone $(SFX_MILESTONE) --sfx $$p || exit 1; done

amiga: gen-check
	. amiga/env.sh && $(MAKE) -C amiga

GATE_LAUNCH = $(if $(GATE_ISOLATED),$(PYTHON) "$(CURDIR)/tools/gate_launch.py",)
smoke: amiga
	. amiga/env.sh && $(GATE_LAUNCH) amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^WC2_SMOKE_OK'

size: amiga
	$(PYTHON) tools/hunk_size.py amiga/out/Wc2.exe

# Release image: built in build/amiga-release with RELEASE=1 (the player's options
# only, amiga_platform.c), stripped to amiga/out/Wc2-release.exe. Then the slaves
# (whdload/Makefile) and their FS-UAE checks (tools/test_whdload.py, docs/whdload.md).
amiga-release: amiga
	mkdir -p build/amiga-release && ln -sf ../../amiga/Makefile build/amiga-release/Makefile
	. amiga/env.sh && $(MAKE) -C build/amiga-release REPO=../.. RELEASE=1
	. amiga/env.sh && elf2hunk build/amiga-release/out/Wc2.elf amiga/out/Wc2-release.exe -s
	$(PYTHON) tools/hunk_size.py --release-of build/amiga-release/out/Wc2.exe amiga/out/Wc2-release.exe

# The diagnostic image stripped, for the scripted WHDLoad runs (KeysTest.slave, its KEYS
# argument; never packaged).
amiga-diag: amiga
	. amiga/env.sh && elf2hunk amiga/out/Wc2.elf amiga/out/Wc2-diag.exe -s

whdload:
	$(MAKE) -C whdload all test smoke boot-test load-test keys-test memfree

test-whdload: whdload amiga-release
	. amiga/env.sh && for m in smoke boot load run; do $(PYTHON) tools/test_whdload.py --mode $$m || exit 1; done

# Installer helper (tools/install-data/README.md): the host build and its test against
# the original installer's tree, the 68020 build and its run in FS-UAE.
install-data:
	. amiga/env.sh && $(MAKE) -C tools/install-data all amiga

test-install-data: install-data
	$(MAKE) -C tools/install-data test
	. amiga/env.sh && $(PYTHON) tools/install-data/test_amiga.py build/install-data/WC2InstallData.exe

# Release (docs/release.md): committed sources only, never a diagnostic build. A clean
# release image, slave and helper, the allowlisted package and its independent check:
# $(RELEASE_DIR)/WC2-<version>.lha, WC2-<version>-whdload.lha (no Wc2) and Wc2.
# The tag (lightweight, the version, pushed) is the owner's; github-release publishes the
# tagged HEAD as a normal release marked latest, as X-Wing's 0.1 and the WHDLoad project's.
RELEASE_DIR ?= dist
RELEASE_VERSION = $$(cat VERSION)
RELEASE_DATE = $$(sed -n "s/^DATE = '\(.*\)'/\1/p" tools/check_release.py)
release:
	@git diff --quiet HEAD && test -z "$$(git status --porcelain --untracked-files=no)" || \
		{ echo "release needs a clean tree: commit or stash first"; exit 1; }
	rm -rf build/amiga-release build/install-data
	$(MAKE) amiga-release whdload install-data
	$(PYTHON) tools/package_release.py amiga/out/Wc2-release.exe $(RELEASE_DIR)
	$(PYTHON) tools/check_release.py $(RELEASE_DIR)

release-check:
	$(PYTHON) tools/check_release.py $(RELEASE_DIR)

github-release: release-check
	@git rev-parse -q --verify "refs/tags/$(RELEASE_VERSION)" >/dev/null || \
		{ echo "tag the release commit first"; exit 1; }
	@[ "$$(git rev-parse "$(RELEASE_VERSION)^{commit}")" = "$$(git rev-parse HEAD)" ] || \
		{ echo "HEAD is not the commit tagged $(RELEASE_VERSION)"; exit 1; }
	@mkdir -p build
	$(PYTHON) tools/check_release.py --notes > build/release-notes.md
	v=$(RELEASE_VERSION) && cd $(RELEASE_DIR) && shasum -a 256 WC2-$$v.lha > WC2-$$v.lha.sha256
	gh release create $(RELEASE_VERSION) $(RELEASE_DIR)/WC2-$(RELEASE_VERSION).lha \
		$(RELEASE_DIR)/WC2-$(RELEASE_VERSION).lha.sha256 $(RELEASE_DIR)/Wc2 \
		--title "Wing Commander II $(RELEASE_VERSION) ($(RELEASE_DATE))" --latest \
		--notes-file build/release-notes.md --verify-tag

test-release-installer: whdload amiga-release install-data
	. amiga/env.sh && $(PYTHON) tools/test_release_installer.py

clean:
	$(MAKE) -C amiga clean
