SHELL := /usr/bin/bash
.DELETE_ON_ERROR:

MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PROJECT_DIR  ?= $(patsubst %/,%,$(MAKEFILE_DIR))
SPECFILE     ?= $(or $(spec),$(PROJECT_DIR)/chronos.spec)
NAME         ?= chronos

RPMBUILD_DIR ?= $(HOME)/rpmbuild
SOURCES_DIR  ?= $(RPMBUILD_DIR)/SOURCES
SRPMS_DIR    ?= $(RPMBUILD_DIR)/SRPMS
RPMS_DIR     ?= $(RPMBUILD_DIR)/RPMS
OUTDIR       ?= $(or $(outdir),$(SRPMS_DIR))

VERSION := $(shell rpmspec -q --qf '%{VERSION}\n' --srpm "$(SPECFILE)" 2>/dev/null | head -n1)

SOURCE_ARCHIVE := $(SOURCES_DIR)/$(NAME)-$(VERSION).tar.gz

.PHONY: all \
	rpm srpm ba bs \
	rpm-local srpm-local ba-local bs-local \
	copr \
	sources local-sources prepare clean info check

all: srpm

rpm: ba
srpm: bs

rpm-local: ba-local
srpm-local: bs-local

# Normal online local binary RPM build:
ba: sources
	rpmbuild -ba \
		--define "_topdir $(RPMBUILD_DIR)" \
		--define "_sourcedir $(SOURCES_DIR)" \
		"$(SPECFILE)"

# Normal online local SRPM build:
bs: sources
	rpmbuild -bs \
		--define "_topdir $(RPMBUILD_DIR)" \
		--define "_sourcedir $(SOURCES_DIR)" \
		--define "_srcrpmdir $(OUTDIR)" \
		"$(SPECFILE)"

# Local generated-source binary RPM build:
ba-local: local-sources
	rpmbuild -ba \
		--define "_topdir $(RPMBUILD_DIR)" \
		--define "_sourcedir $(SOURCES_DIR)" \
		"$(SPECFILE)"

# Local generated-source SRPM build:
bs-local: local-sources
	rpmbuild -bs \
		--define "_topdir $(RPMBUILD_DIR)" \
		--define "_sourcedir $(SOURCES_DIR)" \
		--define "_srcrpmdir $(OUTDIR)" \
		"$(SPECFILE)"

# COPR target (compatible with .copr/Makefile usage)
copr:
	@mkdir -p "$(SOURCES_DIR)" "$(OUTDIR)"
	spectool -g -C "$(SOURCES_DIR)" "$(SPECFILE)"
	rpmbuild -bs \
		--define "_topdir $(RPMBUILD_DIR)" \
		--define "_sourcedir $(SOURCES_DIR)" \
		--define "_srcrpmdir $(OUTDIR)" \
		"$(SPECFILE)"

# Download Source0 declared in the spec.
sources: check prepare
	@echo ":: downloading Source0 into $(SOURCES_DIR)"
	spectool -g -C "$(SOURCES_DIR)" "$(SPECFILE)"
	@test -f "$(SOURCE_ARCHIVE)" || { echo "ERROR: missing $(SOURCE_ARCHIVE)" >&2; exit 1; }

# Generate Source0 from current local checkout.
local-sources: check prepare
	@command -v rsync >/dev/null || { echo "ERROR: rsync not found." >&2; exit 1; }
	@echo ":: creating local Source0: $(SOURCE_ARCHIVE)"
	@tmpdir="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmpdir"' EXIT; \
	mkdir -p "$$tmpdir/$(NAME)-$(VERSION)"; \
	rsync -rt --delete \
		--chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r \
		--exclude='.git' \
		--exclude='.gitignore' \
		--exclude='.copr' \
		--exclude='.local' \
		--exclude='result' \
		--exclude='results' \
		--exclude='dist' \
		--exclude='build' \
		--exclude='__pycache__' \
		--exclude='*.pyc' \
		"$(PROJECT_DIR)/" "$$tmpdir/$(NAME)-$(VERSION)/"; \
	tar --owner=0 --group=0 --numeric-owner \
		-C "$$tmpdir" -czf "$(SOURCE_ARCHIVE)" "$(NAME)-$(VERSION)"
	@echo ":: local Source0 ready: $(SOURCE_ARCHIVE)"

prepare:
	@mkdir -p "$(SOURCES_DIR)" "$(SRPMS_DIR)" "$(RPMS_DIR)" "$(OUTDIR)"

check:
	@test -f "$(SPECFILE)" || { echo "ERROR: spec not found: $(SPECFILE)" >&2; exit 1; }
	@test -n "$(VERSION)" || { echo "ERROR: could not read Version from $(SPECFILE)" >&2; exit 1; }
	@command -v rpmspec >/dev/null || { echo "ERROR: rpmspec not found. Install rpm-build." >&2; exit 1; }
	@command -v rpmbuild >/dev/null || { echo "ERROR: rpmbuild not found. Install rpm-build." >&2; exit 1; }
	@command -v spectool >/dev/null || { echo "ERROR: spectool not found. Install rpmdevtools." >&2; exit 1; }
	@command -v tar >/dev/null || { echo "ERROR: tar not found." >&2; exit 1; }

info:
	@echo "NAME:             $(NAME)"
	@echo "VERSION:          $(VERSION)"
	@echo "PROJECT_DIR:      $(PROJECT_DIR)"
	@echo "SPECFILE:         $(SPECFILE)"
	@echo "RPMBUILD_DIR:     $(RPMBUILD_DIR)"
	@echo "SOURCES_DIR:      $(SOURCES_DIR)"
	@echo "SRPMS_DIR:        $(SRPMS_DIR)"
	@echo "RPMS_DIR:         $(RPMS_DIR)"
	@echo "OUTDIR:           $(OUTDIR)"
	@echo "SOURCE_ARCHIVE:   $(SOURCE_ARCHIVE)"

clean:
	rm -rf build dist *.egg-info src/*.egg-info result results
	rm -f "$(SOURCE_ARCHIVE)"
