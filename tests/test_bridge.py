import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

import yaml
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from backend.bridge import adapter_for, dispatch
from backend.router.common import (
    BackendError,
    Events,
    snapshot,
    terminate_tree,
    validate_request,
)
from backend.router.gamdl import Adapter as GamdlAdapter, VIDEO_TEMPLATE_FIELDS, playlist_templates, probe_stream_info, template
from backend.router.legacy import Adapter as LegacyAdapter
from core.bridge_client import consume, request_for, start_process
from core.download_worker import DownloadJobRunner, DownloadWorker
from core.config import STOREFRONT_BACKUP
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
from ui.settings_page import SettingsPage


APP = QApplication.instance() or QApplication([])
URL = "https://music.apple.com/us/album/test/123"
UNICODE_BRIDGE = r"""
import os
from backend import bridge
class Adapter:
    def run(self, request, events):
        name = request['settings']['unicode-test']
        api_name = '\u6771\u4eac \U0001f3b5'
        print(api_name)
        events.emit('metadata', data={'name': name, 'api_name': api_name})
        return {'name': name, 'utf8_mode': os.environ.get('PYTHONUTF8')}
bridge.adapter_for = lambda wrapper: Adapter()
raise SystemExit(bridge.main())
"""


class BridgeTests(unittest.TestCase):
    def test_every_adapter_imports_when_the_bridge_runs_as_a_script(self):
        root = Path(__file__).resolve().parents[1]
        code = (
            "import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]];"
            "import bridge;"
            "[bridge.adapter_for(w) for w in ('applemusicdecrypt', 'legacy', 'wrapper-v2')]"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(root / "backend"), str(root / "backend" / "runtime")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_legacy_aac_and_video_do_not_require_tcp_wrapper(self):
        for quality, url in (
            ("AAC", URL),
            ("ALAC", "https://music.apple.com/us/music-video/test/123"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                request = validate_request(
                    {
                        "operation": "download",
                        "url": url,
                        "quality": quality,
                        "settings": {},
                    }
                )
                request["scratch"] = tmp

                def run(command, cwd, callback, **kwargs):
                    callback('AMDL_PROGRESS::{"type":"track_start"}', False)
                    callback('AMDL_SUMMARY::{"Success":1,"Error":0}', False)
                    return 0

                with (
                    patch.object(LegacyAdapter, "status") as status,
                    patch("backend.router.legacy.binary", return_value="engine"),
                    patch("backend.router.legacy.run_process", side_effect=run),
                ):
                    LegacyAdapter().run(request, Events(request, io.StringIO()))
                status.assert_not_called()

    def test_legacy_machine_metadata_and_selected_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = validate_request(
                {"operation": "probe", "url": URL, "track_ids": ["7"], "settings": {}}
            )
            request["scratch"] = tmp
            captured = {}

            def run(command, cwd, callback, payload=None, env=None):
                captured.update(env)
                callback("Error connecting to device: connection refused", True)
                callback("AMDL_JSON_START", False)
                callback('{"albumData":{},"tracks":[]}', False)
                callback("AMDL_JSON_END", False)
                return 0

            with (
                patch("backend.router.legacy.run_process", side_effect=run),
                patch("backend.router.legacy.binary", return_value="engine"),
            ):
                result = LegacyAdapter().run(request, Events(request, io.StringIO()))
            self.assertEqual(result["tracks"], [])
            self.assertEqual(captured["APMYX_TRACK_IDS"], "7")

    def test_legacy_playlists_use_playlist_song_format(self):
        for url, expected in (
            ("https://music.apple.com/us/playlist/mix/pl.u-1", "{PlaylistName} {SongName}"),
            (URL, "{SongName}"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                request = validate_request(
                    {
                        "operation": "download",
                        "url": url,
                        "settings": {
                            "wrapper": "legacy",
                            "song-file-format": "{SongName}",
                            "playlist-song-file-format": "{PlaylistName} {SongName}",
                        },
                    }
                )
                request["scratch"] = tmp

                def run(command, cwd, callback, **kwargs):
                    callback('AMDL_PROGRESS::{"type":"track_start"}', False)
                    callback('AMDL_SUMMARY::{"Success":1,"Error":0}', False)
                    return 0

                with (
                    patch.object(LegacyAdapter, "status"),
                    patch("backend.router.legacy.binary", return_value="engine"),
                    patch("backend.router.legacy.run_process", side_effect=run),
                ):
                    LegacyAdapter().run(request, Events(request, io.StringIO()))
                config = yaml.safe_load((Path(tmp) / "config.yaml").read_text(encoding="utf-8"))
                self.assertEqual(config["song-file-format"], expected)

    def test_legacy_partial_failure_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = validate_request(
                {"operation": "download", "url": URL, "settings": {}}
            )
            request["scratch"] = tmp

            def run(command, cwd, callback, **kwargs):
                callback('AMDL_PROGRESS::{"type":"track_start"}', False)
                callback('AMDL_SUMMARY::{"Success":1,"Error":1}', False)
                return 0

            with (
                patch.object(LegacyAdapter, "status"),
                patch("backend.router.legacy.binary", return_value="engine"),
                patch("backend.router.legacy.run_process", side_effect=run),
                self.assertRaises(BackendError),
            ):
                LegacyAdapter().run(request, Events(request, io.StringIO()))

    def test_selects_exact_adapter(self):
        for key, name in (
            ("legacy", "legacy"),
            ("wrapper-v2", "gamdl"),
        ):
            self.assertTrue(type(adapter_for(key)).__module__.endswith(name))
        for removed in ("unknown", "wrapper-lite"):
            with self.assertRaises(BackendError):
                adapter_for(removed)

    def test_removed_go_lite_engine_migrates_to_applemusicdecrypt(self):
        migrated = snapshot({"wrapper": "wrapper-lite", "wrapper-lite-url": "http://127.0.0.1:12345"})
        self.assertEqual(migrated["wrapper"], "applemusicdecrypt")
        self.assertEqual(migrated["applemusicdecrypt-url"], "http://127.0.0.1:12345")
        self.assertNotIn("wrapper-lite-url", migrated)
        kept = snapshot({"wrapper": "wrapper-lite", "wrapper-lite-url": "http://a:1", "applemusicdecrypt-url": "https://hosted.example"})
        self.assertEqual(kept["applemusicdecrypt-url"], "https://hosted.example")
        request = validate_request({"operation": "status", "wrapper": "wrapper-lite", "settings": {}})
        self.assertEqual(request["wrapper"], "applemusicdecrypt")

    def test_dispatch_has_exactly_one_terminal_event(self):
        for error in (
            None,
            BackendError("wrapper_unavailable", "Offline", True),
            ImportError(name="missing"),
        ):
            output = io.StringIO()
            adapter = Mock()
            adapter.run.side_effect = error
            adapter.run.return_value = {"ok": True}
            with patch("backend.bridge.adapter_for", return_value=adapter):
                code = dispatch(request_for("status"), output)
            records = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(sum(r["event"] == "complete" for r in records), 1)
            self.assertEqual(records[-1]["success"], error is None)
            self.assertEqual(code, 0 if error is None else 1)

    def test_invalid_requests_fail_before_backend(self):
        for request in (
            {},
            {"operation": "probe", "url": "file:///a"},
            {"operation": "status", "wrapper": "bad"},
            {"version": 2, "operation": "status"},
            {"operation": "download", "url": URL, "track_ids": []},
        ):
            with self.subTest(request=request), self.assertRaises(BackendError):
                validate_request(request)

    def test_selected_track_progress_is_relative_to_selection(self):
        stream = io.StringIO()
        events = Events({"track_ids": ["7"]}, stream)
        events.emit(
            "progress", data={"type": "track_start", "track_num": 7, "total_tracks": 20}
        )
        event = json.loads(stream.getvalue())
        self.assertEqual(event["data"]["track_num"], 1)
        self.assertEqual(event["data"]["total_tracks"], 1)

    def test_settings_snapshot_and_unsupported_flags(self):
        original = {"wrapper": "legacy", "tag-options": {"write-title": True}}
        frozen = snapshot(original)
        original["tag-options"]["write-title"] = False
        self.assertTrue(frozen["tag-options"]["write-title"])
        with self.assertRaises(BackendError):
            validate_request(
                {
                    "operation": "download",
                    "url": URL,
                    "settings": {
                        "wrapper": "wrapper-v2",
                        "save-animated-artwork": True,
                    },
                }
            )

    def test_wrapper_v2_music_video_names_use_video_tokens(self):
        self.assertEqual(template("{ArtistName} - {VideoName}", VIDEO_TEMPLATE_FIELDS), "{artist} - {title}")
        self.assertEqual(template("{ReleaseYear} [{VideoID}]", VIDEO_TEMPLATE_FIELDS), "{date:%Y} [{title_id}]")
        with self.assertRaises(BackendError):
            template("{SongNumber}", VIDEO_TEMPLATE_FIELDS)

    def test_wrapper_v2_playlist_tracks_use_playlist_folder_and_format(self):
        from types import SimpleNamespace
        from backend.router.gamdl import RUNTIME

        sys.path.insert(0, str(RUNTIME))
        try:
            from gamdl.downloader.base import AppleMusicBaseDownloader
            from gamdl.interface.types import MediaTags, PlaylistTags
        except ImportError:
            self.skipTest("Wrapper v2 runtime is not built")
        finally:
            sys.path.remove(str(RUNTIME))
        settings = {
            "playlist-folder-format": "{PlaylistName}",
            "playlist-song-file-format": "{DiscNumber}-{SongNumber}. {ArtistName} - {SongName}",
        }
        folder, name = playlist_templates(settings)
        paths = SimpleNamespace(
            output_path="out",
            album_folder_template=folder,
            compilation_folder_template=folder,
            no_album_folder_template=folder,
            single_disc_file_template=name,
            multi_disc_file_template=name,
            no_album_file_template=name,
            playlist_folder_template=folder,
            playlist_file_template="{playlist_title}",
            _sanitize_string=lambda value, ext=None: value + (ext or ""),
        )
        playlist = PlaylistTags(artist="A", playlist_id="pl.1", title="Mix", track=7)
        song = MediaTags(album="Album", artist="Artist", title="Song", track=3, disc=2, disc_total=2)
        path = AppleMusicBaseDownloader.get_final_path(paths, song, ".m4a", playlist)
        self.assertEqual(Path(path), Path("out/Mix/1-07. Artist - Song.m4a"))
        path = AppleMusicBaseDownloader.get_playlist_file_path(paths, playlist)
        self.assertEqual(Path(path), Path("out/Mix/Mix.m3u8"))
        folder, name = playlist_templates({**settings, "use-song-metadata-for-playlist-numbering": True})
        paths.single_disc_file_template = paths.multi_disc_file_template = name
        path = AppleMusicBaseDownloader.get_final_path(paths, song, ".m4a", playlist)
        self.assertEqual(Path(path), Path("out/Mix/2-03. Artist - Song.m4a"))
        with self.assertRaises(BackendError):
            playlist_templates({"playlist-folder-format": "{SongName}"})

    def test_wrapper_v2_probe_checks_every_codec_from_one_fetch(self):
        calls = []

        class Song:
            codec_priority = None

            async def get_stream_info(self, media_id, is_library, webplayback=None, playback=None):
                codec = self.codec_priority[0]
                calls.append((codec, playback))
                if codec == "atmos":
                    raise ValueError("not available")
                return SimpleNamespace(audio_track=SimpleNamespace(codec=codec))

        song = Song()
        available = {}
        probe = probe_stream_info(song, ["alac", "atmos", "aac-web"], available)
        info = asyncio.run(probe("1", False, {"web": 1}, {"playback": 1}))
        self.assertEqual(info.audio_track.codec, "alac")
        self.assertEqual([codec for codec, _ in available["1"]], ["alac", "aac-web"])
        self.assertEqual(calls, [(codec, {"playback": 1}) for codec in ("alac", "atmos", "aac-web")])
        self.assertEqual(song.codec_priority, ["alac", "atmos", "aac-web"])

    def test_gamdl_version_auth_and_native_readiness(self):
        settings = snapshot({"wrapper": "wrapper-v2"})
        for me, code in (
            ({"version": "bad"}, "incompatible_wrapper"),
            (
                {"version": "0.0.2", "auth": {"state": "logged_out"}},
                "authentication_required",
            ),
            (
                {"version": "0.0.2", "auth": {"state": "authenticated"}, "runtime": {}},
                "wrapper_unavailable",
            ),
        ):
            with (
                patch(
                    "backend.router.gamdl.http_json", side_effect=[{"status": "ok"}, me]
                ),
                self.assertRaises(BackendError) as exc,
            ):
                GamdlAdapter().status(settings)
            self.assertEqual(exc.exception.code, code)

    def test_gamdl_template_translation(self):
        self.assertEqual(template("{SongNumber}. {SongName}"), "{track:02d}. {title}")
        with self.assertRaises(BackendError):
            template("{Unknown}")

    def test_consumer_rejects_malformed_or_missing_completion(self):
        for content in ("invalid\n", json.dumps({"version": 1, "event": "log"}) + "\n"):
            process = Mock(stdout=io.StringIO(content), stderr=io.StringIO(""))
            process.wait.return_value = 0
            process.poll.return_value = 0
            with self.assertRaises(BackendError):
                consume(process, lambda event: None)

    def test_partial_failure_is_not_success(self):
        records = [
            {
                "version": 1,
                "event": "error",
                "code": "download_failed",
                "message": "One track failed",
            },
            {"version": 1, "event": "complete", "success": False},
        ]
        process = Mock(
            stdout=io.StringIO("\n".join(map(json.dumps, records))),
            stderr=io.StringIO(""),
        )
        process.wait.return_value = 1
        process.poll.return_value = 1
        with self.assertRaisesRegex(BackendError, "One track failed"):
            consume(process, lambda event: None)

    def test_actual_bridge_process_rejects_unknown_wrapper(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "backend/bridge.py")],
            input=json.dumps({"operation": "status", "wrapper": "bad"}),
            capture_output=True,
            text=True,
            timeout=10,
        )
        records = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(records[0]["code"], "invalid_wrapper")
        self.assertEqual(records[-1]["event"], "complete")

    def test_bridge_preserves_unicode_with_windows_default_encoding(self):
        name = "\u65e5\u672c\u8a9e \u2014 \U0001f3b5"
        request = request_for("status", settings={"unicode-test": name})
        process = subprocess.run(
            [sys.executable, "-c", UNICODE_BRIDGE],
            input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"},
            cwd=ROOT,
            timeout=10,
        )
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8"))
        records = [json.loads(line) for line in process.stdout.decode("utf-8").splitlines()]
        self.assertEqual(records[0]["data"]["name"], name)
        self.assertEqual(records[0]["data"]["api_name"], "\u6771\u4eac \U0001f3b5")
        self.assertEqual(records[-1]["result"]["name"], name)
        self.assertEqual(sum(record["event"] == "complete" for record in records), 1)
        self.assertIn("\u6771\u4eac \U0001f3b5", process.stderr.decode("utf-8"))

    def test_gui_launches_bridge_in_utf8_without_changing_parent_environment(self):
        name = "\u65e5\u672c\u8a9e \U0001f3b5"
        request = request_for("status", settings={"unicode-test": name})
        with (
            patch.dict(os.environ, {"PYTHONIOENCODING": "cp1252:strict", "PYTHONUTF8": "0"}),
            patch("core.bridge_client.command", return_value=[sys.executable, "-c", UNICODE_BRIDGE]),
            tempfile.TemporaryDirectory() as scratch,
        ):
            result = consume(start_process(request, scratch), lambda event: None, request["request_id"])
            self.assertEqual(result["name"], name)
            self.assertEqual(result["utf8_mode"], "1")
            self.assertEqual(os.environ["PYTHONIOENCODING"], "cp1252:strict")
            self.assertEqual(os.environ["PYTHONUTF8"], "0")

    def test_cancellation_terminates_descendants(self):
        import psutil

        code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)"
        parent = subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, text=True
        )
        child = int(parent.stdout.readline())
        try:
            terminate_tree(parent)
            parent.wait(timeout=5)
            self.assertFalse(psutil.pid_exists(child))
        finally:
            terminate_tree(parent)
            parent.stdout.close()


class GuiBridgeTests(unittest.TestCase):
    def test_classify_error_keeps_message_and_separates_timeouts_from_wrapper_failures(self):
        from backend.router.common import classify_error
        cases = {
            "Task execution timed out": ("network_error", True),
            "HTTPSConnectionPool(host='aod.itunes.apple.com'): Read timed out.": ("network_error", True),
            "[WinError 10061] No connection could be made because the target machine actively refused it": ("wrapper_unavailable", True),
            "HTTP 401 Unauthorized": ("authentication_required", False),
            "Lossless audio does not exist": ("backend_failed", False),
        }
        for message, (code, retryable) in cases.items():
            failure = classify_error(message)
            self.assertEqual((failure.code, failure.retryable), (code, retryable), message)
            self.assertIn(message, str(failure))

    def test_saved_srt_lyrics_format_falls_back_to_lrc(self):
        request = validate_request({"operation": "status", "settings": {"lrc-format": "srt"}})
        self.assertEqual(request["settings"]["lrc-format"], "lrc")
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "settings.yaml"
            config.write_text("lrc-format: srt\n", encoding="utf-8")
            parent = QMainWindow()
            page = SettingsPage(str(config), parent)
            self.assertEqual(page.config["lrc-format"], "lrc")
            self.assertEqual(page.widgets["lrc-format"].currentText(), "LRC")
            self.assertEqual(page.widgets["lrc-format"].findText("SRT"), -1)
            parent.close()

    def test_wrapper_unavailable_names_target_and_cause_without_credentials(self):
        import requests
        from backend.router.common import http_json
        refused = requests.ConnectionError(
            "HTTPConnectionPool(host='127.0.0.1', port=12340): Max retries exceeded "
            "(Caused by NewConnectionError('[WinError 10061] No connection could be made because the target machine actively refused it'))"
        )
        with patch("backend.router.common.requests.get", side_effect=refused):
            with self.assertRaises(BackendError) as caught:
                http_json("http://user:secret@127.0.0.1:12340/", "/status")
        self.assertEqual(caught.exception.code, "wrapper_unavailable")
        self.assertIn("http://127.0.0.1:12340/status: [WinError 10061]", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        with patch("backend.router.common.requests.get", side_effect=requests.ConnectTimeout("x")):
            with self.assertRaises(BackendError) as caught:
                http_json("https://wrapper.example", "/status")
        self.assertIn("https://wrapper.example/status: timed out", str(caught.exception))

    def test_wrapper_badge_reports_the_selected_wrapper_connection(self):
        from PyQt6.QtWidgets import QPushButton
        from ui.main_window.mixins.ui_setup_features import UiSetupFeatures, WrapperStatusTask

        class Window(QMainWindow, UiSetupFeatures):
            pass

        window = Window()
        self.addCleanup(window.close)
        window.quality_info_badge = QPushButton(window)
        window._on_wrapper_status("applemusicdecrypt", True, "")
        self.assertEqual(window.quality_info_badge.text(), "Wrapper Lite connected")
        window._on_wrapper_status("wrapper-v2", False, "Wrapper v2 is not reachable at http://127.0.0.1:80.")
        self.assertEqual(window.quality_info_badge.text(), "Wrapper v2 not connected")
        self.assertIn("127.0.0.1:80", window.quality_info_badge.toolTip())
        window._set_wrapper_badge("checking", "legacy", "")
        self.assertEqual(window.quality_info_badge.text(), "Checking Legacy Wrapper...")

        results = []
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as elsewhere:
            Path(tmp, "config.yaml").write_text("wrapper: legacy\n", encoding="utf-8")
            Path(elsewhere, "config.yaml").write_text("wrapper: wrapper-v2\n", encoding="utf-8")
            cwd = os.getcwd()
            os.chdir(elsewhere)
            try:
                for outcome in (None, BackendError("wrapper_unavailable", "Legacy Wrapper is offline.")):
                    task = WrapperStatusTask()
                    task.signals.finished.connect(lambda *args: results.append(args))
                    with patch("core.bridge_client.run_request", side_effect=outcome) as run, \
                            patch("ui.main_window.mixins.ui_setup_features.config_path", return_value=Path(tmp, "config.yaml")):
                        task.run()
                    self.assertEqual(run.call_args.args[0]["operation"], "status")
            finally:
                os.chdir(cwd)
        self.assertEqual(results, [("legacy", True, ""), ("legacy", False, "Legacy Wrapper is offline.")])

    def test_artist_page_builds_cards_in_batches_and_loads_visible_artwork(self):
        from PyQt6.QtCore import QObject, pyqtSignal
        import ui.artist.artist_card as card_module
        from ui.artist.artist_discography_page import ArtistDiscographyPage

        class Controller(QObject):
            artist_discography_loaded = pyqtSignal(list)

            def resolve_artist(self, url):
                pass

        items = [
            {"id": str(i), "type": "albums", "attributes": {
                "name": f"Release {i}", "artistName": "A", "releaseDate": f"20{i % 25:02d}-01-01",
                "url": f"https://music.apple.com/us/album/{i}", "artwork": {"url": "https://example.invalid/{w}x{h}.jpg"},
            }}
            for i in range(300)
        ]
        started = []
        window = QMainWindow()
        self.addCleanup(window.close)
        window.card_widgets = {}
        with patch.object(card_module.ARTWORK_POOL, "start", side_effect=started.append):
            page = ArtistDiscographyPage(Controller(), {"name": "A", "appleMusicUrl": "x"})
            window.setCentralWidget(page)
            window.resize(1200, 800)
            window.show()
            APP.processEvents()
            page.populate_album_list(items)
            self.assertLess(page.grid_layouts["albums"].count(), len(items))
            while page._build_queue:
                page._build_next_batch()
            APP.processEvents()
            page._load_visible_artwork()
        self.assertEqual(page.grid_layouts["albums"].count(), len(items))
        self.assertTrue(0 < len(started) < len(items))
        visible = len(started)
        with patch.object(card_module.ARTWORK_POOL, "start", side_effect=started.append):
            for _ in range(5):
                APP.processEvents()
            scrollbar = page._get_current_view().verticalScrollBar()
            self.assertGreater(scrollbar.maximum(), 0)
            scrollbar.setValue(scrollbar.maximum() // 2)
            self.assertLess(page._artwork_timer.remainingTime(), 1000)
            page._load_visible_artwork()
        self.assertTrue(visible < len(started) < len(items))
        with patch.object(page, "download_requested") as download:
            page._on_download_all_clicked()
        self.assertEqual(len(download.emit.call_args.args[0]), len(items))

    def test_wrapper_error_dialog_size_does_not_grow_with_errors(self):
        from ui.main_window.dialogs import WrapperErrorDialog
        short = WrapperErrorDialog("wrapper_unavailable: one line")
        long = WrapperErrorDialog("\n".join(f"wrapper_unavailable: error {i} " + "x" * 200 for i in range(40)))
        self.assertEqual(short.size(), long.size())
        short.close()
        long.close()

    def test_invalid_amd_settings_do_not_save_or_close_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / 'settings.yaml'), parent)
            original = Path(page.config_path).read_bytes()
            closed = []
            page.back_requested.connect(lambda: closed.append(True))
            page.widgets['amd-mv-segment-concurrency'].setText('100')
            with patch('ui.settings_page.QMessageBox.warning') as warning:
                page._on_save()
            warning.assert_called_once()
            self.assertFalse(closed)
            self.assertEqual(Path(page.config_path).read_bytes(), original)
            page.widgets['amd-mv-segment-concurrency'].setText('4')
            with patch.object(page, '_write', return_value=False):
                page._on_save()
            self.assertFalse(closed)
            self.assertTrue(page._dirty)
            parent.close()

    def test_blank_integer_settings_are_rejected_instead_of_saved_as_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / 'settings.yaml'), parent)
            original = Path(page.config_path).read_bytes()
            for key in ('amd-download-timeout', 'limit-max'):
                page.widgets[key].setText('')
                with patch('ui.settings_page.QMessageBox.warning') as warning:
                    self.assertFalse(page._on_apply())
                warning.assert_called_once()
                self.assertEqual(Path(page.config_path).read_bytes(), original)
                page.widgets[key].setText(str(page.DEFAULTS[key]))
            page.widgets['amd-download-timeout'].setText('0')
            self.assertTrue(page._on_apply())
            self.assertEqual(page.config['amd-download-timeout'], 0)
            parent.close()

    def test_amd_settings_pages_save_native_controls_and_preserve_legacy_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            path = Path(tmp) / "settings.yaml"
            path.write_text("wrapper: applemusicdecrypt\ntag-options:\n  write-title: false\nmax-memory-limit: 512\n", encoding="utf-8")
            page = SettingsPage(str(path), parent)
            self.assertIn("Metadata Tagging", page._iter_category_names_in_order())
            self.assertEqual(page._iter_category_names_in_order()[-1], "Wrapper")
            self.assertFalse(page.widgets["tag-options.write-title"].isChecked())
            self.assertTrue(page.widgets["tag-options.write-album"].isChecked())
            for key in ("get-m3u8-mode", "atmos-max", "max-memory-limit", "save-animated-artwork"):
                self.assertTrue(page.wrapper_rows[key][1].isHidden(), key)
            self.assertFalse(page.wrapper_rows["media-user-token"][1].isHidden())
            page.widgets["amd-max-bit-depth"].setCurrentText("16")
            page.widgets["amd-download-timeout"].setText("0")
            page.widgets["amd-mv-segment-concurrency"].setText("8")
            page.widgets["amd-stream-decrypt"].setChecked(False)
            page.widgets["save-cover-file"].setChecked(True)
            page.widgets["playlist-song-file-format"].setText("{PlaylistName}-{SongNumber}")
            mode = page.widgets["lyrics-mode"]
            mode.setCurrentIndex(mode.findData("unsynced"))
            self.assertFalse(page.widgets["lrc-format"].isEnabled())
            page._on_apply()
            reopened = SettingsPage(str(path), parent)
            actual = reopened._collect()
            self.assertEqual(actual["amd-max-bit-depth"], 16)
            self.assertEqual(actual["amd-download-timeout"], 0)
            self.assertEqual(reopened.widgets["amd-download-timeout"].text(), "0")
            self.assertEqual(actual["amd-mv-segment-concurrency"], 8)
            self.assertEqual(actual["lyrics-mode"], "unsynced")
            self.assertFalse(actual["amd-stream-decrypt"])
            self.assertTrue(actual["save-cover-file"])
            self.assertEqual(actual["max-memory-limit"], 512)
            reopened.widgets["wrapper"].setCurrentIndex(reopened.widgets["wrapper"].findData("legacy"))
            self.assertTrue(reopened.wrapper_rows["amd-download-timeout"][1].isHidden())
            self.assertFalse(reopened.wrapper_rows["max-memory-limit"][1].isHidden())
            self.assertTrue(reopened.widgets["lrc-format"].isEnabled())
            reopened.widgets["wrapper"].setCurrentIndex(reopened.widgets["wrapper"].findData("applemusicdecrypt"))
            reopened._apply_metadata_preset("full")
            self.assertTrue(all(
                widget.isChecked() for key, widget in reopened.widgets.items() if key.startswith("tag-options.")
            ))
            with patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), patch.object(reopened, "_show_info_popup"):
                reopened._on_reset()
            self.assertEqual(reopened._collect()["amd-max-bit-depth"], 24)
            self.assertEqual(reopened._collect()["lyrics-mode"], "synced")
            self.assertTrue(reopened.widgets["lrc-format"].isEnabled())
            parent.close()

    def test_wrapper_reset_restores_defaults_and_preserves_download_settings(self):
        for wrapper in ("applemusicdecrypt", "legacy", "wrapper-v2"):
            with self.subTest(wrapper=wrapper), tempfile.TemporaryDirectory() as tmp:
                parent = QMainWindow()
                page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
                page.widgets["storefront"].setText("gb")
                page.widgets["wrapper"].setCurrentIndex(page.widgets["wrapper"].findData(wrapper))
                for key, value in {
                    "applemusicdecrypt-url": "https://wrapper.example",
                    "applemusicdecrypt-api-key": "fixture-wrapper-key",
                    "wrapper-v2-url": "http://localhost:18080",
                    "wrapper-v2-decrypt-host": "localhost",
                    "wrapper-v2-decrypt-port": "10021",
                    "decrypt-m3u8-port": "localhost:10022",
                    "get-m3u8-port": "localhost:20022",
                    "media-user-token": "fixture-media-token",
                    "alac-save-folder": "custom-output",
                    "song-file-format": "{SongName}",
                }.items():
                    page.widgets[key].setText(value)
                page._set_applemusicdecrypt_regions(["jp", "us"])
                combo = page.widgets["applemusicdecrypt-storefront"]
                combo.setCurrentIndex(combo.findData("jp"))
                page._on_apply()
                saved = Path(page.config_path).read_bytes()
                page.widgets["alac-save-folder"].setText("unsaved-output")
                wrapper_tab = next(button for button in page.nav_button_group.buttons() if button.text() == "Wrapper")
                wrapper_tab.click()
                index = page.content_stack.currentIndex()
                with patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                    page.wrapper_reset.click()
                actual = page._collect()
                for key in ("wrapper", "applemusicdecrypt-url", "applemusicdecrypt-api-key", "applemusicdecrypt-storefront", "wrapper-v2-url", "wrapper-v2-decrypt-host", "wrapper-v2-decrypt-port", "decrypt-m3u8-port", "get-m3u8-port"):
                    self.assertEqual(actual[key], page.DEFAULTS[key], key)
                self.assertEqual(actual["storefront"], "gb")
                self.assertNotIn(STOREFRONT_BACKUP, actual)
                self.assertEqual(actual["media-user-token"], "fixture-media-token")
                self.assertEqual(actual["alac-save-folder"], "unsaved-output")
                self.assertEqual(actual["song-file-format"], "{SongName}")
                self.assertTrue(page.widgets["storefront"].isEnabled())
                self.assertEqual(combo.count(), 0)
                self.assertIn("Check connection", combo.placeholderText())
                self.assertTrue(page.wrapper_check.isEnabled())
                self.assertTrue(page._dirty)
                self.assertEqual(page.content_stack.currentIndex(), index)
                self.assertEqual(Path(page.config_path).read_bytes(), saved)
                page._on_apply()
                reopened = SettingsPage(page.config_path, parent)
                self.assertEqual(reopened.widgets["wrapper"].currentData(), "applemusicdecrypt")
                self.assertEqual(reopened.widgets["applemusicdecrypt-api-key"].text(), "")
                self.assertEqual(reopened.widgets["storefront"].text(), "gb")
                parent.close()

    def test_wrapper_reset_can_be_declined_or_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
            page.widgets["applemusicdecrypt-api-key"].setText("fixture-wrapper-key")
            page.widgets["wrapper"].setCurrentIndex(page.widgets["wrapper"].findData("legacy"))
            page._on_apply()
            original = page._collect()
            with patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
                page.wrapper_reset.click()
            self.assertEqual(page._collect(), original)
            self.assertFalse(page._dirty)
            with patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                page.wrapper_reset.click()
            with patch.object(page, "_confirm_discard", return_value=True):
                page._on_cancel()
            self.assertEqual(page._collect(), original)
            parent.close()

    def test_wrapper_reset_ignores_pending_connection_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
            page.thread_pool = Mock()
            page._check_wrapper()
            pending = page._wrapper_check_worker
            with patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                page.wrapper_reset.click()
            message = page.wrapper_status.text()
            with patch("ui.settings_page.run_request", return_value={"regions": ["jp"]}):
                pending.run()
            self.assertEqual(page.wrapper_status.text(), message)
            self.assertEqual(page.widgets["applemusicdecrypt-storefront"].count(), 0)
            page._check_wrapper()
            current = page._wrapper_check_worker
            with patch("ui.settings_page.run_request", return_value={"regions": ["jp"]}):
                pending.run()
            self.assertIs(page._wrapper_check_worker, current)
            self.assertFalse(page.wrapper_check.isEnabled())
            with patch("ui.settings_page.run_request", return_value={"regions": ["us"]}):
                current.run()
            self.assertEqual(page.widgets["applemusicdecrypt-storefront"].currentData(), "us")
            self.assertTrue(page.wrapper_check.isEnabled())
            parent.close()

    def test_amd_storefront_cancel_restores_original_sync_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            path = Path(tmp) / "settings.yaml"
            path.write_text("wrapper: applemusicdecrypt\nstorefront: gb\napplemusicdecrypt-storefront: jp\n", encoding="utf-8")
            page = SettingsPage(str(path), parent)
            self.assertEqual(page.widgets["storefront"].text(), "jp")
            selector = page.widgets["wrapper"]
            selector.setCurrentIndex(selector.findData("legacy"))
            page.widgets["storefront"].setText("in")
            with patch.object(page, "_confirm_discard", return_value=True):
                page._on_cancel()
            self.assertEqual(page.widgets["wrapper"].currentData(), "applemusicdecrypt")
            self.assertEqual(page.widgets["storefront"].text(), "jp")
            page.widgets["wrapper"].setCurrentIndex(page.widgets["wrapper"].findData("legacy"))
            self.assertEqual(page.widgets["storefront"].text(), "gb")
            parent.close()

    def test_amd_connection_synchronizes_saved_storefront_and_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
            page.thread_pool = Mock()
            page.widgets["storefront"].setText("gb")
            combo = page.widgets["applemusicdecrypt-storefront"]
            self.assertIsNone(combo.currentData())
            self.assertIn("Check connection", combo.placeholderText())
            with patch("ui.settings_page.run_request", return_value={"online": True, "regions": ["jp", "us"]}):
                page._check_wrapper()
                page._wrapper_check_worker.run()
            self.assertEqual({combo.itemData(i) for i in range(combo.count())}, {"jp", "us"})
            self.assertEqual(combo.itemText(combo.findData("jp")), "Japan (JP)")
            combo.setCurrentIndex(combo.findData("jp"))
            self.assertEqual(page._collect()["storefront"], "jp")
            self.assertEqual(page._collect()[STOREFRONT_BACKUP], "gb")
            self.assertFalse(page.widgets["storefront"].isEnabled())
            self.assertEqual(page._collect()["applemusicdecrypt-storefront"], "jp")
            page._on_apply()
            restored = SettingsPage(page.config_path, parent)
            self.assertEqual(restored.widgets["applemusicdecrypt-storefront"].currentData(), "jp")
            self.assertEqual(restored.widgets["storefront"].text(), "jp")
            worker = DownloadWorker(Mock())
            worker.queue_paused = True
            media = {"albumData": {}, "tracks": [{"trackData": {"id": "7"}}]}
            with patch.object(worker, "_get_latest_config", return_value=page._collect()):
                worker.add_job_to_queue(1, media, "AAC", URL)
            combo.setCurrentIndex(combo.findData("us"))
            saved = worker.download_queue[0]["backend_settings"]
            self.assertEqual(saved["applemusicdecrypt-storefront"], "jp")
            self.assertEqual(saved["storefront"], "jp")
            worker.add_job_to_queue(2, media, "AAC", URL, backend_settings=saved)
            self.assertEqual(worker.download_queue[1]["backend_settings"]["applemusicdecrypt-storefront"], "jp")
            restored.widgets["wrapper"].setCurrentIndex(restored.widgets["wrapper"].findData("legacy"))
            self.assertTrue(restored.wrapper_rows["applemusicdecrypt-storefront"][1].isHidden())
            self.assertEqual(restored.widgets["storefront"].text(), "gb")
            self.assertTrue(restored.widgets["storefront"].isEnabled())
            restored.widgets["storefront"].setText("in")
            restored.widgets["wrapper"].setCurrentIndex(restored.widgets["wrapper"].findData("applemusicdecrypt"))
            self.assertEqual(restored.widgets["storefront"].text(), "jp")
            self.assertEqual(restored._collect()[STOREFRONT_BACKUP], "in")
            restored._on_apply()
            reopened = SettingsPage(page.config_path, parent)
            reopened.widgets["wrapper"].setCurrentIndex(reopened.widgets["wrapper"].findData("wrapper-v2"))
            self.assertEqual(reopened.widgets["storefront"].text(), "in")
            with (
                patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
                patch.object(reopened, "_show_info_popup"),
            ):
                reopened._on_reset()
            self.assertEqual(reopened.widgets["storefront"].text(), "in")
            parent.close()

    def test_amd_region_cache_is_invalidated_and_stale_checks_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
            page.thread_pool = Mock()
            combo = page.widgets["applemusicdecrypt-storefront"]
            page._set_applemusicdecrypt_regions(["jp", "us"])
            combo.setCurrentIndex(combo.findData("jp"))
            page._set_applemusicdecrypt_regions(["us"])
            self.assertEqual(combo.currentData(), "jp")
            self.assertFalse(combo.model().item(combo.currentIndex()).isEnabled())
            page.widgets["applemusicdecrypt-url"].setText("https://wrapper.example")
            self.assertEqual({combo.itemData(i) for i in range(combo.count())}, {"jp"})
            combo.setCurrentIndex(-1)
            self.assertEqual(page.widgets["storefront"].text(), "")
            page._check_wrapper()
            pending = page._wrapper_check_worker
            page.widgets["applemusicdecrypt-api-key"].setText("changed-fixture-key")
            with patch("ui.settings_page.run_request", return_value={"regions": ["jp", "us"]}):
                pending.run()
            self.assertEqual(combo.count(), 0)
            self.assertIn("changed", page.wrapper_status.text())
            self.assertTrue(page.wrapper_check.isEnabled())
            parent.close()

    def test_wrapper_is_last_and_saves_stable_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
            self.assertEqual(page._iter_category_names_in_order()[-1], "Wrapper")
            combo = page.widgets["wrapper"]
            self.assertEqual(combo.currentData(), "applemusicdecrypt")
            combo.setCurrentIndex(combo.findData("wrapper-v2"))
            self.assertEqual(page._collect()["wrapper"], "wrapper-v2")
            self.assertFalse(page.widgets["save-animated-artwork"].isEnabled())
            page._on_apply()
            restored = SettingsPage(page.config_path, parent)
            self.assertEqual(restored.widgets["wrapper"].currentData(), "wrapper-v2")
            parent.close()

    def test_queue_snapshot_and_restore(self):
        controller = Mock()
        worker = DownloadWorker(controller)
        worker.queue_paused = True
        media = {"albumData": {}, "tracks": [{"trackData": {"id": "7"}}]}
        with patch.object(
            worker, "_get_latest_config", return_value={"wrapper": "wrapper-lite"}
        ):
            worker.add_job_to_queue(1, media, "ALAC", URL)
        self.assertEqual(
            worker.download_queue[0]["backend_settings"]["wrapper"], "applemusicdecrypt"
        )
        worker.add_job_to_queue(
            2, media, "ALAC", URL, backend_settings={"wrapper": "legacy"}
        )
        self.assertEqual(
            worker.download_queue[1]["backend_settings"]["wrapper"], "legacy"
        )

    def test_new_backend_settings_save_and_old_queue_without_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = QMainWindow()
            page = SettingsPage(str(Path(tmp) / "settings.yaml"), parent)
            page.widgets["applemusicdecrypt-url"].setText("http://localhost:18080")
            page.widgets["applemusicdecrypt-api-key"].setText("fixture-wrapper-key")
            self.assertEqual(page.widgets["applemusicdecrypt-api-key"].echoMode().name, "Password")
            self.assertFalse(page.wrapper_rows["applemusicdecrypt-url"][1].isHidden())
            self.assertTrue(page.wrapper_rows["wrapper-v2-url"][1].isHidden())
            page._on_apply()
            restored = SettingsPage(page.config_path, parent)
            self.assertEqual(restored.widgets["wrapper"].currentData(), "applemusicdecrypt")
            self.assertEqual(restored.widgets["applemusicdecrypt-url"].text(), "http://localhost:18080")
            self.assertEqual(restored.widgets["applemusicdecrypt-api-key"].text(), "fixture-wrapper-key")
            selector = restored.widgets["wrapper"]
            selector.setCurrentIndex(selector.findData("legacy"))
            self.assertTrue(restored.wrapper_rows["applemusicdecrypt-api-key"][1].isHidden())
            selector.setCurrentIndex(selector.findData("applemusicdecrypt"))
            with (
                patch("ui.settings_page.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
                patch.object(restored, "_show_info_popup"),
            ):
                restored._on_reset()
            self.assertEqual(restored.widgets["applemusicdecrypt-api-key"].text(), "fixture-wrapper-key")
            worker = DownloadWorker(Mock())
            worker.queue_paused = True
            media = {"albumData": {}, "tracks": [{"trackData": {"id": "7"}}]}
            with patch.object(worker, "_get_latest_config", return_value=page._collect()):
                worker.add_job_to_queue(1, media, "AAC", URL)
            worker.add_job_to_queue(2, media, "AAC", URL, backend_settings={})
            self.assertEqual(worker.download_queue[0]["backend_settings"]["wrapper"], "applemusicdecrypt")
            self.assertEqual(worker.download_queue[0]["backend_settings"]["applemusicdecrypt-url"], "http://localhost:18080")
            self.assertEqual(worker.download_queue[0]["backend_settings"]["applemusicdecrypt-api-key"], "fixture-wrapper-key")
            self.assertEqual(worker.download_queue[1]["backend_settings"]["wrapper"], "legacy")
            parent.close()

    def test_runner_reports_terminal_failure_once(self):
        worker = Mock(was_terminated_intentionally=False)
        request = request_for("download", URL)
        runner = DownloadJobRunner(1, request, 1, worker, "ALAC", original_url=URL)
        finished = []
        runner.signals.finished.connect(lambda *args: finished.append(args))
        with (
            patch("core.download_worker.start_process"),
            patch(
                "core.download_worker.consume",
                side_effect=BackendError("download_failed", "Partial failure"),
            ),
        ):
            runner.run()
        self.assertEqual(len(finished), 1)
        self.assertFalse(finished[0][1])


if __name__ == "__main__":
    unittest.main()
