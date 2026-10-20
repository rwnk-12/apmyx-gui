import base64
from dataclasses import fields
import datetime
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

import requests
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

from .metadata import normalize_lyrics, normalize_metadata
from .lyrics import extras_for, render_lyrics
from .folders import save_folders
from .media_tags import MediaTags

MUSIC_VIDEO_TAGS = {
    "©nam", "©ART", "©alb", "©gen", "©day", "rtng",
    "----:com.apple.iTunes:ISRC",
}


class TaggingError(RuntimeError):
    pass


class SharedTagger:
    def __init__(self, request):
        self.request = request
        self.settings = request.get("settings", {})
        self.artwork_cache = {}
        self.completed = {}

    def path_for(self, value, must_exist=True):
        path = Path(value).resolve(strict=must_exist)
        roots = [self.request.get("scratch"), self.request.get("work_dir")]
        roots.extend(save_folders(self.settings))
        if path.suffix.lower() not in {".m4a", ".mp4", ".m4v"} or (
            must_exist and not path.is_file()
        ):
            raise TaggingError(
                "Shared tagging requires a finished MP4, M4A, or M4V file."
            )
        if not any(path.is_relative_to(Path(root).resolve()) for root in roots if root):
            raise TaggingError(
                "Tagging output is outside this job's output directories."
            )
        return path

    def enabled(self, key, default=True):
        return self.settings.get("tag-options", {}).get(key, default)

    def artwork(self, metadata, payload):
        if not self.settings.get("save-cover-file") and (
            not self.settings.get("embed-cover", True) or not self.enabled("write-cover")
        ):
            return None
        template = metadata["artwork"].get("url")
        if template:
            size = str(self.settings.get("cover-size") or "1200x1200").split("x")
            width, height = size[0], size[-1]
            url = template.replace("{w}", width).replace("{h}", height)
            parts = urlsplit(url)
            if parts.scheme != "https" or not (parts.hostname or "").endswith(
                ".mzstatic.com"
            ):
                raise TaggingError("Artwork must use an Apple HTTPS image endpoint.")
            extension = str(self.settings.get("cover-format") or "jpg").lower()
            if extension in {"jpg", "png"}:
                url = urlunsplit(
                    parts._replace(
                        path=re.sub(
                            r"\.(jpg|jpeg|png|webp)$",
                            "." + extension,
                            parts.path,
                            flags=re.I,
                        )
                    )
                )
            if url not in self.artwork_cache:
                response = requests.get(url, timeout=(5, 30))
                try:
                    response.raise_for_status()
                    self.artwork_cache[url] = response.content
                finally:
                    response.close()
                if len(self.artwork_cache) > 8:
                    self.artwork_cache.pop(next(iter(self.artwork_cache)))
            return self.artwork_cache[url]
        cover = payload.get("cover")
        if isinstance(cover, str):
            return base64.b64decode(cover, validate=True)
        return cover

    def mp4_tags(self, metadata, payload):
        values = {field.name: metadata.get(field.name) for field in fields(MediaTags)}
        for name, value in values.items():
            if value == "" or (name.endswith("_id") and value == 0):
                values[name] = None
        if values["date"]:
            try:
                values["date"] = datetime.datetime.fromisoformat(
                    values["date"].split("Z")[0]
                )
            except ValueError:
                pass
        for field, option in (
            ("album", "write-album"),
            ("album_artist", "write-album-artist"),
            ("artist", "write-artist"),
            ("composer", "write-composer"),
            ("copyright", "write-copyright"),
            ("date", "write-date"),
            ("genre", "write-genre"),
            ("title", "write-title"),
        ):
            if not self.enabled(option):
                values[field] = None
        if not self.enabled("write-disc-track"):
            for field in ("disc", "disc_total", "track", "track_total"):
                values[field] = None
        if not self.enabled("write-rating"):
            values["rating"] = None
        if not self.enabled("write-apple-ids"):
            for field in ("title_id", "album_id", "artist_id"):
                values[field] = None
        if self.settings.get("embed-lrc", True) and self.enabled("write-lyrics"):
            lyrics = (
                render_lyrics(
                    payload["lyrics_ttml"], self.settings.get("lrc-format", "lrc"),
                    self.settings.get("lyrics-mode", "synced")
                    if self.request.get("wrapper", "applemusicdecrypt") == "applemusicdecrypt"
                    else "synced",
                    extras_for(self.settings),
                )
                if payload.get("lyrics_ttml")
                else payload.get("lyrics", "")
            )
            values["lyrics"] = normalize_lyrics(lyrics) or None
        tags = MediaTags(**values).as_mp4_tags("%Y-%m-%dT%H:%M:%SZ")
        if metadata.get("publisher") and self.enabled("write-publisher"):
            tags["\xa9pub"] = [metadata["publisher"]]
        for field, name, option in (
            ("isrc", "ISRC", "write-isrc"),
            ("upc", "BARCODE", "write-upc"),
        ):
            if metadata[field] and self.enabled(option):
                tags["----:com.apple.iTunes:" + name] = [
                    MP4FreeForm(metadata[field].encode("utf-8"))
                ]
        if metadata["media_type"] == 6:
            tags = {key: value for key, value in tags.items() if key in MUSIC_VIDEO_TAGS}
        return tags

    def tag(self, payload):
        try:
            if payload.get("version", 1) != 1:
                raise TaggingError("Unsupported metadata artifact version.")
            path = self.path_for(payload["path"])
            final_path = (
                self.path_for(payload["final_path"], must_exist=False)
                if payload.get("final_path")
                else path
            )
            if path in self.completed:
                return self.completed[path]
            metadata = normalize_metadata(payload, self.settings)
            tags = self.mp4_tags(metadata, payload)
            cover = self.artwork(metadata, payload)
            if cover and self.settings.get("embed-cover", True) and self.enabled("write-cover"):
                image_format = (
                    MP4Cover.FORMAT_PNG
                    if cover.startswith(b"\x89PNG\r\n\x1a\n")
                    else MP4Cover.FORMAT_JPEG
                    if cover.startswith(b"\xff\xd8")
                    else None
                )
                if image_format is None:
                    raise TaggingError("Artwork is not a PNG or JPEG image.")
                tags["covr"] = [MP4Cover(cover, imageformat=image_format)]
            media = MP4(path)
            if media.tags is None:
                media.add_tags()
            media.tags.clear()
            media.tags.update(tags)
            media.save()
            receipt = {
                "version": 1,
                "path": str(final_path),
                "track_id": metadata["source_id"],
                "tagger": "shared-v1",
            }
            self.completed[path] = receipt
            return receipt
        except (TaggingError, requests.RequestException):
            raise
        except Exception as exc:
            raise TaggingError(f"Shared metadata tagging failed: {exc}") from exc
