import importlib.util
import json
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from tools.ime_benchmark import build, draw, follows, split_units, tail, trial_cases


HAS_PINYIN = importlib.util.find_spec("pypinyin") is not None


class UnitTests(unittest.TestCase):
    def test_clause_split_keeps_marks_with_the_clause_they_end(self):
        self.assertEqual(split_units("只要他今天拿到15分，就可以超越卡尔-马龙(4761分)，升至历史第四。"),
                         ["只要他今天拿到15分，", "就可以超越卡尔-马龙(4761分)，", "升至历史第四。"])
        self.assertEqual(split_units("他还说：“只要剧本OK，要我女扮男装、扮丑、搞笑都没问题！”"),
                         ["他还说：“只要剧本OK，", "要我女扮男装、扮丑、搞笑都没问题！”"])
        self.assertEqual(split_units("你好！！今天下雨了……明天见"), ["你好！！", "今天下雨了……", "明天见"])
        self.assertEqual(split_units("1,000元和3.14，好的!"), ["1,000元和3.14，", "好的!"])
        self.assertEqual(split_units("。"), [])
        self.assertEqual(split_units(""), [])

    def test_context_tail_cuts_at_a_clause_mark_near_the_front(self):
        self.assertEqual(tail("好的，没问题", 5), "没问题")
        self.assertEqual(tail("好的，没问题", 6), "好的，没问题")
        self.assertEqual(tail("我们明天去看电影吧", 4), "看电影吧")

    def test_adjacent_sentence_records_of_one_document_are_linked(self):
        row = {"source_record_id": "a.txt:part-3", "group_id": "a.txt"}
        self.assertTrue(follows({"source_record_id": "a.txt:part-2", "group_id": "a.txt"}, row))
        self.assertFalse(follows({"source_record_id": "b.txt:part-2", "group_id": "b.txt"}, row))
        self.assertFalse(follows({"source_record_id": "a.txt:part-1", "group_id": "a.txt"}, row))

    def test_draw_is_deterministic_and_follows_the_target_length_curve(self):
        rows = [(chr(0x4e00 + number) + "字" * (size - 1), "", f"r{number}", 0) for size in range(4, 31) for number in range(400)]
        first, _ = draw(rows + rows, 900, {"mean": 12, "sd": 5}, 4000, random.Random(52))
        second, _ = draw(rows + rows, 900, {"mean": 12, "sd": 5}, 4000, random.Random(52))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 900)
        self.assertEqual(len({row[0] for row in first}), 900)
        sizes = Counter(len(row[0]) for row in first)
        self.assertGreater(sizes[12], sizes[4])
        self.assertGreater(sizes[12], sizes[26])

    def test_trial_covers_every_source_and_operation_cell(self):
        cases = [{"source_id": source, "noise_ops": [{"type": operation}]} for source in ("a", "b") for operation in ("clean", "drop")]
        picked = trial_cases(cases * 10, 7, random.Random(1))
        self.assertEqual(len(picked), 7)
        counts = Counter((row["source_id"], row["noise_ops"][0]["type"]) for row in picked)
        self.assertEqual(sorted(counts.values()), [1, 2, 2, 2])
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)


class BuildTests(unittest.TestCase):
    def fixture(self, root):
        staging = root / "staging"
        rows = {
            "news": [("他说：“好的。”明天见。", "标题"), ("只要他今天拿到15分，就可以超越卡尔-马龙，升至历史第四。", "标题")],
            "chat": [("好的，明天九点开会。", "上次聊到开会"), ("今晚一起吃饭吗？", "")],
        }
        for source, items in rows.items():
            (staging / source).mkdir(parents=True)
            lines = [{"id": f"{source}:{number}", "source_id": source, "source_record_id": f"{number}.txt:part-0",
                      "group_id": f"{number}.txt", "text": text, "context": context} for number, (text, context) in enumerate(items)]
            (staging / source / "part-00000.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in lines) + "\n",
                                                               encoding="utf-8")
        sources = root / "sources.json"
        sources.write_text(json.dumps({"sources": [{"id": "news", "quality_policy": "editorial", "url": "n", "script": "simplified"},
                                                     {"id": "chat", "quality_policy": "manual_review", "url": "c", "script": "simplified"}]}),
                           encoding="utf-8")
        return staging, sources

    @unittest.skipUnless(HAS_PINYIN, "pypinyin dependency is installed by uv sync")
    def test_build_is_uniform_and_refuses_unreviewed_sources_unless_asked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staging, sources = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "include-review"):
                build(staging, sources, root / "out", None, 2, ["clean", "drop"], 52, False, 4, 30, {"mean": 12, "sd": 5}, 4, 2, 1500000, 60)
            manifest = build(staging, sources, root / "out", None, 2, ["clean", "drop"], 52, True, 4, 30, {"mean": 12, "sd": 5}, 4, 2, 1500000, 60)
            read = lambda name: [json.loads(line) for line in (root / "out" / name).read_text(encoding="utf-8").splitlines()]
            self.assertEqual(manifest["by_source"], {"chat": 4, "news": 4})
            self.assertEqual(manifest["base"], 4)
            self.assertTrue(all(4 <= len(row["text"]) <= 30 for row in read("base.jsonl")))
            self.assertTrue(all(row["context"] for row in read("base.jsonl") if row["source_id"] == "news"))
            self.assertEqual({row["quality_policy"] for row in read("base.jsonl") if row["source_id"] == "chat"}, {"manual_review"})
            cases = read("cases.jsonl")
            self.assertTrue(all(row["expected"] == {"action": "commit", "text": row["text"]} for row in cases))
            self.assertTrue(all(row["clean_keys"] and row["keys"] for row in cases))
            self.assertEqual(len({row["id"] for row in cases}), len(cases))
            self.assertEqual(manifest["trial"]["by_source"], {"chat": 2, "news": 2})
            self.assertEqual(len(read("trial-4.jsonl")), 4)
            self.assertTrue(list((root / "out" / "shards").glob("*.rejected.jsonl")))
            again = build(staging, sources, root / "out", None, 2, ["clean", "drop"], 52, True, 4, 30, {"mean": 12, "sd": 5}, 4, 2, 1500000, 60)
            self.assertEqual(again["by_source"], manifest["by_source"])
            self.assertEqual(read("cases.jsonl"), cases)
