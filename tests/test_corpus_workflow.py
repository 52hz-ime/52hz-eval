import json
import gzip
import tempfile
import unittest
from pathlib import Path

from tools.corpus_workflow import extract, load_index, sample, stats


class CorpusWorkflowTests(unittest.TestCase):
    def test_extracts_jsonl_fields_normalizes_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text("\n".join([
                json.dumps({"id": "a", "content": "  明天\n开会。 ", "history": ["上文"]}, ensure_ascii=False),
                json.dumps({"id": "b", "content": "明天 开会。"}, ensure_ascii=False),
                json.dumps({"id": "c", "content": "only english"}, ensure_ascii=False),
            ]) + "\n", encoding="utf-8")
            output = root / "records.jsonl"
            spec = {"id": "demo", "format": "jsonl", "text_fields": ["content"],
                    "context_fields": ["history"], "id_fields": ["id"], "url": "https://example.test"}
            records = extract(spec, source, output)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["text"], "明天 开会。")
            self.assertEqual(records[0]["context"], "上文")
            self.assertEqual(records[0]["source_record_id"], "a")
            self.assertEqual(list(json.loads(line)["id"] for line in output.read_text(encoding="utf-8").splitlines()),
                             [records[0]["id"]])

    def test_sampling_is_deterministic_and_marks_split(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jsonl"
            first.write_text("\n".join(json.dumps({"id": str(i), "source_id": "a", "text": f"句子{i}"}, ensure_ascii=False)
                                     for i in range(6)) + "\n", encoding="utf-8")
            second = root / "second.jsonl"
            second.write_text(json.dumps({"id": "duplicate", "source_id": "b", "text": "句子1"}, ensure_ascii=False) + "\n",
                              encoding="utf-8")
            one = root / "one.jsonl"
            two = root / "two.jsonl"
            selected_one = sample([first, second], one, 3, 52, "test")
            selected_two = sample([first, second], two, 3, 52, "test")
            self.assertEqual(selected_one, selected_two)
            self.assertTrue(all(row["split"] == "test" for row in selected_one))
            self.assertEqual(stats([one]), {"total": 3, "sources": {"a": 3}, "lengths": {"short": 3}})

    def test_sampling_writes_reproducibility_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text(json.dumps({"source_id": "a", "text": "测试句子"}, ensure_ascii=False) + "\n",
                              encoding="utf-8")
            manifest = root / "sample.manifest.json"
            sample([source], root / "sample.jsonl", 1, 52, "test", manifest)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["seed"], 52)
            self.assertEqual(payload["selected"], 1)
            self.assertEqual(payload["sources"], {"a": 1})

    def test_source_index_has_unique_ids(self):
        index = load_index(Path(__file__).parents[1] / "data" / "sources.json")
        self.assertIn("lccc_base", index)
        self.assertIn("clue_corpus_small", index)

    def test_conversation_rows_expand_turns_with_previous_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dialog.jsonl"
            source.write_text(json.dumps({"dialog": ["你好，今天忙吗？", "还好，下午要开会。", "那晚上一起吃饭。"]},
                                         ensure_ascii=False) + "\n", encoding="utf-8")
            records = extract({"id": "dialog", "format": "jsonl", "turns_field": "dialog",
                               "turn_text_fields": [], "id_fields": []}, source, root / "out.jsonl", min_chars=2)
            self.assertEqual([row["text"] for row in records], ["你好，今天忙吗？", "还好，下午要开会。", "那晚上一起吃饭。"])
            self.assertEqual(records[2]["context"], "你好，今天忙吗？\n还好，下午要开会。")

            tokenized = root / "tokenized.jsonl"
            tokenized.write_text(json.dumps({"dialog": ["你好 世 界", "再 见"]}, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
            compact = extract({"id": "tokenized", "format": "jsonl", "turns_field": "dialog",
                               "turn_text_fields": [], "join_tokens": True}, tokenized, root / "compact.jsonl", min_chars=2)
            self.assertEqual([row["text"] for row in compact], ["你好世界", "再见"])

    def test_json_root_array_and_directory_text_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "turns.json"
            json_path.write_text(json.dumps([["第一句", "第二句"]], ensure_ascii=False), encoding="utf-8")
            records = extract({"id": "json", "format": "json", "turn_text_fields": [], "id_fields": []},
                              json_path, root / "json-out.jsonl", min_chars=2)
            self.assertEqual(len(records), 2)
            text_dir = root / "texts"
            text_dir.mkdir()
            (text_dir / "a.txt").write_text("第一行\n", encoding="utf-8")
            (text_dir / "b.txt").write_text("第二行\n", encoding="utf-8")
            records = extract({"id": "text", "format": "text"}, text_dir, root / "text-out.jsonl", min_chars=2)
            self.assertEqual([row["text"] for row in records], ["第一行", "第二行"])

            compressed = root / "records.jsonl.gz"
            with gzip.open(compressed, "wt", encoding="utf-8") as handle:
                handle.write(json.dumps({"text": "压缩输入"}, ensure_ascii=False) + "\n")
            records = extract({"id": "gzip", "format": "jsonl", "text_fields": ["text"]},
                              compressed, root / "gzip-out.jsonl", min_chars=2)
            self.assertEqual([row["text"] for row in records], ["压缩输入"])
