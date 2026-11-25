import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tools.benchmark_pipeline import run


class BenchmarkPipelineTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("pypinyin"), "pypinyin dependency is installed by uv sync")
    def test_same_inputs_reuse_complete_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            raw = root / "raw"
            data.mkdir()
            raw.mkdir()
            (data / "sources.json").write_text(json.dumps({"sources": [{
                "id": "demo", "format": "text", "script": "simplified", "quality_policy": "editorial",
                "url": "https://example.test"
            }]}), encoding="utf-8")
            (raw / "input.txt").write_text("明天开会。\n", encoding="utf-8")
            (data / "pipeline.json").write_text(json.dumps({
                "sources_file": "sources.json",
                "extract": [{"source": "demo", "input": "../raw/input.txt", "min_chars": 2, "max_chars": 30,
                              "limit": 10}],
                "sample": {"count": 10, "seed": 52, "split": "test"}
            }), encoding="utf-8")
            first = run(data / "pipeline.json")
            second = run(data / "pipeline.json")
            self.assertFalse(first.get("skipped", False))
            self.assertTrue(second.get("skipped", False))
            self.assertEqual(first["run_id"], second["run_id"])
            run_dir = root / "build" / "runs" / first["run_id"]
            self.assertTrue((run_dir / "cases.jsonl").is_file())
            self.assertEqual(json.loads((root / "build" / "current.json").read_text())["run_id"], first["run_id"])

    @unittest.skipUnless(importlib.util.find_spec("pypinyin"), "pypinyin dependency is installed by uv sync")
    def test_staging_only_has_separate_idempotent_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            raw = root / "raw"
            data.mkdir()
            raw.mkdir()
            (data / "sources.json").write_text(json.dumps({"sources": [{
                "id": "demo", "format": "text", "script": "simplified", "quality_policy": "editorial"
            }]}), encoding="utf-8")
            (raw / "input.txt").write_text("明天开会。\n", encoding="utf-8")
            config = data / "pipeline.json"
            config.write_text(json.dumps({
                "sources_file": "sources.json",
                "extract": [{"source": "demo", "input": "../raw/input.txt", "min_chars": 2, "max_chars": 30,
                              "chunk_bytes": 128}]
            }), encoding="utf-8")
            first = run(config, stage_only=True)
            second = run(config, stage_only=True)
            self.assertEqual(first["status"], "staging_complete")
            self.assertTrue(second.get("skipped", False))
            self.assertTrue((root / "build" / "staging-runs" / first["run_id"] / "staging").is_dir())
