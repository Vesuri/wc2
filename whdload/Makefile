# Native host cross-build: no Amiga assembler or build utilities required.
# From Secret Weapons of the Luftwaffe's whdload/Makefile (docs/upstream.md).
WHDLOAD ?= $(HOME)/.local/share/amiga/WHDLoad
NDK ?= $(HOME)/.local/opt/m68k-amiga-elf/sys-include
VASM ?= $(HOME)/.local/vasmm68k_mot
AMIGA_SHARE ?= $(HOME)/.local/share/amiga
OUT := ../build/whdload

# all: the release slave. The others are tools/test_whdload.py scaffolding:
# --mode smoke|boot|load, the TEST slave's PASS markers, KeysTest (--mode script: the
# diagnostic image with data/keys as its KEYS argument), and MemFree, which
# records kickemu's free-memory low-water marks for sizing the slave's memory
# reservation (docs/whdload.md, Memory). A sizing variant escapes the $ for make
# and the shell: make -C whdload memfree 'FASTSIZE=\$$600000'. KeysMemFree is both: the
# low water on a scripted route (--mode script --slave build/whdload/KeysMemFree.slave).
.PHONY: all test smoke boot-test load-test memfree keys-test keys-memfree FORCE
all: $(OUT)/Wc2.slave
test: $(OUT)/Wc2Test.slave
smoke: $(OUT)/Smoke.slave
boot-test: $(OUT)/BootTest.slave
load-test: $(OUT)/LoadTest.slave
memfree: $(OUT)/MemFree.slave
keys-test: $(OUT)/KeysTest.slave
keys-memfree: $(OUT)/KeysMemFree.slave
$(OUT)/Wc2Test.slave: VASMFLAGS += -DTEST=1
$(OUT)/BootTest.slave: VASMFLAGS += -DBOOTONLY=1
$(OUT)/LoadTest.slave: VASMFLAGS += -DLOADONLY=1
$(OUT)/KeysTest.slave: VASMFLAGS += -DKEYS=1
$(OUT)/MemFree.slave: VASMFLAGS += -DMEMFREE=\$$100 $(if $(FASTSIZE),-DFASTSIZE=$(FASTSIZE))
$(OUT)/KeysMemFree.slave: VASMFLAGS += -DKEYS=1 -DMEMFREE=\$$100

# Reassemble the small slave on every invocation: SDK includes and assembler
# options must never leave an old diagnostic slave in a release package.
$(OUT)/Wc2.slave $(OUT)/Wc2Test.slave $(OUT)/MemFree.slave $(OUT)/BootTest.slave $(OUT)/LoadTest.slave $(OUT)/KeysTest.slave $(OUT)/KeysMemFree.slave: Wc2Slave.s FORCE
	@mkdir -p $(OUT)/include/lvo
	@for lib in dos exec graphics expansion; do ln -sf "$(NDK)/lvo/$${lib}_lib.i" "$(OUT)/include/lvo/$$lib.i"; done
	@# kick31.s leaves ws_DontCache 0; this copy, found first, points it at slv_DontCache.
	@mkdir -p $(OUT)/include/whdload
	sed 's/dc\.w[[:space:]]*0\([[:space:]]*;ws_DontCache\)/dc.w	slv_DontCache-slv_base\1/' \
		"$(WHDLOAD)/Src/sources/whdload/kick31.s" > $(OUT)/include/whdload/kick31.s
	grep -q 'slv_DontCache-slv_base' $(OUT)/include/whdload/kick31.s
	$(VASM) -m68020 -pic -x -devpac -Fhunkexe -nosym $(VASMFLAGS) -I$(OUT)/include -I"$(WHDLOAD)/Include" -I"$(WHDLOAD)/Src/sources" -I"$(NDK)" -o $@ $<

# The smoke slave is AmigaXDev's shared one with this project's name (smoke_name.i).
$(OUT)/Smoke.slave: $(AMIGA_SHARE)/whdload/SmokeSlave.s smoke_name.i FORCE
	@mkdir -p $(OUT)
	$(VASM) -m68000 -pic -x -devpac -Fhunkexe -nosym -DSMOKE_DATA_LAST=1 -I. -I"$(WHDLOAD)/Include" -I"$(NDK)" -o $@ $<
