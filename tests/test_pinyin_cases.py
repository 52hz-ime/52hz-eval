import importlib.util
import unittest

from tools.pinyin_cases import (LEFT_HAND, accent, compound, convert, error_budget, mutate, neighbor, noise_cases,
                                 operation_label, split_sentences)


HAS_PINYIN = importlib.util.find_spec("pypinyin") is not None


def sentence(text, syllables):
    keys = "".join(syllables)
    return {"id": "case", "text": text, "keys": keys, "pinyin_segments": [
        {"text": text, "keys": keys, "kind": "zh", "syllables": syllables}]}


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

    def test_qwerty_neighbors_include_adjacent_rows(self):
        self.assertIn("r", neighbor("f"))
        self.assertIn("r", neighbor("t"))
        self.assertIn("v", neighbor("f"))

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
        self.assertEqual(first[0]["base_id"], record["id"])
        self.assertEqual(first[0]["clean_keys"], record["keys"])
        self.assertTrue(all(row["expected"] == {"action": "commit", "text": "明天开会"} for row in first))

    def test_unreviewed_source_records_are_not_gold_by_default(self):
        record = {"id": "review", "text": "明天开会", "keys": "mingtiankaihui",
                  "quality_policy": "manual_review", "pinyin_segments": [
                      {"text": "明天开会", "keys": "mingtiankaihui", "kind": "zh",
                       "syllables": ["ming", "tian", "kai", "hui"]},
                  ]}
        self.assertEqual(list(noise_cases([record], ["clean"])), [])
        self.assertEqual(len(list(noise_cases([record], ["clean"], include_review=True))), 1)

    def test_hand_swap_reverses_adjacent_letters_from_different_hands(self):
        record = sentence("我明天去上海", ["wo", "ming", "tian", "qu", "shang", "hai"])
        for seed in range(30):
            changed, noise = mutate(record, "hand_swap", __import__("random").Random(seed))
            position = noise["position"]
            with self.subTest(seed=seed):
                self.assertEqual(sorted(changed), sorted(record["keys"]))
                self.assertNotEqual(changed, record["keys"])
                self.assertNotEqual(record["keys"][position] in LEFT_HAND, record["keys"][position + 1] in LEFT_HAND)
                self.assertEqual(changed, record["keys"][:position] + record["keys"][position + 1] + record["keys"][position]
                                 + record["keys"][position + 2:])

    def test_accent_changes_are_real_pinyin_and_only_apply_where_the_sounds_exist(self):
        self.assertEqual(accent("nasal", "fen"), "feng")
        self.assertEqual(accent("nasal", "feng"), "fen")
        self.assertEqual(accent("nasal", "shang"), "shan")
        self.assertIsNone(accent("nasal", "tian"))
        self.assertEqual(accent("n_l", "nan"), "lan")
        self.assertEqual(accent("n_l", "li"), "ni")
        self.assertIsNone(accent("n_l", "wo"))
        self.assertEqual(accent("retroflex", "zhang"), "zang")
        self.assertIsNone(accent("retroflex", "sang"))
        self.assertEqual(accent("f_h", "fu"), "hu")
        self.assertIsNone(accent("f_h", "wo"))
        with self.assertRaises(ValueError):
            accent("unknown", "en")
        record = sentence("祝你生日快乐", ["zhu", "ni", "sheng", "ri", "kuai", "le"])
        for seed in range(20):
            changed, noise = mutate(record, "nasal", __import__("random").Random(seed))
            with self.subTest(seed=seed):
                self.assertEqual(changed, "zhunishenrikuaile")
                self.assertEqual((noise["from"], noise["to"]), ("sheng", "shen"))

    def test_budget_and_compound_errors(self):
        record = sentence("我明天去上海看朋友", ["wo", "ming", "tian", "qu", "shang", "hai", "kan", "peng", "you"])
        self.assertEqual(error_budget(record), 3)
        self.assertEqual(error_budget(sentence("上海", ["shang", "hai"])), 2)
        for seed in range(30):
            for count in (2, 3):
                changed, ops = compound(record, count, __import__("random").Random(seed))
                with self.subTest(seed=seed, count=count):
                    self.assertEqual(len(ops), count)
                    self.assertEqual(len({op["syllable"] for op in ops}), count)
                    self.assertNotEqual(changed, record["keys"])
        self.assertEqual(operation_label([]), "clean")
        self.assertEqual(operation_label([{"type": "drop"}]), "drop")
        self.assertEqual(operation_label([{"type": "drop"}, {"type": "nasal"}]), "x2")

    def test_multi_error_variants_are_deterministic_and_optional(self):
        record = {"id": "case", "text": "明天开会去上海", "keys": "mingtiankaihuiqushanghai", "quality_policy": "editorial",
                  "pinyin_segments": [{"text": "明天开会去上海", "keys": "mingtiankaihuiqushanghai", "kind": "zh",
                                       "syllables": ["ming", "tian", "kai", "hui", "qu", "shang", "hai"]}]}
        single = list(noise_cases([record], ["clean", "drop"], 52))
        self.assertEqual([case["id"].rsplit("~", 1)[-1] for case in single], ["clean", "drop"])
        first = list(noise_cases([record], ["clean", "drop"], 52, multi=True))
        second = list(noise_cases([record], ["clean", "drop"], 52, multi=True))
        self.assertEqual(first, second)
        self.assertEqual([case["id"].rsplit("~", 1)[-1] for case in first], ["clean", "drop", "x2"])
        self.assertTrue(all(case["expected"] == {"action": "commit", "text": "明天开会去上海"} for case in first))
        self.assertEqual(len(first[2]["noise_ops"]), 2)

