import re
from urllib.parse import urlsplit

from ..common import BackendError
if __package__.startswith("backend."):
    from ...shared.folders import save_folder
    from ...shared.settings import APPLE_MUSIC_DECRYPT_DEFAULTS, INTEGER_RANGES
else:
    from shared.folders import save_folder
    from shared.settings import APPLE_MUSIC_DECRYPT_DEFAULTS, INTEGER_RANGES


TOKENS = {
    "AlbumId": "album_id",
    "AlbumName": "album",
    "ArtistName": "artist",
    "UrlArtistName": "album_artist",
    "ArtistId": "artist_id",
    "SongId": "song_id",
    "SongNumber": "tracknum:02d",
    "TrackNumber": "tracknum:02d",
    "DiscNumber": "disk",
    "SongName": "title",
    "PlaylistName": "playlistName",
    "PlaylistId": "playlistId",
    "ReleaseDate": "album_created",
    "ReleaseYear": "album_created:.4",
    "UPC": "upc",
    "Copyright": "copyright",
    "RecordLabel": "record_company",
    "Codec": "codec",
    "Quality": "audio_info",
    "Tag": "tag",
}
CODEC_PRIORITY = ["alac", "ec3", "ac3", "aac"]
VIDEO_TOKENS = {
    "VideoName": "title",
    "ArtistName": "artist",
    "VideoID": "video_id",
    "ReleaseDate": "date",
    "ReleaseYear": "date:.4",
}


def template(value, tokens=TOKENS):
    names = re.findall(r"\{([^{}]+)\}", value)
    unknown = set(names) - tokens.keys()
    if unknown or value.count("{") != len(names) or value.count("}") != len(names):
        raise BackendError(
            "unsupported_setting",
            "Wrapper Lite cannot use this naming template: " + value,
        )
    return re.sub(r"\{([^{}]+)\}", lambda match: "{" + tokens[match[1]] + "}", value)


def codec_for(request):
    quality = request.get("quality", "ALAC").upper()
    if quality == "ALAC":
        return "alac"
    if quality == "ATMOS":
        return "ec3"
    codec = request["settings"].get("aac-type", "aac-lc").lower()
    if codec in {"aac", "aac-lc"}:
        return "aac"
    if codec in {"aac-binaural", "aac-downmix"}:
        return codec
    raise BackendError(
        "unsupported_quality", "Wrapper Lite does not support this AAC selection."
    )


def parse_endpoint(settings):
    endpoint = urlsplit(settings["applemusicdecrypt-url"])
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        raise BackendError(
            "invalid_endpoint",
            "Wrapper Lite requires an HTTP(S) URL without credentials or query parameters.",
        )
    return endpoint


def wrapper_headers(settings):
    endpoint = parse_endpoint(settings)
    key = str(settings.get("applemusicdecrypt-api-key") or "").strip()
    if not key:
        return {}
    if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", key):
        raise BackendError("invalid_endpoint", "The wrapper API key contains invalid characters.")
    if endpoint.scheme != "https" and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise BackendError("invalid_endpoint", "Remote wrapper API keys require HTTPS.")
    return {"Authorization": "Bearer " + key}


def storefront_for(request, regions=None):
    selected = str(request["settings"].get("applemusicdecrypt-storefront") or "").strip().lower()
    storefront = selected or urlsplit(request["url"]).path.strip("/").split("/")[0].lower()
    if not re.fullmatch(r"[a-z]{2}", storefront):
        raise BackendError("invalid_storefront", "Choose a two-letter Apple Music storefront.")
    if selected and regions is not None and selected not in regions:
        raise BackendError(
            "unsupported_storefront",
            f"The selected wrapper does not serve {selected.upper()}. Choose one of its supported storefronts.",
        )
    return storefront


