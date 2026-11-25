.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
PYTHON ?= python3

.PHONY: help setup test sources download extract pinyin noise clean

help:
	@printf '%s\n' \
	  'make sources   列出已登记的数据来源' \
	  'make download [SOURCES=all]        检查并下载语料（支持逗号分隔）' \
	  'make setup     用 uv 同步 pyproject.toml 依赖' \
	  'make extract   默认完成抽取、转拼音和噪声生成' \
	  'make staging   只做 raw 到可读 staging 分片' \
	  'make clean     删除 build/ 生成物，不删除 raw/ 语料' \
	  'make pinyin    clean JSONL 转拼音（CLEAN_INPUT=...）' \
	  'make noise     从拼音记录生成噪声 cases（PINYIN_INPUT=...）' \
	  'make test      运行 workflow 离线测试' \
	  'python3 -m tools.corpus_workflow run --config data/pipeline.example.json'

sources:
	$(PYTHON) -m tools.corpus_workflow list --sources data/sources.json

SOURCES ?= all
RAW_DIR ?= raw

download:
	$(PYTHON) -m tools.download_sources --sources data/sources.json --raw-dir "$(RAW_DIR)" --select "$(SOURCES)"

setup:
	uv sync

extract:
	uv run python -m tools.benchmark_pipeline --config data/benchmark.pipeline.json

staging:
	uv run python -m tools.benchmark_pipeline --config data/benchmark.pipeline.json --staging-only

clean:
	@test "$(CURDIR)" != "/" || { echo '拒绝在根目录执行清理。' >&2; exit 2; }
	rm -rf -- build
	@printf '%s\n' '已清理 build/；raw/ 原始语料保持不变。'

CLEAN_INPUT ?= build/clean.jsonl
PINYIN_INPUT ?= build/pinyin.jsonl
PINYIN_OUTPUT ?= build/pinyin.jsonl
CASES_OUTPUT ?= build/cases.jsonl

pinyin:
	uv run python -m tools.pinyin_cases pinyin --input "$(CLEAN_INPUT)" --output "$(PINYIN_OUTPUT)" --manifest "$(PINYIN_OUTPUT:.jsonl=.manifest.json)"

noise:
	uv run python -m tools.pinyin_cases noise --input "$(PINYIN_INPUT)" --output "$(CASES_OUTPUT)" --manifest "$(CASES_OUTPUT:.jsonl=.manifest.json)"

test:
	$(PYTHON) -B -m unittest discover -s tests -v
