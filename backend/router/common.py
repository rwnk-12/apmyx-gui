import copy
import json
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import threading
from urllib.parse import urlsplit

import requests

if __package__.startswith("backend."):
    from ..shared.folders import save_folder
    from ..shared.progress import ProgressRouter
    from ..shared.tagging import SharedTagger, TaggingError
else:
    from shared.folders import save_folder
    from shared.progress import ProgressRouter
    from shared.tagging import SharedTagger, TaggingError


ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "providers"
RUNTIME = ROOT / "runtime"
WRAPPERS = {
    "applemusicdecrypt": "Wrapper Lite (Default)",
    "legacy": "Legacy Wrapper",
    "wrapper-v2": "Wrapper v2",
}
DEFAULTS = {
    "wrapper": "applemusicdecrypt",
    "applemusicdecrypt-url": "http://127.0.0.1:12340",
    "applemusicdecrypt-api-key": "",
    "applemusicdecrypt-storefront": "",
    "wrapper-v2-url": "http://127.0.0.1",
    "wrapper-v2-decrypt-host": "127.0.0.1",
    "wrapper-v2-decrypt-port": 10020,
    "decrypt-m3u8-port": "127.0.0.1:10020",
    "get-m3u8-port": "127.0.0.1:20020",
}
UNSUPPORTED = {
    "applemusicdecrypt": {
        "save-artist-cover", "save-animated-artwork", "emby-animated-artwork",
        "get-m3u8-mode", "atmos-max", "max-memory-limit",
        "dl-albumcover-for-playlist",
    },
    "legacy": set(),
    "wrapper-v2": {
        "authorization-token",
        "save-artist-cover",
        "save-animated-artwork",
        "emby-animated-artwork",
        "get-m3u8-mode",
        "alac-max",
        "atmos-max",
        "max-memory-limit",
        "dl-albumcover-for-playlist",
        "mv-audio-type",
        "explicit-choice",
        "clean-choice",
        "apple-master-choice",
    },
}


class BackendError(RuntimeError):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def classify_error(message):
    message = str(message or "").strip() or "Unknown backend error."
    if re.search(
        r"connection refused|actively refused|no connection could be made|connecterror|invalid ckc|playback error",
        message,
        re.I,
    ):
        return BackendError(
            "wrapper_unavailable",
            f"Connection to the selected wrapper failed: {message}",
            True,
        )
    if re.search(
        r"not authenticated|logged.out|not logged|no such account|unauthenticated|authentication required|HTTP (401|403)",
        message,
        re.I,
    ):
        return BackendError(
            "authentication_required",
            f"Authenticate the selected wrapper externally first: {message}",
        )
    if re.search(r"timed out|timeout|connection reset", message, re.I):
        return BackendError("network_error", message, True)
    return BackendError("backend_failed", message)


def migrate_wrapper(settings):
    result = dict(settings or {})
    if result.get("wrapper") == "wrapper-lite":
        result["wrapper"] = "applemusicdecrypt"
        lite_url = str(result.get("wrapper-lite-url") or "").strip()
        current = str(result.get("applemusicdecrypt-url") or "").strip()
        if lite_url and current in ("", DEFAULTS["applemusicdecrypt-url"]):
            result["applemusicdecrypt-url"] = lite_url
    result.pop("wrapper-lite-url", None)
    return result


def snapshot(settings):
    result = copy.deepcopy(DEFAULTS)
    result.update(copy.deepcopy(migrate_wrapper(settings)))
    result["language"] = result.get("language") or "en-US"
    if str(result.get("lrc-format", "")).lower() == "srt":
        result["lrc-format"] = "lrc"
    if result["wrapper"] not in WRAPPERS:
        raise BackendError("invalid_wrapper", "Unknown wrapper selection.")
    return result


def validate_request(request):
    if not isinstance(request, dict) or request.get("version", 1) != 1:
        raise BackendError("invalid_request", "Expected bridge protocol version 1.")
    if request.get("operation") not in {
        "status",
        "probe",
        "download",
    }:
        raise BackendError("invalid_request", "Unknown backend operation.")
    settings = snapshot(request.get("settings", {}))
    wrapper = request.get("wrapper", settings["wrapper"])
    if wrapper == "wrapper-lite":
        wrapper = "applemusicdecrypt"
    if wrapper not in WRAPPERS:
        raise BackendError("invalid_wrapper", "Unknown wrapper selection.")
    settings["wrapper"] = wrapper
    quality = str(request.get("quality", "ALAC")).upper()
    if request["operation"] == "download" and quality not in {
        "ALAC",
        "ATMOS",
        "AAC",
        "AAC-LC",
        "AAC-BINAURAL",
        "AAC-DOWNMIX",
    }:
        raise BackendError(
            "unsupported_quality", "The selected audio quality is not supported."
        )
    if quality.startswith("AAC-"):
        settings["aac-type"] = quality.lower()
        quality = "AAC"
    if request["operation"] == "download":
        for key in {
            "save-artist-cover",
            "save-animated-artwork",
            "emby-animated-artwork",
            "use-song-metadata-for-playlist-numbering",
        } & UNSUPPORTED[wrapper]:
            if settings.get(key):
                raise BackendError(
                    "unsupported_setting",
                    f"The selected backend does not support {key}. Disable it before downloading.",
                )
    if request["operation"] != "status":
        parts = urlsplit(request.get("url", ""))
        if parts.scheme != "https" or parts.hostname not in {
            "music.apple.com",
            "classical.music.apple.com",
            "beta.music.apple.com",
        }:
            raise BackendError("invalid_url", "An Apple Music HTTPS URL is required.")
    selected = request.get("track_ids")
    if selected is not None and (
        not isinstance(selected, list)
        or not all(isinstance(x, str) and x for x in selected)
    ):
        raise BackendError("invalid_request", "track_ids must be a list of track IDs.")
    if request["operation"] == "download" and selected == []:
        raise BackendError("no_tracks", "No tracks selected.")
    return {**request, "settings": settings, "wrapper": wrapper, "quality": quality}


