import copy
import logging
import tempfile

from ..bridge_client import consume, request_for, start_process, terminate_tree
from ..config import load_config
from ..workers import Worker


class FetchCancelled(Exception):
    pass


class MediaMixin:
    def cancel_all_fetches(self):
        for worker in self.active_workers[:]:
            worker.cancel()
        self.active_workers.clear()
        with self.process_lock:
            processes = list(self.active_processes)
            cancelled = list(self.fetching_processes.items())
            self.active_processes.clear()
            self.fetching_processes.clear()
        for process in processes:
            process._apmyx_cancelled = True
            terminate_tree(process)
        for job_id, (_, url) in cancelled:
            self.media_fetch_failed.emit(job_id, url, "Cancelled by user.")
        self.force_clear_all_jobs.emit()

    def fetch_media_for_download(self, url: str, job_id: int):
        self.thread_pool.start(
            Worker(self._fetch_media_worker, url, job_id, load_config())
        )

    def fetch_media_for_track_selection(self, url: str):
        self.thread_pool.start(
            Worker(
                self._fetch_media_generic_worker,
                url,
                self.tracklist_loaded_for_selection,
                load_config(),
            )
        )

    def cancel_fetch(self, job_id: int):
        with self.process_lock:
            entry = self.fetching_processes.pop(job_id, None)
        if entry:
            process, url = entry
            process._apmyx_cancelled = True
            terminate_tree(process)
            with self.process_lock:
                if process in self.active_processes:
                    self.active_processes.remove(process)
            self.media_fetch_failed.emit(job_id, url, "Cancelled by user.")
            return True
        return False

    def _bridge_metadata(self, operation, url, settings, job_id=None):
        config = copy.deepcopy(settings if settings is not None else load_config())
        config["storefront"] = self.storefront
        request = request_for(operation, url, config)
        with tempfile.TemporaryDirectory(prefix="apmyx-probe-") as scratch:
            with self.process_lock:
                if self._shutdown:
                    raise ValueError("Controller is shutting down")
                process = start_process(request, scratch)
                self.active_processes.append(process)
                if job_id is not None:
                    self.fetching_processes[job_id] = (process, url)
            try:

                def event(record):
                    if record["event"] == "progress":
                        data = record["data"]
                        current, total = data.get("current", 0), data.get("total", 0)
                        if job_id is not None:
                            self.media_fetch_progress.emit(job_id, current, total)
                        else:
                            self.status_updated.emit(f"Fetching... ({current}/{total})")

                try:
                    result = consume(process, event, request["request_id"])
                except Exception:
                    if getattr(process, "_apmyx_cancelled", False) is True:
                        raise FetchCancelled() from None
                    raise
                if isinstance(result, dict):
                    result["_backend_settings"] = request["settings"]
                return result
            finally:
                with self.process_lock:
                    if job_id is not None:
                        self.fetching_processes.pop(job_id, None)
                    if process in self.active_processes:
                        self.active_processes.remove(process)

    def _fetch_media_generic_worker(self, url, signal_to_emit, settings=None):
        try:
            signal_to_emit.emit(self._bridge_metadata("probe", url, settings))
            self.update_status_and_log("Details loaded.")
        except Exception as exc:
            self.update_status_and_log(str(exc), "error")
            signal_to_emit.emit({})

    def _fetch_media_worker(self, url, job_id, settings=None):
        try:
            result = self._bridge_metadata("probe", url, settings, job_id)
            self.media_details_loaded.emit(job_id, result, url)
        except FetchCancelled:
            pass
        except Exception as exc:
            self.media_fetch_failed.emit(job_id, url, str(exc))

    def resolve_artist(self, url):
        self.thread_pool.start(Worker(self._resolve_artist_worker, url))

    def _resolve_artist_worker(self, url):
        try:
            self.artist_discography_loaded.emit(self._artist_releases(url))
        except Exception as exc:
            logging.error("Artist resolution failed: %s", exc)
            self.artist_discography_loaded.emit([])
