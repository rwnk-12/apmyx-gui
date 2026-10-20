import base64
import logging
import os

import hashlib

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PyQt6.QtGui import QImageReader
from mutagen import File
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

try:
    from mutagen.opus import Opus
except ImportError:
    Opus = None

from ..workers import Worker

THUMBNAIL_SIZE = 68


def artwork_thumbnail(data, cache=None):
    if not data:
        return None
    data = bytes(data)
    key = hashlib.blake2b(data, digest_size=16).digest()
    if cache is not None and key in cache:
        return cache[key]
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    size = reader.size()
    if size.isValid():
        size.scale(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE), Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    image = reader.read()
    image = None if image.isNull() else image
    if cache is not None:
        cache[key] = image
    return image


class LibraryMixin:
    def scan_local_directory(self, path: str):
        self.update_status_and_log(f"Scanning folder: '{path}'...")
        worker = Worker(self._scan_local_directory_worker, path)
        self.thread_pool.start(worker)

    def _scan_local_directory_worker(self, path: str):
        try:
            self.update_status_and_log(f"Finding audio files in {path}...")
            audio_files = []
            supported_exts = (".m4a", ".mp3", ".flac", ".opus", ".ogg")
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(supported_exts):
                        audio_files.append(os.path.join(root, file))

            audio_files.sort()
            total_files = len(audio_files)
            self.local_scan_results.emit(
                {"type": "scan_started", "data": {"total_files": total_files}}
            )

            chunk, chunk_size, processed_count = [], 100, 0
            thumbnails = {}
            for filepath in audio_files:
                try:
                    audio = File(filepath, easy=True)
                    if not audio:
                        continue

                    title = audio.get(
                        "title", [os.path.splitext(os.path.basename(filepath))[0]]
                    )[0]
                    artist = audio.get("artist", ["Unknown Artist"])[0]
                    album = audio.get("album", ["Unknown Album"])[0]

                    artwork_data = None
                    raw_audio = File(filepath)
                    if isinstance(raw_audio, MP3) and "APIC:" in raw_audio:
                        artwork_data = raw_audio["APIC:"].data
                    elif isinstance(raw_audio, FLAC) and raw_audio.pictures:
                        artwork_data = raw_audio.pictures[0].data
                    elif (
                        isinstance(raw_audio, MP4)
                        and "covr" in raw_audio
                        and raw_audio["covr"]
                    ):
                        artwork_data = raw_audio["covr"][0]
                    elif (
                        isinstance(raw_audio, OggVorbis)
                        or (Opus and isinstance(raw_audio, Opus))
                    ) and "metadata_block_picture" in raw_audio:
                        try:
                            artwork_data = base64.b64decode(
                                raw_audio["metadata_block_picture"][0]
                            )
                        except Exception:
                            artwork_data = None

                    base, _ = os.path.splitext(filepath)
                    has_lyrics = any(os.path.exists(base + ext) for ext in (".lrc", ".ttml", ".txt"))

                    chunk.append(
                        {
                            "filepath": filepath,
                            "title": title,
                            "artist": artist,
                            "album": album,
                            "artwork": artwork_thumbnail(artwork_data, thumbnails),
                            "has_lyrics": has_lyrics,
                        }
                    )
                    processed_count += 1

                    if len(chunk) >= chunk_size:
                        self.local_scan_results.emit({"type": "chunk", "data": chunk})
                        chunk = []

                except Exception as e:
                    logging.warning(f"Could not process file {filepath}: {e}")

            if chunk:
                self.local_scan_results.emit({"type": "chunk", "data": chunk})
            self.local_scan_results.emit(
                {"type": "complete", "data": {"total_found": processed_count}}
            )
        except Exception as e:
            self.update_status_and_log(f"Local scan failed: {e}", "error")
            self.local_scan_results.emit({"type": "error", "data": str(e)})
