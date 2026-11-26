"""Count characters and character pairs in a benchmark's accepted clauses and write them as a word list.

The list is what a decoder needs to tell a real word from an invented spelling when it checks whether
another reading of the keys is worth asking about. Single characters are written too, so that a sentence
can be cut into words by frequency. Clauses that are in the benchmark itself are left out.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from tools.corpus_workflow import write_json, write_jsonl
from tools.pinyin_cases import convert


LEXICON_VERSION = "0.1.0"
RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
DEFAULT_MIN_COUNT = 20


def counts(rows, exclude=frozenset()):
    """Count characters and character pairs inside Chinese text; nothing is counted across punctuation."""
    chars, pairs = Counter(), Counter()
    for text in rows:
        if text in exclude:
            continue
        for run in RUN.findall(text):
            chars.update(run)
            pairs.update(run[index:index + 2] for index in range(len(run) - 1))
    return chars, pairs


def build(benchmark_dir, output, min_count=DEFAULT_MIN_COUNT):
    benchmark_dir = Path(benchmark_dir)
    base = {json.loads(line)["text"] for line in (benchmark_dir / "base.jsonl").open(encoding="utf-8")}
    rows = (json.loads(line)[0] for path in sorted((benchmark_dir / "shards").glob("*-*.jsonl"))
            if not path.name.endswith(".rejected.jsonl") for line in path.open(encoding="utf-8"))
    chars, pairs = counts(rows, base)
    words = [{"word": char, "count": count} for char, count in chars.most_common() if count >= min_count]
    for pair, count in pairs.most_common():
        if count < min_count:
            break
        keys, segments = convert(pair)
        if len(segments) == 1 and segments[0]["kind"] == "zh":
            words.append({"word": pair, "keys": keys, "count": count})
    write_jsonl(output, words)
    manifest = {"lexicon_version": LEXICON_VERSION, "benchmark_dir": str(benchmark_dir), "output": str(output),
                "min_count": min_count, "characters": sum(1 for row in words if len(row["word"]) == 1),
                "pairs": sum(1 for row in words if len(row["word"]) == 2),
                "distinct_pairs": len(pairs), "excluded_clauses": len(base)}
    write_json(Path(output).with_suffix(".manifest.json"), manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", required=True, type=Path, help="make benchmark 的输出目录，读取其中的 shards/ 和 base.jsonl")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT, help="字组至少出现多少次才进入词表（默认 20）")
    args = parser.parse_args(argv)
    try:
        manifest = build(args.benchmark_dir, args.output, args.min_count)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps({key: manifest[key] for key in ("characters", "pairs", "min_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
