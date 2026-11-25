.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
PYTHON ?= python3

.PHONY: help test sources download

help:
	@printf '%s\n' \
	  'make sources   列出已登记的数据来源' \
	  'make download [SOURCES=all]        检查并下载语料（支持逗号分隔）' \
	  'make test      运行 workflow 离线测试' \
	  'python3 -m tools.corpus_workflow run --config data/pipeline.example.json'

sources:
	$(PYTHON) -m tools.corpus_workflow list --sources data/sources.json

SOURCES ?= all
RAW_DIR ?= raw

download:
	$(PYTHON) -m tools.download_sources --sources data/sources.json --raw-dir "$(RAW_DIR)" --select "$(SOURCES)"

test:
	$(PYTHON) -B -m unittest discover -s tests -v
