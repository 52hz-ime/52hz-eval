"""Sample staging records and produce inspectable quality-filter outputs."""

import argparse
import json
import random
import sys
from pathlib import Path

from tools.corpus_workflow import expand_jsonl_inputs, read_jsonl, write_json, write_jsonl
from tools.pinyin_cases import split_sentences
from tools.quality_filter import FILTER_VERSION, filter_rows


def iter_quality_rows(inputs):
    for path in expand_jsonl_inputs(inputs):
        for row in read_jsonl(path):
            text = row.get("text", "")
            if len(text) <= 160:
                yield row
                continue
            parts = split_sentences(text, 160)
            if len(parts) <= 1:
                yield row
                continue
            previous = []
            for index, part in enumerate(parts):
                context = "\n".join(item for item in [row.get("context", ""), *previous[-2:]] if item)
                yield {**row, "id": f"{row['id']}~quality-seg-{index:03d}",
                       "source_record_id": f"{row.get('source_record_id', row['id'])}:quality-seg-{index}",
                       "text": part, "context": context}
                previous.append(part)


def sample_pool(inputs, output, count, seed):
    import random
    reservoir = []
    rng = random.Random(seed)
    candidates = 0
    for row in iter_quality_rows(inputs):
        candidates += 1
        if len(reservoir) < count:
            reservoir.append(row)
        else:
            position = rng.randrange(candidates)
            if position < count:
                reservoir[position] = row
    rng.shuffle(reservoir)
    rows = [{**row, "split": "quality-sample"} for row in reservoir]
    write_jsonl(output, rows)
    return rows


def run(inputs, output_dir, sizes, seed):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    maximum = max(sizes)
    max_path = output_dir / f"sample-{maximum}.jsonl"
    pool = sample_pool(inputs, max_path, maximum, seed)
    summary = {"filter_version": FILTER_VERSION, "seed": seed, "sizes": sizes, "inputs": [str(path) for path in inputs],
               "outputs": {}}
    for size in sorted(sizes):
        rows = pool if size == maximum else random.Random(seed + size).sample(pool, size)
        sample_path = output_dir / f"sample-{size}.jsonl"
        if size != maximum:
            write_jsonl(sample_path, rows)
        accepted_path = output_dir / f"sample-{size}.accepted.jsonl"
        review_path = output_dir / f"sample-{size}.review.jsonl"
        rejected_path = output_dir / f"sample-{size}.rejected.jsonl"
        filter_out_path = output_dir / f"sample-{size}.filter-out.jsonl"
        with accepted_path.open("w", encoding="utf-8") as accepted, review_path.open("w", encoding="utf-8") as review, \
                rejected_path.open("w", encoding="utf-8") as rejected, filter_out_path.open("w", encoding="utf-8") as filter_out:
            report = filter_rows(rows, accepted, review, rejected, filter_out)
        report.update({"sample": size, "sample_path": str(sample_path), "accepted_path": str(accepted_path),
                       "review_path": str(review_path), "rejected_path": str(rejected_path),
                       "filter_out_path": str(filter_out_path)})
        write_json(output_dir / f"sample-{size}.manifest.json", report)
        summary["outputs"][str(size)] = report
        if size != maximum:
            del rows
    del pool
    write_json(output_dir / "manifest.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sizes", default="10000,100000,1000000")
    parser.add_argument("--seed", type=int, default=52)
    args = parser.parse_args(argv)
    sizes = sorted({int(value) for value in args.sizes.split(",") if value.strip()})
    if not sizes or sizes[0] < 1:
        parser.error("sizes must contain positive integers")
    try:
        summary = run(args.input, args.output_dir, sizes, args.seed)
        print(json.dumps({"output_dir": str(args.output_dir), "sizes": summary["sizes"]}, ensure_ascii=False))
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