def translate_settings(request):
    settings = {**APPLE_MUSIC_DECRYPT_DEFAULTS, **request["settings"]}
    for key, (minimum, maximum) in INTEGER_RANGES.items():
        try:
            value = int(settings[key])
        except (ValueError, TypeError) as exc:
            raise BackendError("unsupported_setting", f"{key} must be an integer.") from exc
        if isinstance(settings[key], bool) or not minimum <= value <= maximum:
            raise BackendError("unsupported_setting", f"{key} must be between {minimum} and {maximum}.")
        settings[key] = value
    if settings["amd-max-bit-depth"] not in {16, 24}:
        raise BackendError("unsupported_setting", "Maximum bit depth must be 16 or 24.")
    if settings["lyrics-mode"] not in {"synced", "unsynced"} or settings.get("lrc-format", "lrc") not in {"lrc", "ttml"}:
        raise BackendError("unsupported_setting", "Choose a supported lyrics timing and format.")
    naming = settings if request["operation"] == "download" else {}
    endpoint = parse_endpoint(settings)
    artist = template(naming.get("artist-folder-format", "{UrlArtistName}"))
    album = template(naming.get("album-folder-format", "{AlbumName}"))
    playlist = template(naming.get("playlist-folder-format", "{PlaylistName}"))
    name = template(naming.get("song-file-format") or "{SongNumber}. {SongName}")
    codec = codec_for(request)
    key = {"alac": "alac-save-folder", "ec3": "atmos-save-folder"}.get(codec, "aac-save-folder")
    folder = save_folder(settings, key)
    limit = int(settings.get("limit-max") or 200)
    if limit < 1:
        raise BackendError(
            "unsupported_setting", "The filename length limit must be positive."
        )
    return {
        "version": "0.2.0",
        "instance": {
            "url": endpoint.netloc + endpoint.path.rstrip("/"),
            "secure": endpoint.scheme == "https",
        },
        "localInstance": {"enable": False},
        "region": {
            "language": settings.get("language") or "en-US",
            "languageNotExistWarning": False,
        },
        "download": {
            "parallelNum": 1,
            "maxRunningTasks": 1,
            "codecAlternative": True,
            "codecPriority": [codec] + [item for item in CODEC_PRIORITY if item != codec],
            "streamDecrypt": bool(settings["amd-stream-decrypt"]),
            "lowMemory": bool(settings["amd-low-memory"]),
            "resumeDownload": bool(settings["amd-resume-download"]),
            "alacFix": bool(settings["amd-alac-fix"]),
            "failedSongNotPassIntegrityCheck": bool(settings["amd-verify-integrity"]),
            "downloadTimeout": settings["amd-download-timeout"],
            "decryptBatchSize": settings["amd-decrypt-batch-size"],
            "atmosConventToM4a": True,
            "dirPathFormat": str(folder / artist / album),
            "playlistDirPathFormat": str(folder / playlist),
            "songNameFormat": name,
            "playlistSongNameFormat": template(naming.get("playlist-song-file-format")) if naming.get("playlist-song-file-format") else name,
            "audioInfoFormat": "{bit_depth}B-{sample_rate_kHz}kHz",
            "maxSampleRate": int(settings.get("alac-max") or 192000),
            "maxBitDepth": settings["amd-max-bit-depth"],
            "saveLyrics": False,
            "saveCover": False,
            "lyricsSyllable": settings.get("lrc-type") == "syllable-lyrics",
            "lyricsFormat": "ttml",
            "lyricsExtra": [],
            "afterDownloaded": "",
            "retryTime": settings["amd-download-retries"],
            "maxWaitTime": settings["amd-retry-wait"],
        },
        "metadata": {"embedMetadata": []},
        "mv": {
            "saveDir": str(save_folder(settings, "mv-save-folder")),
            "maxHeight": int(settings.get("mv-max") or 2160),
            "audioType": settings.get("mv-audio-type") or "atmos",
            "segmentConcurrency": settings["amd-mv-segment-concurrency"],
            "segmentRetries": settings["amd-mv-segment-retries"],
        },
    }
