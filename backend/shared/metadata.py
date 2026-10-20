import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from xml.etree import ElementTree
from .lyrics import canonical_ttml

def text(value):
    return unicodedata.normalize("NFC", str(value or "")).strip()


def number(value):
    try:
        return max(0, int(value or 0))
    except (ValueError, TypeError):
        return 0


def attributes(resource):
    return resource.get("attributes", {}) if isinstance(resource, dict) else {}


def relationship(resource, name):
    return resource.get("relationships", {}).get(name, {}).get("data", []) or []


def normalize_lyrics(value):
    if re.match(r"^(<\?xml|<(?:\w+:)?tt(?:\s|>))", text(value)):
        return canonical_ttml(ElementTree.fromstring(text(value)))
    lines = text(value).replace("\r\n", "\n").replace("\r", "\n").splitlines()
    result = []
    for line in lines:
        line = line.rstrip()
        if re.match(r"^\[(ar|al|ti|by|length|offset):", line, re.I):
            continue

        def timestamp(match):
            seconds = Decimal(match[1]) * 60 + Decimal(match[2])
            seconds = seconds.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            return f"[{int(seconds // 60):02d}:{seconds % 60:05.2f}]"

        result.append(re.sub(r"\[(\d+):(\d+(?:\.\d+)?)\]", timestamp, line))
    return "\n".join(result).strip()


def normalize_metadata(payload, settings):
    track = payload.get("track") or {}
    album = payload.get("album") or {}
    playlist = payload.get("playlist") or {}
    attrs, album_attrs = attributes(track), attributes(album)
    if not attrs.get("name"):
        raise ValueError("Track metadata is missing its title.")
    album_tracks = relationship(album, "tracks")
    disc = number(attrs.get("discNumber")) or 1
    disc_tracks = [
        item
        for item in album_tracks
        if number(attributes(item).get("discNumber")) == disc
    ]
    disc_total = max(
        [number(attributes(item).get("discNumber")) for item in album_tracks]
        + [number(payload.get("disc_total")), disc]
    )
    artists = relationship(track, "artists")
    album_id = album.get("id") or next(
        (item.get("id") for item in relationship(track, "albums")), None
    )
    genre = attrs.get("genreNames") or album_attrs.get("genreNames") or []
    result = {
        "title": text(attrs.get("name")),
        "artist": text(attrs.get("artistName")),
        "album": text(album_attrs.get("name") or attrs.get("albumName")),
        "album_artist": text(album_attrs.get("artistName") or attrs.get("artistName")),
        "composer": text(attrs.get("composerName")),
        "genre": text(genre[0] if genre else ""),
        "date": text(album_attrs.get("releaseDate") or attrs.get("releaseDate")),
        "copyright": text(album_attrs.get("copyright") or attrs.get("copyright")),
        "publisher": text(album_attrs.get("recordLabel")),
        "isrc": text(attrs.get("isrc")),
        "upc": text(album_attrs.get("upc")),
        "track": number(attrs.get("trackNumber")),
        "track_total": len(disc_tracks) or number(album_attrs.get("trackCount")),
        "disc": disc,
        "disc_total": disc_total,
        "title_id": number(track.get("id") or payload.get("track_id")),
        "source_id": text(track.get("id") or payload.get("track_id")),
        "album_id": number(album_id),
        "artist_id": number(artists[0].get("id")) if artists else 0,
        "rating": {"explicit": 1, "clean": 2}.get(attrs.get("contentRating"), 0),
        "media_type": 6
        if track.get("type")
        in {"music-videos", "library-music-videos", "uploaded-videos"}
        else 1,
        "artwork": attrs.get("artwork") or album_attrs.get("artwork") or {},
    }
    if playlist and not settings.get("use-songinfo-for-playlist", True):
        parent = attributes(playlist)
        result.update(
            album=text(parent.get("name")),
            album_artist=text(parent.get("artistName") or parent.get("curatorName")),
            album_id=0,
        )
    if (
        playlist
        and not settings.get("use-song-metadata-for-playlist-numbering", False)
        and not settings.get("use-songinfo-for-playlist", True)
    ):
        result.update(
            track=number(payload.get("position")),
            track_total=number(payload.get("total")),
            disc=1,
            disc_total=1,
        )
    return result
