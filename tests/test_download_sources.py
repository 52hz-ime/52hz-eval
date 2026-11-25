import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.download_sources import download_file, hf_files


class DownloadWorkflowTests(unittest.TestCase):
    def test_existing_complete_file_is_skipped_without_curl(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "item.bin"
            target.write_bytes(b"ready")
            with patch("tools.download_sources.subprocess.run") as run:
                self.assertEqual(download_file("https://example.test/item", target, 5), "skip")
            run.assert_not_called()

    def test_huggingface_listing_filters_files_by_patterns(self):
        listing = [{"type": "file", "path": "film/train.json"},
                   {"type": "file", "path": "film/kb_film.json"},
                   {"type": "directory", "path": "film"}]
        self.assertEqual(hf_files(listing, ["film/*.json"]), ["film/kb_film.json", "film/train.json"])

    def test_download_command_retries_transient_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "item.bin"

            def fake_curl(command, check):
                Path(command[command.index("-o") + 1]).write_bytes(b"ready")

            with patch("tools.download_sources.subprocess.run") as run:
                run.side_effect = fake_curl
                download_file("https://example.test/item", target)
            command = run.call_args.args[0]
            self.assertIn("--retry-all-errors", command)
            self.assertIn("--http1.1", command)
