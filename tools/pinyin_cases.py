"""Convert clean Chinese records to pinyin and generate deterministic noise cases."""

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

from tools.corpus_workflow import CJK, EXTRACTOR_VERSION, normalize, read_jsonl, write_json, write_jsonl


GENERATOR_VERSION = "0.1.0"
REVIEW_POLICIES = {"manual_review", "mixed_review"}
SENTENCE_END = set("。！？!?；;…")
CLOSERS = set("”’\"'》」』）)]】〕〉")
PYTHON_IMPORT_ERROR = "pypinyin is required; install requirements.txt first"


def pinyin_for_run(text):
    try:
        from pypinyin import Style, pinyin
    except ImportError as error:
        raise RuntimeError(PYTHON_IMPORT_ERROR) from error
    return [item[0] for item in pinyin(text, style=Style.NORMAL, heteronym=False, errors="keep")]


def split_sentences(text, max_chars=120):
    """Split at sentence punctuation, then conservatively chunk overlong segments."""
    chunks = []
    current = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\n":
            if current:
                chunks.append("".join(current).strip())
                current = []
            index += 1
            continue
        current.append(char)
        if char in SENTENCE_END:
            index += 1
            while index < len(text) and text[index] in SENTENCE_END:
                current.append(text[index])
                index += 1
            while index < len(text) and text[index] in CLOSERS:
                current.append(text[index])
                index += 1
            chunks.append("".join(current).strip())
            current = []
            continue
        index += 1
    if current:
        chunks.append("".join(current).strip())
    result = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            if chunk:
                result.append(chunk)
            continue
        start = 0
        while start < len(chunk):
            end = min(start + max_chars, len(chunk))
            if end < len(chunk):
                boundary = max(chunk.rfind(mark, start + 1, end) for mark in "，,、：: ")
                if boundary > start:
                    end = boundary + 1
            part = chunk[start:end].strip()
            if part:
                result.append(part)
            start = end
    return result


def segmented_records(rows, min_chars=4, max_chars=120):
    for row in rows:
        text = normalize(row.get("text", ""))
        if not text:
            continue
        pieces = split_sentences(text, max_chars)
        previous = []
        for index, piece in enumerate(pieces):
            if len(piece) < min_chars or not CJK.search(piece):
                previous.append(piece)
                continue
            context_parts = [normalize(row.get("context", "")), *previous[-2:]]
            context = "\n".join(item for item in context_parts if item)
            group_id = row.get("group_id", row.get("id", ""))
            yield {
                **row,
                "id": f"{row.get('id', 'row')}~seg-{index:03d}",
                "group_id": group_id,
                "text": piece,
                "context": context,
                "segment_index": index,
                "segmenter_version": GENERATOR_VERSION,
            }
            previous.append(piece)


def convert(text):
    """Return keys and spans while preserving non-Chinese literals byte-for-character."""
    segments = []
    index = 0
    while index < len(text):
        is_chinese = bool(CJK.match(text[index]))
        end = index + 1
        while end < len(text) and bool(CJK.match(text[end])) == is_chinese:
            end += 1
        piece = text[index:end]
        if is_chinese:
            syllables = pinyin_for_run(piece)
            segments.append({"text": piece, "keys": "".join(syllables), "kind": "zh", "syllables": syllables})
        else:
            segments.append({"text": piece, "keys": piece, "kind": "literal"})
        index = end
    return "".join(segment["keys"] for segment in segments), segments


def pinyin_records(rows, min_chars=4, max_chars=120, limit=None):
    count = 0
    for row in segmented_records(rows, min_chars, max_chars):
        keys, segments = convert(row["text"])
        if not any(segment["kind"] == "zh" for segment in segments):
            continue
        yield {**row, "keys": keys, "pinyin_segments": segments, "pinyin_version": GENERATOR_VERSION}
        count += 1
        if limit and count >= limit:
            return


def editable_layout(record):
    keys = record["keys"]
    positions = []
    syllables = []
    offset = 0
    for segment_index, segment in enumerate(record["pinyin_segments"]):
        length = len(segment["keys"])
        if segment["kind"] == "zh":
            positions.extend(range(offset, offset + length))
            for syllable_index, syllable in enumerate(segment["syllables"]):
                start = offset + sum(len(item) for item in segment["syllables"][:syllable_index])
                syllables.append((start, start + len(syllable), segment_index, syllable_index))
        offset += length
    return keys, positions, syllables


QWERTY = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


def neighbor(char):
    for row in QWERTY:
        if char in row:
            index = row.index(char)
            choices = [row[pos] for pos in (index - 1, index + 1) if 0 <= pos < len(row)]
            return choices
    return []


def remove_positions(value, positions):
    removed = set(positions)
    return "".join(char for index, char in enumerate(value) if index not in removed)


