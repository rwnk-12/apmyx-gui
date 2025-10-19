import json
import logging
import os
import re
import subprocess
import sys
import requests
import threading
import traceback
import base64
import concurrent.futures
import asyncio
import aiohttp
import time
import yaml
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QRunnable, QThreadPool, QEventLoop
from requests.adapters import HTTPAdapter
from mutagen import File, MutagenError
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
try:
    from mutagen.opus import Opus
except ImportError:
    Opus = None

from models.track import Album, Track
from xml.dom import minidom
from xml.etree import ElementTree
import datetime

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format='[PYTHON] %(asctime)s - %(levelname)s - %(message)s')

def _resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base_path, relative_path)

class SearchWorkerSignals(QObject):
    search_results_loaded = pyqtSignal(dict)
    search_results_appended = pyqtSignal(str, list)
    category_search_results_loaded = pyqtSignal(str, list)
    status_updated = pyqtSignal(str, str)
    artwork_results_appended = pyqtSignal(list)

class SearchWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = SearchWorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def safe_emit(self, signal, *args):
        if not self._cancelled:
            try:
                signal.emit(*args)
            except RuntimeError:
                
                pass

    @pyqtSlot()
    def run(self):
        try:
            if self._cancelled:
                return
           
            self.fn(self, self.signals, *self.args, **self.kwargs)
        except Exception as e:
            if not self._cancelled:
                logging.error(f"Error in worker function {self.fn.__name__}:\n{traceback.format_exc()}")
                self.safe_emit(self.signals.status_updated, f"Worker error: {e}", "error")

class ManifestFetcherSignals(QObject):
    finished = pyqtSignal(int, dict)
    error = pyqtSignal(int, str)

class ManifestFetcher(QRunnable):
    def __init__(self, index: int, url: str, session: requests.Session, parser_func):
        super().__init__()
        self.index = index
        self.url = url
        self.session = session
        self.parser_func = parser_func
        self.signals = ManifestFetcherSignals()

    @pyqtSlot()
    def run(self):
        try:
            if not self.url:
                raise ValueError("Manifest URL is missing.")
            response = self.session.get(self.url, timeout=20)
            response.raise_for_status()
            manifest_data = response.text
            quality_info = self.parser_func(manifest_data)
            self.signals.finished.emit(self.index, quality_info)
        except Exception as e:
            logging.warning(f"Failed to fetch manifest for track {self.index}: {e}")
            self.signals.error.emit(self.index, str(e))

class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    @pyqtSlot()
    def run(self):
       
        if asyncio.iscoroutinefunction(self.fn):
            asyncio.run(self.fn(*self.args, **self.kwargs))
        else:
            self.fn(*self.args, **self.kwargs)

