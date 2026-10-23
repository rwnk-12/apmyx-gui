import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

from .resources import resource_path

from backend.router.common import BackendError, snapshot, terminate_tree
from backend.shared.progress import PROGRESS_INTERVAL
from backend.shared.files import cleanup_publications


def command():
    if getattr(sys, "frozen", False):
        name = "bridge.exe" if sys.platform == "win32" else "bridge"
        path = Path(resource_path("backend/bin/bridge")) / name
        if not path.is_file():
            raise BackendError(
                "missing_dependency", "Bundled backend bridge is missing."
            )
        return [str(path)]
    return [sys.executable, resource_path("backend/bridge.py")]


def request_for(operation, url="", settings=None, **data):
    config = snapshot(settings or {})
    return {
        "version": 1,
        "request_id": uuid.uuid4().hex,
        "operation": operation,
        "wrapper": config["wrapper"],
        "settings": config,
        "url": url,
        **data,
    }


def start_process(request, scratch):
    process = subprocess.Popen(
        command(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
            "APMYX_PROGRESS_INTERVAL_MS": str(int(PROGRESS_INTERVAL * 1000)),
        },
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    process.stdin.write(json.dumps({**request, "work_dir": scratch}))
    process.stdin.close()
    process._apmyx_request = {**request, "work_dir": scratch}
    process._apmyx_scratch = scratch
    return process


def consume(process, callback, request_id=None):
    terminal = None
    failure = None

    def logs():
        for line in process.stderr:
            logging.debug("Backend worker: %s", line.rstrip())

    reader = threading.Thread(target=logs, daemon=True)
    reader.start()
    try:
        for line in process.stdout:
            try:
                event = json.loads(line)
            except ValueError as exc:
                raise BackendError(
                    "invalid_response", "Backend bridge returned malformed output."
                ) from exc
            if event.get("version") != 1 or (
                request_id and event.get("request_id") != request_id
            ):
                raise BackendError(
                    "invalid_response", "Backend bridge protocol mismatch."
                )
            if terminal is not None:
                raise BackendError(
                    "invalid_response", "Backend emitted events after completion."
                )
            if event["event"] == "error":
                failure = BackendError(
                    event.get("code", "backend_failed"),
                    event.get("message", "Backend failed."),
                    event.get("retryable", False),
                )
            if event["event"] == "complete":
                terminal = event
            callback(event)
        code = process.wait()
        reader.join(timeout=2)
        if failure:
            raise failure
        if code or terminal is None or not terminal.get("success"):
            raise BackendError(
                "backend_failed", "Backend exited without a successful completion."
            )
        return terminal.get("result")
    finally:
        terminate_tree(process)
        if isinstance(getattr(process, "_apmyx_request", None), dict):
            cleanup_publications(process._apmyx_request, process._apmyx_scratch)
        process.stdout.close()
        process.stderr.close()


def run_request(request, callback=lambda event: None):
    with tempfile.TemporaryDirectory(prefix="apmyx-job-") as scratch:
        return consume(start_process(request, scratch), callback, request["request_id"])
