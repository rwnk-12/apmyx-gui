from urllib.parse import parse_qs, parse_qsl, urljoin, urlsplit, urlunsplit

from ..common import BackendError


BASE = "https://amp-api.music.apple.com"


class Catalog:
    def __init__(self, api, storefront, language):
        self.api = api
        self.prefix = f"/v1/catalog/{storefront}/"
        self.language = language
        self.cache = {}

    async def page(self, uri, params=None):
        url = urljoin(BASE, uri)
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.netloc != "amp-api.music.apple.com"
            or not parts.path.startswith(self.prefix)
        ):
            raise BackendError(
                "invalid_response",
                "Wrapper Lite received an invalid catalog page URL.",
            )
        query = {
            **dict(parse_qsl(parts.query, keep_blank_values=True)),
            "l": self.language,
            **(params or {}),
        }
        response = await self.api._request(
            "GET", urlunsplit(parts._replace(query="")), params=query
        )
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise BackendError(
                "invalid_response", "Apple Music returned malformed catalog metadata."
            )
        return data

    async def items(self, uri):
        values, seen = [], set()
        while uri:
            if uri in seen:
                raise BackendError(
                    "invalid_response", "Apple Music repeated a catalog pagination URL."
                )
            seen.add(uri)
            page = await self.page(uri)
            values.extend(page["data"])
            uri = page.get("next")
        return values

    async def resource(self, kind, identifier):
        key = kind, identifier
        if key not in self.cache:
            include = {
                "songs": "albums,artists,genres,composers",
                "albums": "tracks,artists,record-labels",
                "playlists": "tracks,curator",
                "music-videos": "albums,artists,genres",
                "artists": "albums,music-videos",
            }[kind]
            page = await self.page(
                self.prefix + kind + "/" + identifier,
                {"include": include, "extend": "extendedAssetUrls"},
            )
            if not page["data"]:
                raise BackendError(
                    "no_tracks", "Apple Music returned no matching media."
                )
            value = page["data"][0]
            relation = value.get("relationships", {}).get("tracks", {})
            if relation.get("next"):
                relation["data"] = relation.get("data", []) + await self.items(
                    relation["next"]
                )
                relation.pop("next", None)
            if len(self.cache) >= 16:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = value
        return self.cache[key]

    async def collection(self, url):
        parts = urlsplit(url)
        path = parts.path.strip("/").split("/")
        identifier = parse_qs(parts.query).get("i", [path[-1]])[0]
        kind = (
            "song"
            if parse_qs(parts.query).get("i")
            else path[1]
            if len(path) > 2
            else ""
        )
        resource_type = {
            "song": "songs",
            "album": "albums",
            "playlist": "playlists",
            "music-video": "music-videos",
            "artist": "artists",
        }.get(kind)
        if not resource_type:
            raise BackendError(
                "unsupported_request",
                "Wrapper Lite requires a song, album, playlist, artist or music-video URL.",
            )
        parent = await self.resource(resource_type, identifier)
        if resource_type in {"albums", "playlists"}:
            tracks = parent.get("relationships", {}).get("tracks", {}).get("data", [])
        else:
            tracks = [parent]
        return parent, tracks
