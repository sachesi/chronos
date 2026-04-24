TOPDIR := $(HOME)/rpmbuild
SOURCES_DIR := $(TOPDIR)/SOURCES
SPEC := chronos.spec
NAME := chronos
VERSION := $(shell rpmspec -q --qf '%{VERSION}\n' --srpm $(SPEC) | head -n1)

all: srpm

srpm:
	mkdir -p "$(SOURCES_DIR)"
	spectool -g -R $(SPEC)
	rpmbuild -bs $(SPEC)

clean:
	rm -rf build dist *.egg-info src/*.egg-info result
