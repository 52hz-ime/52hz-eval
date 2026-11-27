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
- 原始下载文件和生成结果默认放在 `/data/52hz-eval/raw/`、`/data/52hz-eval/build/`；仓库只保存配置、代码和测试。
- 所有抽取、清洗、去重和采样都由标准库脚本完成，并保存随机种子、抽取器版本和 manifest。
- 原始对话语料不是自动 gold：`manual_review` 和 `mixed_review` 来源先进入待审核池；只有审核通过的记录才能进入正式 benchmark。

## OSS 配置

公开的 OSS 路由配置位于 `data/oss.public.env`；AccessKey 只从本机 `~/.config/52hz/oss.env` 读取，不进入仓库。当前 staging 上传目标是上海地域的 `52hz-ime` Bucket 和 `52hz/staging/` prefix。

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

每个文件都会先检查 `/data/52hz-eval/raw/<source-id>/` 下是否已有完整文件；完整文件打印“已有，跳过”，中断文件保留为 `.part` 并在下次继续。输出包含来源序号、文件序号、当前文件名、下载完成状态和最终汇总。CLUECorpusSmall、THUCNews 等文件较大，下载前应确认磁盘空间；没有自动入口的来源会明确打印 `manual`，不会伪装成已下载。

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
  --input /data/52hz-eval/raw/lccc_base \
  --output /data/52hz-eval/build/lccc-base.jsonl \
  --min-chars 4 --max-chars 160 \
  --manifest /data/52hz-eval/build/lccc-base.manifest.json
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
  --input /data/52hz-eval/build/lccc-base.jsonl /data/52hz-eval/build/comments2019zh.jsonl \
  --output /data/52hz-eval/build/benchmark-clean.jsonl \
  --count 5000 --seed 52 --split dev \
  --manifest /data/52hz-eval/build/benchmark-clean.manifest.json
```

查看来源和长度分布：

```sh
python3 -m tools.corpus_workflow stats --input /data/52hz-eval/build/benchmark-clean.jsonl
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

默认配置 `data/staging.pipeline.json` 会遍历全部已登记来源；缺失的可选来源（例如尚未准备的 Wikipedia）会明确跳过。结果直接位于 `/data/52hz-eval/build/staging/<source-id>/`，不再带 run ID；重复执行会重建当前 staging 树。之前已经生成的 `/data/52hz-eval/build/staging-runs/` 历史结果仍保留，直到执行 `make clean`。

清理所有生成的 clean、pinyin、cases、manifest 和历史 run：

```sh
make clean
```

该命令只删除 `/data/52hz-eval/build/`，不会删除 `/data/52hz-eval/raw/` 中已下载的原始语料。

它使用 `data/benchmark.pipeline.json`，从已经完成的 THUCNews staging 中采样 5,000 条句子，依次生成：

```text
/data/52hz-eval/raw/ 语料
  -> make staging
  -> /data/52hz-eval/build/staging/  不压缩的统一 JSONL 分片，方便检查
  -> make extract
  -> /data/52hz-eval/build/runs/<run-id>/clean.jsonl   抽取、清洗、切句、去重、采样
  -> /data/52hz-eval/build/runs/<run-id>/pinyin.jsonl  中文转拼音，literal 原样保留
  -> /data/52hz-eval/build/runs/<run-id>/cases.jsonl   漏键、重复、邻键、交换、截断等噪声样本
```

结果按 staging 输入、配置、来源文件指纹、处理器源码、`pyproject.toml`/`uv.lock` 和生成器版本计算 run ID，实际保存到 `/data/52hz-eval/build/runs/<run-id>/`。同一条件再次运行会输出“已有完整 run，跳过”；条件变化会生成新的 run，不覆盖旧结果。`/data/52hz-eval/build/current.json` 只保存当前完整 run 的指针。

staging 默认每个分片约 64 MiB，文件名为 `part-00000.jsonl`，保持普通文本格式，便于 `head`、`jq` 和编辑器检查。LCCC 和 CLUE 不在默认正式流程里：前者需要人工审核，后者文件过大。需要调整来源、数量或分片大小时，编辑 `data/benchmark.pipeline.json`，不需要把一串参数写在命令行里。

抽取出的统一 JSONL 先转成带有 literal 片段和音节映射的拼音记录，再生成输入法 cases：

