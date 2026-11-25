# 52Hz Eval

52Hz 的输入数据、评测工具和回归基准。

## 评测范围

- 拼音切分和长句理解
- 中英文、数字和符号混输
- 键盘相邻键误触恢复
- 漏按、多按和字符交换
- 音节块转置
- 首选结果准确率和 Top-k 命中率
- 首次响应延迟和端到端延迟
- 内存、CPU 和模型加载时间
- 自动提交、候选展示和撤销行为

## 数据原则

- 优先使用简体中文的日常对话、帖子、评论和新闻。
- Wikipedia 只作为少量风格对照，不作为主数据来源。
- 每个来源都登记在 `data/sources.json`，记录稳定 ID、来源页面、数据 artifact、格式、字段、推荐占比、使用优先级和质量策略。
- 原始下载文件放在本地 `raw/`，清洗结果放在 `build/`；这两个目录不进入 Git。
- 所有抽取、清洗、去重和采样都由标准库脚本完成，并保存随机种子、抽取器版本和 manifest。
- 原始对话语料不是自动 gold：`manual_review` 和 `mixed_review` 来源先进入待审核池；只有审核通过的记录才能进入正式 benchmark。

## 可复用 workflow

下载来源使用索引里的 Hugging Face 文件清单，默认检查并下载全部已登记来源：

```sh
make download
```

选择多个来源或全部来源：

```sh
make download SOURCES=lccc_base,kdconv
make download SOURCES=all
```

每个文件都会先检查 `raw/<source-id>/` 下是否已有完整文件；完整文件打印“已有，跳过”，中断文件保留为 `.part` 并在下次继续。输出包含来源序号、文件序号、当前文件名、下载完成状态和最终汇总。CLUECorpusSmall、THUCNews 等文件较大，下载前应确认磁盘空间；没有自动入口的来源会明确打印 `manual`，不会伪装成已下载。

先查看来源索引：

```sh
make sources
```

Python 依赖由 `pyproject.toml` 管理，推荐使用 `uv` 建立项目环境：

```sh
make setup
```

对一个原始文本、JSON、JSONL 文件或目录做统一抽取。普通 JSONL 来源的字段由 `data/sources.json` 中的 `text_fields`、`context_fields` 和 `id_fields` 指定；对话来源用 `turns_field` 展开每个 turn，并把此前 turn 作为上下文；若来源是 tokenized 文本，可配置 `join_tokens` 去除分词空格。纯文本来源按行处理：

```sh
python3 -m tools.corpus_workflow extract \
  --source lccc_base \
  --input raw/lccc_base \
  --output build/lccc-base.jsonl \
  --min-chars 4 --max-chars 160 \
  --manifest build/lccc-base.manifest.json
```

抽取阶段会做 Unicode NFC、控制字符清理、空白归一化、中文存在性过滤、长度过滤和同来源精确去重；不会把中文全角标点转换成半角，并写出统一记录：

```json
{
  "id": "lccc_base:...",
  "source_id": "lccc_base",
  "source_record_id": "...",
  "text": "目标句子",
  "context": "可选上下文",
  "source_url": "...",
  "source_script": "simplified",
  "extractor_version": "0.1.0"
}
```

合并多个来源并确定性采样：

```sh
python3 -m tools.corpus_workflow sample \
  --input build/lccc-base.jsonl build/comments2019zh.jsonl \
  --output build/benchmark-clean.jsonl \
  --count 5000 --seed 52 --split dev \
  --manifest build/benchmark-clean.manifest.json
```

查看来源和长度分布：

```sh
python3 -m tools.corpus_workflow stats --input build/benchmark-clean.jsonl
```

完整流程可以写入 `data/pipeline.example.json`，然后运行：

```sh
python3 -m tools.corpus_workflow run --config data/pipeline.example.json
```

配置中的路径相对于配置文件所在目录解析。`run` 先执行所有抽取任务，再执行最终采样；同一个配置和 seed 应产生相同输出。采样 manifest 会记录输入文件、输出文件、请求数量、实际数量、来源分布和 seed。

## 拼音和噪声

默认流程可以只运行一条命令：

```sh
make extract
```

如果只想检查原始语料统一后的内容，不生成拼音和噪声：

```sh
make staging
```

结果位于 `build/staging-runs/<run-id>/staging/`，当前指针是 `build/current-staging.json`；重复执行相同条件会跳过。

清理所有生成的 clean、pinyin、cases、manifest 和历史 run：

```sh
make clean
```

该命令只删除 `build/`，不会删除 `raw/` 中已下载的原始语料。

它使用 `data/benchmark.pipeline.json`，默认从 THUCNews 抽取 5,000 条句子，依次生成：

```text
raw/ 语料
  -> build/runs/<run-id>/staging/  不压缩的统一 JSONL 分片，方便检查
  -> build/runs/<run-id>/clean.jsonl   抽取、清洗、切句、去重、采样
  -> build/runs/<run-id>/pinyin.jsonl  中文转拼音，literal 原样保留
  -> build/runs/<run-id>/cases.jsonl   漏键、重复、邻键、交换、截断等噪声样本
```

结果按输入、配置、来源文件指纹、处理器源码、`pyproject.toml`/`uv.lock` 和生成器版本计算 run ID，实际保存到 `build/runs/<run-id>/`。同一条件再次运行会输出“已有完整 run，跳过”；条件变化会生成新的 run，不覆盖旧结果。`build/current.json` 只保存当前完整 run 的指针。

staging 默认每个分片约 64 MiB，文件名为 `part-00000.jsonl`，保持普通文本格式，便于 `head`、`jq` 和编辑器检查。LCCC 和 CLUE 不在默认正式流程里：前者需要人工审核，后者文件过大。需要调整来源、数量或分片大小时，编辑 `data/benchmark.pipeline.json`，不需要把一串参数写在命令行里。

抽取出的统一 JSONL 先转成带有 literal 片段和音节映射的拼音记录，再生成输入法 cases：

```sh
make pinyin CLEAN_INPUT=build/clean.jsonl
make noise PINYIN_INPUT=build/pinyin.jsonl
```

等价的 CLI 是：

```sh
uv run 52hz-pinyin pinyin \
  --input build/clean.jsonl \
  --output build/pinyin.jsonl \
  --manifest build/pinyin.manifest.json

uv run 52hz-pinyin noise \
  --input build/pinyin.jsonl \
  --output build/cases.jsonl \
  --operations clean,drop,duplicate,insert,neighbor,swap,syllable_swap,truncate_prefix,truncate_suffix \
  --seed 52 \
  --manifest build/cases.manifest.json
```

转拼音使用短语感知的 `pypinyin`，英文、数字、型号和标点作为 literal 原样保留。噪声只修改中文拼音段，并把操作、位置和 seed 写入 `noise_ops`；同一个 `seed` 和记录 ID 会得到相同变体。

默认不会把 `manual_review` 或 `mixed_review` 来源生成正式 cases；审核前如需做探索性输出，显式加 `--include-review`。

## 后续阶段

当前 workflow 只负责原始语料到干净基础句的可复现处理。拼音生成、漏键/邻键/交换/截断等噪声变体，以及 `preview`、`commit`、`ask` 交互标签，放在下一层 generator 中，输入应是这里输出的统一 JSONL，而不是重新读取各个来源的原始格式。

运行离线测试：

```sh
make test
```

## 状态

项目处于评测集和噪声数据生成器设计阶段。
