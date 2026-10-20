import asyncio
import base64
import copy
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "backend/runtime"))
from backend.bridge import dispatch
from backend.router.common import BackendError, Events, validate_request
from backend.router.gamdl import Adapter as GamdlAdapter
from backend.router.legacy import Adapter as LegacyAdapter
from backend.shared.metadata import normalize_metadata
from backend.shared.media_tags import MediaTags
from backend.shared.progress import ProgressRouter, gui_progress
from backend.shared.tagging import SharedTagger, TaggingError
from backend.shared.lyrics import render_lyrics
from mutagen.mp4 import MP4


TRACK = {
    "id": "7",
    "type": "songs",
    "attributes": {
        "name": "Title \u65e5\u672c",
        "artistName": "Artist",
        "albumName": "Album",
        "composerName": "Composer",
        "genreNames": ["Pop"],
        "trackNumber": 2,
        "discNumber": 2,
        "releaseDate": "2020-01-02",
        "isrc": "TEST00000001",
        "contentRating": "explicit",
    },
    "relationships": {"artists": {"data": [{"id": "10"}]}},
}
ALBUM = {
    "id": "11",
    "attributes": {
        "name": "Album",
        "artistName": "Album Artist",
        "trackCount": 3,
        "recordLabel": "Label",
        "copyright": "Copyright",
        "upc": "12345",
        "releaseDate": "2020-01-02",
    },
    "relationships": {
        "tracks": {
            "data": [
                {"attributes": {"discNumber": 1}},
                {"attributes": {"discNumber": 2}},
                {"attributes": {"discNumber": 2}},
            ]
        }
    },
}
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a2ioAAAAASUVORK5CYII="
)


def payload(path):
    return {
        "version": 1,
        "path": str(path),
        "track": copy.deepcopy(TRACK),
        "album": copy.deepcopy(ALBUM),
        "lyrics": "[ar:Artist]\r\n[00:01.00]Line\r\n",
        "cover": base64.b64encode(PNG).decode(),
    }


def mdat_hash(path):
    data = path.read_bytes()
    offset = 0
    digest = hashlib.sha256()
    while offset + 8 <= len(data):
        size, kind = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            size = struct.unpack_from(">Q", data, offset + 8)[0]
            header = 16
        if not size:
            size = len(data) - offset
        if kind == b"mdat":
            digest.update(data[offset + header : offset + size])
        offset += size
    return digest.digest()


SONG_TAGS = {
    "\xa9nam", "\xa9ART", "aART", "\xa9alb", "\xa9day", "\xa9wrt", "\xa9gen",
    "trkn", "disk", "\xa9lyr", "covr", "cprt", "\xa9pub", "rtng", "cnID", "plID", "atID",
    "----:com.apple.iTunes:ISRC", "----:com.apple.iTunes:BARCODE",
}
MUSIC_VIDEO_TAGS = {
    "\xa9nam", "\xa9ART", "\xa9alb", "\xa9gen", "\xa9day", "rtng", "covr",
    "----:com.apple.iTunes:ISRC",
}


