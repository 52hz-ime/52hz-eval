.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
PYTHON ?= python3

.PHONY: help setup test sources download extract staging quality pinyin noise benchmark lexicon clean

help:
	@printf '%s\n' \
	  'make sources   列出已登记的数据来源' \
	  'make download [SOURCES=all]        检查并下载语料（支持逗号分隔）' \
	  'make setup     用 uv 同步 pyproject.toml 依赖' \
	  'make extract   默认完成抽取、转拼音和噪声生成' \
	  'make staging   只做 raw 到可读 staging 分片' \
	  'make quality    采样 10k/100k/1m 并生成 filter 结果' \
	  'make clean     删除 DATA_ROOT/build 生成物，不删除 raw 语料' \
	  'make pinyin    clean JSONL 转拼音（CLEAN_INPUT=...）' \
	  'make noise     从拼音记录生成噪声 cases（PINYIN_INPUT=...）' \
	  'make benchmark [PER_SOURCE=1000] [TRIAL=100]  各来源等量采样子句级 IME benchmark（含试跑小集）' \
	  'make lexicon   从 benchmark 的通过池统计二字词表，供解码器判断追问' \
	  'make test      运行 workflow 离线测试' \
	  'python3 -m tools.corpus_workflow run --config data/pipeline.example.json'

sources:
	$(PYTHON) -m tools.corpus_workflow list --sources data/sources.json

SOURCES ?= all
DATA_ROOT ?= /data/52hz-eval
RAW_DIR ?= $(DATA_ROOT)/raw
BUILD_DIR ?= $(DATA_ROOT)/build
STAGING_CONFIG ?= data/staging.pipeline.json
# make staging SOURCE=thucnews 只重建一个来源，其余 staging 目录保持不变
SOURCE ?=

download:
	$(PYTHON) -m tools.download_sources --sources data/sources.json --raw-dir "$(RAW_DIR)" --select "$(SOURCES)"

setup:
	uv sync

extract:
	uv run python -m tools.benchmark_pipeline --config data/benchmark.pipeline.json --data-root "$(DATA_ROOT)"

staging:
	uv run python -m tools.benchmark_pipeline --config "$(STAGING_CONFIG)" --staging-only --output-dir "$(BUILD_DIR)/staging" --data-root "$(DATA_ROOT)" $(if $(SOURCE),--source "$(SOURCE)")

QUALITY_DIR ?= $(BUILD_DIR)/quality/iteration-001
QUALITY_INPUTS ?= $(BUILD_DIR)/staging/lccc_base $(BUILD_DIR)/staging/lccc_large $(BUILD_DIR)/staging/clue_corpus_small $(BUILD_DIR)/staging/thucnews $(BUILD_DIR)/staging/kdconv

quality:
	uv run python -m tools.quality_pipeline --input $(QUALITY_INPUTS) --output-dir "$(QUALITY_DIR)" --sizes 10000,100000,1000000 --seed 52

BENCHMARK_DIR ?= $(BUILD_DIR)/benchmark/iteration-003
PER_SOURCE ?= 1000
TRIAL ?= 100

# 各来源等量、按逗号句号切成子句、按目标长度分布加权；对话来源尚未人工审核，所以显式 --include-review
benchmark:
	uv run python -m tools.ime_benchmark --staging "$(BUILD_DIR)/staging" --output-dir "$(BENCHMARK_DIR)" \
	  --per-source $(PER_SOURCE) --trial $(TRIAL) --include-review --show 30

# 二字组合至少出现 LEXICON_MIN_COUNT 次才进入词表；词条带拼音，解码器用它判断另一种读法是不是真词
LEXICON ?= $(BUILD_DIR)/benchmark/lexicon.jsonl
LEXICON_MIN_COUNT ?= 20

lexicon:
	uv run python -m tools.word_lexicon --benchmark-dir "$(BENCHMARK_DIR)" --output "$(LEXICON)" --min-count $(LEXICON_MIN_COUNT)

clean:
	@test "$(CURDIR)" != "/" || { echo '拒绝在根目录执行清理。' >&2; exit 2; }
	rm -rf -- "$(BUILD_DIR)"
	@printf '%s\n' '已清理 $(BUILD_DIR)；$(RAW_DIR) 原始语料保持不变。'

CLEAN_INPUT ?= $(BUILD_DIR)/clean.jsonl
PINYIN_INPUT ?= $(BUILD_DIR)/pinyin.jsonl
PINYIN_OUTPUT ?= $(BUILD_DIR)/pinyin.jsonl
CASES_OUTPUT ?= $(BUILD_DIR)/cases.jsonl

pinyin:
	uv run python -m tools.pinyin_cases pinyin --input "$(CLEAN_INPUT)" --output "$(PINYIN_OUTPUT)" --manifest "$(PINYIN_OUTPUT:.jsonl=.manifest.json)"

noise:
	uv run python -m tools.pinyin_cases noise --input "$(PINYIN_INPUT)" --output "$(CASES_OUTPUT)" --manifest "$(CASES_OUTPUT:.jsonl=.manifest.json)"

# 用 uv 的环境跑，转拼音和 benchmark 构建的测试才不会被跳过
test:
	uv run python -B -m unittest discover -s tests -v
