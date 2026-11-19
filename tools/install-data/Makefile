# Run from anywhere: make -C tools/install-data [amiga|test]
# Source amiga/env.sh before building the Amiga binary.
# io*, sha256*, start.s, COPYING.LIB: AmigaXDev install-data, vendored unchanged and
# pinned in vendored.sha256. hashes.h: generated from reference/*.sha256.
ROOT := ../..
BUILD ?= $(ROOT)/build/install-data
CC ?= cc
CFLAGS ?= -O2 -g
WARN = -std=c99 -Wall -Wextra -Werror
SOURCES = install.c sha256.c
HEADERS = io.h sha256.h install_config.h $(BUILD)/hashes.h
AMIGA_CC = m68k-amiga-elf-gcc
AMIGA_NM = $(dir $(shell command -v $(AMIGA_CC)))../m68k-amiga-elf/bin/nm
AMIGA_FLAGS = -std=c99 -O2 -g -m68020 -msoft-float -nostdlib -fno-builtin -fno-tree-loop-distribute-patterns -fstack-usage -Wall -Wextra -Werror -Wno-volatile-register-var -DINSTALL_AMIGA -I$(BUILD)
.PHONY: all amiga test pinned
all: pinned $(BUILD)/WC2InstallData
pinned:
	@shasum -a 256 -c --quiet vendored.sha256
$(BUILD):
	mkdir -p $@
$(BUILD)/hashes.h: hashes.py $(ROOT)/reference/disk-files.sha256 $(ROOT)/reference/install.sha256 | $(BUILD)
	python3 hashes.py $@
$(BUILD)/WC2InstallData: $(SOURCES) io_unix.c $(HEADERS) | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) -I$(BUILD) $(SOURCES) io_unix.c -o $@
amiga: pinned $(BUILD)/WC2InstallData.exe
$(BUILD)/install.o: install.c $(HEADERS) Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/sha256.o: sha256.c sha256.h io.h Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -c $< -o $@
$(BUILD)/io_amiga.o: io_amiga.c io.h install_config.h Makefile | $(BUILD)
	$(AMIGA_CC) $(AMIGA_FLAGS) -I. -c $< -o $@
$(BUILD)/start.o: start.s | $(BUILD)
	$(AMIGA_CC) -m68020 -c $< -o $@
$(BUILD)/WC2InstallData.elf: $(BUILD)/start.o $(BUILD)/install.o $(BUILD)/sha256.o $(BUILD)/io_amiga.o
	$(AMIGA_CC) -nostdlib -m68020 -Wl,--emit-relocs,-Ttext=0,-e,_start,-Map=$(BUILD)/WC2InstallData.map $^ -o $@
	$(AMIGA_NM) -u $@ > $(BUILD)/undefined.txt
	@test ! -s $(BUILD)/undefined.txt
$(BUILD)/WC2InstallData.exe: $(BUILD)/WC2InstallData.elf
	elf2hunk $< $@ -s
test: all
	python3 test_install.py $(BUILD)/WC2InstallData
