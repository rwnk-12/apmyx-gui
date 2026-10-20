import asyncio
import base64
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
URL = "https://music.apple.com/us/album/test/11"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from backend.bridge import adapter_for, dispatch
from backend.router.common import BackendError, Events, http_json, snapshot, validate_request
from backend.router.applemusicdecrypt import Adapter, check_native, load_paths
from backend.router.applemusicdecrypt.config import (
    codec_for,
    storefront_for,
    template,
    translate_settings,
    wrapper_headers,
)
from backend.router.applemusicdecrypt.catalog import Catalog
from backend.shared.files import cleanup_publications, manifest, prefix, publish_file


def token():
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return (
        encode({"alg": "ES256"})
        + "."
        + encode({"exp": time.time() + 3600})
        + ".fixture"
    )


class AppleMusicDecryptContractTests(unittest.TestCase):
    def test_gui_defaults_match_native_applemusicdecrypt_defaults(self):
        load_paths()
        from applemusicdecrypt.config import Download, MV
        from ui.settings_schema import DEFAULTS

        request = validate_request({
            "operation": "download",
            "url": "https://music.apple.com/us/album/test/1",
            "quality": DEFAULTS["preferred-quality"],
            "settings": copy.deepcopy(DEFAULTS),
        })
        config = translate_settings(request)
        native, video = Download(), MV()
        for key in (
            "streamDecrypt", "decryptBatchSize", "downloadTimeout", "resumeDownload",
            "codecAlternative", "failedSongNotPassIntegrityCheck", "alacFix", "lowMemory",
            "maxSampleRate", "maxBitDepth", "retryTime", "maxWaitTime",
        ):
            self.assertEqual(config["download"][key], getattr(native, key), key)
        self.assertEqual(config["download"]["codecPriority"], native.codecPriority)
        self.assertEqual(config["download"]["songNameFormat"], native.songNameFormat)
        self.assertEqual(config["download"]["playlistSongNameFormat"], "{tracknum:02d}. {artist} - {title}")
        for key in ("maxHeight", "audioType", "segmentConcurrency", "segmentRetries"):
            self.assertEqual(config["mv"][key], getattr(video, key), key)
        self.assertEqual((DEFAULTS["save-lrc-file"], DEFAULTS["save-cover-file"]), (native.saveLyrics, native.saveCover))
        self.assertEqual((DEFAULTS["cover-format"], DEFAULTS["cover-size"]), (native.coverFormat, native.coverSize))
        self.assertEqual(
            tuple(kind for kind, key in (("translation", "lyrics-translation"), ("pronunciation", "lyrics-pronunciation")) if DEFAULTS[key]),
            tuple(native.lyricsExtra),
        )
        self.assertTrue(all(value for key, value in DEFAULTS["tag-options"].items() if key.startswith("write-")))

    def test_storefront_override_is_independent_and_rejects_unsupported_regions(self):
        request = validate_request({"operation": "probe", "url": "https://music.apple.com/jp/song/test/7", "settings": {"storefront": "gb"}})
        self.assertEqual(storefront_for(request, ["us"]), "jp")
        request["settings"]["applemusicdecrypt-storefront"] = "US"
        self.assertEqual(storefront_for(request, ["us", "jp"]), "us")
        self.assertEqual(request["settings"]["storefront"], "gb")
        with patch.object(Adapter, "status", return_value={"regions": ["jp"]}):
            with self.assertRaises(BackendError) as failure:
                Adapter().run(request, Events(request, io.StringIO()))
        self.assertEqual(failure.exception.code, "unsupported_storefront")
        request["settings"]["applemusicdecrypt-storefront"] = "not-a-storefront"
        with self.assertRaises(BackendError) as failure:
            storefront_for(request)
        self.assertEqual(failure.exception.code, "invalid_storefront")

    def test_wrapper_api_key_uses_header_and_rejects_unsafe_transport(self):
        settings = snapshot({"applemusicdecrypt-url": "https://wrapper.example"})
        self.assertEqual(wrapper_headers(settings), {})
        settings["applemusicdecrypt-api-key"] = "fixture-wrapper-key"
        self.assertEqual(wrapper_headers(settings), {"Authorization": "Bearer fixture-wrapper-key"})
        for url, key in (
            ("http://wrapper.example", "fixture-wrapper-key"),
            ("https://wrapper.example", "invalid\r\nheader"),
        ):
            with self.assertRaises(BackendError) as failure:
                wrapper_headers({**settings, "applemusicdecrypt-url": url, "applemusicdecrypt-api-key": key})
            self.assertNotIn(key, str(failure.exception))
        response = Mock(status_code=200)
        response.json.return_value = {"code": 0, "data": {"regions": ["us"]}}
        with patch("backend.router.common.requests.get", return_value=response) as get:
            with patch("backend.router.applemusicdecrypt.check_native"):
                self.assertTrue(Adapter().status(settings)["online"])
            self.assertEqual(get.call_args.kwargs["headers"], wrapper_headers(settings))
            self.assertFalse(get.call_args.kwargs["allow_redirects"])
            self.assertNotIn("fixture-wrapper-key", get.call_args.args[0])
            for status, expected in ((302, "invalid_endpoint"), (401, "authentication_required")):
                response.status_code = status
                with self.assertRaises(BackendError) as failure:
                    http_json(settings["applemusicdecrypt-url"], "/status", headers=wrapper_headers(settings))
                self.assertEqual(failure.exception.code, expected)

    def test_cancelling_worker_removes_publication_copy_and_preserves_external_process(
        self,
    ):
        from core.bridge_client import consume
        from backend.router.common import terminate_tree

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            request = {
                "request_id": "cancelled-job",
                "work_dir": folder,
                "settings": {"aac-save-folder": folder},
            }
            partial = root / (prefix(request) + "copy.part")
            script = "\n".join(
                (
                    "import json, pathlib, sys, time",
                    "data = json.loads(sys.argv[1])",
                    "pathlib.Path(data['partial']).write_bytes(b'partial copy')",
                    "pathlib.Path(data['manifest']).write_text(json.dumps(data['partial']) + '\\n', encoding='utf-8')",
                    "print(json.dumps({'version': 1, 'request_id': 'cancelled-job', 'event': 'progress', 'data': {}}), flush=True)",
                    "time.sleep(30)",
                )
            )
            external = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    script,
                    json.dumps(
                        {
                            "partial": str(partial),
                            "manifest": str(manifest(request, folder)),
                        }
                    ),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            process._apmyx_request = request
            process._apmyx_scratch = folder
            try:
                with self.assertRaises(BackendError):
                    consume(
                        process,
                        lambda event: terminate_tree(process),
                        request["request_id"],
                    )
                self.assertFalse(partial.exists())
                self.assertIsNone(external.poll())
            finally:
                terminate_tree(process)
                external.terminate()
                external.wait(timeout=5)

    def test_new_default_and_explicit_existing_selections(self):
        self.assertEqual(snapshot({})["wrapper"], "applemusicdecrypt")
        self.assertIsInstance(adapter_for("applemusicdecrypt"), Adapter)
        for old in ("legacy", "wrapper-v2"):
            self.assertEqual(snapshot({"wrapper": old})["wrapper"], old)
        self.assertEqual(snapshot({"wrapper": "wrapper-lite"})["wrapper"], "applemusicdecrypt")

    def test_amd_download_controls_translate_and_reject_invalid_values(self):
        settings = {
            "amd-max-bit-depth": 16, "amd-download-timeout": 0,
            "amd-download-retries": 4, "amd-retry-wait": 12,
            "amd-decrypt-batch-size": 512, "amd-stream-decrypt": False,
            "amd-low-memory": False, "amd-resume-download": False,
            "amd-alac-fix": False, "amd-verify-integrity": False,
            "amd-mv-segment-concurrency": 8, "amd-mv-segment-retries": 5,
            "playlist-song-file-format": "{SongNumber}. {ArtistName} - {SongName}",
        }
        request = validate_request({"operation": "download", "url": URL, "settings": settings})
        config = translate_settings(request)
        for source, target in {
            "amd-max-bit-depth": "maxBitDepth", "amd-download-timeout": "downloadTimeout",
            "amd-download-retries": "retryTime", "amd-retry-wait": "maxWaitTime",
            "amd-decrypt-batch-size": "decryptBatchSize", "amd-stream-decrypt": "streamDecrypt",
            "amd-low-memory": "lowMemory", "amd-resume-download": "resumeDownload",
            "amd-alac-fix": "alacFix", "amd-verify-integrity": "failedSongNotPassIntegrityCheck",
        }.items():
            self.assertEqual(config["download"][target], settings[source])
        self.assertEqual(config["mv"]["segmentConcurrency"], 8)
        self.assertEqual(config["mv"]["segmentRetries"], 5)
        self.assertEqual(config["download"]["playlistSongNameFormat"], "{tracknum:02d}. {artist} - {title}")
        for key, value in (("amd-max-bit-depth", 20), ("amd-download-timeout", -1), ("amd-download-retries", 0), ("amd-mv-segment-concurrency", 100), ("amd-retry-wait", "bad")):
            with self.subTest(key=key), self.assertRaises(BackendError):
                translate_settings({**request, "settings": {**request["settings"], key: value}})

    def test_default_backend_renders_all_gui_naming_tokens_and_blank_folders(self):
        from types import SimpleNamespace as NS
        from backend.router.applemusicdecrypt import load_paths
        load_paths()
        from applemusicdecrypt.config import Config
        from applemusicdecrypt.metadata import SongMetadata
        from applemusicdecrypt.services import bind
        from applemusicdecrypt.utils import get_song_name_and_dir_path
        from ui.settings_schema import PLACEHOLDERS

        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp:
            settings = {"alac-save-folder": tmp}
            for key in ("song-file-format", "album-folder-format", "artist-folder-format", "playlist-folder-format"):
                settings[key] = "-".join(PLACEHOLDERS[key])
            settings["playlist-song-file-format"] = "{PlaylistName}-{SongNumber}-{SongName}"
            request = validate_request({"operation": "download", "url": URL, "settings": settings})
            config = Config.model_validate(translate_settings(request))
            metadata = SongMetadata(
                song_id="7", title="Song", artist="Artist", album="Album", album_artist="Album Artist",
                artist_id="10", album_id="11", album_created="2020-01-02", upc="123", copyright="Copyright",
                record_company="Label", tracknum=3, disk=2, disk_total=2, track_total={2: 3}, playlist_index=5,
                bit_depth=24, sample_rate=48000, sample_rate_kHz="48.0",
            )
            playlist = NS(data=[NS(id="pl.fixture", attributes=NS(name="Playlist", curatorName="Curator"))])
            with bind({Config: config, "scratch": tmp, "naming_tag": "[E]"}):
                filename, folder = get_song_name_and_dir_path("ALAC", metadata)
                self.assertIn("24B-48.0kHz", str(folder))
                self.assertIn("2020-01-02-2020-123", str(folder))
                self.assertIn("[E]", filename)
                self.assertNotIn("{", filename + str(folder))
                filename, folder = get_song_name_and_dir_path("ALAC", metadata, playlist)
                self.assertEqual(filename, "Playlist-05-Song")
                self.assertIn("24B-48.0kHz", str(folder))
                self.assertNotIn("{", str(folder))
            empty = translate_settings({**request, "settings": {**request["settings"], "artist-folder-format": "", "album-folder-format": "", "playlist-folder-format": ""}})
            self.assertEqual(Path(empty["download"]["dirPathFormat"]), Path(tmp))
            self.assertEqual(Path(empty["download"]["playlistDirPathFormat"]), Path(tmp))

    def test_translation_preserves_independent_pipeline_and_prevents_interaction(self):
        request = validate_request(
            {
                "operation": "download",
                "url": "https://music.apple.com/us/album/test/11",
                "quality": "AAC-BINAURAL",
                "settings": {
                    "applemusicdecrypt-url": "https://localhost:12340/lite",
                    "song-file-format": "{DiscNumber}-{SongNumber} {SongName}",
                    "alac-max": 96000,
                },
            }
        )
        config = translate_settings(request)
        self.assertEqual(
            config["instance"], {"url": "localhost:12340/lite", "secure": True}
        )
        self.assertFalse(config["localInstance"]["enable"])
        self.assertTrue(config["download"]["codecAlternative"])
        self.assertTrue(config["download"]["streamDecrypt"])
        self.assertEqual(config["download"]["maxSampleRate"], 96000)
        self.assertEqual(config["download"]["codecPriority"], ["aac-binaural", "alac", "ec3", "ac3", "aac"])
        self.assertEqual(
            config["download"]["songNameFormat"], "{disk}-{tracknum:02d} {title}"
        )
        self.assertEqual(config["metadata"]["embedMetadata"], [])
        self.assertEqual(config["download"]["afterDownloaded"], "")

    def test_invalid_endpoints_and_saved_templates_fail_explicitly(self):
        request = validate_request(
            {"operation": "download", "url": "https://music.apple.com/us/song/test/7"}
        )
        for url in (
            "file:///local",
            "http://user:password@localhost:12340",
            "http://localhost:12340?token=secret",
        ):
            with self.subTest(url=url), self.assertRaises(BackendError):
                translate_settings(
                    {
                        **request,
                        "settings": {
                            **request["settings"],
                            "applemusicdecrypt-url": url,
                        },
                    }
                )
        with self.assertRaises(BackendError):
            template("{Unknown}")
        with self.assertRaises(BackendError):
            template("broken{")
        with self.assertRaises(BackendError):
            codec_for(
                {**request, "quality": "AAC", "settings": {"aac-type": "invalid"}}
            )

    def test_status_reports_authentication_and_missing_native_dependency(self):
        with (
            patch("backend.router.applemusicdecrypt.check_native"),
            patch(
                "backend.router.applemusicdecrypt.http_json",
                return_value={"code": 0, "data": {"regions": []}},
            ),
        ):
            with self.assertRaises(BackendError) as failure:
                Adapter().status(snapshot({}))
        self.assertEqual(failure.exception.code, "authentication_required")
        with patch(
            "backend.router.applemusicdecrypt.check_native",
            side_effect=BackendError("missing_dependency", "Missing Temari"),
        ):
            with self.assertRaises(BackendError) as failure:
                Adapter().status(snapshot({}))
        self.assertEqual(failure.exception.code, "missing_dependency")

    def test_catalog_rejects_foreign_and_repeated_pagination(self):
        api = Mock()
        catalog = Catalog(api, "us", "en-US")
        with self.assertRaises(BackendError):
            asyncio.run(catalog.page("https://example.com/metadata"))
        catalog.page = AsyncMock(
            return_value={"data": [], "next": "/v1/catalog/us/albums/11/tracks"}
        )
        with self.assertRaises(BackendError):
            asyncio.run(catalog.items("/v1/catalog/us/albums/11/tracks"))

    def test_catalog_retains_pagination_offset_with_selected_language(self):
        response = Mock()
        response.json.return_value = {"data": []}
        api = Mock(_request=AsyncMock(return_value=response))
        asyncio.run(
            Catalog(api, "us", "ja").page(
                "/v1/catalog/us/albums/11/tracks?offset=100&limit=100"
            )
        )
        args, kwargs = api._request.await_args
        self.assertEqual(
            args[1], "https://amp-api.music.apple.com/v1/catalog/us/albums/11/tracks"
        )
        self.assertEqual(kwargs["params"], {"offset": "100", "limit": "100", "l": "ja"})

    def test_atomic_publication_and_cancelled_copy_cleanup_stay_in_job_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "out"
            output.mkdir()
            request = {
                "request_id": "job",
                "scratch": folder,
                "work_dir": folder,
                "settings": {"aac-save-folder": str(output)},
            }
            source = root / "finished.m4a"
            source.write_bytes(b"unchanged-media")
            destination = output / "song.m4a"
            publish_file(source, destination, request)
            self.assertEqual(destination.read_bytes(), b"unchanged-media")
            orphan = output / (prefix(request) + "orphan.part")
            orphan.write_bytes(b"interrupted")
            unrelated = output / "user.part"
            unrelated.write_bytes(b"keep")
            outside = root / (prefix(request) + "outside.part")
            outside.write_bytes(b"keep")
            manifest(request, folder).write_text(
                "\n".join(
                    json.dumps(str(path)) for path in (orphan, unrelated, outside)
                ),
                encoding="utf-8",
            )
            cleanup_publications(request, folder)
            self.assertFalse(orphan.exists())
            self.assertTrue(unrelated.exists())
            self.assertTrue(outside.exists())
            self.assertTrue(destination.exists())


