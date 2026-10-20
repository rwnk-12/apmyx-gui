from concurrent.futures import ThreadPoolExecutor
import logging
import re
import time
from urllib.parse import parse_qs, urlsplit

import requests

from ..token import TokenFetchError
from ..parsers.catalog import parse_api_item


class CatalogMixin:
    _parse_api_item = staticmethod(parse_api_item)

    def _apple_music_get(self, url: str, **kwargs):
        try:
            return self.token_provider.get_response(url, self.storefront, **kwargs)
        except TokenFetchError as exc:
            self.update_status_and_log(str(exc), "error")
            self.token_fetch_failed.emit(str(exc))
            raise ValueError(str(exc)) from exc

    def _catalog_json(self, path: str, params: dict) -> dict:
        url = f"https://amp-api.music.apple.com/v1/catalog/{self.storefront}/{path}"
        for attempt in range(3):
            if self._shutdown:
                raise ValueError("Controller is shutting down")
            try:
                response = self._apple_music_get(url, params=params, timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                if self._shutdown:
                    raise ValueError("Controller is shutting down") from exc
                status = exc.response.status_code if exc.response is not None else None
                if status in (401, 403) or attempt == 2:
                    raise
                logging.warning(
                    "Catalog request failed (attempt %d/3): %s", attempt + 1, exc
                )
                time.sleep(1 + attempt)

    def _search_api(self, query: str, types: str, limit: int, offset: int = 0) -> dict:
        api_types = types.replace("_", "-")
        params = {"term": query, "types": api_types, "limit": limit, "offset": offset}
        if api_types not in ("music-videos", "artists"):
            params["include"] = "relationships.tracks"
        return self._catalog_json("search", params)

    def _lookup_api_item(self, item_type_plural: str, item_id: str) -> dict:
        return self._catalog_json(
            f"{item_type_plural}/{item_id}",
            {"extend": "extendedAssetUrls,relationships.tracks"},
        )

    def _catalog_pages(self, path: str) -> list:
        items, offset = [], 0
        while True:
            page = self._catalog_json(path, {"limit": 100, "offset": offset})
            items.extend(page.get("data", []))
            next_url = page.get("next")
            if not next_url:
                return items
            offset = int(parse_qs(urlsplit(next_url).query).get("offset", [offset + 100])[0])

    def _artist_releases(self, url: str) -> list:
        match = re.search(r"/artist/(?:[^/]+/)?(\d+)", urlsplit(url or "").path)
        if not match:
            raise ValueError("Not an Apple Music artist URL.")
        artist_id = match[1]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pages = list(pool.map(
                lambda kind: self._catalog_pages(f"artists/{artist_id}/{kind}"),
                ("albums", "music-videos"),
            ))
        return [item for page in pages for item in page]
