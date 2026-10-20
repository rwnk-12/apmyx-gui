from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QFileDialog

APP = QApplication.instance() or QApplication([])

from core.controllers.library import artwork_thumbnail
from ui.lyrics_downloader_page import LocalTrackCard, LyricsDownloaderPage


def drain(page, timeout=10):
    deadline = time.monotonic() + timeout
    while page._build_jobs and time.monotonic() < deadline:
        APP.processEvents()


class LyricsPageTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from PyQt6.QtCore import QSettings
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        ini = str(Path(folder.name) / "options.ini")
        settings = patch("ui.lyrics_downloader_page.QSettings", side_effect=lambda *args: QSettings(ini, QSettings.Format.IniFormat))
        settings.start()
        self.addCleanup(settings.stop)
        self.controller = Mock()
        self.page = LyricsDownloaderPage(self.controller)
        self.page.current_path = "/music"

    def tearDown(self):
        self.page.deleteLater()
        APP.processEvents()

    def scan(self, folders=10, per_folder=500, with_lyrics=0):
        tracks = []
        for folder in range(folders):
            for index in range(per_folder):
                tracks.append({
                    "filepath": f"/music/album{folder:02d}/{index:04d}.m4a",
                    "title": f"Song {index}", "artist": "Artist", "album": f"Album {folder}",
                    "artwork": None, "has_lyrics": index < with_lyrics,
                })
        self.page.on_scan_results({"type": "scan_started", "data": {"total_files": len(tracks)}})
        for start in range(0, len(tracks), 100):
            self.page.on_scan_results({"type": "chunk", "data": tracks[start:start + 100]})
        started = time.monotonic()
        self.page.on_scan_results({"type": "complete", "data": {"total_found": len(tracks)}})
        return tracks, time.monotonic() - started

    def test_large_scan_builds_headers_only_and_expands_in_batches(self):
        tracks, elapsed = self.scan()
        self.assertLess(elapsed, 2.0)
        self.assertEqual(len(self.page.tracks), 5000)
        self.assertEqual(self.page.card_widgets, {})
        self.assertEqual(self.page.missing_lyrics_count, 5000)
        self.page._toggle_section("/music/album03")
        self.page._build_next_batch()
        self.assertEqual(len(self.page.card_widgets), 40)
        drain(self.page)
        self.assertEqual(len(self.page.card_widgets), 500)
        self.assertTrue(all(path.startswith("/music/album03/") for path in self.page.card_widgets))

    def test_download_all_keeps_four_in_flight_and_finishes_cleanly(self):
        tracks, _ = self.scan(folders=3, per_folder=20, with_lyrics=5)
        self.page._on_download_all_clicked()
        self.assertEqual(self.controller.download_lyrics_for_track.call_count, 4)
        self.assertEqual(len(self.page._queue), 45 - 4)
        self.page._on_download_all_clicked()
        self.page._on_download_all_section("/music/album00")
        self.assertEqual(self.page._run_total, 45)
        done = 0
        while self.page._inflight:
            filepath = next(iter(self.page._inflight))
            self.page.on_lyrics_download_finished(filepath, done % 3 != 0, "Done" if done % 3 else "Not Available")
            done += 1
            self.assertLessEqual(len(self.page._inflight), 4)
        self.assertEqual(done, 45)
        self.assertEqual(self.controller.download_lyrics_for_track.call_count, 45)
        self.assertFalse(self.page._busy())
        self.assertEqual(self.page.missing_lyrics_count, 15)
        info = self.page.sections["/music/album00"]
        self.assertEqual(info["found_count"] + info["missing_count"], info["total_count"])
        self.assertEqual((info["queued_total"], info["queued_done"]), (0, 0))

    def test_watcher_never_opens_folder_dialog_and_waits_for_downloads(self):
        self.scan(folders=1, per_folder=6)
        self.page._on_download_all_clicked()
        with patch.object(QFileDialog, "getExistingDirectory", side_effect=AssertionError("dialog opened")), \
                patch.object(self.page, "_start_scan") as rescan:
            self.page._on_directory_changed("/music")
            self.page._perform_rescan()
            rescan.assert_not_called()
            for filepath in list(self.page._inflight) + list(self.page._queue):
                self.page.on_lyrics_download_finished(filepath, True, "Done")
            for filepath in list(self.page._inflight):
                self.page.on_lyrics_download_finished(filepath, True, "Done")
            self.assertFalse(self.page._busy())
            self.page._watcher_reset_timer.stop()
            self.page._perform_rescan()
            rescan.assert_called_once_with("/music")

    def test_single_request_jumps_queue_and_stale_results_are_ignored(self):
        self.scan(folders=2, per_folder=10)
        self.page._on_download_all_section("/music/album00")
        target = "/music/album01/0009.m4a"
        self.page._on_get_lyrics_requested(target)
        self.assertEqual(self.page._queue[0], target)
        self.page._remove_section("/music/album00")
        self.assertEqual(list(self.page._queue), [target])
        self.page._remove_section("/music/album01")
        self.assertEqual(len(self.page._queue), 0)
        for filepath in list(self.page._inflight):
            self.page.on_lyrics_download_finished(filepath, True, "Done")
        self.page.on_lyrics_download_finished("/elsewhere/x.m4a", True, "Done")
        self.assertFalse(self.page._busy())

    def test_options_are_sent_with_each_request_and_disable_unused_controls(self):
        self.scan(folders=1, per_folder=2)
        self.page.format_box.setCurrentIndex(self.page.format_box.findData("text"))
        self.assertFalse(self.page.timing_box.isEnabled())
        self.assertFalse(self.page.translation_check.isEnabled())
        self.page.format_box.setCurrentIndex(self.page.format_box.findData("lrc"))
        self.page.timing_box.setCurrentIndex(self.page.timing_box.findData("syllable"))
        self.page.pronunciation_check.setChecked(False)
        self.page.translation_check.setChecked(True)
        self.page._on_download_all_clicked()
        request = self.controller.download_lyrics_for_track.call_args.args[0]
        self.assertEqual(request["options"], {"timing": "syllable", "format": "lrc", "extras": ["translation"]})
        self.assertNotIn("artwork", request)

    def test_card_states_and_thumbnail_are_prepared_off_the_ui_thread(self):
        image = QImage(600, 600, QImage.Format.Format_RGB32)
        image.fill(QColor("#c54863"))
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        cache = {}
        thumb = artwork_thumbnail(bytes(data), cache)
        self.assertEqual((thumb.width(), thumb.height()), (68, 68))
        self.assertIs(artwork_thumbnail(bytes(data), cache), thumb)
        self.assertEqual(len(cache), 1)
        self.assertIsNone(artwork_thumbnail(b"not an image"))
        card = LocalTrackCard({"filepath": "/m/a.m4a", "title": "A", "artist": "B", "artwork": thumb, "has_lyrics": False})
        self.assertEqual(card.action_button.property("state"), "get")
        card.update_status(False, "Queued")
        self.assertEqual((card.action_button.property("state"), card.action_button.isEnabled()), ("busy", False))
        card.update_status(True, "Done")
        self.assertEqual(card.action_button.property("state"), "view")
        card.update_status(False, "Not Available")
        self.assertEqual((card.action_button.property("state"), card.action_button.isEnabled()), ("unavailable", False))


