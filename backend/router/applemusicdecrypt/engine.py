import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import time
import uuid

import requests

from ..common import BackendError, classify_error, normalize_tracks
from .catalog import Catalog
from .config import codec_for, storefront_for, template, translate_settings, wrapper_headers, VIDEO_TOKENS
from .progress import Observer

if __package__.startswith("backend."):
    from ...shared.files import publish_file
    from ...shared.lyrics import extras_for, render_lyrics
    from ...shared.metadata import normalize_metadata
    from ...shared.token import DeveloperTokenProvider, _expiry
else:
    from shared.files import publish_file
    from shared.lyrics import extras_for, render_lyrics
    from shared.metadata import normalize_metadata
    from shared.token import DeveloperTokenProvider, _expiry


@asynccontextmanager
async def runtime(request, events, observer, ready):
    from applemusicdecrypt.config import Config
    from applemusicdecrypt.logger import GlobalLogger
    from applemusicdecrypt.services import bind

    config = Config.model_validate(translate_settings(request))
    logger = GlobalLogger()
    logger.logger.remove()
    logger.logger.add(
        lambda message: events.emit(
            "log",
            level=message.record["level"].name.lower(),
            message=str(message).rstrip(),
        ),
        format="{message}",
        level="WARNING",
        diagnose=False,
        backtrace=False,
    )
    instances = {
        Config: config,
        GlobalLogger: logger,
        asyncio.AbstractEventLoop: asyncio.get_running_loop(),
        "progress": observer,
        "publish": lambda path, metadata: ready.append((path, metadata)),
        "scratch": request["scratch"],
        "destinations": {},
        "limit": int(request["settings"].get("limit-max") or 200),
        "playlist_numbering": request["settings"].get(
            "use-song-metadata-for-playlist-numbering", False
        ),
        "video_name": template(
            request["settings"].get("mv-file-format") or "{ArtistName} - {VideoName}",
            VIDEO_TOKENS,
        )
        if request["operation"] == "download"
        else "{artist} - {title}",
    }
    tasks_before = set(asyncio.all_tasks())
    with bind(instances) as bound, requests.Session() as session:
        from applemusicdecrypt.api import WebAPI
        from applemusicdecrypt.wrapper import WrapperClient
        from applemusicdecrypt.measurer import Measurer
        from applemusicdecrypt.decrypt import Decryptor

        provider = DeveloperTokenProvider(session)
        supplied = (
            str(request["settings"].get("authorization-token") or "")
            .removeprefix("Bearer ")
            .strip()
        )

        class API(WebAPI):
            def _set_token(self):
                self.token = (
                    supplied if _expiry(supplied) > time.time() + 60 else provider.get()
                )

            async def _request(self, *args, **kwargs):
                response = await super()._request(*args, **kwargs)
                if response.status_code in (401, 403):
                    self.token = await asyncio.to_thread(
                        provider.get, rejected_token=self.token
                    )
                    self.client.headers["Authorization"] = "Bearer " + self.token
                    response = await super()._request(*args, **kwargs)
                if not (args and args[0] == "HEAD" and response.status_code == 404):
                    response.raise_for_status()
                return response

            async def get_cover(self, *args, **kwargs):
                return b""

        class Wrapper(WrapperClient):
            @staticmethod
            def _decode_response(method, path, response):
                if response.status_code in (401, 403):
                    raise BackendError(
                        "authentication_required",
                        "Sign in to Wrapper Lite before continuing.",
                    )
                if response.status_code == 404:
                    raise BackendError(
                        "incompatible_wrapper",
                        f"This wrapper-lite version does not support {path}.",
                    )
                try:
                    return WrapperClient._decode_response(method, path, response)
                except Exception as exc:
                    if "non-JSON" in str(exc) or "unexpected envelope" in str(exc):
                        raise BackendError(
                            "invalid_response",
                            "Wrapper-lite returned malformed machine data.",
                        ) from exc
                    raise

        api = API(config.download.proxy, config.download.parallelNum)
        bound[WebAPI] = api
        wrapper = Wrapper(config.instance.url, config.instance.secure)
        wrapper._client.headers.update(wrapper_headers(request["settings"]))
        bound.update(
            {
                WrapperClient: wrapper,
                Measurer: Measurer(),
                Decryptor: Decryptor(wrapper),
            }
        )
        try:
            yield api, wrapper, bound
        finally:
            pending = set(asyncio.all_tasks()) - tasks_before
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await wrapper.close()
            await api.client.aclose()
            if api.download_client is not None:
                await api.download_client.aclose()
            logger.logger.remove()


