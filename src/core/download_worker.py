import json
import copy
import os
import tempfile
from .bridge_client import BackendError, consume, request_for, snapshot, start_process, terminate_tree
from .hints import explain
from backend.shared.progress import gui_progress
import logging
import re
import time
import threading
import yaml

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QRunnable, QThreadPool
from .config import config_path


def explain_failure(message):
    return explain(message)


def saved_message(folders):
    if not folders:
        return "Download complete."
    try:
        folder = os.path.commonpath(folders)
    except ValueError:
        folder = folders[-1]
    return f"Saved to {folder}"

class DownloadJobRunner(QRunnable):

    def __init__(self, job_id, command, total_tracks, worker_ref, quality_preference, is_playlist=False, original_url=""):
        super().__init__()
        self.job_id = job_id
        self.command = command
        self.total_tracks = total_tracks
        self.signals = DownloadWorkerSignals()
        self.worker_ref = worker_ref
        self.skipped_tracks = []
        self.started_at = None
        self.total_tracks_updated = False
        self._pause_triggered = False
        
       
        self.original_url = original_url

        q = (quality_preference or "").strip().lower()
        aac_aliases = {"aac", "aac-lc", "aac_stereo", "aac-stereo", "audio-stereo", "aac-binaural", "aac_downmix", "aac-downmix"}
        self.is_aac = (q in aac_aliases) or q.startswith("aac")
        self.is_mv = '/music-video/' in original_url
        self.is_single_song = '/song/' in original_url or bool(re.search(r'[?&]i=\d+', original_url))
        self.is_playlist = is_playlist
        
 
        self.is_user_playlist = "pl.u-" in original_url
        
      
        self.backend_says_user_playlist = False
        
        self.completed_tracks = 0
        self.current_track_num = 0
        self.current_track_name = "Starting..."
        self.saw_progress = False
        self.error_lines = []
        self.progress_regex = re.compile(r"(?:\r?)(Downloading|Decrypting)\.*?\s+(\d+)%")
        self.video_dim_regex = re.compile(r"^Video: (.+)")


        self.emit_interval = 0.05  
        self.last_emit_time = 0
        self._latest_progress_data = None
        self._progress_lock = threading.Lock()
        self.last_download_percent = 0
        self.last_decrypt_percent = 0
        self.current_phase = "STARTING"
        self.mv_phase = "DOWNLOADING"

        self.total_bytes = None
        self.downloaded_bytes = 0

        self._last_int_percent = None
        self._last_int_overall = None
        self._first_progress_sent = False

        self.info_stderr_patterns = [
            re.compile(r"^Fetching (album|playlist|station|music video) details\.\.\.$"),
            re.compile(r"^(Album|Playlist|MV) metadata found\."),
            re.compile(r"^Probing \d+ tracks concurrently\.\.\.$"),
            re.compile(r"^Connected to device$"),
            re.compile(r"^Received URL:"),
            re.compile(r"^(Video|Audio): "),
            re.compile(r"^MV Remuxing..."),
            re.compile(r"^MV Remuxed."),
            re.compile(r"^Download(ing|ed)"),
            re.compile(r"^Decrypt(ing|ed)"),
        ]

    def _is_decryptor_connection_failure(self, line: str) -> bool:
        return "wrapper_unavailable" in line.lower()

    def _fmt_bytes(self, n: int) -> str:
        if n is None or n < 0:
            return ""
        units = ["B", "KB", "MB", "GB", "TB"]
        s = 0
        f = float(n)
        while f >= 1024.0 and s < len(units) - 1:
            f /= 1024.0
            s += 1
        return f"{f:.1f} {units[s]}"

    def _should_use_album_like_tracking(self):
        return not self.is_single_song and not (self.is_mv and self.total_tracks == 1)

    def _emit_progress(self, status_text, track_percent, overall_percent, force=False):
        now = time.monotonic()
        with self._progress_lock:
            self._latest_progress_data = (status_text, track_percent, overall_percent)
            if force or (now - self.last_emit_time > self.emit_interval):
                self.signals.progress.emit(self.job_id, *self._latest_progress_data)
                self.last_emit_time = now

    def process_line(self, line, is_stderr):
        msg = line.strip()
        if not msg:
            return
        if msg.startswith("AMDL_PROGRESS::"):
            try:
                data = json.loads(msg.split("::", 1)[1])
                if data.get("schema_version") == 1:
                    self.process_progress(data)
                    return
            except ValueError:
                pass

        dim_match = self.video_dim_regex.match(msg)
        if dim_match:
            dimension_str = dim_match.group(1).strip()
            self.signals.stream_label.emit(self.job_id, dimension_str)
            return

        backend = self.command.get("wrapper", "legacy") if isinstance(self.command, dict) else "legacy"
        log_prefix = f"[{backend} Backend{' ERR' if is_stderr else ''}]"
        if msg.startswith('AMDL_PROGRESS::') and '"track_progress"' in msg:
            logging.debug("%s %s", log_prefix, msg)
        else:
            logging.info("%s %s", log_prefix, msg)

        if is_stderr:
            if self._is_decryptor_connection_failure(msg):
                logging.warning(f"PAUSE TRIGGER: Detected decryptor connection failure for job {self.job_id}.")
                self._pause_triggered = True
                self.error_lines.append(msg)
                self.signals.error_line.emit(self.job_id, msg)
                self.signals.pause_queue_requested.emit(self.job_id)
                return

            if not any(p.match(msg) for p in self.info_stderr_patterns):
                logging.error("Download job %s: %s", self.job_id, msg)
                self.error_lines.append(msg)
                self.signals.error_line.emit(self.job_id, msg)

        if msg.startswith("AMDL_PROGRESS::"):
            self.saw_progress = True
            try:
                progress_data = json.loads(msg.replace("AMDL_PROGRESS::", ""))
                progress_type = progress_data.get("type")

                if progress_type == "size":
                    tb = progress_data.get("total_bytes")
                    if isinstance(tb, (int, float)) and tb > 0:
                        self.total_bytes = int(tb)
                    return
                
                elif progress_type == "bytes":
                    db = progress_data.get("downloaded_bytes")
                    tb = progress_data.get("total_bytes")
                    if isinstance(db, (int, float)):
                        self.downloaded_bytes = int(db)
                    if isinstance(tb, (int, float)) and tb > 0:
                        self.total_bytes = int(tb)

                if progress_type == "track_start":
       
                    if progress_data.get("isUserPlaylist"):
                        self.backend_says_user_playlist = True
                        
                    if not self.total_tracks_updated:
                        total_from_backend = progress_data.get("total_tracks")
        
                        if total_from_backend and total_from_backend > 0 and self._should_use_album_like_tracking():
                            self.total_tracks = total_from_backend
                            self.total_tracks_updated = True

            
                    if self._should_use_album_like_tracking():
                        new_track_num = progress_data.get("track_num", 0)
                        if new_track_num > 0:
                            self.completed_tracks = max(self.completed_tracks, new_track_num - 1)

                    self.current_track_name = progress_data.get("name", "Unknown Track")
                    self.current_phase = "DOWNLOADING"
                    self.last_download_percent = 0
                    self.last_decrypt_percent = 0
                    self.total_bytes = None
                    self.downloaded_bytes = 0
                    if self.is_mv:
                        self.mv_phase = "DOWNLOADING"
                    
                    tb = progress_data.get("total_bytes")
                    if isinstance(tb, (int, float)) and tb > 0:
                        self.total_bytes = int(tb)
                        self.downloaded_bytes = 0

                elif progress_type == "track_skip":
                    skipped_name = progress_data.get("name", "Unknown Track")
                    self.skipped_tracks.append(skipped_name)
                    self.signals.track_skipped.emit(self.job_id, skipped_name, str(progress_data.get("reason") or ""))
                    self.completed_tracks += 1

                elif progress_type == "trackstream":
                    
                    streamgroup = (
                        progress_data.get("streamgroup")
                        or progress_data.get("stream_group")
                        or progress_data.get("streamGroup")
                        or ""
                    )
                    
                    self.signals.stream_label.emit(self.job_id, streamgroup or "")

                elif progress_type == "track_progress":
                    percent_f = float(progress_data.get("percent", 0.0))
                    overall_f = ((self.completed_tracks * 100.0) + percent_f) / max(1.0, float(self.total_tracks))
                    percent_i = int(round(percent_f))
                    overall_i = int(round(overall_f))

                    display_track_num = self.completed_tracks + 1
                    status_text = ""
                    phase = progress_data.get("phase")
                    phase_labels = {
                        "downloading": "Downloading", "decrypting": "Decrypting",
                        "remuxing": "Remuxing", "tagging": "Writing tags",
                    }
                    explicit_phase = phase in phase_labels and "phase_percent" in progress_data
                    if explicit_phase:
                        self.current_phase = phase.upper()
                        phase_percent = progress_data["phase_percent"]
                        percent_text = f" ({phase_percent:.0f}%)" if phase_percent is not None else "..."
                        status_text = f"({display_track_num}/{self.total_tracks}) {phase_labels[phase]}{percent_text}: {self.current_track_name}"
                        tb = progress_data.get("total_bytes")
                        db = progress_data.get("downloaded_bytes")
                        if isinstance(tb, (int, float)) and tb > 0:
                            self.total_bytes = int(tb)
                        if isinstance(db, (int, float)):
                            self.downloaded_bytes = int(db)
                    elif self.is_mv:
                        percent = progress_data.get("percent", 0)
                        if percent >= 90: 
                            self.mv_phase = "REMUXING"
                        elif percent >= 50: 
                            self.mv_phase = "PROCESSING"
                        else: 
                            self.mv_phase = "DOWNLOADING"

                        if self.mv_phase == "DOWNLOADING":
                            display_percent = int((percent / 49.0) * 100) if percent < 49 else 100
                            status_text = f"({display_track_num}/{self.total_tracks}) Downloading ({display_percent}%): {self.current_track_name}"
                        elif self.mv_phase == "PROCESSING":
                            status_text = f"({display_track_num}/{self.total_tracks}) Processing: {self.current_track_name}"
                        elif self.mv_phase == "REMUXING":
                            status_text = f"({display_track_num}/{self.total_tracks}) Remuxing video & audio: {self.current_track_name}"
                    else:
                        status_text = f"({display_track_num}/{self.total_tracks}) Downloading ({percent_i}%): {self.current_track_name}"

                    if self.total_bytes and not explicit_phase:
                        if self.is_mv:
                            if self.mv_phase in ("PROCESSING", "REMUXING"):
                                self.downloaded_bytes = int(self.total_bytes)
                            elif isinstance(progress_data.get("downloaded_bytes"), (int, float)):
                                self.downloaded_bytes = int(progress_data["downloaded_bytes"])
                        else:
                            self.downloaded_bytes = int((percent_f / 100.0) * self.total_bytes)

                    size_suffix = ""
                    if self.total_bytes and self.downloaded_bytes > 0:
                        size_suffix = f" • {self._fmt_bytes(self.downloaded_bytes)} of {self._fmt_bytes(self.total_bytes)}"
                    status_text += size_suffix


                    force_emit = (
                        not self._first_progress_sent or
                        self._last_int_percent != percent_i or
                        self._last_int_overall != overall_i
                    )
                    self._first_progress_sent = True
                    self._last_int_percent = percent_i
                    self._last_int_overall = overall_i

                    track_percent = -1.0 if progress_data.get("indeterminate") else percent_f
                    self._emit_progress(status_text, track_percent, overall_f, force=force_emit)

                elif progress_type == "track_complete":
                    self.completed_tracks += 1
      
                    if self._should_use_album_like_tracking():
                        completed_num = progress_data.get("track_num", self.completed_tracks)
                        self.completed_tracks = max(self.completed_tracks, completed_num)

                    overall_progress = (self.completed_tracks * 100.0) / float(self.total_tracks)
                    status_text = f"({self.completed_tracks}/{self.total_tracks}) Finished: {self.current_track_name}"
                    
                    if self.total_bytes:
                        status_text += f" • {self._fmt_bytes(self.total_bytes)}"

                    self._emit_progress(status_text, 100.0, float(overall_progress), force=True)
                    self.current_track_num = 0
                    return

            except json.JSONDecodeError:
                pass

       
        display_track_num = self.completed_tracks + 1

        if "Downloaded" in msg and "Downloading" not in msg:
            if self.current_phase == "DOWNLOADING" and self.last_download_percent < 100:
                self.last_download_percent = 100
                track_progress = 90.0 if self.is_mv else 60.0
                overall_progress = ((self.completed_tracks * 100.0) + track_progress) / float(self.total_tracks)
                next_phase_text = "remuxing..." if self.is_mv else "decrypting..."
                status_text = f"({display_track_num}/{self.total_tracks}) Download complete, {next_phase_text}"
                self._emit_progress(status_text, track_progress, overall_progress, force=True)
                self.current_phase = "REMUXING" if self.is_mv else "DECRYPTING"
                return

        if "MV Remuxing..." in msg:
            if self.current_phase == "DOWNLOADING" and self.last_download_percent < 100:
                self.last_download_percent = 100
                track_progress = 90.0
                overall_progress = ((self.completed_tracks * 100.0) + track_progress) / float(self.total_tracks)
                status_text = f"({display_track_num}/{self.total_tracks}) Download complete, remuxing..."
                self._emit_progress(status_text, track_progress, overall_progress, force=True)
                self.current_phase = "REMUXING"
                return

        match = self.progress_regex.search(line)
        if match:
            self.saw_progress = True
            phase = match.group(1)
            percent = int(match.group(2))
            track_progress = 0.0
            status_text = ""

            if phase == "Downloading":
                self.current_phase = "DOWNLOADING"
                self.last_download_percent = percent
                weight = 0.9 if self.is_mv else 0.6
                track_progress = float(percent * weight)
                status_text = f"({display_track_num}/{self.total_tracks}) Downloading ({percent}%): {self.current_track_name}"
                if self.total_bytes:
                    self.downloaded_bytes = int((percent / 100.0) * self.total_bytes)

            elif phase == "Decrypting":
                self.current_phase = "DECRYPTING"
                self.last_decrypt_percent = percent
                track_progress = 60.0 + (float(percent) * 0.4)
                status_text = f"({display_track_num}/{self.total_tracks}) Decrypting ({percent}%): {self.current_track_name}"
                if self.total_bytes:
                    self.downloaded_bytes = int(self.total_bytes)

            if status_text:
                size_suffix = ""
                if self.total_bytes and self.downloaded_bytes > 0:
                    size_suffix = f" • {self._fmt_bytes(self.downloaded_bytes)} of {self._fmt_bytes(self.total_bytes)}"
                status_text += size_suffix
                overall_progress = ((self.completed_tracks * 100.0) + track_progress) / float(self.total_tracks)
                self._emit_progress(status_text, track_progress, overall_progress)

    @pyqtSlot()
    def process_progress(self, data):
        if data.get("schema_version") != 1:
            self.process_line("AMDL_PROGRESS::" + json.dumps(data), False)
            return
        self.saw_progress = True
        kind = data.get("type")
        self.total_tracks = data.get("total_tracks", self.total_tracks)
        self.current_track_name = data.get("name", self.current_track_name)
        if kind == "trackstream":
            self.signals.stream_label.emit(self.job_id, data.get("streamgroup", ""))
            return
        if kind == "track_skip":
            self.skipped_tracks.append(self.current_track_name)
            self.signals.track_skipped.emit(self.job_id, self.current_track_name, str(data.get("reason") or ""))
        if kind in {"track_start", "track_progress", "track_complete", "track_skip", "track_error"}:
            self.current_phase = data.get("phase", "preparing").upper()
            self.downloaded_bytes = data.get("downloaded_bytes", self.downloaded_bytes)
            self.total_bytes = data.get("total_bytes", self.total_bytes)
            self._emit_progress(*gui_progress(data), force=True)

    def run(self):
        try:
            self.signals.fetching.emit(self.job_id, "Fetching details...")
            self.started_at = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="apmyx-download-") as scratch:
                process = start_process(self.command, scratch)
                self.worker_ref.set_current_process(process)

                saved = []

                def event(record):
                    if record["event"] == "progress":
                        self.process_progress(record["data"])
                    elif record["event"] == "artifact" and (record.get("data") or {}).get("path"):
                        saved.append(os.path.dirname(record["data"]["path"]))
                    elif record["event"] == "log":
                        message = record.get("message", "")
                        if record.get("level") == "error":
                            logging.error("Download job %s: %s", self.job_id, message)
                            self.error_lines.append(message)
                            self.signals.error_line.emit(self.job_id, message)

                consume(process, event, self.command["request_id"])
            self.signals.finished.emit(self.job_id, True, saved_message(saved), self.skipped_tracks)
        except BackendError as exc:
            if self.worker_ref.was_terminated_intentionally:
                self.signals.finished.emit(self.job_id, False, "Cancelled.", self.skipped_tracks)
            elif exc.retryable and exc.code == "wrapper_unavailable":
                logging.warning("Download job %s paused, wrapper unavailable: %s", self.job_id, exc)
                self._pause_triggered = True
                self.signals.error_line.emit(self.job_id, "wrapper_unavailable: " + str(exc))
                self.signals.pause_queue_requested.emit(self.job_id)
            else:
                message = explain_failure(str(exc))
                logging.error("Download job %s failed (%s): %s | %s", self.job_id, exc.code, message, self.command.get("url", ""))
                self.signals.finished.emit(self.job_id, False, message, self.skipped_tracks)
        except Exception as exc:
            message = explain_failure(str(exc))
            logging.exception("Download job %s failed: %s | %s", self.job_id, message, self.command.get("url", ""))
            self.signals.finished.emit(self.job_id, False, message, self.skipped_tracks)
        finally:
            self.worker_ref.set_current_process(None)