@unittest.skipUnless(
    shutil.which("ffmpeg") and (ROOT / "backend/runtime/temari").is_dir(),
    "Built native runtime and FFmpeg are required for media integration fixtures.",
)
class AppleMusicDecryptMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_paths()
        check_native()
        import httpx
        from applemusicdecrypt.config import Config
        from applemusicdecrypt.logger import GlobalLogger
        from applemusicdecrypt.services import bind

        config = Config.model_validate(
            translate_settings(
                validate_request(
                    {
                        "operation": "download",
                        "url": "https://music.apple.com/us/song/test/7",
                    }
                )
            )
        )
        with bind({Config: config, GlobalLogger: GlobalLogger()}):
            from applemusicdecrypt.api import WebAPI
            from applemusicdecrypt.decrypt import Decryptor
            import applemusicdecrypt.mv
        cls.httpx, cls.API, cls.Decryptor = httpx, WebAPI, Decryptor
        cls.folder = tempfile.TemporaryDirectory(
            prefix="amd-fixtures-", dir=ROOT / "build"
        )
        cls.root = Path(cls.folder.name)
        fixture = cls.root / "fragmented.m4a"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=2",
                "-c:a",
                "aac",
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                "-frag_duration",
                "500000",
                str(fixture),
            ],
            check=True,
            capture_output=True,
        )
        cls.media = fixture.read_bytes()
        video = cls.root / "video.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=red:size=32x32:duration=2:rate=10",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+frag_keyframe+empty_moov+default_base_moof",
                "-frag_duration",
                "500000",
                str(video),
            ],
            check=True,
            capture_output=True,
        )
        from applemusicdecrypt.mp4 import parse_init

        video_data = video.read_bytes()
        _, audio_offset = parse_init(cls.media)
        _, video_offset = parse_init(video_data)
        cls.movie_files = {
            "/audio-init.mp4": cls.media[:audio_offset],
            "/audio-fragment.m4s": cls.media[audio_offset:],
            "/video-init.mp4": video_data[:video_offset],
            "/video-fragment.m4s": video_data[video_offset:],
        }
        cls.calls = []
        cls.headers_seen = []
        cls.regions = ["us"]
        cls.ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s" end="2s"><span>Shared </span><span>lyrics</span></p></div></body></tt>'

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = urlsplit(self.path).path
                cls.calls.append(path)
                cls.headers_seen.append((path, self.headers.get("Authorization")))
                base = f"http://127.0.0.1:{self.server.server_port}"
                if path == "/status":
                    data = json.dumps({"code": 0, "data": {"regions": cls.regions}}).encode()
                elif path == "/m3u8":
                    data = json.dumps(
                        {"code": 0, "data": {"m3u8": base + "/master.m3u8"}}
                    ).encode()
                elif path == "/lyrics":
                    data = json.dumps(
                        {"code": 0, "data": {"lyrics": cls.ttml}}
                    ).encode()
                elif path == "/master.m3u8":
                    data = (
                        '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio-stereo-256",NAME="AAC",CHANNELS="2"\n#EXT-X-STREAM-INF:BANDWIDTH=256000,CODECS="mp4a.40.2",AUDIO="audio-stereo-256"\nstream.m3u8\n'
                    ).encode()
                elif path == "/stream.m3u8":
                    data = (
                        '#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="skd://fixture/c22",KEYFORMAT="com.apple.streamingkeydelivery"\n#EXTINF:2,\nmedia.m4a\n#EXT-X-ENDLIST\n'
                    ).encode()
                elif path == "/media.m4a":
                    data = cls.media
                elif path == "/webplayback":
                    data = json.dumps(
                        {"code": 0, "data": {"m3u8": base + "/movie-master.m3u8"}}
                    ).encode()
                elif path == "/movie-master.m3u8":
                    data = (
                        '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio-stereo-256",NAME="AAC",URI="audio-playlist.m3u8",CHANNELS="2"\n#EXT-X-STREAM-INF:BANDWIDTH=256000,RESOLUTION=32x32,CODECS="avc1.640028",AUDIO="audio-stereo-256"\nvideo-playlist.m3u8\n'
                    ).encode()
                elif path in ("/video-playlist.m3u8", "/audio-playlist.m3u8"):
                    stream = path.split("-", 1)[0].lstrip("/")
                    data = (
                        f'#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXT-X-MAP:URI="{stream}-init.mp4"\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="data:text/plain;base64,AAAA",KEYFORMAT="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"\n#EXTINF:2,\n{stream}-fragment.m4s\n#EXT-X-ENDLIST\n'
                    ).encode()
                elif path in cls.movie_files:
                    data = cls.movie_files[path]
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                for offset in range(0, len(data), 512):
                    self.wfile.write(data[offset : offset + 512])
                    self.wfile.flush()
                    if path == "/media.m4a":
                        time.sleep(0.002)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.folder.cleanup()

    def setUp(self):
        self.__class__.regions = ["us"]
        self.api_paths = []
        self.head_paths = []
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.work.cleanup)
        self.output = Path(self.work.name) / "output"
        self.settings = {
            "applemusicdecrypt-url": f"http://127.0.0.1:{self.server.server_port}",
            "authorization-token": token(),
            "embed-cover": False,
            "aac-save-folder": str(self.output),
            "mv-save-folder": str(self.output / "videos"),
            "use-songinfo-for-playlist": False,
            "save-lrc-file": True,
            "lrc-format": "srt",
        }
        self.album = {
            "id": "11",
            "type": "albums",
            "attributes": {
                "name": "Album",
                "artistName": "Artist",
                "trackCount": 2,
                "releaseDate": "2020-01-02",
                "copyright": "Copyright",
                "upc": "123",
                "recordLabel": "Label",
            },
        }
        self.tracks = []
        for identifier in ("7", "8"):
            self.tracks.append(
                {
                    "id": identifier,
                    "type": "songs",
                    "attributes": {
                        "name": "Song " + identifier,
                        "artistName": "Artist",
                        "albumName": "Album",
                        "trackNumber": int(identifier) - 6,
                        "discNumber": 1,
                        "releaseDate": "2020-01-02",
                        "artwork": {"url": ""},
                        "genreNames": ["Pop"],
                        "hasLyrics": True,
                        "hasTimeSyncedLyrics": True,
                        "extendedAssetUrls": {
                            "enhancedHls": self.settings["applemusicdecrypt-url"]
                            + "/master.m3u8"
                        },
                    },
                    "relationships": {
                        "albums": {"data": [copy.deepcopy(self.album)]},
                        "artists": {"data": [{"id": "10"}]},
                        "genres": {"data": [{"id": "14", "type": "genres"}]},
                        "composers": {"data": [{"id": "12", "type": "artists"}]},
                    },
                }
            )
        self.album["relationships"] = {"tracks": {"data": copy.deepcopy(self.tracks)}}
        self.playlist = {
            "id": "pl.fixture",
            "type": "playlists",
            "attributes": {"name": "Playlist", "curatorName": "Curator"},
            "relationships": {"tracks": {"data": list(reversed(self.tracks))}},
        }
        self.video = {
            "id": "9",
            "type": "music-videos",
            "attributes": {
                "name": "Video",
                "artistName": "Artist",
                "genreNames": ["Pop"],
                "releaseDate": "2020-01-02",
            },
            "relationships": {
                "albums": {"data": []},
                "artists": {"data": [{"id": "10"}]},
                "genres": {"data": [{"id": "14", "type": "genres"}]},
            },
        }

    async def api_request(self, api, method, url, **kwargs):
        if str(url).startswith("https://amp-api.music.apple.com/"):
            path = urlsplit(str(url)).path
            if method == "GET":
                self.api_paths.append(path)
            if method == "HEAD":
                self.head_paths.append(path)
                if path.split("/")[3] in getattr(self, "missing_regions", ()):
                    return self.httpx.Response(404, request=self.httpx.Request(method, url))
            if "/songs/" in path:
                raw = self.tracks[int(path.rsplit("/", 1)[1]) - 7]
            elif "/albums/" in path:
                raw = self.album
            elif "/playlists/" in path:
                raw = self.playlist
            elif "/music-videos/" in path:
                raw = self.video
            elif path.endswith("/artists/10/albums"):
                raw = self.album
            elif path.endswith("/artists/10/music-videos"):
                raw = self.video
            elif path.endswith("/artists/10"):
                raw = {"id": "10", "type": "artists", "attributes": {"name": "Artist"}}
            else:
                raise AssertionError(path)
            if getattr(self, "failed_id", None) and path.endswith(
                "/songs/" + self.failed_id
            ):
                return self.httpx.Response(
                    503,
                    json={"error": "fixture failure"},
                    request=self.httpx.Request(method, url),
                )
            return self.httpx.Response(
                200,
                json={"data": [copy.deepcopy(raw)]},
                request=self.httpx.Request(method, url),
            )
        return await api.client.request(method, url, **kwargs)

    def run_request(self, operation="download", url=None, ids=None, quality="AAC"):
        request = {
            "operation": operation,
            "url": url or "https://music.apple.com/us/playlist/test/pl.fixture",
            "settings": self.settings,
            "quality": quality,
            "request_id": "fixture-job",
            "work_dir": self.work.name,
        }
        if ids is not None:
            request["track_ids"] = ids
        output = io.StringIO()
        owner = self

        async def api(api, *args, **kwargs):
            return await owner.api_request(api, *args, **kwargs)

        with (
            patch.object(self.API, "_request", new=api),
            patch.object(self.API, "DOWNLOAD_CHUNK_SIZE", 1024),
            patch.object(
                self.Decryptor,
                "get_template",
                new=AsyncMock(return_value=Mock(decrypt_par=lambda samples: samples)),
            ),
            patch.object(
                self.Decryptor, "mv_content_key", new=AsyncMock(return_value=b"0" * 16)
            ),
            patch(
                "applemusicdecrypt.mv._decrypt_cbcs_sample",
                side_effect=lambda sample, *args: sample,
            ),
        ):
            code = dispatch(request, output)
        return code, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_amd_synced_word_ttml_and_unsynced_files_match_embedded_lyrics(self):
        from mutagen.mp4 import MP4
        ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s" end="2s"><span begin="1s" end="1.5s">Shared </span><span begin="1.5s" end="2s">lyrics</span></p></div></body></tt>'
        for mode, format, suffix in (("synced", "lrc", ".lrc"), ("synced", "ttml", ".ttml"), ("unsynced", "ttml", ".txt")):
            with self.subTest(mode=mode, format=format):
                self.settings.update({"lyrics-mode": mode, "lrc-format": format, "lrc-type": "syllable-lyrics", "aac-save-folder": str(self.output / (mode + format))})
                with patch.object(type(self), "ttml", ttml):
                    code, records = self.run_request(ids=["7"])
                self.assertEqual(code, 0, records)
                path = Path(records[-1]["result"]["artifacts"][0]["path"])
                content = path.with_suffix(suffix).read_text(encoding="utf-8")
                self.assertEqual(MP4(path)["\xa9lyr"], [content])
                if mode == "unsynced":
                    self.assertEqual(content, "Shared lyrics")
                elif format == "lrc":
                    self.assertEqual(content, "[00:01.00]<00:01.00>Shared <00:01.50>lyrics<00:02.00>")
                else:
                    self.assertIn('begin="1.5s"', content)

    def test_amd_artwork_timeout_fails_track_before_publishing_without_pausing(self):
        import requests
        from backend.shared.tagging import SharedTagger
        self.settings.update({"save-cover-file": True, "aac-save-folder": str(self.output / "timeout")})
        with patch.object(SharedTagger, "artwork", side_effect=requests.ReadTimeout("Read timed out.")):
            code, records = self.run_request(ids=["7", "8"])
        self.assertEqual(code, 1, records)
        errors = [event for event in records if event["event"] == "error"]
        self.assertEqual(errors[-1]["code"], "download_failed")
        self.assertFalse(any(event.get("code") == "wrapper_unavailable" for event in records))
        failed = {event["message"].split(":")[0] for event in records if event["event"] == "log" and "timed out" in event["message"]}
        self.assertEqual(failed, {"Song 7", "Song 8"})
        self.assertFalse(list((self.output / "timeout").rglob("*.m4a")))

    def test_amd_sidecar_write_failure_after_publishing_is_a_warning(self):
        from backend.router.applemusicdecrypt import engine
        real = engine.publish_file

        def publish(source, destination, request):
            if Path(destination).suffix == ".lrc":
                raise PermissionError("denied")
            return real(source, destination, request)

        self.settings.update({"lrc-format": "lrc", "aac-save-folder": str(self.output / "sidecar")})
        with patch.object(engine, "publish_file", side_effect=publish):
            code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 0, records)
        self.assertEqual(records[-1]["result"]["completed"], 1)
        self.assertTrue(any(event["event"] == "log" and event["level"] == "warning" and "could not save" in event["message"] for event in records))

    def test_amd_artwork_can_be_saved_without_embedding(self):
        from backend.shared.tagging import SharedTagger
        from mutagen.mp4 import MP4
        cover = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII=")
        self.settings.update({"save-cover-file": True, "embed-cover": False})
        with patch.object(SharedTagger, "artwork", return_value=cover):
            code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 0, records)
        path = Path(records[-1]["result"]["artifacts"][0]["path"])
        self.assertNotIn("covr", MP4(path))
        self.assertEqual((path.parent / "cover.png").read_bytes(), cover)

    def test_probe_reports_native_qualities_in_gui_shape(self):
        code, records = self.run_request("probe")
        self.assertEqual(code, 0, records)
        data = next(event["data"] for event in records if event["event"] == "metadata")
        self.assertEqual(len(data["tracks"]), 2)
        self.assertEqual(data["tracks"][0]["availableCodecs"], ["AAC"])
        self.assertEqual(data["albumData"]["id"], "pl.fixture")

    def test_selected_storefront_drives_probing_and_download_catalogs(self):
        self.__class__.regions = ["us", "jp"]
        self.settings.update({"storefront": "gb", "applemusicdecrypt-storefront": "jp"})
        for operation, url, ids in (
            ("probe", "https://music.apple.com/us/song/test/7", None),
            ("download", "https://music.apple.com/us/playlist/test/pl.fixture", ["7"]),
        ):
            with self.subTest(operation=operation):
                self.api_paths.clear()
                code, records = self.run_request(operation, url, ids)
                self.assertEqual(code, 0, records)
                self.assertTrue(self.api_paths)
                self.assertTrue(all(path.startswith("/v1/catalog/jp/") for path in self.api_paths))
        self.assertEqual(self.settings["storefront"], "gb")

    def test_unavailable_saved_storefront_fails_before_catalog_and_download(self):
        self.settings["applemusicdecrypt-storefront"] = "jp"
        code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 1)
        self.assertFalse(self.api_paths)
        self.assertEqual(next(item["code"] for item in records if item["event"] == "error"), "unsupported_storefront")
        self.assertEqual(sum(item["event"] == "complete" for item in records), 1)

    def test_api_key_reaches_wrapper_but_not_media_downloads_or_events(self):
        self.settings["applemusicdecrypt-api-key"] = "fixture-wrapper-key"
        start = len(self.headers_seen)
        code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 0, records)
        calls = self.headers_seen[start:]
        for path in ("/status", "/m3u8", "/lyrics"):
            self.assertIn((path, "Bearer fixture-wrapper-key"), calls)
        media_calls = [(path, value) for path, value in calls if path in {"/master.m3u8", "/stream.m3u8", "/media.m4a"}]
        self.assertTrue(media_calls)
        self.assertTrue(all(value != "Bearer fixture-wrapper-key" for _, value in media_calls))
        self.assertNotIn("fixture-wrapper-key", json.dumps(records))

    def test_selected_playlist_download_uses_real_pipeline_and_shared_tags(self):
        from mutagen.mp4 import MP4

        code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 0, records)
        result = records[-1]["result"]
        self.assertEqual(result["completed"], 1)
        self.assertEqual(len(result["artifacts"]), 1)
        artifact = result["artifacts"][0]
        self.assertEqual(artifact["tagger"], "shared-v1")
        path = Path(artifact["path"])
        self.assertEqual(path.name, "02. Artist - Song 7.m4a")
        media = MP4(path)
        self.assertEqual(media["\xa9alb"], ["Playlist"])
        self.assertEqual(media["trkn"], [(2, 2)])
        self.assertIn("Shared lyrics", media["\xa9lyr"][0])
        for atom in ("geID", "cmID", "sfID", "stik", "sonm", "xid "):
            self.assertNotIn(atom, media)
        self.assertEqual(media["\xa9pub"], ["Label"])
        self.assertEqual(media["----:com.apple.iTunes:BARCODE"], [b"123"])
        self.assertNotIn("\xa9trk", media)
        self.assertNotIn("purd", media)
        self.assertTrue(path.with_suffix(".lrc").is_file())
        self.assertFalse(path.with_suffix(".srt").exists())
        self.assertGreater(media.info.length, 1.9)
        self.assertEqual(sum(event["event"] == "complete" for event in records), 1)
        progress = [
            event["data"]
            for event in records
            if event["event"] == "progress"
            and event["data"].get("type") == "track_progress"
        ]
        self.assertTrue(
            any(
                event["phase"] == "processing" and event.get("downloaded_bytes", 0) > 0
                for event in progress
            )
        )
        self.assertTrue(all(event["total_tracks"] == 1 for event in progress))
        self.assertFalse(
            any(path.endswith(("/login", "/logout")) for path in self.calls)
        )
        code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 0, records)
        self.assertEqual(records[-1]["result"]["completed"], 0)
        self.assertEqual(len(records[-1]["result"]["skipped"]), 1)

    def test_unknown_selected_track_fails_once_without_downloading(self):
        before = self.calls.count("/media.m4a")
        code, records = self.run_request(ids=["999"])
        self.assertEqual(code, 1)
        self.assertEqual(self.calls.count("/media.m4a"), before)
        self.assertEqual(sum(event["event"] == "complete" for event in records), 1)
        self.assertEqual(
            next(event["code"] for event in records if event["event"] == "error"),
            "no_tracks",
        )

    def test_song_missing_from_one_wrapper_region_checks_the_next(self):
        self.__class__.regions = ["cn", "us"]
        self.missing_regions = {"cn"}
        self.settings["applemusicdecrypt-storefront"] = "us"
        code, records = self.run_request(url="https://music.apple.com/us/song/test/7", ids=["7"])
        self.assertEqual(code, 0, records)
        self.assertIn("/v1/catalog/cn/songs/7", self.head_paths)

    def test_partial_album_failure_does_not_report_success(self):
        self.failed_id = "8"
        code, records = self.run_request(url="https://music.apple.com/us/album/test/11")
        self.assertEqual(code, 1)
        self.assertEqual(sum(event["event"] == "complete" for event in records), 1)
        self.assertFalse(records[-1]["success"])
        self.assertIn(
            "downloaded 1 of 2 tracks",
            next(event["message"] for event in records if event["event"] == "error"),
        )
        self.assertEqual(len(list(self.output.rglob("*.m4a"))), 1)

    def test_wrapper_protocol_errors_are_normalized_without_prompts(self):
        from backend.router.applemusicdecrypt.engine import runtime
        from backend.router.applemusicdecrypt.progress import Observer
        from applemusicdecrypt.wrapper import WrapperClient

        request = validate_request(
            {
                "operation": "probe",
                "url": "https://music.apple.com/us/song/test/7",
                "settings": self.settings,
                "scratch": self.work.name,
            }
        )
        events = Events(request, io.StringIO())

        async def inspect():
            async with runtime(request, events, Observer(events), []) as (
                _,
                wrapper,
                _,
            ):
                for status, body, code in (
                    (401, b"{}", "authentication_required"),
                    (404, b"{}", "incompatible_wrapper"),
                    (200, b"invalid-json", "invalid_response"),
                ):
                    with self.assertRaises(BackendError) as failure:
                        wrapper._decode_response(
                            "GET",
                            "/key",
                            self.httpx.Response(
                                status,
                                content=body,
                                request=self.httpx.Request(
                                    "GET", "http://localhost/key"
                                ),
                            ),
                        )
                    self.assertEqual(failure.exception.code, code)

        with patch.object(
            WrapperClient,
            "login",
            new=AsyncMock(side_effect=AssertionError("No GUI login")),
        ):
            asyncio.run(inspect())

    def test_missing_codec_falls_back_like_native_applemusicdecrypt(self):
        self.settings["atmos-save-folder"] = str(self.output / "atmos")
        code, records = self.run_request(ids=["7"], quality="ATMOS")
        self.assertEqual(code, 0, records)
        self.assertEqual(records[-1]["result"]["completed"], 1)
        self.assertTrue(any(
            event["event"] == "log" and "switched to another audio codec" in event["message"]
            for event in records
        ))

    def test_lyrics_endpoint_errors_skip_lyrics_instead_of_failing(self):
        from applemusicdecrypt.wrapper import WrapperClient
        from mutagen.mp4 import MP4

        self.settings["aac-save-folder"] = str(self.output / "nolyrics")
        for failure in (
            BackendError("incompatible_wrapper", "no /lyrics"),
            BackendError("invalid_response", "HTML error page"),
        ):
            with self.subTest(code=failure.code), patch.object(
                WrapperClient, "lyrics", new=AsyncMock(side_effect=failure)
            ):
                self.settings["aac-save-folder"] = str(self.output / ("nolyrics-" + failure.code))
                code, records = self.run_request(ids=["7"])
                self.assertEqual(code, 0, records)
                path = Path(records[-1]["result"]["artifacts"][0]["path"])
                self.assertNotIn("\xa9lyr", MP4(path))

    def test_tagging_failure_fails_only_that_track(self):
        from backend.shared.tagging import SharedTagger, TaggingError

        real = SharedTagger.tag
        calls = []

        def tag(tagger, payload):
            calls.append(payload["track"]["id"])
            if len(calls) == 1:
                raise TaggingError("Artwork is not a PNG or JPEG image.")
            return real(tagger, payload)

        self.settings["aac-save-folder"] = str(self.output / "tagfail")
        with patch.object(SharedTagger, "tag", new=tag):
            code, records = self.run_request(ids=["7", "8"])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(records[-2]["code"], "download_failed")
        self.assertIn("downloaded 1 of 2 tracks", records[-2]["message"])

    def test_music_video_falls_back_to_available_audio_and_resolution(self):
        from mutagen.mp4 import MP4

        self.settings.update({"mv-audio-type": "atmos", "mv-max": 16, "mv-save-folder": str(self.output / "fallback")})
        code, records = self.run_request(
            url="https://music.apple.com/us/music-video/test/9", ids=["9"]
        )
        self.assertEqual(code, 0, records)
        path = Path(records[-1]["result"]["artifacts"][0]["path"])
        self.assertNotIn("stik", MP4(path))

    def test_music_video_progressive_keeps_signed_composition_offsets(self):
        from applemusicdecrypt.mvprogressive import defragment

        source = self.root / "bframes-frag.mp4"
        output = self.root / "bframes.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24000/1001:duration=2",
             "-f", "lavfi", "-i", "sine=duration=2:sample_rate=44100",
             "-c:v", "libx264", "-bf", "3", "-g", "24", "-c:a", "aac",
             "-movflags", "frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets",
             "-frag_duration", "1000000", str(source)],
            check=True, capture_output=True,
        )
        defragment(str(source), str(output))
        data = output.read_bytes()
        self.assertNotIn(b"moof", data)
        self.assertNotIn(b"mvex", data)
        self.assertEqual(data[8:12], b"isom")
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "json", str(output)],
            check=True, capture_output=True, text=True,
        ).stdout
        starts = {stream["codec_type"]: float(stream["start_time"]) for stream in json.loads(probe)["streams"]}
        self.assertEqual(starts, {"video": 0.0, "audio": 0.0})
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"], check=True, capture_output=True)

    def test_music_video_track_ids_follow_zhaarey(self):
        from applemusicdecrypt.mux import patch_track_ids

        def traf(track_id):
            tfhd = struct.pack(">I4sII", 16, b"tfhd", 0, track_id)
            return struct.pack(">I4s", 8 + len(tfhd), b"traf") + tfhd

        body = traf(1) + traf(2)
        moof = struct.pack(">I4s", 8 + len(body), b"moof") + body
        patched = patch_track_ids(moof, {1: 1, 2: 3}, b"moof", b"tfhd")
        self.assertEqual([struct.unpack(">I", patched[i:i + 4])[0] for i in (28, 52)], [1, 3])

    def test_music_video_uses_native_muxer_shared_tags_and_custom_filename(self):
        from mutagen.mp4 import MP4

        self.settings.update(
            {"mv-audio-type": "aac", "mv-file-format": "{VideoID} - {VideoName}"}
        )
        code, records = self.run_request(
            url="https://music.apple.com/us/music-video/test/9", ids=["9"]
        )
        self.assertEqual(code, 0, records)
        artifact = records[-1]["result"]["artifacts"][0]
        path = Path(artifact["path"])
        self.assertEqual(path.name, "9 - Video.m4v")
        self.assertNotIn("stik", MP4(path))
        self.assertEqual(MP4(path)["\xa9nam"], ["Video"])
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
        )
        phases = {
            event["data"].get("phase")
            for event in records
            if event["event"] == "progress"
        }
        self.assertTrue(
            {"processing", "remuxing", "tagging", "complete"}.issubset(phases)
        )
        self.assertFalse(any(self.output.rglob("*.part")))

    def test_expired_wrapper_authentication_is_not_swallowed_by_native_fallback(self):
        from applemusicdecrypt.wrapper import WrapperClient

        before = self.calls.count("/media.m4a")
        with patch.object(
            WrapperClient,
            "m3u8",
            new=AsyncMock(
                side_effect=BackendError("authentication_required", "Session expired")
            ),
        ):
            code, records = self.run_request(ids=["7"])
        self.assertEqual(code, 1)
        self.assertEqual(
            next(event["code"] for event in records if event["event"] == "error"),
            "authentication_required",
        )
        self.assertEqual(self.calls.count("/media.m4a"), before)