class MediaTagModelTests(unittest.TestCase):
    def test_mp4_conversion_writes_only_applemusicdecrypt_atoms(self):
        tags = MediaTags(
            album="Album", album_artist="Album Artist", album_id=11, artist="Artist",
            artist_id=10, composer="Composer", copyright="C", disc=1, disc_total=2,
            genre="Pop", lyrics="Line", rating=0, title="Title", title_id=7, track=3,
            track_total=9, date=datetime.date(2020, 1, 2),
        ).as_mp4_tags("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(set(tags), SONG_TAGS - {"covr", "\xa9pub", "----:com.apple.iTunes:ISRC", "----:com.apple.iTunes:BARCODE"})
        self.assertEqual(tags["rtng"], [0])
        self.assertEqual(tags["\xa9day"], ["2020-01-02T00:00:00Z"])
        self.assertEqual(tags["disk"], [[1, 2]])
        empty = MediaTags(disc=0, disc_total=0, track=0, track_total=0).as_mp4_tags()
        self.assertNotIn("trkn", empty)
        self.assertNotIn("disk", empty)


class SharedProgressTests(unittest.TestCase):
    @unittest.skipUnless(
        (ROOT / "backend/runtime/gamdl/interface/song.py").is_file(),
        "The pinned GAMDL runtime is required for its lyrics API integration.",
    )
    def test_gamdl_keeps_raw_word_lyrics_for_shared_renderer(self):
        from gamdl.interface.song import AppleMusicSongInterface

        ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="00:01.235" end="00:04.000"><span>Human </span><span>Nature</span></p></div></body></tt>'
        metadata = {
            "id": "7",
            "attributes": {"hasLyrics": True, "playParams": {}},
        }
        response = copy.deepcopy(metadata)
        response["relationships"] = {
            "syllable-lyrics": {"data": [{"attributes": {"ttml": ttml}}]}
        }
        base = Mock(lyrics_type="syllable-lyrics")
        base.apple_music_api.get_song = AsyncMock(return_value={"data": [response]})
        lyrics = asyncio.run(AppleMusicSongInterface(base).get_lyrics(metadata))
        base.apple_music_api.get_song.assert_awaited_once_with(
            "7", include="syllable-lyrics,albums"
        )
        self.assertEqual(lyrics.ttml, ttml)
        self.assertEqual(render_lyrics(lyrics.ttml), "[00:01.24]Human Nature")

    def test_pipelined_video_streams_share_one_monotonic_track(self):
        router = ProgressRouter({}, interval=0)
        router.normalize({"type": "track_start", "name": "Video"})
        records = []
        for stream in (1, 2):
            for phase in ("downloading", "decrypting"):
                records.append(
                    router.normalize(
                        {
                            "type": "track_progress",
                            "phase": phase,
                            "phase_percent": 100,
                            "stream_index": stream,
                            "stream_count": 2,
                        }
                    )
                )
        self.assertEqual(
            [record["percent"] for record in records], [30, 47.5, 77.5, 95]
        )

    def test_lrc_includes_translation_and_pronunciation_lines(self):
        ttml = (
            '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:itunes="http://music.apple.com/lyric-ttml-internal">'
            '<head><metadata><iTunesMetadata xmlns="http://music.apple.com/lyric-ttml-internal">'
            '<translations><translation type="subtitle" xml:lang="en"><text for="L1">Hello</text></translation></translations>'
            '<transliterations><transliteration xml:lang="ja-Latn"><text for="L1"><span>kon</span> <span>nichiwa</span></text></transliteration></transliterations>'
            '</iTunesMetadata></metadata></head>'
            '<body><div><p begin="1s" end="2s" itunes:key="L1">こんにちは</p></div></body></tt>'
        )
        self.assertEqual(
            render_lyrics(ttml, "lrc", "synced", ("translation", "pronunciation")),
            "[00:01.00]こんにちは\n[00:01.00]Hello\n[00:01.00]kon nichiwa",
        )
        self.assertEqual(render_lyrics(ttml, "lrc", "synced", ()), "[00:01.00]こんにちは")
        self.assertNotIn("Hello", render_lyrics(ttml, "lrc", "synced", ("pronunciation",)))

    def test_shared_lyrics_keep_word_spans_and_normalize_timestamp_precision(self):
        ttml = '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="61.235s" end="64s"><span>Human </span><span>Nature</span></p></div></body></tt>'
        self.assertEqual(render_lyrics(ttml), "[01:01.24]Human Nature")
        self.assertEqual(
            render_lyrics(ttml, "ttml"),
            render_lyrics(ttml.replace("<body>", "<body>\n  "), "ttml"),
        )

    def test_all_engines_have_one_schema_and_identical_phase_weights(self):
        results = []
        for engine in ("legacy", "wrapper-v2", "applemusicdecrypt"):
            router = ProgressRouter({"wrapper": engine, "track_ids": ["7"]}, interval=0)
            router.normalize(
                {
                    "type": "track_start",
                    "track_num": 9,
                    "total_tracks": 20,
                    "name": "Song",
                }
            )
            records = [
                router.normalize(
                    {"type": "track_progress", "phase": phase, "phase_percent": value}
                )
                for phase, value in (
                    ("downloading", 50),
                    ("decrypting", 50),
                    ("remuxing", 100),
                    ("tagging", 100),
                )
            ]
            results.append([record["percent"] for record in records])
            self.assertTrue(
                all(
                    record["schema_version"] == 1
                    and record["track_num"] == 1
                    and record["total_tracks"] == 1
                    for record in records
                )
            )
        self.assertEqual(results, [[30, 77.5, 98, 99]] * 3)

    def test_first_phase_and_terminal_updates_bypass_rate_limit(self):
        router = ProgressRouter({})
        router.normalize({"type": "track_start", "name": "Song"})
        self.assertIsNotNone(
            router.normalize(
                {"type": "track_progress", "phase": "downloading", "phase_percent": 0}
            )
        )
        self.assertIsNone(
            router.normalize(
                {"type": "track_progress", "phase": "downloading", "phase_percent": 10}
            )
        )
        self.assertIsNotNone(
            router.normalize(
                {"type": "track_progress", "phase": "decrypting", "phase_percent": 0}
            )
        )
        done = router.normalize({"type": "track_complete"})
        self.assertEqual(done["percent"], 100)
        self.assertIsNone(router.normalize({"type": "track_complete"}))

    def test_unknown_totals_and_nonfinite_values_are_not_fake_percentages(self):
        router = ProgressRouter({}, interval=0)
        record = router.normalize(
            {
                "type": "track_progress",
                "phase": "downloading",
                "phase_percent": float("nan"),
            }
        )
        self.assertTrue(record["indeterminate"])
        self.assertEqual(gui_progress(record)[1], -1)
        self.assertLess(record["percent"], 100)

    def test_duplicate_start_does_not_increment_selected_track(self):
        router = ProgressRouter({"track_ids": ["7", "8"]}, interval=0)
        start = {"type": "track_start", "track_id": "7", "name": "Song"}
        self.assertEqual(router.normalize(start)["track_num"], 1)
        self.assertIsNone(router.normalize(start))
        router.normalize({"type": "track_complete"})
        self.assertEqual(router.normalize({**start, "track_id": "8"})["track_num"], 2)

    def test_playlist_tag_policy_and_original_numbering(self):
        data = payload("unused")
        data.update(
            playlist={"attributes": {"name": "Playlist", "curatorName": "Curator"}},
            position=8,
            total=12,
        )
        canonical = normalize_metadata(data, {"use-songinfo-for-playlist": False})
        self.assertEqual(
            (
                canonical["album"],
                canonical["track"],
                canonical["track_total"],
                canonical["disc"],
            ),
            ("Playlist", 8, 12, 1),
        )
        original = normalize_metadata(
            data,
            {
                "use-songinfo-for-playlist": False,
                "use-song-metadata-for-playlist-numbering": True,
            },
        )
        self.assertEqual(
            (original["track"], original["disc"], original["track_total"]), (2, 2, 2)
        )


@unittest.skipUnless(
    shutil.which("ffmpeg"),
    "FFmpeg is required to generate an independent MP4 test fixture.",
)
class SharedTaggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(
            prefix="shared-tag-tests-", dir=ROOT / "build"
        )
        cls.root = Path(cls.folder.name)
        cls.fixture = cls.root / "fixture.m4a"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=duration=0.05",
                "-c:a",
                "aac",
                str(cls.fixture),
            ],
            check=True,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        self.settings = {
            "alac-save-folder": str(self.root),
            "aac-save-folder": str(self.root),
            "embed-cover": True,
            "embed-lrc": True,
        }
        self.path = self.root / (self.id().split(".")[-1] + ".m4a")
        shutil.copyfile(self.fixture, self.path)

    def test_day_uses_album_date_without_extra_date_tags(self):
        track = {**TRACK, "attributes": {**TRACK["attributes"], "releaseDate": "1973-01-05"}}
        album = {**ALBUM, "attributes": {**ALBUM["attributes"], "releaseDate": "1991-11-19"}}
        request, events = self.events("legacy")
        events.tag_file({"version": 1, "path": str(self.path), "track": track, "album": album})
        tagged = MP4(self.path)
        self.assertEqual(tagged["\xa9day"], ["1991-11-19T00:00:00Z"])
        self.assertNotIn("----:com.apple.iTunes:RELEASETIME", tagged)
        self.assertNotIn("purd", tagged)
        self.assertNotIn("\xa9trk", tagged)

    def test_tag_switches_remove_ids_and_rating(self):
        options = {key: True for key in ("write-title", "write-artist", "write-album")}
        options.update({"write-apple-ids": False, "write-rating": False})
        self.settings["tag-options"] = options
        request, events = self.events("legacy")
        events.tag_file({"version": 1, "path": str(self.path), "track": TRACK, "album": ALBUM})
        tagged = MP4(self.path)
        for atom in ("cnID", "plID", "atID", "rtng"):
            self.assertNotIn(atom, tagged, atom)
        self.assertEqual(tagged["\xa9nam"], [TRACK["attributes"]["name"]])

    def events(self, wrapper):
        request = validate_request(
            {
                "operation": "download",
                "wrapper": wrapper,
                "url": "https://music.apple.com/us/song/test/7",
                "settings": self.settings,
                "scratch": str(self.root),
                "track_ids": ["7"],
            }
        )
        events = Events(request, io.StringIO())
        return request, events

    def test_engine_handoffs_produce_identical_tags_and_unchanged_audio(self):
        outputs = []
        for engine in ("legacy", "wrapper-v2"):
            path = self.root / (engine + ".m4a")
            shutil.copyfile(self.fixture, path)
            before = mdat_hash(path)
            media = MP4(path)
            media["\xa9too"] = [engine]
            media["----:com.apple.iTunes:ENGINE_ONLY"] = [engine.encode()]
            media.save()
            request, events = self.events(engine)
            data = payload(path)
            data["lyrics"] = "Engine-specific lyrics: " + engine
            data["lyrics_ttml"] = (
                '<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s">Line</p></div></body></tt>'
            )
            if engine == "legacy":

                def run(command, cwd, callback, **kwargs):
                    callback("AMDL_ARTIFACT::" + json.dumps(data), False)
                    callback('AMDL_PROGRESS::{"type":"track_complete"}', False)
                    callback('AMDL_SUMMARY::{"Success":1,"Error":0}', False)
                    return 0

                with (
                    patch.object(LegacyAdapter, "status"),
                    patch("backend.router.legacy.binary", return_value="engine"),
                    patch("backend.router.legacy.run_process", side_effect=run),
                ):
                    LegacyAdapter().run(request, events)
            else:
                self.gamdl_handoff(request, events, path)
            tagged = MP4(path)
            self.assertEqual(mdat_hash(path), before)
            self.assertNotIn("\xa9too", tagged)
            self.assertNotIn("----:com.apple.iTunes:ENGINE_ONLY", tagged)
            self.assertEqual(tagged["trkn"], [(2, 2)])
            self.assertEqual(tagged["disk"], [(2, 2)])
            self.assertEqual(tagged["\xa9lyr"], ["[00:01.00]Line"])
            self.assertEqual(len(events.tagger.completed), 1)
            self.assertEqual(set(tagged.tags), SONG_TAGS)
            self.assertEqual(tagged["\xa9pub"], ["Label"])
            self.assertNotIn("purd", tagged)
            self.assertNotIn("\xa9trk", tagged)
            self.assertEqual(tagged["----:com.apple.iTunes:BARCODE"], [b"12345"])
            outputs.append(dict(tagged.tags))
        self.assertEqual(outputs[0], outputs[1])

    def gamdl_handoff(self, request, events, path):
        from types import SimpleNamespace as NS
        from gamdl.api import AppleMusicApi
        from gamdl.api.wrapper import WrapperApi
        from gamdl.downloader import AppleMusicDownloader
        from gamdl.interface import AppleMusicBaseInterface
        from gamdl.interface.enums import CoverFormat

        wrapper = NS(client=NS(aclose=AsyncMock()))
        api = NS(active_subscription=True, client=NS(aclose=AsyncMock()))
        base = NS(
            get_album_cached=AsyncMock(return_value=ALBUM),
            itunes_api=NS(client=NS(aclose=AsyncMock())),
            cover_format=CoverFormat.JPG,
        )
        media = NS(
            partial=False,
            index=0,
            total=1,
            media_id="7",
            media_metadata=TRACK,
            tags=NS(album_id=11),
            playlist_metadata=None,
            lyrics=NS(
                synced="Different native lyric format",
                unsynced="Line",
                ttml='<tt xmlns="http://www.w3.org/ns/ttml"><body><div><p begin="1s">Line</p></div></body></tt>',
            ),
            stream_info=NS(audio_track=NS(), video_track=None),
        )

        async def items(self, url):
            yield NS(media=media)

        async def download(self, item):
            await self.base.apply_tags(str(path), media.tags, PNG)

        with (
            patch.object(WrapperApi, "create", new=AsyncMock(return_value=wrapper)),
            patch.object(
                AppleMusicApi, "create_from_wrapper", new=AsyncMock(return_value=api)
            ),
            patch.object(
                AppleMusicBaseInterface, "create", new=AsyncMock(return_value=base)
            ),
            patch.object(AppleMusicDownloader, "get_download_item_from_url", new=items),
            patch.object(AppleMusicDownloader, "download", new=download),
        ):
            asyncio.run(GamdlAdapter().execute(request, events))

    def test_disabled_fields_are_removed_for_every_writer(self):
        self.settings["tag-options"] = {
            "write-artist": False,
            "write-cover": False,
            "write-lyrics": False,
            "write-disc-track": False,
        }
        tagger = SharedTagger({"settings": self.settings})
        tagger.tag(payload(self.path))
        tags = MP4(self.path)
        for name in ("\xa9ART", "covr", "\xa9lyr", "trkn", "disk"):
            self.assertNotIn(name, tags)

    def test_music_video_tags_match_applemusicdecrypt(self):
        data = payload(self.path)
        data["track"]["type"] = "music-videos"
        data["track"]["attributes"].update({"contentRating": "clean", "sortName": "Title Sort", "xid": "ISRC:TEST00000001"})
        data["album"]["attributes"].update({"isCompilation": True})
        before = mdat_hash(self.path)
        SharedTagger({"settings": self.settings}).tag(data)
        tags = MP4(self.path)
        self.assertEqual(set(tags.tags), MUSIC_VIDEO_TAGS)
        self.assertEqual(tags["rtng"], [2])
        self.assertEqual(tags["\xa9day"], ["2020-01-02T00:00:00Z"])
        self.assertEqual(bytes(tags["----:com.apple.iTunes:ISRC"][0]), b"TEST00000001")
        self.assertEqual(mdat_hash(self.path), before)

    def test_disabled_title_artist_and_isrc_are_removed(self):
        self.settings["tag-options"] = {"write-artist": False, "write-title": False, "write-isrc": False}
        SharedTagger({"settings": self.settings}).tag(payload(self.path))
        tags = MP4(self.path)
        for atom in ("\xa9nam", "\xa9ART", "----:com.apple.iTunes:ISRC"):
            self.assertNotIn(atom, tags)

    def test_gamdl_preserves_shared_tagging_error_code(self):
        request, events = self.events("wrapper-v2")
        with patch.object(
            events.tagger, "tag", side_effect=TaggingError("Fixture error")
        ):
            with self.assertRaises(BackendError) as failure:
                self.gamdl_handoff(request, events, self.path)
        self.assertEqual(failure.exception.code, "tagging_failed")

    def test_rejects_invalid_artifact_without_changing_file(self):
        before = self.path.read_bytes()
        tagger = SharedTagger({"settings": self.settings})
        with self.assertRaises(TaggingError):
            tagger.tag({**payload(self.path), "version": 2})
        with self.assertRaises(TaggingError):
            tagger.tag({**payload(self.path), "track": {}})
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(TaggingError):
            SharedTagger(
                {"settings": {"alac-save-folder": str(self.root / "elsewhere")}}
            ).tag(payload(self.path))

    def test_tagging_failure_has_one_failed_terminal_result(self):
        request, _ = self.events("legacy")
        output = io.StringIO()
        adapter = Mock()
        adapter.run.side_effect = lambda req, events: events.tag_file(
            {**payload(self.path), "track": {}}
        )
        with patch("backend.bridge.adapter_for", return_value=adapter):
            self.assertEqual(dispatch(request, output), 1)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            [event["code"] for event in records if event["event"] == "error"],
            ["tagging_failed"],
        )
        self.assertEqual(sum(event["event"] == "complete" for event in records), 1)
        self.assertFalse(records[-1]["success"])

    def test_completed_download_cannot_bypass_shared_tagger(self):
        request, _ = self.events("legacy")
        output = io.StringIO()
        adapter = Mock()
        adapter.run.return_value = {"Success": 1, "Error": 0}
        with patch("backend.bridge.adapter_for", return_value=adapter):
            self.assertEqual(dispatch(request, output), 1)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(
            next(record["code"] for record in records if record["event"] == "error"),
            "invalid_response",
        )
        self.assertFalse(records[-1]["success"])

    def test_mixed_existing_and_new_files_verify_each_engine_count(self):
        for wrapper, result in (
            ("legacy", {"Success": 2, "Error": 0}),
            ("wrapper-v2", {"completed": 1, "skipped": ["Existing"]}),
        ):
            with self.subTest(wrapper=wrapper):
                request, _ = self.events(wrapper)
                output = io.StringIO()

                def download(req, events):
                    events.emit(
                        "progress",
                        data={"type": "track_skip", "reason": "Already exists"},
                    )
                    events.tag_file(payload(self.path))
                    return result

                adapter = Mock(run=download)
                with patch("backend.bridge.adapter_for", return_value=adapter):
                    self.assertEqual(dispatch(request, output), 0)
                records = [json.loads(line) for line in output.getvalue().splitlines()]
                self.assertEqual(len(records[-1]["result"]["artifacts"]), 1)

    def test_gamdl_existing_skip_cannot_hide_an_untagged_new_file(self):
        request, _ = self.events("wrapper-v2")
        output = io.StringIO()

        def download(req, events):
            events.emit(
                "progress", data={"type": "track_skip", "reason": "Already exists"}
            )
            return {"completed": 1, "skipped": ["Existing"]}

        with patch("backend.bridge.adapter_for", return_value=Mock(run=download)):
            self.assertEqual(dispatch(request, output), 1)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(records[-1]["success"])
