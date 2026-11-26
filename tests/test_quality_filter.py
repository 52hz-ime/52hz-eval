import json
import tempfile
import unittest
from pathlib import Path

from tools.quality_filter import classify
from tools.quality_pipeline import run


class QualityFilterTests(unittest.TestCase):
    def test_flags_obvious_artifacts_without_rejecting_names(self):
        self.assertEqual(classify({"text": "正常的句子。"})["status"], "accepted")
        self.assertEqual(classify({"text": "王蒙在北京。"})["status"], "accepted")
        self.assertEqual(classify({"text": "记者王蒙与"})["status"], "review")
        self.assertEqual(classify({"text": "内容_COUNT_异常"})["status"], "rejected")

    def test_quality_pipeline_writes_filter_out_and_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "part-00000.jsonl").write_text("\n".join([
                json.dumps({"id": "1", "source_id": "demo", "text": "正常的句子。"}, ensure_ascii=False),
                json.dumps({"id": "2", "source_id": "demo", "text": "内容_COUNT_异常"}, ensure_ascii=False),
            ]) + "\n", encoding="utf-8")
            result = run([source], root / "out", [2], 52)
            report = result["outputs"]["2"]
            self.assertEqual(report["counts"]["accepted"], 1)
            self.assertEqual(report["counts"]["rejected"], 1)
            self.assertEqual(len((root / "out" / "sample-2.filter-out.jsonl").read_text().splitlines()), 1)
