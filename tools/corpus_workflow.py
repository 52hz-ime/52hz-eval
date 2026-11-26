"""Extract, normalize, deduplicate, sample, and report corpus records."""

import argparse
import gzip
import hashlib
import json
import random
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path


EXTRACTOR_VERSION = "0.1.0"
STAGING_SCHEMA = "staging.v1"
DEFAULT_CHUNK_BYTES = 64 * 1024 * 1024
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]")
SPACE = re.compile(r"\s+")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;…])(?=[^。！？!?；;…])|[\r\n]+")


def load_index(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sources"), list):
        raise ValueError("source index must contain a sources array")
    index = {}
    for source in payload["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise ValueError("every source must have a string id")
        if source["id"] in index:
            raise ValueError(f"duplicate source id: {source['id']}")
        index[source["id"]] = source
    return index


def source(index, source_id):
    try:
        return index[source_id]
    except KeyError as error:
        raise ValueError(f"unknown source: {source_id}") from error


def normalize(value, join_tokens=False):
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = unicodedata.normalize("NFC", value)
    value = CONTROL.sub("", value)
    value = SPACE.sub(" ", value).strip()
    return value.replace(" ", "") if join_tokens else value


def get_path(value, path):
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def flatten(value):
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(flatten(item))
        return values
    return [value]


def first_field(row, fields):
    values = []
    for path in fields:
        value = get_path(row, path)
        values.extend(item for item in flatten(value) if item not in (None, ""))
    return values


def join_field(row, fields, join_tokens=False):
    values = []
    for value in first_field(row, fields):
        text = normalize(value, join_tokens)
        if text:
            values.append(text)
    return "\n".join(values)


def split_units(value, mode=""):
    if mode != "sentences":
        return [value]
    return [part.strip() for part in SENTENCE_SPLIT.split(value) if part.strip()]


def iter_input(path, fmt):
    path = Path(path)
    files = sorted(item for item in path.rglob("*") if item.is_file() and not item.name.startswith(".") and
                   not item.name.endswith(".part")) if path.is_dir() else [path]
    for input_file in files:
        if fmt == "json":
            try:
                with open_text(input_file) as handle:
                    payload = json.load(handle)
            except json.JSONDecodeError as error:
                raise ValueError(f"{input_file}: invalid JSON: {error.msg}") from error
            if isinstance(payload, list):
                for number, row in enumerate(payload, 1):
                    yield f"{input_file.name}:{number}", row
            elif isinstance(payload, dict) and any(isinstance(value, list) for value in payload.values()):
                for split, rows in payload.items():
                    if not isinstance(rows, list):
                        continue
                    for number, row in enumerate(rows, 1):
                        yield f"{input_file.name}:{split}:{number}", row
            else:
                yield input_file.name, payload
            continue
        with open_text(input_file) as handle:
            for number, line in enumerate(handle, 1):
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                location = f"{input_file.name}:{number}"
                if fmt == "jsonl":
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise ValueError(f"{input_file}:{number}: invalid JSON: {error.msg}") from error
                    yield location, row
                else:
                    yield location, line


def open_text(path):
    return gzip.open(path, "rt", encoding="utf-8") if Path(path).suffix == ".gz" else Path(path).open(encoding="utf-8")


def stable_id(source_id, source_record_id, text):
    digest = hashlib.sha256(f"{source_id}\0{source_record_id}\0{text}".encode()).hexdigest()[:16]
    return f"{source_id}:{digest}"


def make_record(source_spec, source_record_id, text, context):
    return {
        "schema_version": STAGING_SCHEMA,
        "id": stable_id(source_spec["id"], source_record_id, text),
        "source_id": source_spec["id"],
        "source_record_id": source_record_id,
        "group_id": source_record_id.split(":turn-", 1)[0].split(":part-", 1)[0],
        "text": text,
        "context": context,
        "source_url": source_spec.get("url", ""),
        "source_script": source_spec.get("script", "unknown"),
        "quality_policy": source_spec.get("quality_policy", "manual_review"),
        "extractor_version": EXTRACTOR_VERSION,
    }


def turn_candidates(row, source_spec, location):
    if isinstance(row, str):
        yield normalize(row, source_spec.get("join_tokens", False)), "", location
        return
    turns_field = source_spec.get("turns_field")
    turns = row if isinstance(row, list) else get_path(row, turns_field) if turns_field else None
    if isinstance(turns, list):
        base_ids = first_field(row, source_spec.get("id_fields", [])) if isinstance(row, dict) else []
        base_id = normalize(base_ids[0]) if base_ids else location
        previous = []
        for index, turn in enumerate(turns):
            if isinstance(turn, dict):
                fields = source_spec.get("turn_text_fields", source_spec.get("text_fields", []))
                values = first_field(turn, fields)
                text = normalize(values[0], source_spec.get("join_tokens", False)) if values else ""
            else:
                text = normalize(turn, source_spec.get("join_tokens", False))
            if text:
                yield text, "\n".join(previous), f"{base_id}:turn-{index}"
                previous.append(text)
        return
    if not isinstance(row, dict):
        return
    values = first_field(row, source_spec.get("text_fields", []))
    text = normalize(values[0], source_spec.get("join_tokens", False)) if values else ""
    context = join_field(row, source_spec.get("context_fields", []), source_spec.get("join_tokens", False))
    ids = first_field(row, source_spec.get("id_fields", []))
    base_id = normalize(ids[0]) if ids else location
    for index, part in enumerate(split_units(text, source_spec.get("split", ""))):
        source_record_id = base_id if index == 0 and len(split_units(text, source_spec.get("split", ""))) == 1 else f"{base_id}:part-{index}"
        yield part, context, source_record_id


def extract(source_spec, input_path, output_path, min_chars=4, max_chars=240, limit=None, manifest_path=None):
    fmt = source_spec.get("format", "text")
    seen = set()
    records = []
    for location, row in iter_input(input_path, fmt):
        for text, context, source_record_id in turn_candidates(row, source_spec, location):
            if not min_chars <= len(text) <= max_chars or not CJK.search(text):
                continue
            key = normalize(text)
            if key in seen:
                continue
            seen.add(key)
            records.append(make_record(source_spec, source_record_id, text, context))
            if limit and len(records) >= limit:
                break
        if limit and len(records) >= limit:
            break
    write_jsonl(output_path, records)
    if manifest_path:
        write_json(manifest_path, {
            "workflow_version": EXTRACTOR_VERSION,
            "operation": "extract",
            "source_id": source_spec["id"],
            "source_url": source_spec.get("url", ""),
            "input": str(input_path),
            "output": str(output_path),
            "format": fmt,
            "min_chars": min_chars,
            "max_chars": max_chars,
            "limit": limit,
            "records": len(records),
        })
    return records


def extract_chunks(source_spec, input_path, output_dir, min_chars=4, max_chars=240, limit=None,
                   chunk_bytes=DEFAULT_CHUNK_BYTES, manifest_path=None, deduplicate=True):
    """Write human-readable, uncompressed staging JSONL chunks without loading all rows."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    seen = set() if deduplicate else None
    files = []
    handle = None
    current_size = 0
    records = 0

    def open_chunk(number):
        path = output_dir / f"part-{number:05d}.jsonl"
        files.append(path)
        return path.open("w", encoding="utf-8")

    try:
        for location, row in iter_input(input_path, source_spec.get("format", "text")):
            for text, context, source_record_id in turn_candidates(row, source_spec, location):
                if not min_chars <= len(text) <= max_chars or not CJK.search(text):
                    continue
                if seen is not None:
                    key = normalize(text)
                    if key in seen:
                        continue
                    seen.add(key)
                record = make_record(source_spec, source_record_id, text, context)
                line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                encoded_size = len(line.encode("utf-8"))
                if handle is None or (current_size and current_size + encoded_size > chunk_bytes):
                    if handle is not None:
                        handle.close()
                    handle = open_chunk(len(files))
                    current_size = 0
                handle.write(line)
                current_size += encoded_size
                records += 1
                if limit and records >= limit:
                    break
            if limit and records >= limit:
                break
    finally:
        if handle is not None:
            handle.close()
    result = {"schema_version": STAGING_SCHEMA, "source_id": source_spec["id"],
              "input": str(input_path), "output_dir": str(output_dir), "files": [str(path) for path in files],
              "records": records, "chunk_bytes": chunk_bytes, "deduplicate": deduplicate,
              "extractor_version": EXTRACTOR_VERSION}
    if manifest_path:
        write_json(manifest_path, result)
    return result


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{number}: invalid JSON: {error.msg}") from error
            if not isinstance(row, dict) or not isinstance(row.get("text"), str):
                raise ValueError(f"{path}:{number}: expected a record with text")
            yield row


def expand_jsonl_inputs(paths):
    expanded = []
    for path in paths:
        path = Path(path)
        if path.is_dir():
            expanded.extend(sorted(item for item in path.rglob("part-*.jsonl") if item.is_file()))
        else:
            expanded.append(path)
    return expanded


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sample(inputs, output_path, count, seed, split="", manifest_path=None, deduplicate=True):
    records = []
    seen = set() if deduplicate else None
    candidates = 0
    rng = random.Random(seed)
    for path in expand_jsonl_inputs(inputs):
        for row in read_jsonl(path):
            if seen is not None:
                key = normalize(row["text"])
                if key in seen:
                    continue
                seen.add(key)
            candidates += 1
            if len(records) < count:
                records.append(row)
            else:
                position = rng.randrange(candidates)
                if position < count:
                    records[position] = row
    rng.shuffle(records)
    selected = records[:count]
    if split:
        selected = [{**row, "split": split} for row in selected]
    write_jsonl(output_path, selected)
    if manifest_path:
        write_json(manifest_path, {
            "workflow_version": EXTRACTOR_VERSION,
            "operation": "sample",
            "inputs": [str(path) for path in inputs],
            "output": str(output_path),
            "requested": count,
            "candidates": candidates,
            "selected": len(selected),
            "seed": seed,
            "split": split,
            "deduplicate": deduplicate,
            "sources": dict(sorted(Counter(row.get("source_id", "unknown") for row in selected).items())),
        })
    return selected


def stats(inputs):
    rows = [row for path in inputs for row in read_jsonl(path)]
    by_source = Counter(row.get("source_id", "unknown") for row in rows)
    lengths = Counter("short" if len(row["text"]) < 20 else "medium" if len(row["text"]) < 60 else "long"
                      for row in rows)
    return {"total": len(rows), "sources": dict(sorted(by_source.items())), "lengths": dict(sorted(lengths.items()))}


def run_pipeline(config_path):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent
    index_path = root / config.get("sources_file", "data/sources.json")
    index = load_index(index_path)
    generated_chunks = []
    jobs = config.get("extract", [])
    for number, job in enumerate(jobs, 1):
        spec = source(index, job["source"])
        input_path = root / job["input"]
        if not input_path.exists() and job.get("optional"):
            print(f"[{number}/{len(jobs)}] 跳过缺失可选来源：{job['source']} ({input_path})", flush=True)
            continue
        print(f"[{number}/{len(jobs)}] staging：{job['source']} -> {input_path}", flush=True)
        if job.get("staging_dir"):
            result = extract_chunks(spec, input_path, root / job["staging_dir"], job.get("min_chars", 4),
                                    job.get("max_chars", 240), job.get("limit"), job.get("chunk_bytes", DEFAULT_CHUNK_BYTES),
                                    root / job["manifest"] if job.get("manifest") else None,
                                    job.get("deduplicate", True))
            generated_chunks.extend(result["files"])
            print(f"    完成：{result['records']} 条，{len(result['files'])} 个分片", flush=True)
        else:
            extract(spec, input_path, root / job["output"], job.get("min_chars", 4),
                    job.get("max_chars", 240), job.get("limit"),
                    root / job["manifest"] if job.get("manifest") else None)
    sample_config = config.get("sample")
    if sample_config:
        configured_inputs = [root / path for path in sample_config.get("inputs", [])]
        sample_inputs = expand_jsonl_inputs([Path(path) for path in generated_chunks] or configured_inputs)
        sample(sample_inputs, root / sample_config["output"],
               sample_config["count"], sample_config.get("seed", 52), sample_config.get("split", ""),
               root / sample_config["manifest"] if sample_config.get("manifest") else None,
               sample_config.get("deduplicate", True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listed = commands.add_parser("list", help="list indexed sources")
    listed.add_argument("--sources", default="data/sources.json")
    extracted = commands.add_parser("extract", help="normalize and deduplicate one raw source")
    extracted.add_argument("--sources", default="data/sources.json")
    extracted.add_argument("--source", required=True, dest="source_id")
    extracted.add_argument("--input", required=True, type=Path)
    extracted.add_argument("--output", required=True, type=Path)
    extracted.add_argument("--min-chars", type=int, default=4)
    extracted.add_argument("--max-chars", type=int, default=240)
    extracted.add_argument("--limit", type=int)
    extracted.add_argument("--manifest", type=Path)
    sampled = commands.add_parser("sample", help="sample extracted records deterministically")
    sampled.add_argument("--input", required=True, nargs="+", type=Path)
    sampled.add_argument("--output", required=True, type=Path)
    sampled.add_argument("--count", required=True, type=int)
    sampled.add_argument("--seed", type=int, default=52)
    sampled.add_argument("--split", default="")
    sampled.add_argument("--manifest", type=Path)
    reported = commands.add_parser("stats", help="report source and length counts")
    reported.add_argument("--input", required=True, nargs="+", type=Path)
    pipeline = commands.add_parser("run", help="run a JSON pipeline configuration")
    pipeline.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            for item in sorted(load_index(args.sources).values(), key=lambda row: (row.get("priority", 99), row["id"])):
                print(json.dumps({key: item.get(key) for key in ("id", "name", "family", "priority", "script", "url")}, ensure_ascii=False))
        elif args.command == "extract":
            index = load_index(args.sources)
            records = extract(source(index, args.source_id), args.input, args.output, args.min_chars,
                              args.max_chars, args.limit, args.manifest)
            print(json.dumps({"output": str(args.output), "records": len(records)}, ensure_ascii=False))
        elif args.command == "sample":
            records = sample(args.input, args.output, args.count, args.seed, args.split, args.manifest)
            print(json.dumps({"output": str(args.output), "records": len(records), "seed": args.seed}, ensure_ascii=False))
        elif args.command == "stats":
            print(json.dumps(stats(args.input), ensure_ascii=False, sort_keys=True))
        else:
            run_pipeline(args.config)
            print(json.dumps({"config": str(args.config), "status": "ok"}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