```sh
make pinyin CLEAN_INPUT=/data/52hz-eval/build/clean.jsonl
make noise PINYIN_INPUT=/data/52hz-eval/build/pinyin.jsonl
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

## 子句级 IME benchmark

`make benchmark` 从整个 staging 树构建各来源等量的 benchmark，默认写到 `/data/52hz-eval/build/benchmark/iteration-003/`：

```sh
make benchmark                       # 每个来源 1000 条基础子句，另抽 300 条试跑小集
make benchmark PER_SOURCE=300 TRIAL=100 BENCHMARK_DIR=/data/52hz-eval/build/benchmark/try-004
```

处理步骤：

1. **按逗号和句号切成子句。** 每条 staging 记录在 `，。！？；…` 处切开，标点留在它结束的子句上；`、` 不切，数字之间的 ASCII 逗号不切（`1,000`、`3.14` 保持完整）。一个子句就是一次“连续输入后按空格”的单位，长度限定 4–30 个字符。
2. **每个子句单独清洗。** 规则在 `quality_filter.py`（0.3.0）。除了原有规则，还拒绝：没有开头的收尾引号或括号、以收尾符或标点开头、以引号开头符结尾、汉字之间夹空格、URL / @ / # / 表情符号、繁体和日文汉字、非汉字非 ASCII 的字母、兼容区和扩展 B 的生僻字、`1、` `12:` 这样的列表编号、英文字母超过 30% 或数字超过 40%。逗号后面的收尾引号不算问题，例如 `……不成问题，”`。
3. **各来源等量采样。** 长度按目标正态分布加权（默认均值 12、标准差 5），实际分布写在 `manifest.json` 的 `lengths` 里。
4. **上文取两行。** 记录 `context` 的最后一行（对话的上一轮、新闻的标题），加上同一个文档里的前一个子句，各至多 60 字；不传完整对话历史。

噪声分三类，每条子句每种各生成一个变体：

- **按键错误**：`drop` 漏按、`duplicate` 多按、`insert` 多按一个相邻键、`neighbor` 按成相邻键、`swap` 相邻两个字母颠倒、`hand_swap` 左右手不同步（左右手的两个相邻字母颠倒）、`truncate_suffix` 句尾字母没打完。
- **口音合并**：`nasal`（en/eng、in/ing、an/ang 互相不分）、`n_l`、`retroflex`（zh/z、ch/c、sh/s）、`f_h`。变换后的音节仍然是合法拼音。
- **多错**：`x2`、`x3`，不同的音节各错一处。额度是 `max(2, round(0.3 × 音节数))`，10 个音节容 3 个；每个错误数生成一个变体，所以评分可以按错误个数看。

对话来源仍是 `manual_review` / `mixed_review`，所以 `make benchmark` 显式带 `--include-review`。直接运行命令而不带它时，只要选中的来源里有待审核的，就会报错退出，不会悄悄只剩一个来源。

产物：

```text
base.jsonl        抽中的基础子句及其拼音
cases.jsonl       基础子句 × 噪声操作，字段和之前的 cases.jsonl 相同
trial-300.jsonl   按来源 × 噪声类型轮流抽取的试跑小集（TRIAL=300）
trial-100.jsonl   按来源 × 操作轮流抽取的试跑小集
manifest.json     来源、操作、长度分布、被各条规则拦截的数量
shards/           每个来源的扫描缓存；staging、过滤规则和切分规则不变时直接复用
```

第一次运行要扫描全部 staging（约 46 GB，32 核约 2 分钟），之后改采样数量、长度目标或种子只需几秒。`shards/<来源>-<缓存键>.rejected.jsonl` 按千分之一抽样保存了被拒绝的子句和命中的规则，用来人工检查清洗是否误伤。

`make lexicon` 从同一个 benchmark 的通过池统计单字频率和至少出现 20 次的二字组合，写成带拼音的词表 `/data/52hz-eval/build/benchmark/lexicon.jsonl`（约 45 万条，1 分钟）。benchmark 本身不使用它。它是为“追问”课题准备的：解码器要判断按键的另一处读法是不是一个真词，需要一份词表；让模型自己列举会编出不存在的词。

改了 staging 的切分规则时可以只重建一个来源，其余目录不动：

```sh
make staging SOURCE=thucnews
```

THUCNews 的记录是按句切出来的。之前的切分把句号和它后面的收尾引号分到了两条记录，产生 `”不知比尔。` 这样的开头；现在收尾引号跟随它闭合的那一句，需要用上面的命令重建一次 thucnews。

## 后续阶段

当前 workflow 只负责原始语料到干净基础句的可复现处理。拼音生成、漏键/邻键/交换/截断等噪声变体，以及 `preview`、`commit`、`ask` 交互标签，放在下一层 generator 中，输入应是这里输出的统一 JSONL，而不是重新读取各个来源的原始格式。

运行离线测试：

```sh
make test
```

## 状态

项目处于评测集和噪声数据生成器设计阶段。
