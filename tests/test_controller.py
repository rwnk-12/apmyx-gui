import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import requests
from PyQt6.QtCore import QCoreApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from core.app import AppController
from core.config import STOREFRONT_BACKUP, load_config, sync_storefront
from core.parsers.catalog import parse_api_item
from core.parsers.lyrics import get_lyrics_from_ttml
from core.parsers.manifest import merge_quality, parse_qualities_from_manifest
from core.resources import resource_path
from core.workers import Worker


def backend_process(data=None, exit_code=0):
    progress = (
        'AMDL_PROGRESS::{"type":"probe_start","total":2}\n'
        "AMDL_PROGRESS::invalid\n"
        'AMDL_PROGRESS::{"type":"probe_progress","current":2,"total":2}\n'
    )
    output = "AMDL_JSON_START" + json.dumps(data or {"albumData": {}}) + "AMDL_JSON_END"
    process = Mock(
        stdout=io.StringIO(progress + output), stderr=io.StringIO("backend status\n")
    )
    process.wait.return_value = exit_code
    process.poll.return_value = None
    return process


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.controller = AppController()
        self.addCleanup(self.controller.session.close)

    def test_search_runs_in_real_pool_and_releases_worker(self):
        controller = self.controller
        controller._search_api = Mock(return_value={"results": {}})
        loaded = []
        controller.search_results_loaded.connect(loaded.append)
        controller.search("test")
        self.assertTrue(controller.thread_pool.waitForDone(2000))
        self.app.processEvents()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["songs"], [])
        self.assertEqual(controller.active_workers, [])

    def test_artist_releases_come_from_the_public_catalog_without_the_bridge(self):
        controller = self.controller
        calls = []

        def catalog(path, params):
            calls.append((path, params))
            if path.endswith("/albums") and params["offset"] == 0:
                return {"data": [{"id": "a1", "type": "albums"}], "next": f"/v1/catalog/us/{path}?offset=100"}
            kind = "albums" if path.endswith("/albums") else "music-videos"
            return {"data": [{"id": f"{kind}-{params['offset']}", "type": kind}]}

        controller._catalog_json = Mock(side_effect=catalog)
        loaded = []
        controller.artist_discography_loaded.connect(loaded.append)
        with patch.object(controller, "_bridge_metadata") as bridge:
            controller.resolve_artist("https://music.apple.com/us/artist/name/123")
            self.assertTrue(controller.thread_pool.waitForDone(2000))
            self.app.processEvents()
        bridge.assert_not_called()
        self.assertEqual([item["id"] for item in loaded[0]], ["a1", "albums-100", "music-videos-0"])
        self.assertIn(("artists/123/albums", {"limit": 100, "offset": 100}), calls)
        with self.assertRaises(ValueError):
            controller._artist_releases("https://music.apple.com/us/album/name/123")

    def test_search_worker_cleanup_after_cancel_and_unhandled_error(self):
        controller = self.controller
        controller.thread_pool = Mock()
        for cancelled in (True, False):
            with self.subTest(cancelled=cancelled):
                action = Mock(side_effect=RuntimeError("test failure"))
                controller._start_search(
                    action, "search_results_loaded", controller.search_results_loaded
                )
                worker = controller.active_workers[0]
                if cancelled:
                    worker.cancel()
                worker.run()
                self.assertEqual(controller.active_workers, [])
                self.assertEqual(action.call_count, 0 if cancelled else 1)

    def test_artwork_signal_routing_and_inherited_qt_slots(self):
        controller = self.controller
        controller.thread_pool = Mock()
        controller._search_api = Mock(
            return_value={
                "results": {
                    "albums": {
                        "data": [
                            {
                                "id": "1",
                                "attributes": {
                                    "name": "Album",
                                    "artwork": {"url": "https://img/{w}x{h}"},
                                },
                            }
                        ]
                    }
                }
            }
        )
        results = []
        controller.artwork_search_results_loaded.connect(results.append)
        controller.search_for_artwork("album")
        controller.active_workers[0].run()
        self.assertEqual(results[0][0]["artworkUrl"], "https://img/5000x5000")
        self.assertEqual(controller.active_workers, [])
        self.assertGreaterEqual(
            controller.metaObject().indexOfSlot(
                b"download_lyrics_for_track(PyQt_PyObject,QString)"
            ),
            0,
        )

    def test_shared_api_retry_and_shutdown(self):
        controller = self.controller
        success = Mock()
        success.json.return_value = {"data": []}
        controller._apple_music_get = Mock(
            side_effect=[requests.ConnectionError(), success]
        )
        with patch("core.controllers.catalog.time.sleep"):
            self.assertEqual(controller._lookup_api_item("songs", "123"), {"data": []})
        self.assertEqual(controller._apple_music_get.call_count, 2)
        controller._shutdown = True
        with self.assertRaisesRegex(ValueError, "shutting down"):
            controller._search_api("test", "songs", 1)
        self.assertEqual(controller._apple_music_get.call_count, 2)

    def test_api_does_not_repeat_exhausted_auth_refresh(self):
        denied = Mock(status_code=401)
        denied.raise_for_status.side_effect = requests.HTTPError(response=denied)
        self.controller._apple_music_get = Mock(return_value=denied)
        with self.assertRaises(requests.HTTPError):
            self.controller._lookup_api_item("songs", "123")
        self.controller._apple_music_get.assert_called_once()

    def test_backend_metadata_progress_and_registry_cleanup(self):
        controller = self.controller
        result, progress = [], []
        controller.media_details_loaded.connect(lambda *args: result.append(args))
        controller.media_fetch_progress.connect(lambda *args: progress.append(args))
        process = backend_process({"albumData": {"attributes": {"name": "Album"}}})

        def consume(proc, callback, request_id):
            callback({"event": "progress", "data": {"current": 0, "total": 2}})
            callback({"event": "progress", "data": {"current": 2, "total": 2}})
            return {"albumData": {}, "tracks": []}

        with (
            patch("core.controllers.media.start_process", return_value=process),
            patch("core.controllers.media.consume", side_effect=consume),
        ):
            controller._fetch_media_worker("https://music.apple.com/us/album/123", 7)
        self.app.processEvents()
        self.assertEqual(result[0][0], 7)
        self.assertEqual(progress, [(7, 0, 2), (7, 2, 2)])
        self.assertEqual(controller.active_processes, [])
        self.assertEqual(controller.fetching_processes, {})

    def test_backend_generic_failure_and_cancellation(self):
        controller = self.controller
        result, failures = [], []
        controller.tracklist_loaded_for_selection.connect(result.append)
        controller.media_fetch_failed.connect(lambda *args: failures.append(args))
        with patch(
            "core.controllers.media.MediaMixin._bridge_metadata",
            side_effect=ValueError("Backend failure"),
        ):
            controller._fetch_media_generic_worker(
                "url", controller.tracklist_loaded_for_selection
            )
        self.assertEqual(result, [{}])
        process = backend_process()
        controller.active_processes.append(process)
        controller.fetching_processes[9] = (process, "url")
        with patch("core.controllers.media.terminate_tree") as terminate:
            self.assertTrue(controller.cancel_fetch(9))
        terminate.assert_called_once_with(process)
        self.assertEqual(failures[0][0], 9)
        self.assertEqual(controller.active_processes, [])

    def test_details_quality_enrichment_does_not_mutate_input(self):
        controller = self.controller
        tracks = [{"id": "1", "attributes": {"audioTraits": ["lossless"]}}]
        controller._fetch_all_manifests_async = AsyncMock(
            return_value=[(0, {"bitDepth": 24})]
        )
        loaded = []
        controller.track_qualities_loaded.connect(loaded.append)
        asyncio.run(controller._fetch_qualities_for_dialog_async(tracks))
        self.assertEqual(loaded[0][0]["attributes"]["bitDepth"], 24)
        self.assertNotIn("bitDepth", tracks[0]["attributes"])

    def test_artwork_error_still_emits_failure(self):
        results = []
        self.controller.artwork_download_finished.connect(
            lambda *args: results.append(args)
        )
        self.controller.download_artwork_worker({"id": "1", "name": "Album"})
        self.assertFalse(results[0][1])


