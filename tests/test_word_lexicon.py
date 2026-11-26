import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tools.word_lexicon import build, counts


class WordLexiconTests(unittest.TestCase):
    def test_characters_and_pairs_are_counted_inside_chinese_runs_only(self):
        chars, pairs = counts(["明天开会。明天开心", "abc你好", "明 天"])
        self.assertEqual((chars["明"], chars["好"]), (3, 1))
        self.assertEqual(pairs["明天"], 2)
        self.assertEqual(pairs["开会"], 1)
        self.assertEqual(pairs["天开"], 2)  # a pair that crosses a word boundary still counts as a pair
        self.assertNotIn("好明", pairs)     # but a pair never spans punctuation or whitespace
        self.assertNotIn("天明", pairs)

    def test_pairs_of_the_benchmark_clauses_are_not_counted(self):
        self.assertEqual(counts(["明天开会", "明天开会"], exclude={"明天开会"}), ({}, {}))

    @unittest.skipUnless(importlib.util.find_spec("pypinyin"), "pypinyin dependency is installed by uv sync")
    def test_build_writes_characters_and_frequent_pairs_with_their_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shards").mkdir()
            rows = [["明天开会。" if number % 2 else "我们明天开户。", "", f"r{number}", 0] for number in range(20)]
            (root / "shards" / "demo-abc.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
            (root / "shards" / "demo-abc.rejected.jsonl").write_text('[["不要统计", "", "x", 0]]\n', encoding="utf-8")
            (root / "base.jsonl").write_text(json.dumps({"text": "我们明天开户。"}, ensure_ascii=False) + "\n", encoding="utf-8")
            manifest = build(root, root / "lexicon.jsonl", 3)
            words = [json.loads(line) for line in (root / "lexicon.jsonl").read_text(encoding="utf-8").splitlines()]
            # The excluded clause is the one in base.jsonl; only the other sentence contributes pairs.
            self.assertEqual({row["word"] for row in words if len(row["word"]) == 2}, {"明天", "天开", "开会"})
            self.assertEqual({row["word"] for row in words if len(row["word"]) == 1}, set("明天开会"))
            self.assertTrue(all(row["count"] == 10 for row in words))
            self.assertIn({"word": "开会", "keys": "kaihui", "count": 10}, words)
            self.assertTrue(all("keys" not in row for row in words if len(row["word"]) == 1))
            self.assertEqual(manifest["excluded_clauses"], 1)
            self.assertTrue((root / "lexicon.manifest.json").is_file())
