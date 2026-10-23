import logging
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from core import logs


class LogFileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        app_dir = patch.object(logs, "app_dir", return_value=Path(self.folder.name))
        app_dir.start()
        self.addCleanup(app_dir.stop)
        root = logging.getLogger()
        self.addCleanup(setattr, root, "level", root.level)
        self.addCleanup(setattr, threading, "excepthook", threading.excepthook)
        with patch.object(logs, "install_qt_handler"):
            self.handler = logs.setup_file_logging("9.8.7")
        self.addCleanup(root.removeHandler, self.handler)
        self.addCleanup(self.handler.close)

    def read(self):
        self.handler.flush()
        return logs.log_path().read_text(encoding="utf-8")

    def test_session_header_errors_in_order_and_secrets_hidden(self):
        token = "eyJhbGciOiJFUzI1NiJ9.eyJpc3MiOiJhcG15eCJ9.c2lnbmF0dXJlX3ZhbHVl"
        logging.info("routine progress line")
        logging.warning("first warning")
        logging.error("second error media-user-token=%s Bearer %s in %s", "A" * 60, token, Path.home() / "Music")

        def crash():
            raise RuntimeError("worker blew up")

        def fetch_details():
            try:
                {}["missing"]
            except KeyError as exc:
                logging.error(f"Could not load details: {exc}")

        worker = threading.Thread(target=crash, name="downloader")
        worker.start()
        worker.join()
        fetch_details()
        text = self.read()
        lines = [line for line in text.splitlines() if line.startswith("[")]
        self.assertRegex(lines[0], r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] INFO apmyx: ===== apmyx 9\.8\.7 started")
        self.assertNotIn("routine progress line", text)
        self.assertRegex(lines[1], r"WARNING test_logs\.test_session_header_errors_in_order_and_secrets_hidden:\d+: first warning")
        self.assertRegex(lines[2], r"ERROR test_logs\.test_session_header_errors_in_order_and_secrets_hidden:\d+: second error")
        self.assertRegex(lines[3], r"CRITICAL test_logs\.crash:\d+: Unhandled exception in thread downloader")
        self.assertIn("RuntimeError: worker blew up", text)
        self.assertRegex(lines[4], r"ERROR test_logs\.fetch_details:\d+: Could not load details")
        self.assertIn("Traceback (most recent call last)", text.split("Could not load details", 1)[1])
        self.assertIn("KeyError: 'missing'", text)
        self.assertNotIn("A" * 60, text)
        self.assertNotIn(token, text)
        self.assertNotIn(str(Path.home()), text)
        self.assertIn("~", lines[2])
        times = [re.match(r"^\[([^\]]+)\]", line)[1] for line in lines]
        self.assertEqual(times, sorted(times))

    def test_unwritable_folder_does_not_break_startup(self):
        with patch.object(logs, "log_dir", return_value=Path(self.folder.name) / "file-not-dir"):
            (Path(self.folder.name) / "file-not-dir").write_text("x")
            self.assertIsNone(logs.setup_file_logging("9.8.7"))


if __name__ == "__main__":
    unittest.main()