class SkipReasonTests(unittest.TestCase):
    def test_skip_reason_reaches_the_summary_dialog(self):
        from PyQt6.QtWidgets import QTableWidget
        from core.download_worker import DownloadJobRunner
        from ui.download_job_widget import SkippedTracksDialog
        runner = DownloadJobRunner(1, {"wrapper": "applemusicdecrypt"}, 2, Mock(), "ALAC")
        skipped = []
        runner.signals.track_skipped.connect(lambda *args: skipped.append(args))
        runner.process_progress({"schema_version": 1, "type": "track_skip", "name": "Take On Me", "reason": "Already exists"})
        runner.process_progress({"schema_version": 1, "type": "track_skip", "name": "Other"})
        self.assertEqual(skipped, [(1, "Take On Me", "Already exists"), (1, "Other", "")])
        dialog = SkippedTracksDialog(["Take On Me", "Other"], 0, "ALAC", None, {"Take On Me": "Already exists"})
        table = dialog.findChild(QTableWidget)
        self.assertEqual(table.item(0, 1).text(), "Skipped (Already exists)")
        self.assertEqual(table.item(1, 1).text(), "Skipped (Not in ALAC)")
        dialog.deleteLater()


TTML = (
    '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:itunes="http://music.apple.com/lyric-ttml-internal" itunes:timing="Word">'
    '<body><div><p begin="1s" end="2s"><span begin="1s" end="1.5s">Hello </span><span begin="1.5s" end="2s">world</span></p></div></body></tt>'
)


class LyricsWorkerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from core.app import AppController
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.audio = Path(self.folder.name) / "song.m4a"
        self.audio.write_bytes(b"x")
        self.controller = AppController(storefront="us")
        self.addCleanup(self.controller.session.close)
        self.results = []
        self.controller.lyrics_download_finished.connect(lambda *args: self.results.append(args))
        self.config = {"wrapper": "applemusicdecrypt", "applemusicdecrypt-url": "https://wrapper.example", "applemusicdecrypt-api-key": "key"}

    def run_worker(self, options, songs=None, wrapper_ttml=TTML):
        songs = songs if songs is not None else [{"id": "42", "attributes": {"hasLyrics": True, "hasTimeSyncedLyrics": True}}]
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0, "data": {"lyrics": wrapper_ttml}}
        with patch("core.controllers.lyrics.load_config", return_value=self.config), \
                patch.object(self.controller, "_search_api", return_value={"results": {"songs": {"data": songs}}}) as search, \
                patch("requests.get", return_value=response) as get:
            self.controller._download_lyrics_for_track_worker(
                {"artist": "A", "title": "B", "album": "C", "options": options}, str(self.audio)
            )
        return search, get

    def test_wrapper_supplies_each_format_without_a_media_user_token(self):
        for options, extension, expected in (
            ({"timing": "syllable", "format": "lrc", "extras": []}, ".lrc", "[00:01.00]<00:01.00>Hello <00:01.50>world<00:02.00>"),
            ({"timing": "line", "format": "ttml", "extras": []}, ".ttml", '<tt xmlns="http://www.w3.org/ns/ttml"'),
            ({"timing": "line", "format": "text", "extras": []}, ".txt", "Hello world"),
        ):
            with self.subTest(format=options["format"]):
                search, get = self.run_worker(options)
                self.assertEqual(self.results[-1][1:], (True, "Done"))
                self.assertEqual(get.call_args.kwargs["params"]["syllable"], "1" if options["timing"] == "syllable" else "0")
                self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer key"})
                self.assertTrue(get.call_args.args[0].endswith("/lyrics"))
                content = self.audio.with_suffix(extension).read_text(encoding="utf-8")
                self.assertTrue(content.startswith(expected), content[:80])
                self.assertNotIn("ns0:", content)

    def test_songs_without_lyrics_skip_the_wrapper_and_existing_files_skip_search(self):
        search, get = self.run_worker({"format": "lrc"}, songs=[{"id": "9", "attributes": {"hasLyrics": False}}])
        self.assertEqual(self.results[-1][1:], (False, "Not Available"))
        get.assert_not_called()
        self.audio.with_suffix(".lrc").write_text("[00:01.00]x", encoding="utf-8")
        search, get = self.run_worker({"format": "lrc"})
        self.assertEqual(self.results[-1][1:], (True, "Exists"))
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
