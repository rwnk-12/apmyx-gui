import logging
import os
import sys
import threading

import requests
from requests.adapters import HTTPAdapter
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QThreadPool

from .resources import resource_path
from .token import DeveloperTokenProvider
from .config import sync_storefront
from .controllers.catalog import CatalogMixin
from .controllers.search import SearchMixin
from .controllers.media import MediaMixin
from .controllers.details import DetailsMixin
from .controllers.lyrics import LyricsMixin
from .controllers.artwork import ArtworkMixin
from .controllers.library import LibraryMixin
from .controllers.updates import UpdatesMixin

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO, format="[PYTHON] %(asctime)s - %(levelname)s - %(message)s"
    )


class AppController(
    QObject,
    CatalogMixin,
    SearchMixin,
    MediaMixin,
    DetailsMixin,
    LyricsMixin,
    ArtworkMixin,
    LibraryMixin,
    UpdatesMixin,
):

    media_details_loaded = pyqtSignal(int, dict, str)
    search_results_loaded = pyqtSignal(dict)
    search_failed = pyqtSignal(str)
    search_results_appended = pyqtSignal(str, list)
    artist_discography_loaded = pyqtSignal(list)
    status_updated = pyqtSignal(str)
    media_fetch_failed = pyqtSignal(int, str, str)
    tracklist_loaded_for_selection = pyqtSignal(dict)
    category_search_results_loaded = pyqtSignal(str, list)
    album_details_for_info_loaded = pyqtSignal(dict)
    song_details_for_info_loaded = pyqtSignal(dict)
    media_fetch_progress = pyqtSignal(int, int, int)
    token_fetch_failed = pyqtSignal(str)
    track_qualities_loaded = pyqtSignal(list)
    force_clear_all_jobs = pyqtSignal()
    video_details_for_preview_loaded = pyqtSignal(dict)
    artwork_search_results_loaded = pyqtSignal(list)
    artwork_search_results_appended = pyqtSignal(list)
    local_scan_results = pyqtSignal(dict)
    lyrics_download_finished = pyqtSignal(str, bool, str)
    lyrics_content_ready_for_save = pyqtSignal(str, bool, str)
    lyrics_download_started = pyqtSignal(str)
    artwork_download_started = pyqtSignal(str)
    artwork_download_finished = pyqtSignal(str, bool, str)
    update_available = pyqtSignal(dict)

    CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/536"

    def __init__(self, storefront="us"):
        super().__init__()
        self.thread_pool = QThreadPool()

        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.headers.update({"User-Agent": self.CHROME_USER_AGENT})
        self.storefront = storefront.lower()

        self.token_provider = DeveloperTokenProvider(self.session)

        self.active_workers = []
        self._shutdown = False
        self.active_processes = []
        self.fetching_processes = {}
        self.process_lock = threading.Lock()

        self.VERSION = "0.0.0"
        self.REPO_OWNER = ""
        self.REPO_NAME = ""
        self.RELEASES_URL = ""

        self.update_status_and_log("Ready.")

    def apply_runtime_settings(self, config: dict):
        try:
            config = sync_storefront(config)
            new_sf = (config.get("storefront") or "").lower()
            if "storefront" in config and new_sf != self.storefront:
                self.storefront = new_sf
                self.update_status_and_log(
                    f"Storefront switched to '{new_sf}'. New searches will use this region."
                )
            if "use-song-metadata-for-playlist-numbering" in config:
                self.update_status_and_log(
                    f"Playlist metadata override set to: {config['use-song-metadata-for-playlist-numbering']}. This will affect new playlist downloads."
                )
        except Exception as e:
            self.update_status_and_log(
                f"Failed to apply runtime settings: {e}", "error"
            )

    def stop_all_tasks(self):
        logging.info("Signalling all controller tasks to stop for shutdown...")
        self._shutdown = True
        self.cancel_all_fetches()
        self.session.close()
        self.thread_pool.clear()

    @pyqtSlot(str, str)
    def update_status_and_log(self, message: str, level: str = "info"):
        if level == "info":
            logging.info(message)
        elif level == "error":
            logging.error(message)
        self.status_updated.emit(message)
