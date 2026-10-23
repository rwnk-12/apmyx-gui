import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "backend/runtime"))

from backend.router.common import Events
from backend.router.gamdl_progress import GamdlProgress
from core.bridge_client import request_for
from core.download_worker import DownloadJobRunner
from PyQt6.QtWidgets import QApplication
from ui.download_job_widget import DownloadJobWidget

APP = QApplication.instance() or QApplication([])


class ProgressTests(unittest.TestCase):
    def test_multiple_streams_and_phases_never_reset_track_progress(self):
        output = io.StringIO()
        events = Events({}, output)
        events.progress.interval = 0
        progress = GamdlProgress(events)
        progress.reset(2)
        for _ in range(2):
            progress.start_stream()
            progress.report("downloading", 50, 50, 100)
            progress.finish_stream()
        progress.report("decrypting", 50)
        progress.report("decrypting", 100)
        progress.report("remuxing", 100)
        progress.report("tagging", 100)
        records = [json.loads(line)["data"] for line in output.getvalue().splitlines()]
        percents = [record["percent"] for record in records]
        self.assertEqual(percents, sorted(percents))
        self.assertEqual(percents[-1], 99)
        self.assertEqual(records[1]["phase_percent"], 25)
        self.assertEqual(records[4]["phase_percent"], 75)
        self.assertEqual(records[5]["downloaded_bytes"], 100)
        progress.reset()
        self.assertEqual(progress.percent, 0)
        self.assertEqual(progress.completed_bytes, 0)

    def test_gui_uses_phase_percentage_and_real_bytes(self):
        request = request_for("download", "https://music.apple.com/us/song/test/1", {"wrapper": "wrapper-v2"})
        runner = DownloadJobRunner(1, request, 1, Mock(), "ALAC")
        updates = []
        runner.signals.progress.connect(lambda *args: updates.append(args))
        runner.process_line('AMDL_PROGRESS::' + json.dumps({"type": "track_start", "name": "Song"}), False)
        runner.process_line('AMDL_PROGRESS::' + json.dumps({"type": "track_progress", "phase": "downloading", "phase_percent": 50, "percent": 30, "downloaded_bytes": 50, "total_bytes": 100}), False)
        self.assertIn("Downloading (50%)", updates[-1][1])
        self.assertEqual(runner.downloaded_bytes, 50)
        runner.process_line('AMDL_PROGRESS::' + json.dumps({"type": "track_progress", "phase": "decrypting", "phase_percent": 50, "percent": 77.5}), False)
        self.assertIn("Decrypting (50%)", updates[-1][1])
        self.assertEqual(updates[-1][2:], (77.5, 77.5))

    def test_unknown_total_shows_busy_and_resumes_at_actual_progress(self):
        widget = DownloadJobWidget(1, {"albumData": {}, "tracks": []}, Mock(), "ALAC")
        self.addCleanup(widget.close)
        widget.update_progress("Downloading...", -1, 30)
        self.assertEqual(widget.job_progress_bar.maximum(), 0)
        widget.update_progress("Decrypting (50%)", 77.5, 77.5)
        self.assertEqual(widget.job_progress_bar.maximum(), 1000)
        self.assertEqual(widget.job_progress_bar.value(), 775)
        widget.update_progress("Downloading...", -1, 77.5)
        widget.set_paused_ui()
        self.assertEqual(widget.job_progress_bar.maximum(), 1000)

    def test_finished_job_shows_elapsed_time_excluding_pauses(self):
        widget = DownloadJobWidget(1, {"albumData": {}, "tracks": []}, Mock(), "ALAC")
        self.addCleanup(widget.close)
        with patch("ui.download_job_widget.time.monotonic", side_effect=[0, 60, 500, 574]):
            widget.set_in_progress_ui()
            widget.set_paused_ui()
            widget._state = "queued"
            widget.set_in_progress_ui()
            widget.set_finished("Download complete.", True, [])
        self.assertEqual(widget.status_label.text(), "Download complete • 2m 14s")
        failed = DownloadJobWidget(2, {"albumData": {}, "tracks": []}, Mock(), "ALAC")
        self.addCleanup(failed.close)
        failed.set_finished("Cancelled.", False, [])
        self.assertEqual(failed.status_label.text(), "Cancelled.")

    def test_finished_job_shows_where_files_were_saved(self):
        from core.download_worker import saved_message
        album = os.path.join("C:\\Music", "apmyx-downloads", "ALAC", "Artist", "Hmm...")
        self.assertEqual(saved_message([]), "Download complete.")
        self.assertEqual(saved_message([album, album]), f"Saved to {album}")
        self.assertEqual(saved_message([os.path.join(album, "Disc 1"), os.path.join(album, "Disc 2")]), f"Saved to {album}")
        widget = DownloadJobWidget(1, {"albumData": {}, "tracks": []}, Mock(), "ALAC")
        self.addCleanup(widget.close)
        with patch("ui.download_job_widget.time.monotonic", side_effect=[0, 5]):
            widget.set_in_progress_ui()
            widget.set_finished(f"Saved to {album}", True, [])
        self.assertEqual(widget.status_label.text().replace("\u200b", ""), f"Saved to {album} • 5s")
        self.assertEqual(widget.status_label.toolTip(), album)

    def test_legacy_percentage_stays_unchanged(self):
        runner = DownloadJobRunner(1, request_for("download"), 1, Mock(), "ALAC")
        updates = []
        runner.signals.progress.connect(lambda *args: updates.append(args))
        runner.process_line('AMDL_PROGRESS::{"type":"track_progress","percent":42}', False)
        self.assertEqual(updates[-1][2:], (42, 42))

    def test_logging_initialization_does_not_duplicate_records(self):
        with patch("atexit.register"):
            from main import setup_logging

        output = io.StringIO()
        logger = logging.getLogger()
        with patch.object(logger, "handlers", []), patch.object(logger, "level", logger.level), patch.object(sys, "stdout", output), patch.object(sys, "excepthook", sys.excepthook), patch("main.setup_file_logging"):
            setup_logging()
            setup_logging()
            logging.info("one progress record")
            self.assertEqual(output.getvalue().count("one progress record"), 1)


class DownloadProgressTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / "backend/runtime/gamdl").is_dir():
            raise unittest.SkipTest("Build the pinned GAMDL runtime to run transfer integration tests.")

    async def test_real_http_worker_reports_bytes_and_preserves_output(self):
        await self.download_fixture(True)

    async def test_unknown_size_worker_reports_activity_without_fake_percentage(self):
        await self.download_fixture(False)

    async def test_worker_failure_reaches_the_caller(self):
        await self.download_fixture(True, failure=True)

    async def test_cancellation_stops_the_progress_worker(self):
        await self.download_fixture(True, cancel=True)

    async def test_hls_worker_reports_progress_and_preserves_fragment_order(self):
        await self.download_fixture(True, hls=True)

    async def download_fixture(self, known_size, failure=False, cancel=False, hls=False):
        from gamdl.downloader.base import AppleMusicBaseDownloader

        payload = bytes(range(256)) * (32768 if hls else 8192)
        segment_size = len(payload) // 8
        if hls:
            payload = b''.join(bytes([index]) * segment_size for index in range(8))

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if failure:
                    self.send_error(404)
                    return
                body = payload
                if self.path.endswith('.m3u8'):
                    body = ('#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXT-X-VERSION:3\n' + ''.join(f'#EXTINF:1,\nsegment-{index}.ts\n' for index in range(8)) + '#EXT-X-ENDLIST\n').encode()
                elif self.path.startswith('/segment-'):
                    index = int(self.path.split('-')[1].split('.')[0])
                    body = payload[index * segment_size:(index + 1) * segment_size]
                self.send_response(200)
                if known_size:
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for offset in range(0, len(body), 65536):
                        self.wfile.write(body[offset:offset + 65536])
                        self.wfile.flush()
                        time.sleep(0.15 if cancel else 0.025)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            updates = []
            active = asyncio.get_running_loop().create_future()

            def progress(*args, **kwargs):
                updates.append((args, kwargs))
                if args[2] and not active.done():
                    active.set_result(None)

            downloader = AppleMusicBaseDownloader(Mock(), silent=True, progress_callback=progress)
            with tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / "track.m4a"
                url = f"http://127.0.0.1:{server.server_port}/" + ('playlist.m3u8' if hls else 'audio')
                if failure:
                    with self.assertRaisesRegex(RuntimeError, 'yt-dlp failed'):
                        await downloader.download_stream(url, str(path))
                    return
                if cancel:
                    import psutil
                    before = {child.pid for child in psutil.Process().children(recursive=True)}
                    task = asyncio.create_task(downloader.download_stream(url, str(path)))
                    try:
                        await asyncio.wait_for(active, 15)
                        children = {child.pid for child in psutil.Process().children(recursive=True)} - before
                    finally:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    self.assertTrue(children)
                    survivors = []
                    for pid in children:
                        try:
                            child = psutil.Process(pid)
                            if child.status() == psutil.STATUS_ZOMBIE:
                                continue
                            command = " ".join(child.cmdline())
                        except psutil.NoSuchProcess:
                            continue
                        if "resource_tracker" not in command:
                            survivors.append(command)
                    self.assertFalse(survivors)
                    return
                await downloader.download_stream(url, str(path))
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(payload).digest())
            self.assertGreater(len(updates), 2)
            self.assertEqual(updates[-1][0][1], 100)
            self.assertEqual(updates[-1][0][2], len(payload))
            if known_size:
                self.assertTrue(any(0 < args[1] < 100 for args, _ in updates))
            else:
                self.assertTrue(any(args[1] is None for args, _ in updates))
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
