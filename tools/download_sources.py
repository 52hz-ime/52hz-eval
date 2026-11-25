"""Download indexed corpus files with resumable, idempotent progress output."""

import argparse
import fnmatch
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from tools.corpus_workflow import load_index


def hf_listing(repo):
    url = f"https://huggingface.co/api/datasets/{repo}/tree/main?recursive=true&expand=false"
    last_error = None
    for attempt in range(8):
        try:
            with urlopen(url, timeout=30) as response:
                payload = json.load(response)
            break
        except OSError as error:
            last_error = error
            if attempt == 7:
                raise
            print(f"  清单请求失败，{attempt + 1}/8 次重试：{error}", flush=True)
            time.sleep(2)
    else:
        raise last_error
    if not isinstance(payload, list):
        raise ValueError(f"unexpected Hugging Face file listing for {repo}")
    return payload


def hf_files(listing, include):
    files = [item["path"] for item in listing if item.get("type") == "file" and
             any(fnmatch.fnmatch(item.get("path", ""), pattern) for pattern in include)]
    if not files:
        raise ValueError(f"no files matched for {repo}: {', '.join(include)}")
    return sorted(files)


def download_file(url, target, expected_size=None):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        if expected_size is None or target.stat().st_size == expected_size:
            return "skip"
        if target.stat().st_size > expected_size:
            raise ValueError(f"existing file is larger than remote file: {target}")
    partial = target.with_name(target.name + ".part")
    if partial.is_file() and expected_size is not None and partial.stat().st_size == expected_size:
        partial.replace(target)
        return "download"
    command = ["curl", "-fL", "--http1.1", "--retry", "8", "--retry-all-errors", "--retry-delay", "2",
               "--continue-at", "-", "--progress-bar", "-o", str(partial), url]
    subprocess.run(command, check=True)
    if expected_size is not None and partial.stat().st_size != expected_size:
        raise ValueError(f"size mismatch for {target}: {partial.stat().st_size} != {expected_size}")
    partial.replace(target)
    return "download"


def download_source(source_spec, raw_dir):
    config = source_spec.get("download")
    if not config:
        print(f"  [manual] {source_spec['id']}: no automatic download configured")
        return {"downloaded": 0, "skipped": 0, "manual": 1, "failed": 0}
    if config.get("kind") == "manual":
        print(f"  [manual] {source_spec['id']}: {config.get('instructions', 'see source URL')}")
        return {"downloaded": 0, "skipped": 0, "manual": 1, "failed": 0}
    if config.get("kind") != "hf":
        raise ValueError(f"unsupported download kind for {source_spec['id']}: {config.get('kind')}")
    listing = hf_listing(config["repo"])
    files = hf_files(listing, config["include"])
    summary = {"downloaded": 0, "skipped": 0, "manual": 0, "failed": 0}
    for number, path in enumerate(files, 1):
        url = f"https://huggingface.co/datasets/{config['repo']}/resolve/main/{quote(path, safe='/')}?download=true"
        target = Path(raw_dir) / source_spec["id"] / path
        remote = next(item for item in listing if item.get("path") == path)
        size = remote.get("size")
        print(f"  [{number}/{len(files)}] {source_spec['id']}/{path}", flush=True)
        status = download_file(url, target, size)
        summary["skipped" if status == "skip" else "downloaded"] += 1
        print(f"      {'已有，跳过' if status == 'skip' else '下载完成'}：{target}", flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="data/sources.json")
    parser.add_argument("--raw-dir", default="raw", type=Path)
    parser.add_argument("--select", default="lccc_base", help="comma-separated source IDs, or all")
    args = parser.parse_args(argv)
    try:
        index = load_index(args.sources)
        selected = list(index) if args.select == "all" else [item.strip() for item in args.select.split(",") if item.strip()]
        unknown = [item for item in selected if item not in index]
        if unknown:
            raise ValueError(f"unknown source: {', '.join(unknown)}")
        total = {"downloaded": 0, "skipped": 0, "manual": 0, "failed": 0}
        print(f"52Hz corpus download: {len(selected)} source(s), raw={args.raw_dir}", flush=True)
        for number, source_id in enumerate(selected, 1):
            print(f"[{number}/{len(selected)}] 检查 {source_id}", flush=True)
            result = download_source(index[source_id], args.raw_dir)
            for key, value in result.items():
                total[key] += value
        print("完成：" + ", ".join(f"{key}={value}" for key, value in total.items()), flush=True)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"下载失败：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
