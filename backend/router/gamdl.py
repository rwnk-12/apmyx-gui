import asyncio
import copy
import dataclasses
import logging
import re
from types import SimpleNamespace
import sys

from .common import BackendError, RUNTIME, http_json, normalize_tracks, save_folder, tcp_check
from .gamdl_progress import GamdlProgress


TEMPLATE_FIELDS = {
    "AlbumName": "album",
    "AlbumId": "album_id",
    "ArtistName": "artist",
    "UrlArtistName": "album_artist",
    "ArtistId": "artist_id",
    "SongName": "title",
    "SongId": "title_id",
    "SongNumber": "track:02d",
    "TrackNumber": "track:02d",
    "DiscNumber": "disc",
    "PlaylistName": "playlist_title",
    "PlaylistId": "playlist_id",
}


PLAYLIST_TEMPLATE_FIELDS = {
    "PlaylistName": "playlist_title",
    "PlaylistId": "playlist_id",
}


VIDEO_TEMPLATE_FIELDS = {
    "VideoName": "title",
    "ArtistName": "artist",
    "VideoID": "title_id",
    "ReleaseDate": "date:%Y-%m-%d",
    "ReleaseYear": "date:%Y",
}


def template(value, fields=TEMPLATE_FIELDS):
    unknown = set(re.findall(r"\{([^}]+)\}", value)) - fields.keys()
    if unknown:
        raise BackendError(
            "unsupported_setting",
            "Wrapper v2 does not support these naming tokens: " + ", ".join(sorted(unknown)),
        )
    return re.sub(r"\{([^}]+)\}", lambda m: "{" + fields[m[1]] + "}", value)


def playlist_templates(settings):
    name = settings.get("playlist-song-file-format") or settings.get(
        "song-file-format", "{SongNumber}. {SongName}"
    )
    fields = TEMPLATE_FIELDS
    if not settings.get("use-song-metadata-for-playlist-numbering", False):
        name = name.replace("{DiscNumber}", "1")
        fields = {
            **TEMPLATE_FIELDS,
            "SongNumber": "playlist_track:02d",
            "TrackNumber": "playlist_track:02d",
        }
    return (
        template(
            settings.get("playlist-folder-format", "{PlaylistName}"),
            PLAYLIST_TEMPLATE_FIELDS,
        ),
        template(name, fields),
    )


def probe_stream_info(song, codecs, available):
    stream_info = song.get_stream_info

    async def probe(media_id, is_library, webplayback=None, playback=None):
        found = []
        for codec in codecs:
            song.codec_priority = [codec]
            try:
                info = await stream_info(media_id, is_library, webplayback, playback)
            except Exception:
                continue
            finally:
                song.codec_priority = codecs
            if info.audio_track:
                found.append((codec, info))
        available[media_id] = found
        if not found:
            return await stream_info(media_id, is_library, webplayback, playback)
        return found[0][1]

    return probe


