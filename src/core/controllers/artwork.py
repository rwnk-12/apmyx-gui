import logging
import re

from ..workers import Worker
from ..config import load_config


class ArtworkMixin:
    def download_artwork(self, item_data: dict):
        self.update_status_and_log(
            f"Downloading artwork for {item_data.get('name', 'item')}...", "info"
        )
        worker = Worker(self.download_artwork_worker, item_data)
        self.thread_pool.start(worker)

    def download_artwork_worker(self, item_data: dict):
        try:
            item_id = item_data.get("id")
            item_name = item_data.get("name", "Unknown")
            artwork_url = item_data.get("artworkUrl", "")

            if not artwork_url:
                raise ValueError("No artwork URL available")

            self.artwork_download_started.emit(item_id)

            config_data = load_config()
            cover_size = config_data.get("cover-size", "5000x5000")
            try:
                width, height = map(int, cover_size.split("x"))
            except Exception:
                width, height = 5000, 5000

            if "{w}" in artwork_url and "{h}" in artwork_url:
                artwork_url = artwork_url.replace("{w}", str(width)).replace(
                    "{h}", str(height)
                )
            elif "w=600" in artwork_url or "h=600" in artwork_url:
                artwork_url = artwork_url.replace("w=600", f"w={width}").replace(
                    "h=600", f"h={height}"
                )
            elif "w=" in artwork_url and "h=" in artwork_url:
                artwork_url = re.sub(r"w=\d+", f"w={width}", artwork_url)
                artwork_url = re.sub(r"h=\d+", f"h={height}", artwork_url)
            elif "x" in artwork_url:
                artwork_url = re.sub(
                    r"/(\d{2,4})x(\d{2,4})", f"/{width}x{height}", artwork_url
                )

            response = self.session.get(artwork_url, timeout=30)
            response.raise_for_status()

            artwork_data = response.content

            self.artwork_download_finished.emit(
                item_id, True, artwork_data.decode("latin1")
            )
            self.update_status_and_log(f"Artwork ready for {item_name}", "info")

        except Exception as e:
            error_msg = str(e)
            logging.error(f"Artwork download failed: {error_msg}")
            self.artwork_download_finished.emit(
                item_data.get("id", ""), False, error_msg
            )
            self.update_status_and_log(
                f"Failed to download artwork: {error_msg}", "error"
            )