async def probe(parent, tracks, wrapper, events):
    from applemusicdecrypt.quality import get_available_audio_quality

    entries = []
    for index, raw in enumerate(tracks):
        qualities = []
        if raw.get("type") == "music-videos":
            qualities = [
                {
                    "codec": "AAC",
                    "quality": "Music Video",
                    "group": "music-video",
                    "selected": False,
                }
            ]
        elif raw.get("type") == "songs":
            try:
                url = await wrapper.m3u8(raw["id"])
                for quality in await get_available_audio_quality(url):
                    codec = (
                        "ALAC"
                        if quality.codec == "alac"
                        else "ATMOS"
                        if quality.codec in {"ec3", "ac3"}
                        else "AAC"
                    )
                    qualities.append(
                        {
                            "codec": codec,
                            "quality": quality.codec_id,
                            "group": quality.codec_id,
                            "selected": False,
                            "sample_rate": quality.sample_rate,
                            "bit_depth": quality.bit_depth,
                        }
                    )
            except Exception as exc:
                failure = (
                    exc if isinstance(exc, BackendError) else classify_error(str(exc))
                )
                if failure.code in {
                    "authentication_required",
                    "wrapper_unavailable",
                    "incompatible_wrapper",
                    "invalid_response",
                }:
                    raise failure
                events.emit(
                    "log",
                    level="warning",
                    message=f"Quality probe unavailable for track {raw['id']}: {type(exc).__name__}",
                )
        entries.append(
            {
                "trackData": raw,
                "availableQualities": qualities,
                "availableCodecs": sorted({item["codec"] for item in qualities}),
            }
        )
        events.emit(
            "progress",
            data={"type": "probe_progress", "current": index + 1, "total": len(tracks)},
        )
    result = normalize_tracks(parent, entries)
    events.emit("metadata", data=result)
    return result


async def execute(request, events):
    observer, ready = Observer(events), []
    async with runtime(request, events, observer, ready) as (api, wrapper, bound):
        storefront = storefront_for(request)
        catalog = Catalog(
            api, storefront, request["settings"].get("language") or "en-US"
        )
        parent, tracks = await catalog.collection(request["url"])
        if parent.get("type") == "artists":
            raise BackendError(
                "unsupported_request",
                "Resolve the artist's releases before selecting tracks.",
            )
        tracks = [
            track for track in tracks if track.get("type") in {"songs", "music-videos"}
        ]
        if not tracks:
            raise BackendError(
                "no_tracks", "Wrapper Lite found no supported media."
            )
        if request["operation"] == "probe":
            return await probe(parent, tracks, wrapper, events)
        return await download(
            request, events, observer, ready, bound, catalog, parent, tracks
        )