class Adapter:
    def status(self, settings):
        health = http_json(settings["wrapper-v2-url"], "/health")
        me = http_json(settings["wrapper-v2-url"], "/me")
        if me.get("version") != "0.0.2":
            raise BackendError(
                "incompatible_wrapper", "Wrapper v2 must be API version 0.0.2."
            )
        if me.get("auth", {}).get("state") != "authenticated":
            raise BackendError(
                "authentication_required", "Authenticate wrapper-v2 externally first."
            )
        if not me.get("runtime", {}).get("playback_ready", False):
            raise BackendError(
                "wrapper_unavailable", "Wrapper-v2 playback is not ready.", True
            )
        tcp_check(
            settings["wrapper-v2-decrypt-host"], settings["wrapper-v2-decrypt-port"]
        )
        return {
            "online": health.get("status") == "ok",
            "authentication": "authenticated",
            "version": me["version"],
        }

    def run(self, request, events):
        status = self.status(request["settings"])
        if request["operation"] == "status":
            return status
        runtime = RUNTIME
        if runtime.is_dir():
            sys.path.insert(0, str(runtime))
        return asyncio.run(self.execute(request, events))

    async def execute(self, request, events):
        from gamdl.api import AppleMusicApi
        from gamdl.api.wrapper import WrapperApi
        from gamdl.downloader import (
            AppleMusicBaseDownloader,
            AppleMusicDownloader,
            AppleMusicSongDownloader,
            AppleMusicMusicVideoDownloader,
            AppleMusicUploadedVideoDownloader,
        )
        from gamdl.interface import (
            AppleMusicBaseInterface,
            AppleMusicInterface,
            AppleMusicSongInterface,
            AppleMusicMusicVideoInterface,
            AppleMusicUploadedVideoInterface,
        )
        from gamdl.interface.enums import (
            SongCodec,
            CoverFormat,
            SyncedLyricsFormat,
            MusicVideoResolution,
        )
        import structlog

        structlog.configure(
            logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        )
        settings = request["settings"]
        wrapper = await WrapperApi.create(
            base_url=settings["wrapper-v2-url"],
            decrypt_host=settings["wrapper-v2-decrypt-host"],
            decrypt_port=int(settings["wrapper-v2-decrypt-port"]),
        )
        api = None
        base_interface = None
        try:
            api = await AppleMusicApi.create_from_wrapper(
                wrapper, language=settings.get("language") or "en-US"
            )
            if not api.active_subscription:
                raise BackendError(
                    "authentication_required",
                    "Wrapper-v2 account has no active subscription.",
                )
            base_interface = await AppleMusicBaseInterface.create(
                apple_music_api=api,
                wrapper_api=wrapper,
                cover_format=CoverFormat.RAW if request["operation"] == "download" else CoverFormat(settings.get("cover-format", "jpg")),
                cover_size=int(
                    str(settings.get("cover-size", "1200x1200")).split("x")[0]
                ),
            )
            from gamdl.interface.types import Cover

            async def get_cover(metadata, interface=base_interface):
                if interface.cover_format != CoverFormat.RAW:
                    return await AppleMusicBaseInterface.get_cover(interface, metadata)
                template = metadata["attributes"]["artwork"]["url"]
                raw = re.sub(
                    r"/\{w\}x\{h\}[a-z]*\.(?:jpe?g|png|webp)$",
                    "",
                    template.replace("is1-ssl", "a1").replace("image/thumb/", ""),
                )
                try:
                    if await interface.get_cover_bytes(raw):
                        return Cover(template_url=template, url=raw,
                                     file_extension=await interface._get_cover_file_extension(raw))
                except Exception:
                    pass
                width, _, height = str(settings.get("cover-size") or "1200x1200").partition("x")
                sized = template.replace("{w}", width).replace("{h}", height or width)
                return Cover(template_url=template, url=sized, file_extension=".jpg")

            base_interface.get_cover = get_cover
            quality = request.get("quality", "ALAC").upper()
            base_interface.lyrics_type = settings.get("lrc-type") or "lyrics"
            codec = (
                "alac"
                if quality == "ALAC"
                else "atmos"
                if quality == "ATMOS"
                else {"aac-lc": "aac-web"}.get(
                    settings.get("aac-type", "aac-lc"),
                    settings.get("aac-type", "aac-lc"),
                )
            )
            song = AppleMusicSongInterface(
                base_interface,
                codec_priority=[SongCodec(codec)],
                synced_lyrics_format=SyncedLyricsFormat(
                    settings.get("lrc-format", "lrc")
                ),
            )
            video = AppleMusicMusicVideoInterface(
                base_interface,
                resolution=MusicVideoResolution(
                    str(settings.get("mv-max", 2160)) + "p"
                ),
            )
            uploaded = AppleMusicUploadedVideoInterface(base_interface)
            interface = AppleMusicInterface(song, video, uploaded)
            if request["operation"] == "probe":
                parent = None
                tracks = {}
                probe_codecs = [SongCodec.ALAC, SongCodec.ATMOS, SongCodec.AAC_WEB]
                available = {}
                song.get_stream_info = probe_stream_info(song, probe_codecs, available)
                song.codec_priority = probe_codecs
                async for media in interface.get_media_from_url(request["url"]):
                    raw = media.media_metadata
                    if not raw:
                        continue
                    if raw.get("type") in {"albums", "playlists"}:
                        parent = raw
                        continue
                    entry = tracks.setdefault(
                        media.media_id,
                        {
                            "trackData": raw,
                            "availableQualities": [],
                            "availableCodecs": [],
                        },
                    )
                    if media.partial:
                        continue
                    found = available.pop(media.media_id, [])
                    if not found and media.stream_info and media.stream_info.audio_track:
                        found = [(None, media.stream_info)]
                    for probe_codec, info in [] if media.error else found:
                        stream = info.audio_track
                        name = str(
                            getattr(stream.codec, "value", stream.codec)
                            or getattr(probe_codec, "value", "")
                        )
                        selected_codec = (
                            "ALAC"
                            if "alac" in name
                            else "ATMOS"
                            if "atmos" in name
                            else "AAC"
                        )
                        entry["availableCodecs"].append(selected_codec)
                        entry["availableQualities"].append(
                            {
                                "codec": selected_codec,
                                "quality": name,
                                "group": name,
                                "selected": False,
                            }
                        )
                    events.emit(
                        "progress",
                        data={
                            "type": "probe_progress",
                            "current": (media.index or 0) + 1,
                            "total": media.total or 1,
                        },
                    )
                if not tracks:
                    raise BackendError(
                        "no_tracks", "Wrapper v2 found no downloadable tracks."
                    )
                result = normalize_tracks(
                    parent or next(iter(tracks.values()))["trackData"],
                    list(tracks.values()),
                )
                events.emit("metadata", data=result)
                return result

            async def filtered(raw):
                ids = request.get("track_ids")
                return (
                    ids is not None
                    and raw.get("type") in {"songs", "music-videos"}
                    and raw["id"] not in ids
                )

            interface.flat_filter_function = filtered
            folder_key = (
                "mv-save-folder"
                if "/music-video/" in request["url"]
                else "alac-save-folder"
                if quality == "ALAC"
                else "atmos-save-folder"
                if quality == "ATMOS"
                else "aac-save-folder"
            )
            artist = template(settings.get("artist-folder-format", "{UrlArtistName}"))
            album = template(settings.get("album-folder-format", "{AlbumName}"))
            filename = template(
                settings.get("song-file-format", "{SongNumber}. {SongName}")
            )
            playlist, playlist_file = playlist_templates(settings)
            if "/music-video/" in request["url"]:
                no_album_folder = ""
                no_album_file = template(
                    settings.get("mv-file-format") or "{ArtistName} - {VideoName}",
                    VIDEO_TEMPLATE_FIELDS,
                )
            else:
                no_album_folder = artist.replace("{album_artist}", "{artist}")
                no_album_file = filename
            excludes = []
            if not settings.get("embed-cover", True):
                excludes.append("cover")
            if not settings.get("embed-lrc", True):
                excludes.append("lyrics")
            tags = settings.get("tag-options", {})
            for source, tag in {
                "write-title": "title",
                "write-artist": "artist",
                "write-album": "album",
                "write-album-artist": "album_artist",
                "write-composer": "composer",
                "write-lyrics": "lyrics",
                "write-cover": "cover",
            }.items():
                if tags.get(source) is False:
                    excludes.append(tag)

            progress = GamdlProgress(events)
            current_metadata = {}
            album_metadata_cache = {}

            async def album_for(media):
                album_id = media.tags.album_id if media.tags else None
                if not album_id:
                    return {}
                if album_id not in album_metadata_cache:
                    album = copy.deepcopy(await base_interface.get_album_cached(album_id))
                    relation = album.get("relationships", {}).get("tracks", {})
                    next_uri = relation.get("next")
                    while next_uri:
                        page = await api.get_extended_api_data(next_uri, relation.get("href"))
                        relation.setdefault("data", []).extend(page.get("data", []))
                        next_uri = page.get("next")
                    if len(album_metadata_cache) >= 8:
                        album_metadata_cache.pop(next(iter(album_metadata_cache)))
                    album_metadata_cache[album_id] = album
                return album_metadata_cache[album_id]

            class DownloadBase(AppleMusicBaseDownloader):
                async def download_stream(self, *args, **kwargs):
                    progress.start_stream()
                    await super().download_stream(*args, **kwargs)
                    progress.finish_stream()

                def get_final_path(self, tags, file_extension, playlist_tags):
                    paths = playlist_paths if playlist_tags else self
                    return AppleMusicBaseDownloader.get_final_path(
                        paths, tags, file_extension, playlist_tags
                    )

                async def apply_tags(self, *args, **kwargs):
                    path = args[0] if args else kwargs["media_path"]
                    cover = args[2] if len(args) > 2 else kwargs.get("cover_bytes")
                    events.tag_file({**current_metadata, "path": path, "cover": cover})

            base = DownloadBase(
                interface=interface,
                output_path=str(save_folder(settings, folder_key)),
                temp_path=request["scratch"],
                album_folder_template="/".join(filter(None, (artist, album))),
                compilation_folder_template="/".join(filter(None, (artist, album))),
                no_album_folder_template=no_album_folder,
                playlist_folder_template=playlist,
                single_disc_file_template=filename,
                multi_disc_file_template=filename,
                no_album_file_template=no_album_file,
                playlist_file_template="{playlist_title}",
                truncate=int(settings.get("limit-max", 200)),
                exclude_tags=excludes,
                silent=True,
                progress_callback=progress.report,
            )
            playlist_paths = SimpleNamespace(
                output_path=base.output_path,
                album_folder_template=playlist,
                compilation_folder_template=playlist,
                no_album_folder_template=playlist,
                single_disc_file_template=playlist_file,
                multi_disc_file_template=playlist_file,
                no_album_file_template=playlist_file,
                _sanitize_string=base._sanitize_string,
            )
            downloader = AppleMusicDownloader(
                song=AppleMusicSongDownloader(base),
                music_video=AppleMusicMusicVideoDownloader(base),
                uploaded_video=AppleMusicUploadedVideoDownloader(base),
                save_cover=False,
                no_synced_lyrics=not settings.get("save-lrc-file", False),
            )
            completed, failed, skipped = 0, 0, []
            async for item in downloader.get_download_item_from_url(request["url"]):
                media = item.media
                if media.partial:
                    continue
                if (
                    request.get("track_ids") is not None
                    and media.media_id not in request["track_ids"]
                ):
                    continue
                raw = media.media_metadata or {}
                name = raw.get("attributes", {}).get("name", media.media_id)
                stream_info = media.stream_info
                progress.reset(sum(
                    bool(getattr(stream_info, track, None))
                    for track in ("audio_track", "video_track")
                ))
                events.emit(
                    "progress",
                    data={
                        "type": "track_start",
                        "track_num": media.index + 1,
                        "total_tracks": media.total or 1,
                        "name": name,
                        "codec": quality,
                    },
                )
                try:
                    album_metadata = await album_for(media)
                    current_metadata.clear()
                    current_metadata.update(
                        version=1, track=raw, album=album_metadata,
                        final_path=getattr(item, "final_path", None),
                        playlist=media.playlist_metadata,
                        position=media.index + 1, total=media.total,
                        lyrics=(media.lyrics.synced or media.lyrics.unsynced or "") if media.lyrics else "",
                        lyrics_ttml=getattr(media.lyrics, "ttml", None),
                    )
                    if not settings.get("embed-lrc", True) and media.tags:
                        media.tags = dataclasses.replace(media.tags, lyrics=None)
                    await downloader.download(item)
                    completed += 1
                    events.emit(
                        "progress",
                        data={
                            "type": "track_complete",
                            "track_num": media.index + 1,
                            "total_tracks": media.total or 1,
                            "name": name,
                        },
                    )
                except BackendError:
                    raise
                except Exception as exc:
                    if type(exc).__name__ == "GamdlDownloaderMediaFileExistsError":
                        skipped.append(name)
                        events.emit(
                            "progress",
                            data={
                                "type": "track_skip",
                                "name": name,
                                "reason": "Already exists",
                            },
                        )
                    else:
                        failed += 1
                        events.emit("log", level="error", message=f"{name}: {exc}")
            if failed or not (completed or skipped):
                raise BackendError(
                    "download_failed",
                    f"Wrapper v2 downloaded {completed} of {completed + failed} tracks.",
                )
            return {"completed": completed, "skipped": skipped}
        finally:
            if base_interface is not None:
                await base_interface.itunes_api.client.aclose()
            if api is not None:
                await api.client.aclose()
            await wrapper.client.aclose()
