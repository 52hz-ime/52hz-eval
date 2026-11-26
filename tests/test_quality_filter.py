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

    def test_ime_units_reject_stray_quotes_and_source_artifacts(self):
        accepted = ["只要他今天拿到15分，", "“只要剧本OK，", "但是我们没有抓住机会，”", "他将成为最年轻的26000分先生。",
                    "我保留50元和100元这两种套餐，", "今晚一起吃饭吗？", "好的，没问题", "二〇一四年春天", "乾坤大挪移", "於是他就走了", "别墅区域"]
        for text in accepted:
            with self.subTest(text=text):
                self.assertEqual(classify({"text": text}, 4, 30), {"status": "accepted", "flags": [], "filter_version": "0.3.0"})
        rejected = {"”不知比尔。": "leading_closer", "他说：“": "trailing_opener", "我想还是不要有这样的”时候”了": "unmatched_closer",
                    "新浪科技讯 北京时间11月6日消息，": "cjk_space", ">>>火箭击败森林狼": "repeated_character",
                    "详情见https://example.com/x": "url_or_handle", "他問我要走什麽風格，": "traditional_chars",
                    "有多馀的友善，": "traditional_chars", "ㄅㄆㄇ注音": "other_scripts", "α粒子": "other_scripts", "café": "other_scripts",
                    "1、拉简-隆多，": "list_numbering", "11投4中得到13分4篮板7助攻，": "digit_heavy", "据ESPN报道，": "latin_heavy",
                    "★清淡饮食。": "symbol_or_emoticon",
                    "北京电信副总经理梁宝俊则说，我们保留了50元和100元这两种套餐，但月收费100元以上的都升级，": "too_long", "是": "too_short"}
        for text, flag in rejected.items():
            with self.subTest(text=text):
                self.assertEqual(classify({"text": text}, 4, 30)["status"], "rejected")
                self.assertIn(flag, classify({"text": text}, 4, 30)["flags"])
