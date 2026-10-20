def parse_api_item(item: dict, size: int = 600) -> dict | None:
    if not item or not item.get("attributes"):
        return None
    attrs = item["attributes"]
    artwork_url = attrs.get("artwork", {}).get("url", "")

    if artwork_url and "{w}" in artwork_url:
        artwork_url = artwork_url.replace("{w}", str(size)).replace("{h}", str(size))

    duration_ms = attrs.get("durationInMillis", 0)
    seconds = duration_ms // 1000
    duration_str = f"{seconds // 60}:{seconds % 60:02d}"

    previews = attrs.get("previews", [])
    preview_url = previews[0]["url"] if previews else None

    parsed = {
        "id": item.get("id"),
        "type": item.get("type"),
        "name": attrs.get("name"),
        "artist": attrs.get("artistName"),
        "albumName": attrs.get("albumName"),
        "artworkUrl": artwork_url,
        "appleMusicUrl": attrs.get("url"),
        "previewUrl": preview_url,
        "durationStr": duration_str,
        "contentRating": attrs.get("contentRating"),
        "copyright": attrs.get("copyright"),
        "editorialNotes": attrs.get("editorialNotes", {}).get("standard"),
        "genreNames": attrs.get("genreNames", []),
        "isCompilation": attrs.get("isCompilation", False),
        "recordLabel": attrs.get("recordLabel"),
        "releaseDate": attrs.get("releaseDate"),
        "trackCount": attrs.get("trackCount"),
        "upc": attrs.get("upc"),
        "isrc": attrs.get("isrc"),
        "audioTraits": attrs.get("audioTraits", []),
        "composerName": attrs.get("composerName"),
        "hasLyrics": attrs.get("hasLyrics", False),
        "hasTimeSyncedLyrics": attrs.get("hasTimeSyncedLyrics", False),
        "isAppleDigitalMaster": attrs.get("isAppleDigitalMaster", False),
        "tracks_data": item.get("relationships", {}).get("tracks", {}).get("data", []),
        "attributes": attrs,
        "curatorName": attrs.get("curatorName"),
    }

    for k in ["codec", "bitrate", "avgBitrate", "sampleRateHz", "bitDepth", "channels"]:
        if attrs.get(k) is not None:
            parsed[k] = attrs[k]

    return parsed