def mutate(record, operation, rng):
    keys, editable, syllables = editable_layout(record)
    if not editable:
        return None
    if operation == "drop":
        position = rng.choice(editable)
        return keys[:position] + keys[position + 1:], {"type": operation, "position": position, "from": keys[position]}
    if operation == "duplicate":
        position = rng.choice(editable)
        return keys[:position + 1] + keys[position:], {"type": operation, "position": position, "value": keys[position]}
    if operation == "insert":
        position = rng.choice(editable)
        value = rng.choice(neighbor(keys[position]) or [keys[position]])
        return keys[:position] + value + keys[position:], {"type": operation, "position": position, "value": value}
    if operation == "neighbor":
        choices = [(position, neighbor(keys[position])) for position in editable if neighbor(keys[position])]
        if not choices:
            return None
        position, values = rng.choice(choices)
        value = rng.choice(values)
        return keys[:position] + value + keys[position + 1:], {"type": operation, "position": position,
                                                                 "from": keys[position], "to": value}
    if operation == "swap":
        choices = [position for position in editable if position + 1 in editable]
        if not choices:
            return None
        position = rng.choice(choices)
        value = keys[:position] + keys[position + 1] + keys[position] + keys[position + 2:]
        return value, {"type": operation, "position": position}
    if operation == "syllable_swap":
        choices = [(left, right) for left, right in zip(syllables, syllables[1:])
                   if left[2] == right[2] and left[3] + 1 == right[3]]
        if not choices:
            return None
        left, right = rng.choice(choices)
        value = keys[:left[0]] + keys[right[0]:right[1]] + keys[left[0]:left[1]] + keys[right[1]:]
        return value, {"type": operation, "left": left[3], "right": right[3]}
    if operation in ("truncate_prefix", "truncate_suffix", "truncate_middle"):
        if operation == "truncate_prefix":
            position = editable[0]
            removed = [position]
        elif operation == "truncate_suffix":
            position = editable[-1]
            removed = [position]
        else:
            position = rng.choice(editable)
            removed = [position]
        return remove_positions(keys, removed), {"type": operation, "positions": removed}
    raise ValueError(f"unknown noise operation: {operation}")


def stable_seed(seed, record_id, operation):
    digest = hashlib.sha256(f"{seed}\0{record_id}\0{operation}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def noise_cases(rows, operations, seed=52, limit=None, include_review=False):
    count = 0
    for row in rows:
        if row.get("quality_policy") in REVIEW_POLICIES and not include_review:
            continue
        base = {**row, "base_id": row["id"], "clean_keys": row["keys"], "event": "space",
                "expected": {"action": "commit", "text": row["text"]}, "noise_ops": []}
        for operation in operations:
            if operation == "clean":
                case = {**base, "id": f"{row['id']}~clean"}
            else:
                result = mutate(row, operation, random.Random(stable_seed(seed, row["id"], operation)))
                if result is None:
                    continue
                keys, noise = result
                case = {**base, "id": f"{row['id']}~{operation}", "keys": keys, "noise_ops": [noise]}
            yield case
            count += 1
            if limit and count >= limit:
                return


def write_pinyin(input_path, output_path, min_chars, max_chars, limit, manifest):
    rows = pinyin_records(read_jsonl(input_path), min_chars, max_chars, limit)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    if manifest:
        write_json(manifest, {"operation": "pinyin", "input": str(input_path), "output": str(output_path),
                              "records": count, "generator_version": GENERATOR_VERSION,
                              "extractor_version": EXTRACTOR_VERSION})
    return count


def write_noise(input_path, output_path, operations, seed, limit, manifest, include_review=False):
    rows = noise_cases(read_jsonl(input_path), operations, seed, limit, include_review)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            counts[row["id"].rsplit("~", 1)[-1]] += 1
    if manifest:
        write_json(manifest, {"operation": "noise", "input": str(input_path), "output": str(output_path),
                              "operations": operations, "seed": seed, "records": sum(counts.values()),
                              "by_operation": dict(sorted(counts.items())), "include_review": include_review,
                              "generator_version": GENERATOR_VERSION})
    return sum(counts.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pinyin = commands.add_parser("pinyin", help="segment clean records and convert to pinyin")
    pinyin.add_argument("--input", required=True, type=Path)
    pinyin.add_argument("--output", required=True, type=Path)
    pinyin.add_argument("--min-chars", type=int, default=4)
    pinyin.add_argument("--max-chars", type=int, default=120)
    pinyin.add_argument("--limit", type=int)
    pinyin.add_argument("--manifest", type=Path)
    noise = commands.add_parser("noise", help="generate deterministic IME noise cases")
    noise.add_argument("--input", required=True, type=Path)
    noise.add_argument("--output", required=True, type=Path)
    noise.add_argument("--operations", default="clean,drop,duplicate,insert,neighbor,swap,syllable_swap,truncate_prefix,truncate_suffix")
    noise.add_argument("--seed", type=int, default=52)
    noise.add_argument("--limit", type=int)
    noise.add_argument("--manifest", type=Path)
    noise.add_argument("--include-review", action="store_true",
                       help="include manual_review and mixed_review records for exploratory output")
    args = parser.parse_args(argv)
    try:
        if args.command == "pinyin":
            count = write_pinyin(args.input, args.output, args.min_chars, args.max_chars, args.limit, args.manifest)
        else:
            operations = [item.strip() for item in args.operations.split(",") if item.strip()]
            count = write_noise(args.input, args.output, operations, args.seed, args.limit, args.manifest,
                                args.include_review)
        print(json.dumps({"output": str(args.output), "records": count}, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