class DownloadWorkerSignals(QObject):
    fetching = pyqtSignal(int, str)
    progress = pyqtSignal(int, str, float, float)
    track_skipped = pyqtSignal(int, str, str)
    finished = pyqtSignal(int, bool, str, list)
    error_line = pyqtSignal(int, str)
    stream_label = pyqtSignal(int, str)
    pause_queue_requested = pyqtSignal(int)

class DownloadWorker(QObject):
    job_fetching = pyqtSignal(int, str)
    job_progress = pyqtSignal(int, str, float, float)
    track_skipped = pyqtSignal(int, str, str)
    job_finished = pyqtSignal(int, bool, str, list)
    job_cancelled = pyqtSignal(int)
    job_error_line = pyqtSignal(int, str)
    job_stream_label = pyqtSignal(int, str)
    queue_has_been_paused = pyqtSignal(list)
    job_started = pyqtSignal(int)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.download_queue = []
        self.is_busy = False
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(1)
        self.current_process = None
        self.was_terminated_intentionally = False
        self.current_job_id = None
        self.current_job_dict = None
        self.queue_paused = False

    def set_current_process(self, process):
        self.current_process = process

    def stop_current_job(self):
        self.was_terminated_intentionally = True
        if self.current_process and self.current_process.poll() is None:
            logging.info(f"Sending termination signal to process for job {self.current_job_id}")
            terminate_tree(self.current_process)

    def pause_queue(self):
        if not self.queue_paused:
            logging.info("Download queue is being paused.")
            self.queue_paused = True

    def resume_queue(self):
        if self.queue_paused:
            logging.info("Download queue is being resumed.")
            self.queue_paused = False
            self._process_queue()

    @pyqtSlot()
    def on_force_clear_all(self):
        queued_jobs = list(self.download_queue)
        self.download_queue.clear()
        for job in queued_jobs:
            self.job_cancelled.emit(job['job_id'])
        if self.is_busy:
            self.stop_current_job()

    def cancel_job(self, job_id: int) -> bool:
        removed = False

        if self.is_busy and self.current_job_id == job_id:
            logging.info(f"Requesting cancellation for running job {job_id}.")
            self.stop_current_job()
            removed = True

   
        initial_len = len(self.download_queue)
        self.download_queue = [job for job in self.download_queue if job['job_id'] != job_id]
        if len(self.download_queue) < initial_len:
            logging.info(f"Removed job {job_id} from queue before it started.")
            removed = True


        if not removed:
            if self.controller.cancel_fetch(job_id):
                removed = True
        
        if not removed:
            logging.warning(f"Could not cancel job {job_id}. It may have already finished or was not found.")

        return removed

    def has_pending(self) -> bool:
        return bool(self.download_queue)

    @pyqtSlot(int, dict, str, str)
    def add_job_to_queue(self, job_id, media_data, quality_preference, original_url, backend_settings=None):
        saved = backend_settings if backend_settings is not None else media_data.get('_backend_settings')
        settings = snapshot({'wrapper': 'legacy', **saved} if saved is not None else self._get_latest_config())
        media_data = copy.deepcopy(media_data)
        media_data['_backend_settings'] = settings
        job = {
            'backend_settings': settings,
            'job_id': job_id,
            'media_data': media_data,
            'quality': quality_preference,
            'original_url': original_url
        }
        self.download_queue.append(job)
        self._process_queue()

    def _get_latest_config(self):
        try:
            with open(config_path(), 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logging.warning("config.yaml not found when starting job. Using defaults.")
            return {}
        except Exception as e:
            logging.error(f"Error reading config.yaml when starting job: {e}. Using defaults.")
            return {}

    def _process_queue(self):
        if self.is_busy or not self.download_queue or self.queue_paused:
            return

        self.is_busy = True
        self.was_terminated_intentionally = False
        job = self.download_queue.pop(0)
        self.current_job_id = job['job_id']
        self.current_job_dict = job
        self.job_started.emit(self.current_job_id)

        try:
            url_to_download = job['original_url']
            media_data = job['media_data']
            quality_pref = job['quality']
            total_tracks = len(media_data.get('tracks', []))

            if total_tracks == 0:
                raise ValueError("Media data contains no tracks.")

            is_playlist_url = "/playlist/" in url_to_download

            settings = job.get('backend_settings', {'wrapper': 'legacy'})
            track_ids = [str(track.get('trackData', track)['id']) for track in media_data.get('tracks', [])]
            command = request_for('download', url_to_download, settings, quality=quality_pref,
                                  track_ids=track_ids, media_data=media_data)

            runner = DownloadJobRunner(
                job['job_id'], 
                command, 
                total_tracks, 
                self, 
                quality_pref, 
                is_playlist=is_playlist_url,
                original_url=url_to_download 
            )
            
            runner.signals.fetching.connect(self.job_fetching)
            runner.signals.progress.connect(self.job_progress)
            runner.signals.track_skipped.connect(self.track_skipped)
            runner.signals.error_line.connect(self.job_error_line)
            runner.signals.stream_label.connect(self._on_stream_label)
            runner.signals.finished.connect(self._on_job_finished)
            runner.signals.pause_queue_requested.connect(self._handle_pause_request)

            self.thread_pool.start(runner)

        except Exception as e:
            logging.error(f"Failed to start job {job['job_id']}: {e}")
            self._on_job_finished(job['job_id'], False, f"Error preparing job: {e}", [])

    @pyqtSlot(int)
    def _handle_pause_request(self, job_id):
        if self.queue_paused:
            return
        
        self.pause_queue()
        self.stop_current_job() 

        full_queue_to_persist = [self.current_job_dict] + self.download_queue
        

        self.download_queue.clear()
        

        self.queue_has_been_paused.emit(full_queue_to_persist)
        

        self.is_busy = False
        self.current_job_id = None
        self.current_job_dict = None

    @pyqtSlot(int, bool, str, list)
    def _on_job_finished(self, job_id, success, message, skipped_tracks):
        self.job_finished.emit(job_id, success, message, skipped_tracks)
        self.is_busy = False
        self.current_job_id = None
        self.current_job_dict = None
        self._process_queue()

    @pyqtSlot(int, str)
    def _on_stream_label(self, job_id, label):
        self.job_stream_label.emit(job_id, label)

    @pyqtSlot()
    def cancel_all_jobs(self):
        logging.info("Unified cancel all jobs requested.")
        self.controller.cancel_all_fetches()
        self.on_force_clear_all()