class UtilityTests(unittest.TestCase):
    def test_storefront_sync_preserves_original_across_region_and_wrapper_changes(self):
        original = {"wrapper": "applemusicdecrypt", "storefront": "gb", "applemusicdecrypt-storefront": "jp"}
        active = sync_storefront(original)
        self.assertEqual(original["storefront"], "gb")
        self.assertEqual(active["storefront"], "jp")
        self.assertEqual(active[STOREFRONT_BACKUP], "gb")
        self.assertEqual(sync_storefront(active), active)
        active["applemusicdecrypt-storefront"] = "us"
        active = sync_storefront(active)
        self.assertEqual(active["storefront"], "us")
        self.assertEqual(active[STOREFRONT_BACKUP], "gb")
        restored = sync_storefront({**active, "wrapper": "legacy"})
        self.assertEqual(restored["storefront"], "gb")
        self.assertNotIn(STOREFRONT_BACKUP, restored)
        restored["storefront"] = "in"
        active = sync_storefront({**restored, "wrapper": "applemusicdecrypt"})
        self.assertEqual(active["storefront"], "us")
        self.assertEqual(sync_storefront({**active, "wrapper": "wrapper-v2"})["storefront"], "in")

    def test_storefront_sync_restores_blank_and_migrates_saved_selection(self):
        active = sync_storefront({"storefront": "", "applemusicdecrypt-storefront": "jp"})
        self.assertEqual(active[STOREFRONT_BACKUP], "")
        self.assertEqual(sync_storefront({**active, "wrapper": "legacy"})["storefront"], "")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            text = "wrapper: applemusicdecrypt\nstorefront: gb\napplemusicdecrypt-storefront: jp\n"
            path.write_text(text, encoding="utf-8")
            loaded = load_config(path)
            self.assertEqual(loaded["storefront"], "jp")
            self.assertEqual(loaded[STOREFRONT_BACKUP], "gb")
            self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_catalog_and_manifest_parsers(self):
        item = {"id": "1", "attributes": {"name": "Song", "durationInMillis": 125000}}
        self.assertEqual(parse_api_item(item)["durationStr"], "2:05")
        metadata = base64.b64encode(
            json.dumps({"a": {"IS-ATMOS": True, "BITS-PER-SAMPLE": 24}}).encode()
        ).decode()
        manifest = f'#EXT-X-SESSION-DATA:DATA-ID="com.apple.hls.audioAssetMetadata",VALUE="{metadata}"\n'
        manifest += (
            '#EXT-X-STREAM-INF:BANDWIDTH=1000,AVERAGE-BANDWIDTH=900,CODECS="alac"'
        )
        quality = parse_qualities_from_manifest(manifest)
        self.assertEqual(quality["bitDepth"], 24)
        self.assertEqual(set(quality["audioTraits"]), {"atmos", "spatial"})
        self.assertEqual(quality["avgBitrate"], 900)
        self.assertEqual(merge_quality(item, quality)["attributes"]["codec"], "alac")
        self.assertNotIn("codec", item["attributes"])

    def test_lyrics_conversion_and_passthrough(self):
        ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="00:02.50">Hello <span>world</span></p></div></body></tt>'
        self.assertEqual(get_lyrics_from_ttml(ttml, "lrc"), "[00:02.50]Hello world")
        self.assertEqual(get_lyrics_from_ttml(ttml, "ttml"), ttml)

    def test_config_defaults_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            self.assertEqual(load_config(path), {})
            path.write_text("storefront: in", encoding="utf-8")
            self.assertEqual(load_config(path), {"storefront": "in"})
            path.write_text("- invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)

    def test_resource_paths_source_and_frozen(self):
        expected = (
            Path(__file__).resolve().parents[1] / "src" / "core" / "downloader.exe"
        )
        self.assertEqual(Path(resource_path("src/core/downloader.exe")), expected)
        with patch.object(sys, "_MEIPASS", "bundle", create=True):
            self.assertEqual(Path(resource_path("asset")), Path("bundle/asset"))

    def test_generic_worker_supports_coroutines(self):
        called = []

        async def action(value):
            called.append(value)

        Worker(action, 42).run()
        self.assertEqual(called, [42])


if __name__ == "__main__":
    unittest.main()
