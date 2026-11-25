import importlib.util
import unittest

from tools.pinyin_cases import convert, mutate, noise_cases, split_sentences


HAS_PINYIN = importlib.util.find_spec("pypinyin") is not None


class PinyinCaseTests(unittest.TestCase):
    def test_sentence_split_keeps_terminal_punctuation(self):
        self.assertEqual(split_sentences("你好！今天下雨了……明天再见", 120), ["你好！", "今天下雨了……", "明天再见"])

    @unittest.skipUnless(HAS_PINYIN, "pypinyin dependency is installed by uv sync")
    def test_convert_preserves_literals_and_uses_phrase_pinyin(self):
        keys, segments = convert("重庆ABC-239")
        self.assertEqual(keys, "chongqingABC-239")
        self.assertEqual(segments[0]["syllables"], ["chong", "qing"])
        self.assertEqual(segments[1], {"text": "ABC-239", "keys": "ABC-239", "kind": "literal"})

    def test_noise_does_not_change_literal_span(self):
        record = {"id": "case", "text": "明天ABC", "keys": "mingtianABC", "pinyin_segments": [
            {"text": "明天", "keys": "mingtian", "kind": "zh", "syllables": ["ming", "tian"]},
            {"text": "ABC", "keys": "ABC", "kind": "literal"},
        ]}
        changed, operation = mutate(record, "neighbor", __import__("random").Random(52))
        self.assertNotEqual(changed, record["keys"])
        self.assertEqual(changed[-3:], "ABC")
        self.assertEqual(operation["type"], "neighbor")

    def test_noise_cases_are_deterministic_and_keep_expected_text(self):
        record = {"id": "case", "text": "明天开会", "keys": "mingtiankaihui", "pinyin_segments": [
            {"text": "明天开会", "keys": "mingtiankaihui", "kind": "zh",
             "syllables": ["ming", "tian", "kai", "hui"]},
        ]}
        operations = ["clean", "drop", "syllable_swap", "truncate_suffix"]
        first = list(noise_cases([record], operations, 52))
        second = list(noise_cases([record], operations, 52))
        self.assertEqual(first, second)
        self.assertEqual(first[0]["keys"], record["keys"])
        self.assertTrue(all(row["expected"] == {"action": "commit", "text": "明天开会"} for row in first))

    def test_unreviewed_source_records_are_not_gold_by_default(self):
        record = {"id": "review", "text": "明天开会", "keys": "mingtiankaihui",
                  "quality_policy": "manual_review", "pinyin_segments": [
                      {"text": "明天开会", "keys": "mingtiankaihui", "kind": "zh",
                       "syllables": ["ming", "tian", "kai", "hui"]},
                  ]}
        self.assertEqual(list(noise_cases([record], ["clean"])), [])
        self.assertEqual(len(list(noise_cases([record], ["clean"], include_review=True))), 1)
