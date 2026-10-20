import logging
import traceback

import requests
from PyQt6.QtCore import pyqtSlot

from ..workers import SearchWorker, SearchWorkerSignals


class SearchMixin:
    def _start_search(self, fn, result_signal, destination, *args):
        worker = SearchWorker(fn, *args)
        getattr(worker.signals, result_signal).connect(destination)
        worker.signals.status_updated.connect(self.update_status_and_log)
        self.active_workers.append(worker)

        def cleanup():
            if worker in self.active_workers:
                self.active_workers.remove(worker)

        worker.signals.finished.connect(cleanup)
        self.thread_pool.start(worker)

    def search(self, query: str):
        self.update_status_and_log(f"Searching for: '{query}'...")
        self._start_search(
            self._initial_search_worker,
            "search_results_loaded",
            self.search_results_loaded,
            query,
        )

    def search_for_albums(self, query: str):
        self.update_status_and_log(f"Searching for albums: '{query}'...")
        self._start_search(
            self._search_for_albums_worker,
            "category_search_results_loaded",
            self.category_search_results_loaded,
            query,
        )

    def search_for_music_videos(self, query: str):
        self.update_status_and_log(f"Searching for music videos: '{query}'...")
        self._start_search(
            self._search_for_music_videos_worker,
            "category_search_results_loaded",
            self.category_search_results_loaded,
            query,
        )

    def search_for_playlists(self, query: str):
        self.update_status_and_log(f"Searching for playlists: '{query}'...")
        self._start_search(
            self._search_for_playlists_worker,
            "category_search_results_loaded",
            self.category_search_results_loaded,
            query,
        )

    def _search_for_playlists_worker(
        self, worker: SearchWorker, signals: SearchWorkerSignals, query: str
    ):
        try:
            if worker.is_cancelled():
                return

            api_results = self._search_api(query, "playlists", 30)

            if worker.is_cancelled():
                return

            playlists_data = (
                api_results.get("results", {}).get("playlists", {}).get("data", [])
            )
            all_playlists = [
                p for item in playlists_data if (p := self._parse_api_item(item))
            ]

            worker.safe_emit(
                signals.category_search_results_loaded, "playlists", all_playlists
            )
            worker.safe_emit(
                signals.status_updated, "Playlist search complete.", "info"
            )

        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated,
                f"API playlist search request failed: {e}",
                "error",
            )
            worker.safe_emit(signals.category_search_results_loaded, "playlists", [])

    def search_for_artwork(self, query: str):
        self.update_status_and_log(f"Searching for artwork: '{query}'...")
        self._start_search(
            self._search_for_artwork_worker,
            "category_search_results_loaded",
            self._on_artwork_search_results,
            query,
        )

    @pyqtSlot(str, list)
    def _on_artwork_search_results(self, category, results):
        if category == "albums":
            self.artwork_search_results_loaded.emit(results)

    def load_more_artwork(self, query: str, offset: int):
        self.update_status_and_log(f"Loading more artwork for '{query}'...")
        self._start_search(
            self._load_more_artwork_worker,
            "artwork_results_appended",
            self.artwork_search_results_appended,
            query,
            offset,
        )

    def load_more_results(self, query: str, category: str, offset: int):
        self.update_status_and_log(f"Loading more {category} for '{query}'...")
        self._start_search(
            self._load_more_worker,
            "search_results_appended",
            self.search_results_appended,
            query,
            category,
            offset,
        )

    def _initial_search_worker(
        self, worker: SearchWorker, signals: SearchWorkerSignals, query: str
    ):
        try:
            if worker.is_cancelled():
                return

            api_results = self._search_api(
                query, "songs,albums,artists,music-videos,playlists", 30
            )

            if worker.is_cancelled():
                return

            songs_data = api_results.get("results", {}).get("songs", {}).get("data", [])
            all_songs = [p for item in songs_data if (p := self._parse_api_item(item))]

            albums_data = (
                api_results.get("results", {}).get("albums", {}).get("data", [])
            )
            all_albums = [
                p for item in albums_data if (p := self._parse_api_item(item))
            ]

            artists_data = (
                api_results.get("results", {}).get("artists", {}).get("data", [])
            )
            all_artists = [
                p for item in artists_data if (p := self._parse_api_item(item))
            ]

            videos_data = (
                api_results.get("results", {}).get("music-videos", {}).get("data", [])
            )
            all_videos = [
                p for item in videos_data if (p := self._parse_api_item(item))
            ]

            playlists_data = (
                api_results.get("results", {}).get("playlists", {}).get("data", [])
            )
            all_playlists = [
                p for item in playlists_data if (p := self._parse_api_item(item))
            ]

            if worker.is_cancelled():
                return

            top_results_map = {
                **{
                    item["id"]: item
                    for item in [
                        all_songs[0] if all_songs else None,
                        all_albums[0] if all_albums else None,
                        all_artists[0] if all_artists else None,
                        all_videos[0] if all_videos else None,
                        all_playlists[0] if all_playlists else None,
                    ]
                    if item is not None and item.get("id")
                }
            }
            top_results = list(top_results_map.values())

            final_results = {
                "top_results": top_results,
                "songs": all_songs,
                "albums": all_albums,
                "artists": all_artists,
                "music_videos": all_videos,
                "playlists": all_playlists,
            }

            worker.safe_emit(signals.search_results_loaded, final_results)
            worker.safe_emit(signals.status_updated, "Search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated, f"API search request failed: {e}", "error"
            )
            worker.safe_emit(signals.search_results_loaded, {})
        except Exception:
            logging.error(
                f"Unexpected error processing search results:\n{traceback.format_exc()}"
            )
            worker.safe_emit(
                signals.status_updated,
                "Failed to process search results. See console for details.",
                "error",
            )
            worker.safe_emit(signals.search_results_loaded, {})

    def _search_for_albums_worker(
        self, worker: SearchWorker, signals: SearchWorkerSignals, query: str
    ):
        try:
            if worker.is_cancelled():
                return
            api_results = self._search_api(query, "albums", 30)
            if worker.is_cancelled():
                return
            albums_data = (
                api_results.get("results", {}).get("albums", {}).get("data", [])
            )
            all_albums = [
                p for item in albums_data if (p := self._parse_api_item(item))
            ]
            worker.safe_emit(
                signals.category_search_results_loaded, "albums", all_albums
            )
            worker.safe_emit(signals.status_updated, "Album search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated, f"API album search request failed: {e}", "error"
            )
            worker.safe_emit(signals.category_search_results_loaded, "albums", [])

    def _search_for_music_videos_worker(
        self, worker: SearchWorker, signals: SearchWorkerSignals, query: str
    ):
        try:
            if worker.is_cancelled():
                return
            api_results = self._search_api(query, "music-videos", 30)
            if worker.is_cancelled():
                return
            videos_data = (
                api_results.get("results", {}).get("music-videos", {}).get("data", [])
            )
            all_videos = [
                p for item in videos_data if (p := self._parse_api_item(item))
            ]
            worker.safe_emit(
                signals.category_search_results_loaded, "music_videos", all_videos
            )
            worker.safe_emit(
                signals.status_updated, "Music video search complete.", "info"
            )
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated,
                f"API music video search request failed: {e}",
                "error",
            )
            worker.safe_emit(signals.category_search_results_loaded, "music_videos", [])

    def _search_for_artwork_worker(
        self, worker: SearchWorker, signals: SearchWorkerSignals, query: str
    ):
        try:
            if worker.is_cancelled():
                return
            api_results = self._search_api(query, "albums", 50)
            if worker.is_cancelled():
                return
            albums_data = (
                api_results.get("results", {}).get("albums", {}).get("data", [])
            )
            all_albums = [
                p
                for item in albums_data
                if (p := self._parse_api_item(item, size=5000))
            ]
            worker.safe_emit(
                signals.category_search_results_loaded, "albums", all_albums
            )
            worker.safe_emit(signals.status_updated, "Artwork search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated,
                f"API artwork search request failed: {e}",
                "error",
            )
            worker.safe_emit(signals.category_search_results_loaded, "albums", [])

    def _load_more_artwork_worker(
        self,
        worker: SearchWorker,
        signals: SearchWorkerSignals,
        query: str,
        offset: int,
    ):
        try:
            if worker.is_cancelled():
                return
            api_results = self._search_api(query, "albums", 50, offset)
            if worker.is_cancelled():
                return

            new_items_data = (
                api_results.get("results", {}).get("albums", {}).get("data", [])
            )
            new_items = [
                p
                for item in new_items_data
                if (p := self._parse_api_item(item, size=5000))
            ]

            worker.safe_emit(signals.artwork_results_appended, new_items)
            worker.safe_emit(
                signals.status_updated,
                f"Loaded {len(new_items)} more artworks.",
                "info",
            )
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated,
                f"API 'load more' artwork request failed: {e}",
                "error",
            )
            worker.safe_emit(signals.artwork_results_appended, [])

    def _load_more_worker(
        self,
        worker: SearchWorker,
        signals: SearchWorkerSignals,
        query: str,
        category: str,
        offset: int,
    ):
        try:
            if worker.is_cancelled():
                return
            api_results = self._search_api(query, category, 30, offset)
            if worker.is_cancelled():
                return

            api_category_key = category.replace("_", "-")
            new_items_data = (
                api_results.get("results", {}).get(api_category_key, {}).get("data", [])
            )
            new_items = [
                p for item in new_items_data if (p := self._parse_api_item(item))
            ]

            worker.safe_emit(signals.search_results_appended, category, new_items)
            worker.safe_emit(
                signals.status_updated,
                f"Loaded {len(new_items)} more {category}.",
                "info",
            )
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(
                signals.status_updated, f"API 'load more' request failed: {e}", "error"
            )
            worker.safe_emit(signals.search_results_appended, category, [])