async def download(request, events, observer, ready, bound, catalog, parent, tracks):
    from applemusicdecrypt.exceptions import CodecNotFoundException
    from applemusicdecrypt.flags import Flags
    from applemusicdecrypt.models.album_meta import AlbumMeta
    from applemusicdecrypt.models.song_data import Datum as SongDatum
    from applemusicdecrypt.models.playlist_info import PlaylistInfo
    from applemusicdecrypt.rip import Ripper
    from applemusicdecrypt.mv import MVRipper
    from applemusicdecrypt.url import parse_track

    selected = request.get("track_ids")
    available = {str(track["id"]) for track in tracks}
    if selected is not None and not set(selected).issubset(available):
        raise BackendError(
            "no_tracks", "The selected tracks are absent from this album or playlist."
        )
    entries = [
        (position, raw)
        for position, raw in enumerate(tracks, 1)
        if selected is None or str(raw["id"]) in selected
    ]
    playlist = parent if parent.get("type") == "playlists" else None
    playlist_model = (
        PlaylistInfo.model_validate({"data": [playlist]}) if playlist else None
    )
    if playlist_model:
        playlist_model.songIdIndexMapping = {
            raw["id"]: index for index, raw in enumerate(tracks, 1)
        }
    flags = Flags(language=catalog.language)
    codec, ripper = codec_for(request), Ripper()
    completed, skipped, failed = 0, [], []
    for index, (position, item) in enumerate(entries, 1):
        observer.reset()
        ready.clear()
        raw = item
        name = raw.get("attributes", {}).get("name") or raw["id"]
        events.emit(
            "progress",
            data={
                "type": "track_start",
                "track_num": index,
                "total_tracks": len(entries),
                "track_id": raw["id"],
                "name": name,
            },
        )
        try:
            raw = await catalog.resource(raw["type"], raw["id"])
            albums = raw.get("relationships", {}).get("albums", {}).get("data", [])
            album = await catalog.resource("albums", albums[0]["id"]) if albums else {}
            attrs = raw.get("attributes", {})
            bound["naming_tag"] = "".join(
                request["settings"].get(key, default)
                for key, default, enabled in (
                    (
                        "explicit-choice",
                        "[E]",
                        attrs.get("contentRating") == "explicit",
                    ),
                    ("clean-choice", "[C]", attrs.get("contentRating") == "clean"),
                    (
                        "apple-master-choice",
                        "[M]",
                        attrs.get("isAppleDigitalMaster")
                        or attrs.get("isMasteredForItunes"),
                    ),
                )
                if enabled
            )
            url = parse_track(raw["id"], raw["type"], catalog.prefix.split("/")[3])
            if raw["type"] == "music-videos":
                await MVRipper().rip(
                    url,
                    flags,
                    codec=codec
                    if parent.get("type") in {"albums", "playlists"}
                    else None,
                    playlist=playlist_model,
                    album_id=parent.get("id")
                    if parent.get("type") == "albums"
                    else None,
                )
            else:
                if not album:
                    raise BackendError(
                        "invalid_response",
                        "Wrapper Lite requires the song's original album metadata.",
                    )
                ripper._song_info_cache[(raw["id"], url.storefront, flags.language)] = (
                    SongDatum.model_validate(raw)
                )
                ripper._album_info_cache[
                    (album["id"], url.storefront, flags.language)
                ] = AlbumMeta.model_validate({"data": [album]})
                await ripper.rip_song(url, codec, flags, playlist=playlist_model)
            failure = observer.failure()
            if failure:
                raise failure
            if observer.skipped:
                skipped.append(name)
                events.emit(
                    "progress",
                    data={
                        "type": "track_skip",
                        "name": name,
                        "reason": "Already exists",
                    },
                )
                continue
            if len(ready) != 1:
                raise BackendError(
                    "invalid_response",
                    "Wrapper Lite finished without handing off one completed media file.",
                )
            path, metadata = ready[0]
            destination = bound["destinations"].get(path)
            if destination is None:
                raise BackendError(
                    "invalid_response",
                    "Wrapper Lite did not register the output destination.",
                )
            lyrics = getattr(metadata, "lyrics", None)
            artifact = {
                    "version": 1,
                    "path": str(path),
                    "final_path": str(destination),
                    "track": raw,
                    "album": album,
                    "playlist": playlist,
                    "position": position,
                    "total": len(tracks),
                    "lyrics_ttml": lyrics,
                }
            events.tag_file(artifact)
            events.emit(
                "progress",
                data={
                    "type": "track_progress",
                    "phase": "finalizing",
                    "phase_percent": None,
                },
            )
            sidecars = []
            if request["settings"].get("save-cover-file"):
                cover = events.tagger.artwork(
                    normalize_metadata(artifact, request["settings"]), artifact
                )
                if cover:
                    extension = "png" if cover.startswith(b"\x89PNG\r\n\x1a\n") else "jpg"
                    sidecars.append((destination.parent / ("cover." + extension), cover))
            if lyrics and request["settings"].get("save-lrc-file"):
                mode = request["settings"].get("lyrics-mode", "synced")
                kind = request["settings"].get("lrc-format") or "lrc"
                sidecars.append((
                    destination.with_suffix(".txt" if mode == "unsynced" else "." + kind),
                    render_lyrics(lyrics, kind, mode, extras_for(request["settings"])).encode("utf-8"),
                ))
            publish_file(path, destination, request)
            for target, content in sidecars:
                if target.exists():
                    continue
                try:
                    staged = Path(request["scratch"]) / (uuid.uuid4().hex + target.suffix)
                    staged.write_bytes(content)
                    publish_file(staged, target, request)
                except OSError as exc:
                    events.emit("log", level="warning", message=f"{name}: could not save {target.name}: {exc}")
            completed += 1
            events.emit("progress", data={"type": "track_complete", "name": name})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = (
                BackendError("unsupported_quality", str(exc))
                if isinstance(exc, CodecNotFoundException)
                else exc
                if isinstance(exc, BackendError)
                else classify_error(str(exc))
            )
            failed.append(failure)
            events.emit("progress", data={"type": "track_error", "name": name})
            events.emit("log", level="error", message=f"{name}: {failure}")
            if failure.code in {
                "authentication_required",
                "wrapper_unavailable",
                "missing_dependency",
                "incompatible_wrapper",
            }:
                raise failure
    if failed:
        raise BackendError(
            "download_failed",
            f"Wrapper Lite downloaded {completed} of {completed + len(failed)} tracks. {failed[0]}",
        )
    return {"completed": completed, "skipped": skipped}
