import asyncio
import logging
import re
import traceback

import aiohttp

from ..workers import Worker
from ..parsers.manifest import parse_qualities_from_manifest, merge_quality


class DetailsMixin:
    _parse_qualities_from_manifest = staticmethod(parse_qualities_from_manifest)

    def fetch_album_for_info(self, url: str):
        self.update_status_and_log("Fetching... full album details for info...")
        worker = Worker(self._fetch_album_for_info_worker_async, url)
        self.thread_pool.start(worker)

    def fetch_song_for_info(self, song_data: dict):
        self.update_status_and_log("Fetching... quality details for song...")
        worker = Worker(self._fetch_song_for_info_worker_async, song_data)
        self.thread_pool.start(worker)

    def fetch_video_for_preview(self, video_data: dict):
        self.update_status_and_log("Fetching... video details for preview...")
        worker = Worker(self._fetch_video_for_preview_worker, video_data)
        self.thread_pool.start(worker)

    def fetch_qualities_for_dialog(self, tracks: list):
        self.update_status_and_log(
            f"Fetching... quality details for {len(tracks)} tracks..."
        )
        worker = Worker(self._fetch_qualities_for_dialog_async, tracks)
        self.thread_pool.start(worker)

    async def _fetch_manifest_async(self, session, index, track):
        try:
            manifest_url = (
                track.get("attributes", {})
                .get("extendedAssetUrls", {})
                .get("enhancedHls")
            )
            if not manifest_url:
                return index, {}

            async with session.get(manifest_url, timeout=20) as response:
                response.raise_for_status()
                manifest_data = await response.text()
                quality_info = self._parse_qualities_from_manifest(manifest_data)
                return index, quality_info
        except Exception as e:
            logging.warning(f"Failed to fetch manifest for track {index} (async): {e}")
            return index, {}

    async def _fetch_all_manifests_async(self, tracks):
        async with aiohttp.ClientSession(
            headers={"User-Agent": self.CHROME_USER_AGENT}
        ) as session:
            tasks = [
                self._fetch_manifest_async(session, i, track)
                for i, track in enumerate(tracks)
            ]
            results = await asyncio.gather(*tasks)
            return results

    async def _fetch_qualities_for_dialog_async(self, tracks: list):
        try:
            manifest_results = await self._fetch_all_manifests_async(tracks)

            updated_tracks = []
            for index, quality_info in manifest_results:
                track_copy = tracks[index].copy()
                if quality_info:
                    track_copy = merge_quality(track_copy, quality_info)
                updated_tracks.append(track_copy)

            self.track_qualities_loaded.emit(updated_tracks)
            self.update_status_and_log("Quality details loaded.")
        except Exception as e:
            logging.error(
                f"Error fetching qualities for dialog:\n{traceback.format_exc()}"
            )
            self.update_status_and_log(f"Failed to fetch quality details: {e}", "error")
            self.track_qualities_loaded.emit(tracks)

    async def _fetch_album_for_info_worker_async(self, url: str):
        try:
            match = re.search(
                r"music\.apple\.com/[^/]+/([^/]+)/[^/]+/(\d+|pl\.[^?]+)", url
            )
            if not match:
                raise ValueError("Could not parse item type and ID from URL.")

            item_type, item_id = match.group(1), match.group(2)
            item_type_plural = (
                f"{item_type}s" if not item_type.endswith("s") else item_type
            )

            api_result = self._lookup_api_item(item_type_plural, item_id)
            item_data = api_result.get("data", [{}])[0]

            if not item_data:
                raise ValueError("API response did not contain item data.")

            tracks = (
                item_data.get("relationships", {}).get("tracks", {}).get("data", [])
            )

            if not tracks:
                parsed_data = self._parse_api_item(item_data)
                self.album_details_for_info_loaded.emit(parsed_data)
                return

            self.update_status_and_log(
                f"Fetching... quality details for {len(tracks)} tracks..."
            )

            manifest_results = await self._fetch_all_manifests_async(tracks)

            for index, quality_info in manifest_results:
                if quality_info:
                    tracks[index] = merge_quality(tracks[index], quality_info)

            parsed_data = self._parse_api_item(item_data)
            if not parsed_data:
                raise ValueError("Failed to parse final API item data.")

            self.album_details_for_info_loaded.emit(parsed_data)
            self.update_status_and_log("Full details loaded for info dialog.")

        except Exception as e:
            logging.error(
                f"Unexpected error fetching details for info dialog:\n{traceback.format_exc()}"
            )
            self.update_status_and_log(f"Failed to fetch details: {e}", "error")
            self.media_fetch_failed.emit(-1, url, f"Could not fetch details: {e}")

    async def _fetch_song_for_info_worker_async(self, song_data: dict):
        try:
            song_id = song_data.get("id")
            if not song_id:
                raise ValueError("Song data is missing an ID.")

            api_result = self._lookup_api_item("songs", song_id)
            item_data = api_result.get("data", [{}])[0]

            if not item_data:
                raise ValueError("API response did not contain song data.")

            manifest_url = (
                item_data.get("attributes", {})
                .get("extendedAssetUrls", {})
                .get("enhancedHls")
            )
            if not manifest_url:
                self.song_details_for_info_loaded.emit(self._parse_api_item(item_data))
                return

            async with aiohttp.ClientSession(
                headers={"User-Agent": self.CHROME_USER_AGENT}
            ) as session:
                async with session.get(manifest_url, timeout=20) as response:
                    response.raise_for_status()
                    manifest_data = await response.text()
                    quality_info = self._parse_qualities_from_manifest(manifest_data)

            item_data = merge_quality(item_data, quality_info)

            parsed_data = self._parse_api_item(item_data)
            if not parsed_data:
                raise ValueError("Failed to parse final API item data for song.")

            self.song_details_for_info_loaded.emit(parsed_data)
            self.update_status_and_log("Song quality details loaded.")

        except Exception as e:
            logging.error(
                f"Error fetching song details for info dialog:\n{traceback.format_exc()}"
            )
            self.update_status_and_log(f"Failed to fetch song details: {e}", "error")
            self.song_details_for_info_loaded.emit(song_data)

    def _fetch_video_for_preview_worker(self, video_data: dict):
        try:
            video_id = video_data.get("id")
            if not video_id:
                raise ValueError("Video data is missing an ID.")

            api_result = self._lookup_api_item("music-videos", video_id)
            item_data = api_result.get("data", [{}])[0]

            if not item_data:
                raise ValueError("API response did not contain video data.")

            parsed_data = self._parse_api_item(item_data)
            if not parsed_data:
                raise ValueError("Failed to parse final API item data for video.")

            self.video_details_for_preview_loaded.emit(parsed_data)
        except Exception as e:
            logging.error(
                f"Error fetching video details for preview:\n{traceback.format_exc()}"
            )
            self.update_status_and_log(f"Failed to fetch video details: {e}", "error")
            self.video_details_for_preview_loaded.emit(video_data)
