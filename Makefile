## Wing Commander II — repository-level targets.

.PHONY: all help extract install hash check-ref prepare-reference reference-staging compare \
	reference-emulator reference gen gen-check lint test test-decode test-x86 test-m68k test-sabotage \
	test-guards host amiga smoke size clean

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
	@echo "  make hash               re-record $(INSTALL_HASHES) from ref/ (deliberate change only)"
	@echo "  make check-ref          verify ref/ against $(INSTALL_HASHES)"
	@echo "  make prepare-reference  copy ref/ to disposable $(REFERENCE_ROOT)"
	@echo "  make reference-staging  play the disposable copy in DOSBox Staging"
	@echo "  make compare            PC WC1 vs WC2 code and data comparison -> tmp/compare/"
	@echo "  make reference-emulator build instrumented DOSBox-X (tools/patches/ORDER)"
	@echo "  make reference          gate 1: every milestone twice, image proof, identical state"
	@echo
	@echo "  Translator and Amiga build (Secret Weapons of Luftwaffe's; docs/upstream.md):"
	@echo "  make gen                translate the in-scope modules -> build/gen (none before P1.4)"
	@echo "  make gen-check          G1: headers, digests and byte-identical regeneration of build/gen"
	@echo "  make lint               G2: no guest-address names in hand-written code"
	@echo "  make test               lint, decoder, x86/68020 differentials (space, boundary), guards, gen-check"
	@echo "  make test-sabotage      planted faults must fail the x86 and 68020 differentials"
	@echo "  make host               link generated program + runtime for Unicorn 68020 -> build/host/swotl.elf"
	@echo "  make amiga              build amiga/out/Wc2.exe"
	@echo "  make smoke              boot it under FS-UAE + GDB: takeover live, then hand-back"
	@echo "  make size               account for code, data, symbols and relocations in the executable"
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
	. amiga/env.sh && python3 tools/origin_pak.py verify tmp/union ref/WING2/GAMEDAT || true
	. amiga/env.sh && python3 tools/wc_compare.py tmp/wc1/disk01/WC.EXE ref/WING2/WC2.EXE \
		--control ref/WING2/INSTALL.EXE --csv tmp/compare/funcs.csv | tee tmp/compare/report.txt

reference-emulator:
	tools/build_dosbox_x.sh

# Gate 1 (docs/pc-reference-loop.md): reference/milestones.csv, two runs each.
reference: check-ref
	. amiga/env.sh && $(PYTHON) tools/reference.py

# --- Translator, tests and builds (Secret Weapons of Luftwaffe 658fc60, docs/upstream.md) ---

gen:
	$(PYTHON) -m translator.gen

gen-check:
	$(PYTHON) -m translator.check gen --regen

lint:
	$(PYTHON) -m translator.check lint

test-decode:
	$(PYTHON) tests/test_decode.py

# The "forms" and "blocks" corpora come from the game's code: empty until P2.
CORPORA ?= space,boundary
test-x86:
	$(PYTHON) tests/x86_diff.py --only $(CORPORA)

test-m68k:
	$(PYTHON) tests/m68k_diff.py --only $(CORPORA)

test-guards: gen
	$(PYTHON) tests/test_guards.py

# Checks run in parallel after the one writer of build/gen (gen-check); each logs
# to tmp/test/<name>.log and prints one status line.
JOBS ?= $(shell sysctl -n hw.ncpu 2>/dev/null || nproc)
RUN = @mkdir -p tmp/test; if $(2) > tmp/test/$(1).log 2>&1; then echo "ok    $(1)"; \
	else echo "FAIL  $(1) (tmp/test/$(1).log)"; tail -n 15 tmp/test/$(1).log; exit 1; fi
SHARDS = space.0/1 boundary.0/1
# Unit tests (docs/upstream.md lists the deferred ones); test_load_image needs ref/.
UNIT_TESTS = test_align test_align_convergence test_amiga_input test_block_boundary \
	test_byteorder_entries test_carry_entries test_compact test_cost_meter \
	test_display_queue test_dosbox_retf test_fixture_inputs test_fm_allocation \
	test_fm_cache test_fm_envelope test_fm_phase test_fm_quality test_fm_render \
	test_gate_runner test_helper_branches test_hunk_size test_joystick_cli \
	test_joystick_events test_joystick_link test_load_image test_joystick_recorder test_joystick_replay \
	test_jump_fusion test_key_release test_m68k_assembly test_next_branch \
	test_oracle_boundary test_oracle_exception_writes test_reglive test_rep_lowering \
	test_rep_replay test_replay_chords test_replay_events test_smc_flow
TESTS = t-lint t-decode t-guards $(subst /,-of-,$(SHARDS:%=t-x86-%)) $(subst /,-of-,$(SHARDS:%=t-m68k-%)) \
	$(UNIT_TESTS:%=t-unit-%)

test: gen-check
	@$(MAKE) -s -k -j$(JOBS) $(TESTS)

test-sabotage: gen-check
	@$(MAKE) -s -k -j$(JOBS) t-sab-x86 t-sab-m68k

t-lint:
	$(call RUN,lint,$(PYTHON) -m translator.check lint)
t-decode:
	$(call RUN,decode,$(PYTHON) tests/test_decode.py)
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

build/host/swotl.elf: $(HOST_OBJ)
	$(CROSS)ld -Ttext=0x10000 -e _start -o $@ $(HOST_OBJ)

host: gen-check build/host/swotl.elf

amiga: gen-check
	. amiga/env.sh && $(MAKE) -C amiga

GATE_LAUNCH = $(if $(GATE_ISOLATED),$(PYTHON) "$(CURDIR)/tools/gate_launch.py",)
smoke: amiga
	. amiga/env.sh && $(GATE_LAUNCH) amiga/debug.sh "" "$(CURDIR)/amiga/diag_smoke.gdb" | grep -q '^WC2_SMOKE_OK'

size: amiga
	$(PYTHON) tools/hunk_size.py amiga/out/Wc2.exe

clean:
	$(MAKE) -C amiga clean
