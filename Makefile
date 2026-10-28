## Wing Commander II — repository-level targets.

.PHONY: all help extract install hash check-ref prepare-reference reference-staging

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
	rsync -a --delete --chmod=u+w ref/ $(REFERENCE_ROOT)/

reference-staging: prepare-reference
	dosbox-staging --noprimaryconf --nolocalconf -conf reference/dosbox-staging.conf
	$(MAKE) check-ref
