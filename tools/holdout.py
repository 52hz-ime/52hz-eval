"""Draw a second stratified set that shares no case with the first, to check on it what was tuned on the first.

The draw is the same round-robin over every source and operation cell as the trial set, over the cases the
first set left out.
"""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from tools.corpus_workflow import read_jsonl, write_jsonl
from tools.ime_benchmark import operation_of, trial_cases


def draw_holdout(cases, excluded, size, rng):
    """`size` cases from `cases`, none of them among `excluded` ids, covering every source x operation cell in turn."""
    left_out = set(excluded)
    return trial_cases([row for row in cases if row["id"] not in left_out], size, rng)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="make benchmark 生成的 cases.jsonl")
    parser.add_argument("--exclude", type=Path, nargs="*", default=[], help="已经用过的集合，新集合与它们没有一条相同")
    parser.add_argument("--size", type=int, required=True)
    parser.add_argument("--seed", type=int, default=110011)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    cases = list(read_jsonl(args.cases))
    excluded = {row["id"] for path in args.exclude for row in read_jsonl(path)}
    picked = draw_holdout(cases, excluded, args.size, random.Random(args.seed))
    if len(picked) < args.size:
        parser.exit(2, f"excluding {len(excluded)} cases leaves too few to draw {args.size}: got {len(picked)}\n")
    write_jsonl(args.output, picked)
    print(json.dumps({"output": str(args.output), "cases": len(picked), "excluded": len(excluded), "seed": args.seed,
                      "by_source": dict(sorted(Counter(row["source_id"] for row in picked).items())),
                      "by_operation": dict(sorted(Counter(operation_of(row) for row in picked).items()))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
