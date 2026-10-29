## Wing Commander II — repository-level targets.

.PHONY: all help extract install hash check-ref prepare-reference reference-staging compare

REFERENCE_ROOT ?= tmp/pc-root
INSTALL_OUT ?= tmp/pc-install
INSTALL_SECS ?= 1800
INSTALL_HASHES := reference/install.sha256

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
