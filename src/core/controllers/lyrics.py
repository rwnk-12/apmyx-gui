import logging
import os

from PyQt6.QtCore import pyqtSlot

from ..workers import Worker
from ..config import load_config
from ..parsers.lyrics import convert_time_to_lrc, time_to_seconds, get_lyrics_from_ttml


class LyricsMixin:
    _convert_time_to_lrc = staticmethod(convert_time_to_lrc)
    _time_to_seconds = staticmethod(time_to_seconds)
    _get_lyrics_from_ttml = staticmethod(get_lyrics_from_ttml)

    @pyqtSlot(dict, str)
    def download_lyrics_for_track(self, track_data: dict, local_filepath: str):
        worker = Worker(
            self._download_lyrics_for_track_worker, track_data, local_filepath
        )
        self.thread_pool.start(worker)

    def download_lyrics(self, item_data: dict):
        self.update_status_and_log(
            f"Downloading lyrics for {item_data.get('name', 'item')}...", "info"
        )
        worker = Worker(self.download_lyrics_worker, item_data)
        self.thread_pool.start(worker)

    def download_lyrics_worker(self, item_data: dict):
        try:
            item_id = item_data.get("id")
            item_name = item_data.get("name", "Unknown")

            if not item_id:
                raise ValueError("Item has no ID")

            self.lyrics_download_started.emit(item_id)

            ttml_content = self._fetch_lyrics_for_song(item_id)
            if not ttml_content:
                raise Exception("No synced lyrics available")

            config = load_config()

            lrc_format = config.get("lrc-format", "lrc")
            synced_lyrics = self._get_lyrics_from_ttml(ttml_content, lrc_format)

            if not synced_lyrics:
                raise Exception("Failed to parse TTML")

            self.lyrics_content_ready_for_save.emit(item_id, True, synced_lyrics)
            self.update_status_and_log(f"Lyrics ready for {item_name}", "info")

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Lyrics download failed: {error_msg}")
            self.lyrics_content_ready_for_save.emit(
                item_data.get("id", ""), False, error_msg
            )
            self.update_status_and_log(
                f"Failed to download lyrics: {error_msg}", "error"
            )

    def _wrapper_lyrics(self, config: dict, song_id: str, syllable: bool) -> str | None:
        import requests
        from backend.router.applemusicdecrypt.config import wrapper_headers
        from backend.router.common import migrate_wrapper

        config = migrate_wrapper(config)
        wrapper = config.get("wrapper", "applemusicdecrypt")
        if wrapper == "applemusicdecrypt":
            url, headers = config.get("applemusicdecrypt-url"), wrapper_headers(config)
        else:
            return None
        if not url:
            return None
        response = requests.get(
            str(url).rstrip("/") + "/lyrics",
            params={
                "adamId": song_id,
                "language": config.get("language") or "en-US",
                "region": self.storefront or "us",
                "syllable": "1" if syllable else "0",
            },
            headers=headers,
            timeout=(5, 30),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise ValueError(data.get("msg") or "The wrapper returned no lyrics.")
        return (data.get("data") or {}).get("lyrics") or None

    def _fetch_ttml(self, song_id: str, syllable: bool = False) -> str | None:
        config = load_config()
        try:
            ttml = self._wrapper_lyrics(config, song_id, syllable)
            if ttml:
                return ttml
        except Exception as e:
            logging.warning(f"Wrapper lyrics failed for song {song_id}: {e}")
        return self._fetch_lyrics_for_song(song_id, syllable)

    def _fetch_lyrics_for_song(self, song_id: str, syllable: bool = False) -> str | None:
        try:
            config = load_config()

            media_user_token = (
                config.get("media-user-token")
                or config.get("MEDIA-USER-TOKEN")
                or config.get("Media-User-Token")
            )
            if not media_user_token:
                logging.error("media-user-token not found in config.yaml")
                return None

            endpoint = "syllable-lyrics" if syllable else "lyrics"
            url = f"https://amp-api.music.apple.com/v1/catalog/{self.storefront}/songs/{song_id}/{endpoint}?l=en&extend=ttmlLocalizations"
            headers = {
                "User-Agent": self.CHROME_USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            }
            cookies = {"media-user-token": media_user_token}

            logging.info(f"Requesting lyrics for song {song_id}")
            response = self._apple_music_get(
                url, headers=headers, cookies=cookies, timeout=30
            )

            if response.status_code == 404:
                raise ValueError("No lyrics available for this song")
            response.raise_for_status()

            data = response.json()
            if (
                "data" in data
                and len(data["data"]) > 0
                and "attributes" in data["data"][0]
            ):
                attributes = data["data"][0]["attributes"]
                ttml = attributes.get("ttml")
                if ttml:
                    return ttml

                ttml_local = attributes.get("ttmlLocalizations")
                if isinstance(ttml_local, dict):
                    if "en" in ttml_local and ttml_local["en"].get("ttml"):
                        return ttml_local["en"]["ttml"]
                    for lang_data in ttml_local.values():
                        if lang_data.get("ttml"):
                            return lang_data["ttml"]
                elif isinstance(ttml_local, list):
                    for lang_data in ttml_local:
                        if lang_data.get("ttml"):
                            return lang_data["ttml"]

            logging.warning(f"No TTML content found for song {song_id}")
            return None

        except Exception as e:
            logging.error(f"Failed to fetch TTML for song {song_id}: {e}")
            if "No lyrics available" in str(e):
                raise e
            return None

    def _download_lyrics_for_track_worker(self, track_data: dict, local_filepath: str):
        try:
            if not os.path.isfile(local_filepath):
                raise ValueError(f"Invalid path: '{local_filepath}' is not a file.")

            search_term = f"{track_data.get('artist', '')} {track_data.get('title', '')} {track_data.get('album', '')}"
            if not search_term.strip():
                raise ValueError("Not enough metadata to search for lyrics.")

            from backend.shared.lyrics import render_lyrics

            options = track_data.get("options") or {}
            output = options.get("format", "lrc")
            syllable = options.get("timing") == "syllable"
            extension = {"lrc": "lrc", "ttml": "ttml", "text": "txt"}.get(output, "lrc")
            lyrics_path = os.path.splitext(local_filepath)[0] + "." + extension
            if os.path.exists(lyrics_path):
                self.lyrics_download_finished.emit(local_filepath, True, "Exists")
                return

            api_results = self._search_api(search_term, "songs", 5)
            songs_data = api_results.get("results", {}).get("songs", {}).get("data", [])
            if not songs_data:
                raise ValueError("No match found on Apple Music.")

            wanted = "hasLyrics" if output == "text" else "hasTimeSyncedLyrics"
            best_match = next(
                (s for s in songs_data if s.get("attributes", {}).get(wanted)),
                None,
            )
            if not best_match:
                raise ValueError("No lyrics available for this song")

            track_id_for_download = best_match.get("id")
            if not track_id_for_download:
                raise ValueError("Could not get ID from Apple Music result.")

            ttml_content = self._fetch_ttml(track_id_for_download, syllable)
            if not ttml_content:
                raise Exception("No synced lyrics available")

            content = render_lyrics(
                ttml_content,
                "ttml" if output == "ttml" else "lrc",
                "unsynced" if output == "text" else "synced",
                tuple(options.get("extras") or ()) if output == "lrc" else (),
            )
            if not content.strip():
                raise Exception("No synced lyrics available")

            with open(lyrics_path, "w", encoding="utf-8") as f:
                f.write(content)
            self.lyrics_download_finished.emit(local_filepath, True, "Done")

        except Exception as e:
            error_message = str(e)
            logging.error(
                f"Lyrics download for {track_data.get('title')} failed: {error_message}"
            )

            final_status = "Failed"
            if (
                "no lyrics available" in error_message.lower()
                or "no match found" in error_message.lower()
                or "no synced lyrics available" in error_message.lower()
            ):
                final_status = "Not Available"

            self.lyrics_download_finished.emit(local_filepath, False, final_status)