class Events:
    def __init__(self, request, output=None):
        self.request = request
        self.output = output or sys.stdout
        self.done = False
        self.lock = threading.Lock()
        self.track_number = 0
        self.progress = ProgressRouter(request)
        self.tagger = SharedTagger(request)

    def tag_file(self, payload):
        self.emit("progress", data={"type": "track_progress", "phase": "tagging", "phase_percent": None})
        try:
            result = self.tagger.tag(payload)
        except TaggingError as exc:
            raise BackendError("tagging_failed", str(exc)) from exc
        self.emit("progress", data={"type": "track_progress", "phase": "tagging", "phase_percent": 100})
        self.emit("artifact", data=result)
        return result

    def emit(self, event, **data):
        with self.lock:
            if self.done:
                return
            if event == "progress":
                progress = self.progress.normalize(data.get("data", {}))
                if progress is None:
                    return
                data["data"] = progress
            self.done = event == "complete"
            record = {
                "version": 1,
                "request_id": self.request.get("request_id"),
                "wrapper": self.request.get("wrapper", DEFAULTS["wrapper"]),
                "event": event,
                **data,
            }
            print(json.dumps(record, ensure_ascii=False), file=self.output, flush=True)


def binary(engine, name):
    suffix = ".exe" if sys.platform == "win32" else ""
    candidates = [PROVIDERS / engine / "bin" / (name + suffix)]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise BackendError("missing_dependency", f"Build the {engine} backend first.")


def tcp_check(host, port):
    try:
        with socket.create_connection((host.strip("[]"), int(port)), timeout=3):
            pass
    except (OSError, ValueError) as exc:
        raise BackendError(
            "wrapper_unavailable", f"Cannot connect to {host}:{port}.", True
        ) from exc


def request_failure_reason(exc):
    if isinstance(exc, requests.Timeout):
        return "timed out"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code} {exc.response.reason}".strip()
    match = re.search(r"\[(?:WinError|Errno|SSL)[^\]]*\][^'\")]*", str(exc))
    return match[0].strip().rstrip(".") if match else type(exc).__name__


def http_json(url, path, headers=None):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise BackendError(
            "invalid_endpoint", "Wrapper endpoint must be an HTTP(S) URL."
        )
    try:
        options = {"timeout": (3, 10)}
        if headers:
            options.update(headers=headers, allow_redirects=False)
        response = requests.get(url.rstrip("/") + path, **options)
        if headers and 300 <= response.status_code < 400:
            raise BackendError(
                "invalid_endpoint", "Authenticated wrapper requests must not redirect."
            )
        if response.status_code in (401, 403):
            raise BackendError(
                "authentication_required",
                "Check the wrapper API key or authenticate the wrapper externally.",
            )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        host = parts.netloc.rpartition("@")[2]
        target = f"{parts.scheme}://{host}{parts.path.rstrip('/')}{path}"
        raise BackendError(
            "wrapper_unavailable",
            f"The wrapper HTTP endpoint is unavailable ({target}: {request_failure_reason(exc)}).",
            True,
        ) from exc
    except ValueError as exc:
        raise BackendError(
            "invalid_response", "The wrapper returned invalid JSON."
        ) from exc


def terminate_tree(process):
    if process.poll() is not None:
        return
    import psutil

    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        parent.terminate()
        _, alive = psutil.wait_procs(children + [parent], timeout=2)
        for item in alive:
            try:
                item.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass


def run_process(command, cwd, callback, payload=None, env=None):
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if payload is not None:
        process.stdin.write(json.dumps(payload))
        process.stdin.close()
    lines = queue.Queue()

    def drain(stream, is_error):
        for line in stream:
            lines.put((line.rstrip(), is_error))
        stream.close()
        lines.put(None)

    for stream, is_error in ((process.stdout, False), (process.stderr, True)):
        threading.Thread(target=drain, args=(stream, is_error), daemon=True).start()
    ended = 0
    try:
        while ended < 2:
            item = lines.get()
            if item is None:
                ended += 1
            else:
                callback(*item)
        return process.wait()
    finally:
        terminate_tree(process)


def normalize_tracks(parent, tracks):
    return {
        "albumData": parent,
        "tracks": [
            t
            if "trackData" in t
            else {"trackData": t, "availableQualities": [], "availableCodecs": []}
            for t in tracks
        ],
    }
