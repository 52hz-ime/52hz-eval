"""Run the versioned, idempotent clean -> pinyin -> noise benchmark pipeline."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from tools.corpus_workflow import EXTRACTOR_VERSION, run_pipeline, write_json
from tools.pinyin_cases import GENERATOR_VERSION, write_noise, write_pinyin


PIPELINE_VERSION = "0.1.0"
PARTIAL_BYTES = 65536


def digest_file(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        first = handle.read(PARTIAL_BYTES)
        digest.update(first)
        if path.stat().st_size > PARTIAL_BYTES:
            handle.seek(-PARTIAL_BYTES, os.SEEK_END)
            digest.update(handle.read(PARTIAL_BYTES))
    return {"size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns, "partial_sha256": digest.hexdigest()}


def input_signature(path):
    path = Path(path)
    if path.is_file():
        return {"path": str(path), "file": digest_file(path)}
    if path.is_dir():
        files = {}
        for child in sorted(item for item in path.rglob("*") if item.is_file() and not item.name.endswith(".part")):
            files[str(child.relative_to(path))] = digest_file(child)
        return {"path": str(path), "files": files}
    return {"path": str(path), "missing": True}


def canonical_digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_config(config_path):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent
    sources_file = (root / config.get("sources_file", "data/sources.json")).resolve()
    inputs = []
    for job in config.get("extract", []):
        inputs.append(input_signature((root / job["input"]).resolve()))
    tracked = {"config": config, "sources": sources_file.read_text(encoding="utf-8"),
               "inputs": inputs, "extractor_version": EXTRACTOR_VERSION,
               "generator_version": GENERATOR_VERSION, "pipeline_version": PIPELINE_VERSION}
    for filename in ("pyproject.toml", "uv.lock"):
        path = root.parent / filename if root.name == "data" else root / filename
        if path.is_file():
            tracked[filename] = digest_file(path)
    for filename in ("tools/corpus_workflow.py", "tools/pinyin_cases.py", "tools/benchmark_pipeline.py"):
        path = root.parent / filename if root.name == "data" else root / filename
        if path.is_file():
            tracked[filename] = digest_file(path)
    return config, root, sources_file, tracked


def resolved_config(config, root, sources_file, partial, include_sample=True):
    jobs = []
    outputs = []
    for index, job in enumerate(config.get("extract", [])):
        output = partial / "extract" / f"{index:02d}-{job['source']}.jsonl"
        manifest = partial / "extract" / f"{index:02d}-{job['source']}.manifest.json"
        jobs.append({**job, "input": str((root / job["input"]).resolve()), "output": str(output),
                     "staging_dir": str(partial / "staging" / job["source"]),
                     "manifest": str(partial / "staging" / f"{job['source']}.manifest.json")})
        outputs.append(str(output))
    sample = config.get("sample")
    resolved = {"sources_file": str(sources_file), "extract": jobs}
    if sample and include_sample:
        resolved["sample"] = {**sample, "inputs": outputs, "output": str(partial / "clean.jsonl"),
                               "manifest": str(partial / "clean.manifest.json")}
    return resolved


def complete(final_dir, stage_only=False):
    manifest = final_dir / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if stage_only:
        return payload.get("status") == "staging_complete" and (final_dir / "staging").is_dir()
    return payload.get("status") == "complete" and (final_dir / "staging").is_dir() and all(
        (final_dir / name).is_file() for name in ("clean.jsonl", "pinyin.jsonl", "cases.jsonl"))


def replace_paths(value, old, new):
    if isinstance(value, str):
        return value.replace(str(old), str(new))
    if isinstance(value, list):
        return [replace_paths(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_paths(item, old, new) for key, item in value.items()}
    return value


def rewrite_run_paths(run_dir, old_dir):
    for path in run_dir.rglob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        write_json(path, replace_paths(payload, old_dir, run_dir))


def run(config_path, stage_only=False):
    config, root, sources_file, tracked = load_config(config_path)
    run_id = f"v{PIPELINE_VERSION}-{canonical_digest(tracked)[:12]}"
    build_dir = (root.parent / "build") if root.name == "data" else (root / "build")
    runs_dir = build_dir / "runs"
    final_dir = (build_dir / "staging-runs" if stage_only else runs_dir) / run_id
    if complete(final_dir, stage_only):
        manifest = json.loads((final_dir / "manifest.json").read_text(encoding="utf-8"))
        print(f"已有完整 run，跳过：{final_dir}")
        pointer = build_dir / ("current-staging.json" if stage_only else "current.json")
        write_json(pointer, {"run_id": run_id, "path": str(final_dir), "status": "complete"})
        return {**manifest, "skipped": True}
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(tempfile.mkdtemp(prefix=f"{run_id}.partial-", dir=final_dir.parent))
    manifest = {"run_id": run_id, "pipeline_version": PIPELINE_VERSION,
                "operation": "staging" if stage_only else "benchmark", "status": "running",
                "config": str(Path(config_path).resolve()), "tracked_digest": canonical_digest(tracked),
                "tracked": tracked, "extractor_version": EXTRACTOR_VERSION,
                "generator_version": GENERATOR_VERSION}
    write_json(partial / "manifest.json", manifest)
    try:
        resolved = resolved_config(config, root, sources_file, partial, include_sample=not stage_only)
        write_json(partial / "pipeline.resolved.json", resolved)
        resolved_path = partial / "pipeline.resolved.json"
        run_pipeline(resolved_path)
        if stage_only:
            manifest.update({"status": "staging_complete", "outputs": {"staging": "staging"}})
        else:
            pinyin_count = write_pinyin(partial / "clean.jsonl", partial / "pinyin.jsonl", 4, 120, None,
                                        partial / "pinyin.manifest.json")
            case_count = write_noise(partial / "pinyin.jsonl", partial / "cases.jsonl",
                                     ["clean", "drop", "duplicate", "insert", "neighbor", "swap",
                                      "syllable_swap", "truncate_prefix", "truncate_suffix"],
                                     config.get("sample", {}).get("seed", 52), None,
                                     partial / "cases.manifest.json")
            manifest.update({"status": "complete", "outputs": {"clean": "clean.jsonl", "pinyin": "pinyin.jsonl",
                                                                   "cases": "cases.jsonl"},
                            "counts": {"pinyin": pinyin_count, "cases": case_count}})
        write_json(partial / "manifest.json", manifest)
        if final_dir.exists():
            raise FileExistsError(f"run directory already exists but is incomplete: {final_dir}")
        partial.rename(final_dir)
        rewrite_run_paths(final_dir, partial)
        write_json(build_dir / ("current-staging.json" if stage_only else "current.json"),
                   {"run_id": run_id, "path": str(final_dir), "status": manifest["status"]})
        print(f"生成完成：{final_dir}")
        return manifest
    except Exception as error:
        manifest.update({"status": "failed", "error": str(error)})
        write_json(partial / "manifest.json", manifest)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="data/benchmark.pipeline.json", type=Path)
    parser.add_argument("--staging-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        run(args.config, args.staging_only)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