class AppController(QObject):
    media_details_loaded = pyqtSignal(int, dict, str)
    search_results_loaded = pyqtSignal(dict)
    search_failed = pyqtSignal(str)
    search_results_appended = pyqtSignal(str, list)
    artist_discography_loaded = pyqtSignal(list)
    status_updated = pyqtSignal(str)
    media_fetch_failed = pyqtSignal(int, str, str)
    tracklist_loaded_for_selection = pyqtSignal(dict)
    tracklist_loaded_for_viewing = pyqtSignal(dict)
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
    lyrics_search_results_loaded = pyqtSignal(list)
    local_scan_results = pyqtSignal(dict)
    lyrics_download_finished = pyqtSignal(str, bool, str)
    lyrics_content_ready_for_save = pyqtSignal(str, bool, str)
    lyrics_download_started = pyqtSignal(str)
    artwork_download_started = pyqtSignal(str)
    artwork_download_finished = pyqtSignal(str, bool, str)
    updatecheckfinished = pyqtSignal(str, str, str)

    CHROME_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/536"

    def __init__(self, storefront='us'):
        super().__init__()
        self.thread_pool = QThreadPool()
        self.downloader_executable = self._find_downloader()
        
        self.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        
        self.session.headers.update({"User-Agent": self.CHROME_USER_AGENT})
        self.storefront = storefront.lower()
        
        self.dev_token = None
        self.token_lock = threading.Lock()
        
        self.active_workers = []
        self._shutdown = False
        self.active_processes = []
        self.fetching_processes = {}
        self.process_lock = threading.Lock()
        
        self.VERSION = "0.0.0"
        self.REPO_OWNER = ""
        self.REPO_NAME = ""
        self.RELEASES_URL = ""
        
        if not self.downloader_executable:
            self.update_status_and_log("FATAL: downloader executable not found!", 'error')
        else:
            self.update_status_and_log("Ready.")

    def apply_runtime_settings(self, config: dict):
        try:
            new_sf = (config.get('storefront') or '').lower()
            if new_sf and new_sf != self.storefront:
                with self.token_lock:
                    self.storefront = new_sf
                    self.dev_token = None
                self.update_status_and_log(
                    f"Storefront switched to '{new_sf}'. New searches will use this region."
                )
        except Exception as e:
            self.update_status_and_log(f"Failed to apply runtime settings: {e}", 'error')

    def stop_all_tasks(self):
        logging.info("Signalling all controller tasks to stop for shutdown...")
        self._shutdown = True
        self.cancel_all_fetches()
        self.session.close()
        self.thread_pool.clear()

    def cancel_all_fetches(self):
        logging.info("Cancelling all in-flight fetch operations...")
        for worker in self.active_workers[:]:
            if hasattr(worker, 'cancel'):
                worker.cancel()
        self.active_workers.clear()

        
        with self.process_lock:
           
            for job_id, (proc, url) in list(self.fetching_processes.items()):
                if proc.poll() is None:
                    logging.info(f"Terminating fetch subprocess PID {proc.pid} for job {job_id}")
                    proc.terminate()
                    self.media_fetch_failed.emit(job_id, url, "Cancelled by user.")
            self.fetching_processes.clear()

            for proc in self.active_processes[:]:
                if proc.poll() is None:
                    logging.info(f"Terminating generic subprocess PID {proc.pid}")
                    proc.terminate()
            self.active_processes.clear()
        
        self.force_clear_all_jobs.emit()

    def _find_downloader(self) -> str:
        exe_name = "downloader.exe" if sys.platform == "win32" else "downloader"
        
        path_to_check = _resource_path(os.path.join('src', 'core', exe_name))
        
        if os.path.exists(path_to_check):
            return path_to_check
        
        return ""

    @pyqtSlot(str, str)
    def update_status_and_log(self, message: str, level: str = 'info'):
        if level == 'info': logging.info(message)
        elif level == 'error': logging.error(message)
        self.status_updated.emit(message)

    def fetch_media_for_download(self, url: str, job_id: int):
        self.update_status_and_log(f"Fetching... for: {url}...")
        worker = Worker(self._fetch_media_worker, url, job_id)
        self.thread_pool.start(worker)

    def fetch_media_for_track_selection(self, url: str):
        self.update_status_and_log(f"Fetching... for: {url}...")
        worker = Worker(self._fetch_media_generic_worker, url, self.tracklist_loaded_for_selection)
        self.thread_pool.start(worker)

    def fetch_media_for_viewing(self, url: str):
        self.update_status_and_log(f"Fetching... for viewing: {url}...")
        worker = Worker(self._fetch_media_generic_worker, url, self.tracklist_loaded_for_viewing)
        self.thread_pool.start(worker)

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
        self.update_status_and_log(f"Fetching... quality details for {len(tracks)} tracks...")
        worker = Worker(self._fetch_qualities_for_dialog_async, tracks)
        self.thread_pool.start(worker)

    def cancel_fetch(self, job_id: int):
        with self.process_lock:
            if job_id in self.fetching_processes:
                process, url = self.fetching_processes.pop(job_id)
                if process.poll() is None:
                    logging.info(f"Cancelling fetch process for job {job_id} (PID: {process.pid})")
                    process.terminate()
                    if process in self.active_processes:
                        self.active_processes.remove(process)
                    self.media_fetch_failed.emit(job_id, url, "Cancelled by user during fetch.")
                    return True
        return False

    def _parse_qualities_from_manifest(self, manifest_data: str) -> dict:
        traits = set()
        info = {"audioTraits": [], "codec": None, "bitrate": None, "avgBitrate": None,
                "sampleRateHz": None, "bitDepth": None, "channels": None}

        for line in manifest_data.splitlines():
            if line.startswith('#EXT-X-SESSION-DATA:') and 'com.apple.hls.audioAssetMetadata' in line:
                try:
                    b64 = re.search(r'VALUE="([^"]+)"', line)
                    if b64:
                        meta = json.loads(base64.b64decode(b64.group(1)))
                        for asset in (meta.values() if isinstance(meta, dict) else []):
                            codec = (asset.get('AUDIO-FORMAT-ID') or asset.get('CODEC') or info["codec"])
                            if codec: info["codec"] = codec
                            if asset.get('IS-ATMOS') or asset.get('AUDIO-FORMAT-ID') in ['ec+3','ac-4']:
                                traits.add('atmos')
                            if asset.get('IS-SPATIAL'):
                                traits.add('spatial')
                            sr = (asset.get('SAMPLE-RATE-HZ') or asset.get('AUDIO-SAMPLE-RATE-HZ') or
                                  asset.get('SAMPLE-RATE') or asset.get('SAMPLE_RATE'))
                            bd = (asset.get('BITS-PER-SAMPLE') or asset.get('BIT-DEPTH') or asset.get('BIT_DEPTH') or asset.get('BITS_PER_SAMPLE'))
                            ch = asset.get('CHANNELS') or asset.get('NUM-CHANNELS')
                            if sr and not info["sampleRateHz"]: info["sampleRateHz"] = int(sr)
                            if bd and not info["bitDepth"]: info["bitDepth"] = int(bd)
                            if ch and not info["channels"]: info["channels"] = int(ch)
                except Exception:
                    pass

        stream_re = re.compile(r'#EXT-X-STREAM-INF:([^\r\n]+)')
        for m in stream_re.finditer(manifest_data):
            attrs = m.group(1)
            bw = re.search(r'BANDWIDTH=(\d+)', attrs)
            abw = re.search(r'AVERAGE-BANDWIDTH=(\d+)', attrs)
            codecs = re.search(r'CODECS="([^"]+)"', attrs)
            if bw:
                b = int(bw.group(1))
                if (info["bitrate"] or 0) < b:
                    info["bitrate"] = b
            if abw:
                a = int(abw.group(1))
                if (info["avgBitrate"] or 0) < a:
                    info["avgBitrate"] = a
            if codecs and not info["codec"]:
                info["codec"] = codecs.group(1)

        if 'atmos' in traits:
            traits.add('spatial')
        info["audioTraits"] = list(traits)
        return info

    async def _fetch_manifest_async(self, session, index, track):
        try:
            manifest_url = track.get('attributes', {}).get('extendedAssetUrls', {}).get('enhancedHls')
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
        async with aiohttp.ClientSession(headers={"User-Agent": self.CHROME_USER_AGENT}) as session:
            tasks = [self._fetch_manifest_async(session, i, track) for i, track in enumerate(tracks)]
            results = await asyncio.gather(*tasks)
            return results

    async def _fetch_qualities_for_dialog_async(self, tracks: list):
        try:
            manifest_results = await self._fetch_all_manifests_async(tracks)
            
            updated_tracks = []
            for index, quality_info in manifest_results:
                track_copy = tracks[index].copy()
                if quality_info:
                    tr_attrs = track_copy.setdefault('attributes', {})
                    if 'audioTraits' in quality_info:
                        tr_attrs['audioTraits'] = list(set(tr_attrs.get('audioTraits', [])) | set(quality_info['audioTraits']))
                    for k in ['codec','bitrate','avgBitrate','sampleRateHz','bitDepth','channels']:
                        if quality_info.get(k) is not None:
                            tr_attrs[k] = quality_info[k]
                updated_tracks.append(track_copy)
            
            self.track_qualities_loaded.emit(updated_tracks)
            self.update_status_and_log("Quality details loaded.")
        except Exception as e:
            logging.error(f"Error fetching qualities for dialog:\n{traceback.format_exc()}")
            self.update_status_and_log(f"Failed to fetch quality details: {e}", 'error')
            self.track_qualities_loaded.emit(tracks)
    async def _fetch_album_for_info_worker_async(self, url: str):
        try:
            match = re.search(r'music\.apple\.com/[^/]+/([^/]+)/[^/]+/(\d+|pl\.[^?]+)', url)
            if not match: 
                raise ValueError("Could not parse item type and ID from URL.")
            
            item_type, item_id = match.group(1), match.group(2)
            item_type_plural = f"{item_type}s" if not item_type.endswith('s') else item_type
            
            api_result = self._lookup_api_item(item_type_plural, item_id)
            item_data = api_result.get('data', [{}])[0]
            
            if not item_data: 
                raise ValueError("API response did not contain item data.")
            
            tracks = item_data.get('relationships', {}).get('tracks', {}).get('data', [])
            
            if not tracks:
                parsed_data = self._parse_api_item(item_data)
                self.album_details_for_info_loaded.emit(parsed_data)
                return
            
            self.update_status_and_log(f"Fetching... quality details for {len(tracks)} tracks...")
            
            manifest_results = await self._fetch_all_manifests_async(tracks)
            
            for index, quality_info in manifest_results:
                if quality_info:
                    tr = tracks[index].setdefault('attributes', {})
                    if 'audioTraits' in quality_info:
                        tr['audioTraits'] = list(set(tr.get('audioTraits', [])) | set(quality_info['audioTraits']))
                    for k in ['codec','bitrate','avgBitrate','sampleRateHz','bitDepth','channels']:
                        if quality_info.get(k) is not None:
                            tr[k] = quality_info[k]
            
            parsed_data = self._parse_api_item(item_data)
            if not parsed_data: 
                raise ValueError("Failed to parse final API item data.")
            
            self.album_details_for_info_loaded.emit(parsed_data)
            self.update_status_and_log("Full details loaded for info dialog.")
            
        except Exception as e:
            logging.error(f"Unexpected error fetching details for info dialog:\n{traceback.format_exc()}")
            self.update_status_and_log(f"Failed to fetch details: {e}", 'error')
            self.media_fetch_failed.emit(-1, url, f"Could not fetch details: {e}")

    async def _fetch_song_for_info_worker_async(self, song_data: dict):
        try:
            song_id = song_data.get('id')
            if not song_id:
                raise ValueError("Song data is missing an ID.")

            api_result = self._lookup_api_item('songs', song_id)
            item_data = api_result.get('data', [{}])[0]

            if not item_data:
                raise ValueError("API response did not contain song data.")

            manifest_url = item_data.get('attributes', {}).get('extendedAssetUrls', {}).get('enhancedHls')
            if not manifest_url:
                self.song_details_for_info_loaded.emit(self._parse_api_item(item_data))
                return

            async with aiohttp.ClientSession(headers={"User-Agent": self.CHROME_USER_AGENT}) as session:
                async with session.get(manifest_url, timeout=20) as response:
                    response.raise_for_status()
                    manifest_data = await response.text()
                    quality_info = self._parse_qualities_from_manifest(manifest_data)

            tr_attrs = item_data.setdefault('attributes', {})
            if 'audioTraits' in quality_info:
                tr_attrs['audioTraits'] = list(set(tr_attrs.get('audioTraits', [])) | set(quality_info['audioTraits']))
            for k in ['codec','bitrate','avgBitrate','sampleRateHz','bitDepth','channels']:
                if quality_info.get(k) is not None:
                    tr_attrs[k] = quality_info[k]

            parsed_data = self._parse_api_item(item_data)
            if not parsed_data:
                raise ValueError("Failed to parse final API item data for song.")

            self.song_details_for_info_loaded.emit(parsed_data)
            self.update_status_and_log("Song quality details loaded.")

        except Exception as e:
            logging.error(f"Error fetching song details for info dialog:\n{traceback.format_exc()}")
            self.update_status_and_log(f"Failed to fetch song details: {e}", 'error')
            self.song_details_for_info_loaded.emit(song_data)

    def _fetch_video_for_preview_worker(self, video_data: dict):
        try:
            video_id = video_data.get('id')
            if not video_id:
                raise ValueError("Video data is missing an ID.")
            
            api_result = self._lookup_api_item('music-videos', video_id)
            item_data = api_result.get('data', [{}])[0]

            if not item_data:
                raise ValueError("API response did not contain video data.")
            
            parsed_data = self._parse_api_item(item_data)
            if not parsed_data:
                raise ValueError("Failed to parse final API item data for video.")
            
            self.video_details_for_preview_loaded.emit(parsed_data)
        except Exception as e:
            logging.error(f"Error fetching video details for preview:\n{traceback.format_exc()}")
            self.update_status_and_log(f"Failed to fetch video details: {e}", 'error')
            self.video_details_for_preview_loaded.emit(video_data)

    def _fetch_media_generic_worker(self, url: str, signal_to_emit):
        command = [self.downloader_executable, "--json-output", url]
        process = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            with self.process_lock:
                self.active_processes.append(process)

            stdout_buf = []
            probe_total = None

            def stdout_reader():
                nonlocal probe_total
                for line in iter(process.stdout.readline, ''):
                    if not line: break
                    msg = line.strip()
                    if msg.startswith("AMDL_PROGRESS::"):
                        try:
                            data = json.loads(msg[len("AMDL_PROGRESS::"):].strip())
                            t = data.get("type")
                            if t == "probe_start":
                                probe_total = int(data.get("total", 0))
                                self.status_updated.emit(f"Fetching... (0/{probe_total})")
                            elif t == "probe_progress":
                                cur = int(data.get("current", 0))
                                tot = int(data.get("total", probe_total or 0))
                                self.status_updated.emit(f"Fetching... ({cur}/{tot})")
                        except Exception:
                            pass
                    stdout_buf.append(line)

            def stderr_reader():
                for line in iter(process.stderr.readline, ''):
                    if not line: break
                    self.status_updated.emit(line.strip())

            t_out = threading.Thread(target=stdout_reader, daemon=True)
            t_err = threading.Thread(target=stderr_reader, daemon=True)
            t_out.start()
            t_err.start()

            return_code = process.wait()
            t_out.join()
            t_err.join()

            if return_code != 0:
                self.update_status_and_log(f"Error fetching details.", 'error')
                signal_to_emit.emit({})
                return

            full_out = "".join(stdout_buf)
            json_match = re.search(r'AMDL_JSON_START(.*)AMDL_JSON_END', full_out, re.DOTALL)
            if not json_match:
                self.update_status_and_log("Error: Could not parse details data.", 'error')
                signal_to_emit.emit({})
                return

            media_data = json.loads(json_match.group(1))
            signal_to_emit.emit(media_data)
            self.update_status_and_log("Details loaded.")
        except Exception as e:
            self.update_status_and_log(f"Failed to execute Go backend for details: {e}", 'error')
            signal_to_emit.emit({})
        finally:
            with self.process_lock:
                if process and process in self.active_processes:
                    self.active_processes.remove(process)

    def _fetch_media_worker(self, url: str, job_id: int):
        command = [self.downloader_executable, "--json-output", url]
        process = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            with self.process_lock:
                self.active_processes.append(process)
                if job_id > 0:
                    self.fetching_processes[job_id] = (process, url)

            stdout_buf = []
            probe_total = None

            def stdout_reader():
                nonlocal probe_total
                for line in iter(process.stdout.readline, ''):
                    if not line: break
                    msg = line.strip()
                    if msg.startswith("AMDL_PROGRESS::"):
                        try:
                            data = json.loads(msg[len("AMDL_PROGRESS::"):].strip())
                            t = data.get("type")
                            if t == "probe_start":
                                probe_total = int(data.get("total", 0))
                                self.media_fetch_progress.emit(job_id, 0, probe_total)
                            elif t == "probe_progress":
                                cur = int(data.get("current", 0))
                                tot = int(data.get("total", probe_total or 0))
                                self.media_fetch_progress.emit(job_id, cur, tot)
                        except Exception:
                            pass
                    stdout_buf.append(line)

            def stderr_reader():
                for line in iter(process.stderr.readline, ''):
                    if not line: break
                    self.status_updated.emit(line.strip())

            t_out = threading.Thread(target=stdout_reader, daemon=True)
            t_err = threading.Thread(target=stderr_reader, daemon=True)
            t_out.start()
            t_err.start()

            return_code = process.wait()
            t_out.join()
            t_err.join()

            with self.process_lock:
                if job_id > 0 and job_id not in self.fetching_processes:
                    logging.info(f"Fetch for job {job_id} was cancelled. Aborting post-processing.")
                    return

            if return_code != 0:
                error_message = f"Failed to fetch media. See console for details."
                self.update_status_and_log(f"Error fetching metadata for {url}. Check console for details.", 'error')
                self.media_fetch_failed.emit(job_id, url, error_message)
                return

            full_out = "".join(stdout_buf)
            json_match = re.search(r'AMDL_JSON_START(.*)AMDL_JSON_END', full_out, re.DOTALL)
            if not json_match:
                self.update_status_and_log(f"Error: Could not find metadata JSON for {url}.", 'error')
                logging.error(f"Backend output for {url} did not contain valid JSON block:\n{full_out}")
                self.media_fetch_failed.emit(job_id, url, "Could not parse backend response.")
                return
            
            media_data = json.loads(json_match.group(1))
            
            self.media_details_loaded.emit(job_id, media_data, url)
            
            name = media_data.get('albumData', {}).get('attributes', {}).get('name', 'Unknown')
            self.update_status_and_log(f"Added '{name}' to queue.")
        except Exception as e:
            self.update_status_and_log(f"Failed to execute Go backend for {url}: {e}", 'error')
            self.media_fetch_failed.emit(job_id, url, f"Execution error: {e}")
        finally:
            with self.process_lock:
                if job_id > 0:
                    self.fetching_processes.pop(job_id, None)
                if process and process in self.active_processes:
                    self.active_processes.remove(process)

    def search(self, query: str):
        self.update_status_and_log(f"Searching for: '{query}'...")
        worker = SearchWorker(self._initial_search_worker, query)
        worker.signals.search_results_loaded.connect(self.search_results_loaded)
        worker.signals.status_updated.connect(self.update_status_and_log)
        
        self.active_workers.append(worker)
        
        def cleanup(results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        
        worker.signals.search_results_loaded.connect(cleanup)
        self.thread_pool.start(worker)

    def search_for_albums(self, query: str):
        self.update_status_and_log(f"Searching for albums: '{query}'...")
        worker = SearchWorker(self._search_for_albums_worker, query)
        worker.signals.category_search_results_loaded.connect(self.category_search_results_loaded)
        worker.signals.status_updated.connect(self.update_status_and_log)
        
        self.active_workers.append(worker)
        
        def cleanup(category, results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        
        worker.signals.category_search_results_loaded.connect(cleanup)
        self.thread_pool.start(worker)

    def search_for_music_videos(self, query: str):
        self.update_status_and_log(f"Searching for music videos: '{query}'...")
        worker = SearchWorker(self._search_for_music_videos_worker, query)
        worker.signals.category_search_results_loaded.connect(self.category_search_results_loaded)
        worker.signals.status_updated.connect(self.update_status_and_log)
        
        self.active_workers.append(worker)
        
        def cleanup(category, results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        
        worker.signals.category_search_results_loaded.connect(cleanup)
        self.thread_pool.start(worker)

    def search_for_playlists(self, query: str):
        self.update_status_and_log(f"Searching for playlists: '{query}'...")
        worker = SearchWorker(self._search_for_playlists_worker, query)
        worker.signals.category_search_results_loaded.connect(self.category_search_results_loaded)
        worker.signals.status_updated.connect(self.update_status_and_log)
        self.active_workers.append(worker)
        
        def cleanup(category, results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        
        worker.signals.category_search_results_loaded.connect(cleanup)
        self.thread_pool.start(worker)

    def _search_for_playlists_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str):
        try:
            if worker.is_cancelled():
                return
            
            api_results = self._search_api(query, "playlists", 30)
            
            if worker.is_cancelled():
                return
            
            playlists_data = api_results.get('results', {}).get('playlists', {}).get('data', [])
            all_playlists = [p for item in playlists_data if (p := self._parse_api_item(item))]
            
            worker.safe_emit(signals.category_search_results_loaded, 'playlists', all_playlists)
            worker.safe_emit(signals.status_updated, "Playlist search complete.", "info")
        
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API playlist search request failed: {e}", "error")
            worker.safe_emit(signals.category_search_results_loaded, 'playlists', [])

    def search_for_artwork(self, query: str):
        self.update_status_and_log(f"Searching for artwork: '{query}'...")
        worker = SearchWorker(self._search_for_artwork_worker, query)
        worker.signals.category_search_results_loaded.connect(self._on_artwork_search_results)
        worker.signals.status_updated.connect(self.update_status_and_log)
        self.active_workers.append(worker)
        def cleanup(category, results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        worker.signals.category_search_results_loaded.connect(cleanup)
        self.thread_pool.start(worker)

    @pyqtSlot(str, list)
    def _on_artwork_search_results(self, category, results):
        if category == 'albums':
            self.artwork_search_results_loaded.emit(results)

    def load_more_artwork(self, query: str, offset: int):
        self.update_status_and_log(f"Loading more artwork for '{query}'...")
        worker = SearchWorker(self._load_more_artwork_worker, query, offset)
        worker.signals.artwork_results_appended.connect(self.artwork_search_results_appended)
        worker.signals.status_updated.connect(self.update_status_and_log)
        self.active_workers.append(worker)
        def cleanup(results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        worker.signals.artwork_results_appended.connect(cleanup)
        self.thread_pool.start(worker)

    def load_more_results(self, query: str, category: str, offset: int):
        self.update_status_and_log(f"Loading more {category} for '{query}'...")
        worker = SearchWorker(self._load_more_worker, query, category, offset)
        worker.signals.search_results_appended.connect(self.search_results_appended)
        worker.signals.status_updated.connect(self.update_status_and_log)
        
        self.active_workers.append(worker)
        
        def cleanup(category, results):
            if worker in self.active_workers:
                self.active_workers.remove(worker)
        
        worker.signals.search_results_appended.connect(cleanup)
        self.thread_pool.start(worker)

    def _get_apple_music_dev_token(self) -> str | None:
        with self.token_lock:
            if self.dev_token:
                return self.dev_token
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logging.info(f"No cached token found. Fetching new developer token (Attempt {attempt + 1}/{max_retries})...")
                    homepage_res = self.session.get(f'https://music.apple.com/{self.storefront}/browse', timeout=20)
                    homepage_res.raise_for_status()
                    match = re.search(r'/assets/index-legacy[~-][^/"]+\.js', homepage_res.text)
                    if not match: raise ValueError("Could not find core JS file.")
                    js_url = f"https://music.apple.com{match.group(0)}"
                    js_res = self.session.get(js_url, timeout=20)
                    js_res.raise_for_status()
                    token_match = re.search(r'eyJh[a-zA-Z0-9\._-]+', js_res.text)
                    if not token_match: raise ValueError("Could not find bearer token.")
                    self.dev_token = token_match.group(0)
                    logging.info("Successfully fetched and cached new developer token.")
                    return self.dev_token
                except (requests.RequestException, ValueError) as e:
                    logging.error(f"Failed to get developer token on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                    else:
                        error_msg = "Failed to get developer token after multiple attempts.\n\nPlease check your network connection, retry searching, or restart the app."
                        self.update_status_and_log(f"Failed to get developer token after {max_retries} attempts: {e}", 'error')
                        self.token_fetch_failed.emit(error_msg)
                        return None
        return None

    def _parse_api_item(self, item: dict, size: int = 600) -> dict | None:
        if not item or not item.get('attributes'): return None
        attrs = item['attributes']
        artwork_url = attrs.get('artwork', {}).get('url', '')
        
        if artwork_url and '{w}' in artwork_url:
            artwork_url = artwork_url.replace('{w}', str(size)).replace('{h}', str(size))

        duration_ms = attrs.get('durationInMillis', 0)
        seconds = duration_ms // 1000
        duration_str = f"{seconds // 60}:{seconds % 60:02d}"

        previews = attrs.get('previews', [])
        preview_url = previews[0]['url'] if previews else None

        parsed = {
            'id': item.get('id'), 'type': item.get('type'), 'name': attrs.get('name'),
            'artist': attrs.get('artistName'), 'albumName': attrs.get('albumName'),
            'artworkUrl': artwork_url, 'appleMusicUrl': attrs.get('url'),
            'previewUrl': preview_url,
            'durationStr': duration_str,
            'contentRating': attrs.get('contentRating'),
            'copyright': attrs.get('copyright'),
            'editorialNotes': attrs.get('editorialNotes', {}).get('standard'),
            'genreNames': attrs.get('genreNames', []),
            'isCompilation': attrs.get('isCompilation', False),
            'recordLabel': attrs.get('recordLabel'),
            'releaseDate': attrs.get('releaseDate'),
            'trackCount': attrs.get('trackCount'),
            'upc': attrs.get('upc'),
            'isrc': attrs.get('isrc'),
            'audioTraits': attrs.get('audioTraits', []),
            'composerName': attrs.get('composerName'),
            'hasLyrics': attrs.get('hasLyrics', False),
            'hasTimeSyncedLyrics': attrs.get('hasTimeSyncedLyrics', False),
            'isAppleDigitalMaster': attrs.get('isAppleDigitalMaster', False),
            'tracks_data': item.get('relationships', {}).get('tracks', {}).get('data', []),
            'attributes': attrs,
            'curatorName': attrs.get('curatorName'),
        }
        
        for k in ['codec','bitrate','avgBitrate','sampleRateHz','bitDepth','channels']:
            if attrs.get(k) is not None:
                parsed[k] = attrs[k]
                
        return parsed

    def _search_api(self, query: str, types: str, limit: int, offset: int = 0) -> dict:
        if self._shutdown:
            raise ValueError("Controller is shutting down")
            
        token = self._get_apple_music_dev_token()
        if not token:
            raise ValueError("Could not retrieve developer token for search.")
            
        headers = {"Authorization": f"Bearer {token}", "Origin": "https://music.apple.com", "Referer": "https://music.apple.com/"}
        
        api_call_types = types.replace('_', '-')
        params = {"term": query, "types": api_call_types, "limit": limit, "offset": offset}
        
        if types not in ["music_videos", "artists"]:
            params["include"] = "relationships.tracks"

        api_url = f"https://amp-api.music.apple.com/v1/catalog/{self.storefront}/search"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(api_url, headers=headers, params=params, timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as e:
                if self._shutdown:
                    raise ValueError("Controller is shutting down")
                if e.response.status_code in [401, 403]:
                    logging.warning("Developer token expired or invalid. Fetching a new one and retrying.")
                    self.dev_token = None
                    new_token = self._get_apple_music_dev_token()
                    if not new_token:
                        raise ValueError("Failed to refresh developer token.")
                    
                    headers["Authorization"] = f"Bearer {new_token}"
                    continue
                else:
                    logging.error(f"API search request failed with HTTP error on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise e
            except requests.RequestException as e:
                logging.error(f"API search request failed on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    raise e
        
        raise ValueError("API search failed after multiple retries.")

    def _lookup_api_item(self, item_type_plural: str, item_id: str) -> dict:
        token = self._get_apple_music_dev_token()
        if not token:
            raise ValueError("Could not retrieve developer token for lookup.")
            
        headers = {"Authorization": f"Bearer {token}", "Origin": "https://music.apple.com", "Referer": "https://music.apple.com/"}
        params = {"extend": "extendedAssetUrls,relationships.tracks"}
        
        api_url = f"https://amp-api.music.apple.com/v1/catalog/{self.storefront}/{item_type_plural}/{item_id}"
        
        max_retries = 3
        last_exception = None

        for attempt in range(max_retries):
            try:
                response = self.session.get(api_url, headers=headers, params=params, timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as e:
                last_exception = e
                if self._shutdown:
                    raise ValueError("Controller is shutting down")
                
                if e.response.status_code in [401, 403]:
                    logging.warning(f"Token expired on attempt {attempt + 1}. Refreshing...")
                    self.dev_token = None
                    new_token = self._get_apple_music_dev_token()
                    if not new_token:
                        raise ValueError("Failed to refresh developer token.")
                    headers["Authorization"] = f"Bearer {new_token}"
                else:
                    logging.error(f"API lookup failed with HTTP error on attempt {attempt + 1}/{max_retries}: {e}")
            
            except requests.RequestException as e:
                last_exception = e
                logging.error(f"API lookup failed with network error on attempt {attempt + 1}/{max_retries}: {e}")

            if attempt < max_retries - 1:
                time.sleep(1 + attempt)
            
        raise ValueError(f"API lookup failed for {item_type_plural}/{item_id} after {max_retries} attempts.") from last_exception

    def _initial_search_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str):
        try:
            if worker.is_cancelled(): return

            api_results = self._search_api(query, "songs,albums,artists,music-videos,playlists", 30)
            
            if worker.is_cancelled(): return
            
            songs_data = api_results.get('results', {}).get('songs', {}).get('data', [])
            all_songs = [p for item in songs_data if (p := self._parse_api_item(item))]
            
            albums_data = api_results.get('results', {}).get('albums', {}).get('data', [])
            all_albums = [p for item in albums_data if (p := self._parse_api_item(item))]
            
            artists_data = api_results.get('results', {}).get('artists', {}).get('data', [])
            all_artists = [p for item in artists_data if (p := self._parse_api_item(item))]

            videos_data = api_results.get('results', {}).get('music-videos', {}).get('data', [])
            all_videos = [p for item in videos_data if (p := self._parse_api_item(item))]
            
            playlists_data = api_results.get('results', {}).get('playlists', {}).get('data', [])
            all_playlists = [p for item in playlists_data if (p := self._parse_api_item(item))]
            
            if worker.is_cancelled(): return

            top_results_map = {
                **{item['id']: item for item in [
                    all_songs[0] if all_songs else None,
                    all_albums[0] if all_albums else None,
                    all_artists[0] if all_artists else None,
                    all_videos[0] if all_videos else None,
                    all_playlists[0] if all_playlists else None,
                ] if item is not None and item.get('id')}
            }
            top_results = list(top_results_map.values())

            final_results = {
                "top_results": top_results, "songs": all_songs,
                "albums": all_albums, "artists": all_artists,
                "music_videos": all_videos,
                "playlists": all_playlists
            }

            worker.safe_emit(signals.search_results_loaded, final_results)
            worker.safe_emit(signals.status_updated, "Search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API search request failed: {e}", 'error')
            worker.safe_emit(signals.search_results_loaded, {})
        except Exception:
            logging.error(f"Unexpected error processing search results:\n{traceback.format_exc()}")
            worker.safe_emit(signals.status_updated, "Failed to process search results. See console for details.", 'error')
            worker.safe_emit(signals.search_results_loaded, {})

    def _search_for_albums_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str):
        try:
            if worker.is_cancelled(): return
            api_results = self._search_api(query, "albums", 30)
            if worker.is_cancelled(): return
            albums_data = api_results.get('results', {}).get('albums', {}).get('data', [])
            all_albums = [p for item in albums_data if (p := self._parse_api_item(item))]
            worker.safe_emit(signals.category_search_results_loaded, 'albums', all_albums)
            worker.safe_emit(signals.status_updated, "Album search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API album search request failed: {e}", 'error')
            worker.safe_emit(signals.category_search_results_loaded, 'albums', [])

    def _search_for_music_videos_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str):
        try:
            if worker.is_cancelled(): return
            api_results = self._search_api(query, "music-videos", 30)
            if worker.is_cancelled(): return
            videos_data = api_results.get('results', {}).get('music-videos', {}).get('data', [])
            all_videos = [p for item in videos_data if (p := self._parse_api_item(item))]
            worker.safe_emit(signals.category_search_results_loaded, 'music_videos', all_videos)
            worker.safe_emit(signals.status_updated, "Music video search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API music video search request failed: {e}", 'error')
            worker.safe_emit(signals.category_search_results_loaded, 'music_videos', [])

    def _search_for_artwork_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str):
        try:
            if worker.is_cancelled(): return
            api_results = self._search_api(query, "albums", 50)
            if worker.is_cancelled(): return
            albums_data = api_results.get('results', {}).get('albums', {}).get('data', [])
            all_albums = [p for item in albums_data if (p := self._parse_api_item(item, size=5000))]
            worker.safe_emit(signals.category_search_results_loaded, 'albums', all_albums)
            worker.safe_emit(signals.status_updated, "Artwork search complete.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API artwork search request failed: {e}", 'error')
            worker.safe_emit(signals.category_search_results_loaded, 'albums', [])

    def _load_more_artwork_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str, offset: int):
        try:
            if worker.is_cancelled(): return
            api_results = self._search_api(query, "albums", 50, offset)
            if worker.is_cancelled(): return
            
            new_items_data = api_results.get('results', {}).get('albums', {}).get('data', [])
            new_items = [p for item in new_items_data if (p := self._parse_api_item(item, size=5000))]
            
            worker.safe_emit(signals.artwork_results_appended, new_items)
            worker.safe_emit(signals.status_updated, f"Loaded {len(new_items)} more artworks.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API 'load more' artwork request failed: {e}", 'error')
            worker.safe_emit(signals.artwork_results_appended, [])

    def _load_more_worker(self, worker: SearchWorker, signals: SearchWorkerSignals, query: str, category: str, offset: int):
        try:
            if worker.is_cancelled(): return
            api_results = self._search_api(query, category, 30, offset)
            if worker.is_cancelled(): return
            
            api_category_key = category.replace('_', '-')
            new_items_data = api_results.get('results', {}).get(api_category_key, {}).get('data', [])
            new_items = [p for item in new_items_data if (p := self._parse_api_item(item))]
            
            worker.safe_emit(signals.search_results_appended, category, new_items)
            worker.safe_emit(signals.status_updated, f"Loaded {len(new_items)} more {category}.", "info")
        except (requests.RequestException, ValueError) as e:
            self.search_failed.emit(str(e))
            worker.safe_emit(signals.status_updated, f"API 'load more' request failed: {e}", 'error')
            worker.safe_emit(signals.search_results_appended, category, [])

    def resolve_artist(self, url: str):
        self.update_status_and_log(f"Fetching... discography for artist...")
        worker = Worker(self._resolve_artist_worker, url)
        self.thread_pool.start(worker)

    def _resolve_artist_worker(self, url: str):
        command = [self.downloader_executable, "--resolve-artist", url, "--json-output"]
        process = None
        try:
            process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            with self.process_lock:
                self.active_processes.append(process)

            stdout, stderr = process.communicate()

            if process.returncode != 0:
                self.update_status_and_log(f"Error resolving artist: {stderr}", 'error')
                self.artist_discography_loaded.emit([])
                return

            json_match = re.search(r'AMDL_JSON_START(.*)AMDL_JSON_END', stdout, re.DOTALL)
            if not json_match:
                self.update_status_and_log("Error: Could not find discography JSON in backend output.", 'error')
                self.artist_discography_loaded.emit([])
                return
            
            raw_discography = json.loads(json_match.group(1))
            self.artist_discography_loaded.emit(raw_discography)

        except Exception as e:
            self.update_status_and_log(f"Failed to execute Go backend for artist resolution: {e}", 'error')
            self.artist_discography_loaded.emit([])
        finally:
            with self.process_lock:
                if process and process in self.active_processes:
                    self.active_processes.remove(process)

    def search_for_lyrics(self, query: str):
        self.update_status_and_log(f"Searching for tracks: '{query}'...")
        worker = Worker(self._search_for_lyrics_worker, query)
        self.thread_pool.start(worker)

    def scan_local_directory(self, path: str):
        self.update_status_and_log(f"Scanning folder: '{path}'...")
        worker = Worker(self._scan_local_directory_worker, path)
        self.thread_pool.start(worker)

    @pyqtSlot(dict, str)
    def download_lyrics_for_track(self, track_data: dict, local_filepath: str):
        worker = Worker(self._download_lyrics_for_track_worker, track_data, local_filepath)
        self.thread_pool.start(worker)

    def download_lyrics(self, item_data: dict):
        self.update_status_and_log(f"Downloading lyrics for {item_data.get('name', 'item')}...", "info")
        worker = Worker(self.download_lyrics_worker, item_data)
        self.thread_pool.start(worker)

    def download_lyrics_worker(self, item_data: dict):
        try:
            item_id = item_data.get('id')
            item_name = item_data.get('name', 'Unknown')
            
            if not item_id:
                raise ValueError("Item has no ID")
            
            self.lyrics_download_started.emit(item_id)
            
            ttml_content = self._fetch_lyrics_for_song(item_id)
            if not ttml_content:
                raise Exception("No synced lyrics available")
            
            config = {}
            try:
                with open("config.yaml", "r") as f:
                    config = yaml.safe_load(f) or {}
            except FileNotFoundError:
                pass
            
            lrc_format = config.get("lrc-format", "lrc")
            synced_lyrics = self._get_lyrics_from_ttml(ttml_content, lrc_format)
            
            if not synced_lyrics:
                raise Exception("Failed to parse TTML")
            
            self.lyrics_content_ready_for_save.emit(item_id, True, synced_lyrics)
            self.update_status_and_log(f"Lyrics ready for {item_name}", "info")
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Lyrics download failed: {error_msg}")
            self.lyrics_content_ready_for_save.emit(item_data.get('id', ''), False, error_msg)
            self.update_status_and_log(f"Failed to download lyrics: {error_msg}", "error")

    def download_artwork(self, item_data: dict):
        self.update_status_and_log(f"Downloading artwork for {item_data.get('name', 'item')}...", "info")
        worker = Worker(self.download_artwork_worker, item_data)
        self.thread_pool.start(worker)

    def download_artwork_worker(self, item_data: dict):
        try:
            import yaml  
            
            item_id = item_data.get('id')
            item_name = item_data.get('name', 'Unknown')
            artwork_url = item_data.get('artworkUrl', '')
            
            if not artwork_url:
                raise ValueError("No artwork URL available")
            
            self.artwork_download_started.emit(item_id)


            try:
                with open('config.yaml', 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f) or {}
            except FileNotFoundError:
                config_data = {}
            cover_size = config_data.get('cover-size', '5000x5000')
            try:
                width, height = map(int, cover_size.split('x'))
            except Exception:
                width, height = 5000, 5000  

            if '{w}' in artwork_url and '{h}' in artwork_url:
            
                artwork_url = artwork_url.replace('{w}', str(width)).replace('{h}', str(height))
            elif 'w=600' in artwork_url or 'h=600' in artwork_url:
             
                artwork_url = artwork_url.replace('w=600', f'w={width}').replace('h=600', f'h={height}')
            elif 'w=' in artwork_url and 'h=' in artwork_url:
             
                import re
                artwork_url = re.sub(r'w=\d+', f'w={width}', artwork_url)
                artwork_url = re.sub(r'h=\d+', f'h={height}', artwork_url)
            elif 'x' in artwork_url:
             
                import re
                artwork_url = re.sub(r'/(\d{2,4})x(\d{2,4})', f'/{width}x{height}', artwork_url)
          

            response = self.session.get(artwork_url, timeout=30)
            response.raise_for_status()
            
            artwork_data = response.content
            
            self.artwork_download_finished.emit(item_id, True, artwork_data.decode('latin1'))
            self.update_status_and_log(f"Artwork ready for {item_name}", "info")
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Artwork download failed: {error_msg}")
            self.artwork_download_finished.emit(item_data.get('id', ''), False, error_msg)
            self.update_status_and_log(f"Failed to download artwork: {error_msg}", "error")

    def _search_for_lyrics_worker(self, query: str):
        try:
            api_results = self._search_api(query, "songs,albums", 25)
            
            all_tracks = []
            songs_data = api_results.get('results', {}).get('songs', {}).get('data', [])
            all_tracks.extend([p for item in songs_data if (p := self._parse_api_item(item))])
            
            albums_data = api_results.get('results', {}).get('albums', {}).get('data', [])
            for album in albums_data:
                tracks_data = album.get('relationships', {}).get('tracks', {}).get('data', [])
                all_tracks.extend([p for item in tracks_data if (p := self._parse_api_item(item))])

            self.lyrics_search_results_loaded.emit(all_tracks)
        except Exception as e:
            self.update_status_and_log(f"Lyrics search failed: {e}", "error")
            self.lyrics_search_results_loaded.emit([])

    def _scan_local_directory_worker(self, path: str):
        try:
            self.update_status_and_log(f"Finding audio files in {path}...")
            audio_files = []
            supported_exts = ('.m4a', '.mp3', '.flac', '.opus', '.ogg')
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(supported_exts):
                        audio_files.append(os.path.join(root, file))
            
            audio_files.sort()
            total_files = len(audio_files)
            self.local_scan_results.emit({'type': 'scan_started', 'data': {'total_files': total_files}})

            chunk, chunk_size, processed_count = [], 25, 0
            for filepath in audio_files:
                try:
                    audio = File(filepath, easy=True)
                    if not audio: continue
                    
                    title = audio.get('title', [os.path.splitext(os.path.basename(filepath))[0]])[0]
                    artist = audio.get('artist', ['Unknown Artist'])[0]
                    album = audio.get('album', ['Unknown Album'])[0]

                    artwork_data = None
                    raw_audio = File(filepath)
                    if isinstance(raw_audio, MP3) and 'APIC:' in raw_audio: artwork_data = raw_audio['APIC:'].data
                    elif isinstance(raw_audio, FLAC) and raw_audio.pictures: artwork_data = raw_audio.pictures[0].data
                    elif isinstance(raw_audio, MP4) and 'covr' in raw_audio and raw_audio['covr']: artwork_data = raw_audio['covr'][0]
                    elif (isinstance(raw_audio, Oggvorbis) or (Opus and isinstance(raw_audio, Opus))) and 'metadata_block_picture' in raw_audio:
                        try: artwork_data = base64.b64decode(raw_audio['metadata_block_picture'][0])
                        except Exception: artwork_data = None

                    base, _ = os.path.splitext(filepath)
                    has_lyrics = os.path.exists(base + '.lrc') or os.path.exists(base + '.ttml')

                    chunk.append({'filepath': filepath, 'title': title, 'artist': artist, 'album': album, 'artwork_data': artwork_data, 'has_lyrics': has_lyrics})
                    processed_count += 1

                    if len(chunk) >= chunk_size:
                        self.local_scan_results.emit({'type': 'chunk', 'data': chunk})
                        chunk = []

                except Exception as e:
                    logging.warning(f"Could not process file {filepath}: {e}")

            if chunk: self.local_scan_results.emit({'type': 'chunk', 'data': chunk})
            self.local_scan_results.emit({'type': 'complete', 'data': {'total_found': processed_count}})
        except Exception as e:
            self.update_status_and_log(f"Local scan failed: {e}", "error")
            self.local_scan_results.emit({'type': 'error', 'data': str(e)})

    def _fetch_lyrics_for_song(self, song_id: str) -> str | None:
        try:
            token = self._get_apple_music_dev_token()
            if not token:
                raise ValueError("Could not retrieve developer token for lyrics.")
            
            config = {}
            try:
                with open('config.yaml', 'r') as f:
                    config = yaml.safe_load(f) or {}
            except FileNotFoundError:
                logging.error("config.yaml not found!")
                return None
            
            media_user_token = (config.get('media-user-token') or config.get('MEDIA-USER-TOKEN') or config.get('Media-User-Token'))
            if not media_user_token:
                logging.error("media-user-token not found in config.yaml")
                return None

            url = f"https://amp-api.music.apple.com/v1/catalog/{self.storefront}/songs/{song_id}/lyrics?l=en&extend=ttmlLocalizations"
            headers = {
                "Authorization": f"Bearer {token}", "Origin": "https://music.apple.com", "Referer": "https://music.apple.com/",
                "User-Agent": self.CHROME_USER_AGENT, "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"
            }
            cookies = {'media-user-token': media_user_token}
            
            logging.info(f"Requesting lyrics for song {song_id}")
            response = self.session.get(url, headers=headers, cookies=cookies, timeout=30)
            
            if response.status_code == 404: raise ValueError("No lyrics available for this song")
            response.raise_for_status()
            
            data = response.json()
            if 'data' in data and len(data['data']) > 0 and 'attributes' in data['data'][0]:
                attributes = data['data'][0]['attributes']
                ttml = attributes.get('ttml')
                if ttml:
                    return ttml
                
                ttml_local = attributes.get('ttmlLocalizations')
                if isinstance(ttml_local, dict):
                    if 'en' in ttml_local and ttml_local['en'].get('ttml'):
                        return ttml_local['en']['ttml']
                    for lang_data in ttml_local.values():
                        if lang_data.get('ttml'):
                            return lang_data['ttml']
                elif isinstance(ttml_local, list):
                    for lang_data in ttml_local:
                        if lang_data.get('ttml'):
                            return lang_data['ttml']
            
            logging.warning(f"No TTML content found for song {song_id}")
            return None
                
        except Exception as e:
            logging.error(f"Failed to fetch TTML for song {song_id}: {e}")
            if "No lyrics available" in str(e):
                raise e
            return None

    def _convert_time_to_lrc(self, time_str):
        try:
            if ':' in time_str:
                parts = time_str.split(':')
                minutes, seconds = int(parts[0]), float(parts[1])
            else:
                minutes, seconds = int(float(time_str) // 60), float(time_str) % 60
            return f"[{minutes:02d}:{seconds:05.2f}]"
        except (ValueError, IndexError) as e:
            logging.warning(f"Could not convert time '{time_str}': {e}")
            return None

    def _time_to_seconds(self, time_str):
        try:
            if ':' in time_str:
                parts = time_str.split(':')
                return int(parts[0]) * 60 + float(parts[1])
            return float(time_str)
        except:
            return 0

    def _get_lyrics_from_ttml(self, lyrics_ttml: str, lrc_format: str):
        try:
            if lrc_format == "ttml": return lyrics_ttml
            root = ElementTree.fromstring(lyrics_ttml)
            all_lines = []
            body = root.find('{http://www.w3.org/ns/ttml}body')
            if body is not None:
                for div in body.findall('{http://www.w3.org/ns/ttml}div'):
                    for p in div.findall('{http://www.w3.org/ns/ttml}p'):
                        begin, text = p.attrib.get('begin'), "".join(p.itertext()).strip()
                        if begin and text:
                            if lrc_time := self._convert_time_to_lrc(begin):
                                all_lines.append((begin, lrc_time, text))
            
            if not all_lines: raise ValueError("No lyrics lines found in TTML")
            all_lines.sort(key=lambda x: self._time_to_seconds(x[0]))
            return "\n".join([f"{lrc_time}{text}" for _, lrc_time, text in all_lines])
        except Exception as e:
            logging.error(f"Failed to convert TTML to LRC: {e}")
            return None

    def _download_lyrics_for_track_worker(self, track_data: dict, local_filepath: str):
        try:
            if not os.path.isfile(local_filepath):
                raise ValueError(f"Invalid path: '{local_filepath}' is not a file.")

            search_term = f"{track_data.get('artist', '')} {track_data.get('title', '')} {track_data.get('album', '')}"
            if not search_term.strip():
                raise ValueError("Not enough metadata to search for lyrics.")

            api_results = self._search_api(search_term, "songs", 5)
            songs_data = api_results.get('results', {}).get('songs', {}).get('data', [])
            if not songs_data:
                raise ValueError("No match found on Apple Music.")

            best_match = next((s for s in songs_data if s.get('attributes', {}).get('hasTimeSyncedLyrics')), None)
            if not best_match:
                best_match = songs_data[0]
                
            track_id_for_download = best_match.get('id')
            if not track_id_for_download:
                raise ValueError("Could not get ID from Apple Music result.")

            config = {}
            try:
                with open('config.yaml', 'r') as f: config = yaml.safe_load(f) or {}
            except FileNotFoundError: pass
            
            lrc_format = config.get('lrc-format', 'lrc')
            filename_no_ext = os.path.splitext(os.path.basename(local_filepath))[0]
            lyrics_path = os.path.join(os.path.dirname(local_filepath), f"{filename_no_ext}.{lrc_format}")

            if os.path.exists(lyrics_path):
                self.lyrics_download_finished.emit(local_filepath, True, "Exists")
                return

            ttml_content = self._fetch_lyrics_for_song(track_id_for_download)
            if not ttml_content:
                raise Exception("No synced lyrics available")

            synced_lyrics = self._get_lyrics_from_ttml(ttml_content, lrc_format)
            if not synced_lyrics:
                raise Exception("Failed to parse TTML")

            with open(lyrics_path, 'w', encoding='utf-8') as f:
                f.write(synced_lyrics)
            self.lyrics_download_finished.emit(local_filepath, True, "Done")

        except Exception as e:
            error_message = str(e)
            logging.error(f"Lyrics download for {track_data.get('title')} failed: {error_message}")
            
            final_status = "Failed"
            if "no lyrics available" in error_message.lower() or \
               "no match found" in error_message.lower() or \
               "no synced lyrics available" in error_message.lower():
                final_status = "Not Available"
            
            self.lyrics_download_finished.emit(local_filepath, False, final_status)

    def checkforupdates(self):
        worker = Worker(self._check_for_updates_worker)
        self.thread_pool.start(worker)

    def _check_for_updates_worker(self):
        try:
            api_url = f"https://api.github.com/repos/{self.REPO_OWNER}/{self.REPO_NAME}/releases/latest"
            response = self.session.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                latest_version = data['tag_name'].lstrip('v')
                release_url = data['html_url']
                current_version = self.VERSION
                self.updatecheckfinished.emit(latest_version, current_version, release_url)
            else:
                logging.warning(f"GitHub API failed for update check: {response.status_code}")
                self.updatecheckfinished.emit("", self.VERSION, "")
        except Exception as e:
            logging.warning(f"Update check error: {e}")
            self.updatecheckfinished.emit("", self.VERSION, "")

    def is_newer_version(self, latest, current):
        def parse_version(v):
            try:
                clean_v = (v or "0.0.0").split('-')[0]
                return tuple(map(int, clean_v.split('.')))
            except ValueError:
                return (0, 0, 0)
        return parse_version(latest) > parse_version(current)