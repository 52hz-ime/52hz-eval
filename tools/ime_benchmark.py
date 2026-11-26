"""Build the clause-level, source-uniform IME benchmark from the staging tree.

Each staging record is cut at commas and sentence marks, every clause is cleaned by the quality
filter, and the same number of clauses is drawn from every source with a bell-shaped length mix.
"""

import argparse
import heapq
import inspect
import json
import math
import os
import random
import re
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

from tools.benchmark_pipeline import canonical_digest, digest_file, input_signature
from tools.corpus_workflow import EXTRACTOR_VERSION, expand_jsonl_inputs, load_index, read_jsonl, stable_id, write_json, write_jsonl
from tools.pinyin_cases import GENERATOR_VERSION, convert, noise_cases
from tools import quality_filter
from tools.quality_filter import FILTER_VERSION, classify


BENCHMARK_VERSION = "0.1.0"
# Losing the very first keystroke and swapping two whole syllables are rare in daily typing, so neither is a benchmark operation.
OPERATIONS = ["clean", "drop", "duplicate", "insert", "neighbor", "swap", "truncate_suffix"]
CLOSER_TEXT = "”’）》」』〕】〉"
BOUNDARY = re.compile(rf"([，。！？；…]+[{CLOSER_TEXT}]*|(?<=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])[,;!?]+[{CLOSER_TEXT}]*)")
CLAUSE_MARK = re.compile(r"[，。！？；…]")
REVIEW_POLICIES = {"manual_review", "mixed_review"}


def split_units(text):
    """Split at commas and sentence marks; each mark stays with the clause it ends."""
    parts = BOUNDARY.split(text)
    units = [parts[index] + parts[index + 1] for index in range(0, len(parts) - 1, 2) if parts[index].strip()]
    units.append(parts[-1])
    return [unit.strip() for unit in units if unit.strip()]


