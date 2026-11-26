import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tools.benchmark_pipeline import run, stage_flat


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

    def test_flat_staging_rebuilds_only_the_requested_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "data" / "sources.json").write_text(json.dumps({"sources": [
                {"id": "news", "format": "jsonl", "split": "sentences", "text_fields": ["content"], "quality_policy": "editorial"},
                {"id": "chat", "format": "text", "quality_policy": "editorial"}]}), encoding="utf-8")
            (root / "raw").mkdir()
            (root / "raw" / "news.jsonl").write_text(json.dumps({"id": "n1", "content": "他说：“好的。”明天见。"}, ensure_ascii=False) + "\n",
                                                  encoding="utf-8")
            (root / "raw" / "chat.txt").write_text("明天见啦。\n", encoding="utf-8")
            config = root / "data" / "pipeline.json"
            config.write_text(json.dumps({"sources_file": "sources.json", "extract": [
                {"source": "news", "input": "../raw/news.jsonl", "staging_dir": "unused-news"},
                {"source": "chat", "input": "../raw/chat.txt", "staging_dir": "unused-chat"}]}), encoding="utf-8")
            stage = root / "staging"
            stage_flat(config, stage)
            chat_before = (stage / "chat" / "part-00000.jsonl").read_bytes()
            stage_flat(config, stage, only="news")
            texts = [json.loads(line)["text"] for line in (stage / "news" / "part-00000.jsonl").read_text().splitlines()]
            self.assertEqual(texts, ["他说：“好的。”", "明天见。"])
            self.assertEqual((stage / "chat" / "part-00000.jsonl").read_bytes(), chat_before)
            self.assertFalse(list(stage.glob(".*partial*")))
            self.assertEqual(json.loads((stage / "news.manifest.json").read_text())["output_dir"], str(stage / "news"))
            with self.assertRaises(ValueError):
                stage_flat(config, stage, only="missing")