def tail(text, limit):
    """Keep the end of a preceding clause, cut at a clause mark when one is near the front."""
    if len(text) <= limit:
        return text
    piece = text[-limit:]
    mark = CLAUSE_MARK.search(piece, 0, limit // 2)
    return piece[mark.end():] if mark else piece


def part_number(record_id):
    return int(record_id.rsplit(":part-", 1)[1]) if ":part-" in record_id else None


def follows(previous, row):
    """Tell whether two consecutive sentence records belong to the same document."""
    number, before = part_number(row["source_record_id"]), part_number(previous["source_record_id"])
    return (number is not None and before is not None and number == before + 1
            and previous.get("group_id") == row.get("group_id"))


def operation_of(case):
    return case["noise_ops"][0]["type"] if case["noise_ops"] else "clean"


def scan_file(path, min_chars, max_chars, shards, context_chars, rejected_rate, seed):
    """Return the accepted units of one staging file that fall into the sampled hash shard."""
    kept, rejected, flags = [], [], Counter()
    sampler = random.Random(f"{seed}\0{path}")
    previous = None
    for row in read_jsonl(path):
        before = tail(previous["text"], context_chars) if previous is not None and follows(previous, row) else ""
        context = tail((row.get("context") or "").split("\n")[-1], context_chars)
        for index, unit in enumerate(split_units(row["text"])):
            if not min_chars <= len(unit) <= max_chars:
                flags["too_short" if len(unit) < min_chars else "too_long"] += 1
                continue
            quality = classify({"text": unit}, min_chars, max_chars)
            if quality["status"] != "accepted":
                flags.update(quality["flags"])
                if sampler.random() < rejected_rate:
                    rejected.append({"text": unit, "source_id": row.get("source_id"), "quality": quality})
                continue
            if zlib.crc32(unit.encode("utf-8")) % shards == 0:
                kept.append((unit, "\n".join(part for part in (context, before) if part), row["source_record_id"], index))
            before = tail(unit, context_chars)
        previous = row
    return kept, rejected, flags


def estimate_shards(files, records, min_chars, max_chars, shard_size):
    """Pick one hash shard of the accepted units so the parent keeps roughly shard_size rows."""
    seen = accepted = 0
    for row in read_jsonl(files[0]):
        seen += 1
        accepted += sum(classify({"text": unit}, min_chars, max_chars)["status"] == "accepted"
                        for unit in split_units(row["text"]))
        if seen >= 20000:
            break
    if not seen or not records:
        return 1
    return max(1, round(accepted / seen * records / shard_size))


def scan_rules():
    """The part of this module that decides what a scan keeps; unrelated edits must not invalidate the cache."""
    return {"boundary": BOUNDARY.pattern, **{name: inspect.getsource(globals()[name])
                                             for name in ("split_units", "tail", "follows", "scan_file")}}


def scan(staging, source, rules, cache_dir, seed, workers):
    """Scan one source in parallel, or reuse the shard files written for the same staging, rules and shard."""
    directory = Path(staging) / source
    files = expand_jsonl_inputs([directory])
    if not files:
        raise ValueError(f"来源 {source} 的 staging 目录里没有 part-*.jsonl：{directory}")
    manifest_path = Path(staging) / f"{source}.manifest.json"
    records = json.loads(manifest_path.read_text(encoding="utf-8")).get("records", 0) if manifest_path.is_file() else 0
    shards = estimate_shards(files, records, rules["min_chars"], rules["max_chars"], rules["shard_size"])
    # The filter source and the scanning functions are part of the key, so a rule change never reuses a stale shard.
    key = canonical_digest({"source": source, "staging": input_signature(directory), "filter": FILTER_VERSION,
                            "filter_source": digest_file(quality_filter.__file__), "scan_rules": scan_rules(),
                            "rules": rules, "shards": shards})[:12]
    info = {"shards": shards, "files": len(files), "records": records, "cache": f"{source}-{key}"}
    stem = Path(cache_dir) / info["cache"]
    if stem.with_suffix(".jsonl").is_file():
        rows = [json.loads(line) for line in stem.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
        flags = Counter(json.loads(stem.with_suffix(".flags.json").read_text(encoding="utf-8"))) if stem.with_suffix(".flags.json").is_file() else Counter()
        print(f"[{source}] 复用已扫描的 1/{shards} 哈希分片：{len(rows)} 条通过清洗的子句", flush=True)
        return rows, flags, info
    task = partial(scan_file, min_chars=rules["min_chars"], max_chars=rules["max_chars"], shards=shards,
                   context_chars=rules["context_chars"], rejected_rate=rules["rejected_rate"], seed=seed)
    rows, rejected, flags = [], [], Counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for kept, dropped, counts in pool.map(task, files, chunksize=1):
            rows.extend(kept)
            rejected.extend(dropped)
            flags.update(counts)
    stem.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(stem.with_suffix(".jsonl"), rows)
    write_jsonl(stem.with_suffix(".rejected.jsonl"), rejected)
    write_json(stem.with_suffix(".flags.json"), dict(sorted(flags.items())))
    print(f"[{source}] 扫描 {len(files)} 个分片，1/{shards} 哈希分片内有 {len(rows)} 条通过清洗的子句", flush=True)
    return rows, flags, info


def draw(rows, count, length, reservoir, rng):
    """Reservoir-sample the shard uniformly, then reweight the pool towards the target length curve."""
    seen, pool = set(), []
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        item = (rng.random(), len(pool), row)
        if len(pool) < reservoir:
            heapq.heappush(pool, item)
        elif item[0] > pool[0][0]:
            heapq.heapreplace(pool, item)
    natural = Counter(len(row[0]) for _, _, row in pool)
    # Weighted draw without replacement: each pool row is kept in proportion to target length share over natural share.
    target = {size: math.exp(-0.5 * ((size - length["mean"]) / length["sd"]) ** 2) for size in natural}
    ranked = sorted((-rng.random() ** (natural[len(row[0])] / target[len(row[0])]), order, row) for _, order, row in pool)
    return [row for _, _, row in ranked[:count]], {"distinct": len(seen), "pool": len(pool), "natural": dict(sorted(natural.items()))}


def trial_cases(cases, size, rng):
    """Draw cases round-robin over every source and operation cell so no cell is left out."""
    cells = defaultdict(list)
    for case in cases:
        cells[(case["source_id"], operation_of(case))].append(case)
    queues = {cell: rng.sample(rows, len(rows)) for cell, rows in sorted(cells.items())}
    picked, cells = [], sorted(queues)
    while len(picked) < size and any(queues.values()):
        # Whole rounds cover every cell; a partial last round picks its cells at random so no source is favoured.
        round_cells = cells if size - len(picked) >= len(cells) else rng.sample(cells, size - len(picked))
        for cell in round_cells:
            if queues[cell] and len(picked) < size:
                picked.append(queues[cell].pop())
    return picked


def length_stats(sizes):
    mean = sum(sizes) / len(sizes)
    return {"length_mean": round(mean, 2), "length_sd": round(math.sqrt(sum((size - mean) ** 2 for size in sizes) / len(sizes)), 2),
            "length_max": max(sizes), "lengths": dict(sorted(Counter(sizes).items()))}


def build(staging, sources_file, output_dir, sources, per_source, operations, seed, include_review, min_chars, max_chars,
          length, trial, workers, shard_size, context_chars, show=0, rejected_rate=0.001):
    staging, output_dir = Path(staging), Path(output_dir)
    index = load_index(sources_file)
    sources = sources or sorted(item.name for item in staging.iterdir() if item.is_dir() and list(item.glob("part-*.jsonl")))
    unknown = [name for name in sources if name not in index]
    if unknown:
        raise ValueError("来源索引里没有这些来源：" + ", ".join(unknown))
    waiting = [name for name in sources if index[name].get("quality_policy") in REVIEW_POLICIES]
    if waiting and not include_review:
        raise ValueError("这些来源还在待审核池里，加上 --include-review 才会均匀采样：" + ", ".join(waiting))
    output_dir.mkdir(parents=True, exist_ok=True)
    rules = {"min_chars": min_chars, "max_chars": max_chars, "shard_size": shard_size, "context_chars": context_chars,
             "rejected_rate": rejected_rate}
    rng = random.Random(seed)
    base, report, flags = [], {}, Counter()
    for source in sources:
        rows, counts, info = scan(staging, source, rules, output_dir / "shards", seed, workers)
        flags.update(counts)
        chosen, stats = draw(rows, per_source, length, max(20 * per_source, 5000), rng)
        if len(chosen) < per_source:
            raise ValueError(f"来源 {source} 只能抽出 {len(chosen)} 条，不足 {per_source}；调小 --per-source 或 --min-chars")
        spec = index[source]
        for unit, context, record_id, position in chosen:
            base.append({"id": stable_id(source, f"{record_id}:unit-{position}", unit), "source_id": source,
                         "source_record_id": record_id, "text": unit, "context": context,
                         "source_url": spec.get("url", ""), "source_script": spec.get("script", "unknown"),
                         "quality_policy": spec.get("quality_policy", "manual_review"),
                         "quality": classify({"text": unit}, min_chars, max_chars), "split": "benchmark",
                         "unit_index": position, "extractor_version": EXTRACTOR_VERSION, "segmenter_version": BENCHMARK_VERSION})
        info.update({"quality_policy": spec.get("quality_policy"), "selected": len(chosen), **length_stats([len(row[0]) for row in chosen]), **stats})
        report[source] = info
    keyed = []
    for row in base:
        keys, segments = convert(row["text"])
        if any(segment["kind"] == "zh" for segment in segments):
            keyed.append({**row, "keys": keys, "pinyin_segments": segments, "pinyin_version": GENERATOR_VERSION})
    cases = list(noise_cases(keyed, operations, seed, include_review=True))
    rng.shuffle(cases)
    write_jsonl(output_dir / "base.jsonl", keyed)
    write_jsonl(output_dir / "cases.jsonl", cases)
    manifest = {"benchmark_version": BENCHMARK_VERSION, "filter_version": FILTER_VERSION, "generator_version": GENERATOR_VERSION,
                "seed": seed, "include_review": include_review, "sources": sources, "operations": operations,
                "min_chars": min_chars, "max_chars": max_chars, "length_target": length,
                "context_chars": context_chars, "per_source": per_source,
                "base": len(keyed), "cases": len(cases), **length_stats([len(row["text"]) for row in keyed]),
                "by_source": dict(sorted(Counter(row["source_id"] for row in cases).items())),
                "by_operation": dict(sorted(Counter(operation_of(row) for row in cases).items())),
                "rejected_flags": dict(sorted(flags.items())), "by_source_detail": report}
    if trial:
        picked = trial_cases(cases, trial, rng)
        write_jsonl(output_dir / f"trial-{trial}.jsonl", picked)
        manifest["trial"] = {"file": f"trial-{trial}.jsonl", "cases": len(picked),
                             "by_source": dict(sorted(Counter(row["source_id"] for row in picked).items())),
                             "by_operation": dict(sorted(Counter(operation_of(row) for row in picked).items())),
                             **length_stats([len(row["text"]) for row in picked])}
    write_json(output_dir / "manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("base", "cases", "length_mean", "length_sd", "length_max", "by_source", "by_operation")},
                     ensure_ascii=False), flush=True)
    for row in random.Random(seed).sample(keyed, min(show, len(keyed))) if show else []:
        print(f"  {row['source_id']:18s} {row['text']}", flush=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--staging", required=True, type=Path)
    parser.add_argument("--sources-file", default="data/sources.json", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--sources", help="逗号分隔的 staging 来源；默认是 staging 目录下全部来源")
    parser.add_argument("--per-source", type=int, default=1000, help="每个来源抽多少条基础子句（默认 1000，各来源等量）")
    parser.add_argument("--operations", default=",".join(OPERATIONS))
    parser.add_argument("--seed", type=int, default=52)
    parser.add_argument("--include-review", action="store_true",
                        help="把 manual_review / mixed_review 来源也纳入采样；不加时遇到这些来源会报错")
    parser.add_argument("--min-chars", type=int, default=4)
    parser.add_argument("--max-chars", type=int, default=30)
    parser.add_argument("--length-mean", type=float, default=12.0, help="目标长度分布的均值")
    parser.add_argument("--length-sd", type=float, default=5.0, help="目标长度分布的标准差")
    parser.add_argument("--trial", type=int, default=0, help="另抽一份按来源×操作分层的小集，写成 trial-<N>.jsonl")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--shard-size", type=int, default=1500000, help="每个来源先按哈希抽一个分片再做采样，这是分片的目标条数")
    parser.add_argument("--context-chars", type=int, default=60, help="上文保留的字符数上限")
    parser.add_argument("--show", type=int, default=0, help="随机打印多少条基础子句供人工抽查")
    args = parser.parse_args(argv)
    sources = [item.strip() for item in args.sources.split(",") if item.strip()] if args.sources else None
    operations = [item.strip() for item in args.operations.split(",") if item.strip()]
    try:
        build(args.staging, args.sources_file, args.output_dir, sources, args.per_source, operations, args.seed, args.include_review,
              args.min_chars, args.max_chars, {"mean": args.length_mean, "sd": args.length_sd}, args.trial, args.workers,
              args.shard_size, args.context_chars, args.show)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
