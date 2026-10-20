import math
import time


PROGRESS_INTERVAL = 0.05
PHASES = {
    "preparing": (0, 0),
    "downloading": (0, 60),
    "processing": (0, 95),
    "decrypting": (60, 35),
    "remuxing": (95, 3),
    "tagging": (98, 1),
    "finalizing": (99, 0),
}


def format_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024


def gui_progress(data):
    kind = data.get("type")
    labels = {
        "preparing": "Preparing",
        "downloading": "Downloading",
        "processing": "Processing",
        "decrypting": "Decrypting",
        "remuxing": "Remuxing",
        "tagging": "Writing tags",
        "finalizing": "Finalizing",
        "complete": "Finished",
        "failed": "Failed",
    }
    phase = data.get("phase", "preparing")
    phase_percent = data.get("phase_percent")
    suffix = (
        f" ({phase_percent:.0f}%)"
        if phase_percent is not None and kind == "track_progress"
        else ""
    )
    status = f"({data.get('track_num', 1)}/{data.get('total_tracks', 1)}) {labels.get(phase, 'Processing')}{suffix}: {data.get('name', '')}"
    downloaded, total = data.get("downloaded_bytes"), data.get("total_bytes")
    if downloaded and total:
        status += f" \u2022 {format_bytes(downloaded)} of {format_bytes(total)}"
    elif downloaded:
        status += f" \u2022 {format_bytes(downloaded)}"
    track_percent = (
        -1.0
        if data.get("indeterminate") and kind == "track_progress"
        else float(data.get("percent", 0))
    )
    return status, track_percent, float(data.get("overall_percent", 0))


def percentage(value):
    try:
        value = float(value)
        return min(100, max(0, value)) if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


class StreamProgress:
    def __init__(self, events):
        self.events = events
        self.reset()

    def reset(self, streams=1):
        self.streams = max(1, streams)
        self.completed_streams = 0
        self.completed_bytes = 0
        self.stream_bytes = 0
        self.percent = 0

    def start_stream(self):
        self.stream_bytes = 0
        self.report("downloading", 0)

    def finish_stream(self):
        self.report("downloading", 100)
        self.completed_streams += 1
        self.completed_bytes += self.stream_bytes

    def report(
        self, phase, percent, downloaded_bytes=None, total_bytes=None, **details
    ):
        phase_percent = percentage(percent)
        if phase == "downloading":
            if downloaded_bytes is not None:
                self.stream_bytes = int(downloaded_bytes)
            if phase_percent is not None:
                phase_percent = min(
                    100,
                    (self.completed_streams + phase_percent / 100) / self.streams * 100,
                )
            details["downloaded_bytes"] = self.completed_bytes + self.stream_bytes
            if total_bytes and self.completed_streams + 1 == self.streams:
                details["total_bytes"] = self.completed_bytes + total_bytes
        start, weight = PHASES[phase]
        self.percent = max(self.percent, start + weight * (phase_percent or 0) / 100)
        self.events.emit(
            "progress",
            data={
                "type": "track_progress",
                "phase": phase,
                "phase_percent": phase_percent,
                **details,
            },
        )


class ProgressRouter:
    def __init__(self, request, interval=PROGRESS_INTERVAL):
        self.request = request
        self.interval = interval
        self.index = 0
        self.total = (
            len(request.get("track_ids") or [])
            or len(request.get("media_data", {}).get("tracks", []))
            or 1
        )
        self.current = {}
        self.finished = False
        self.last_sent = 0
        self.last_phase = None
        self.skipped_existing = 0

    def normalize(self, data):
        data = dict(data)
        kind = data.get("type")
        if kind in {"probe_start", "probe_progress"}:
            return data
        if kind == "track_start":
            key = data.get("track_id") or (data.get("track_num"), data.get("name"))
            if self.current.get("_key") == key and not self.finished:
                return None
            self.index = (
                self.index + 1
                if self.request.get("track_ids")
                else int(data.get("track_num") or self.index + 1)
            )
            self.total = len(self.request.get("track_ids") or []) or int(
                data.get("total_tracks") or self.total
            )
            self.current = {
                "_key": key,
                "percent": 0,
                "phase": "preparing",
                "phase_percent": None,
                "name": data.get("name", ""),
                "track_id": data.get("track_id"),
            }
            self.finished = False
            self.last_phase = None
        elif self.finished and kind not in {"track_skip", "track_error"}:
            return None
        if kind in {"size", "bytes"}:
            for field in ("downloaded_bytes", "total_bytes"):
                if field in data:
                    self.current[field] = data[field]
            if kind == "size":
                return None
            data["type"] = kind = "track_progress"
        if kind == "track_progress":
            phase = data.get("phase", self.current.get("phase", "processing"))
            phase = phase if phase in PHASES else "processing"
            phase_percent = percentage(data.get("phase_percent"))
            if "phase_percent" not in data and data.get("phase") in PHASES:
                phase_percent = percentage(data.get("percent"))
            start, weight = PHASES[phase]
            value = start + weight * (phase_percent or 0) / 100
            streams = int(data.get("stream_count") or 1)
            stream = int(data.get("stream_index") or 1)
            if streams > 1 and phase in {"downloading", "decrypting", "processing"}:
                value = ((stream - 1) * 95 + value) / streams
            if not data.get("phase") and "percent" in data:
                value = percentage(data["percent"]) or 0
            data.update(
                phase=phase,
                phase_percent=phase_percent,
                percent=max(self.current.get("percent", 0), min(99, value)),
                indeterminate=phase_percent is None,
            )
        elif kind in {"track_complete", "track_skip", "track_error"}:
            if not self.index:
                self.index = 1
                self.total = int(data.get("total_tracks") or self.total)
            if self.finished:
                if data.get("track_num") == self.index:
                    return None
                self.index += 1
                self.current = {"percent": 0, "name": data.get("name", "")}
            if kind == "track_skip" and data.get("reason") == "Already exists":
                self.skipped_existing += 1
            self.finished = True
            data.update(
                phase="complete" if kind != "track_error" else "failed",
                phase_percent=100 if kind != "track_error" else None,
            )
            data["percent"] = (
                100 if kind != "track_error" else self.current.get("percent", 0)
            )
        elif kind == "trackstream":
            data["streamgroup"] = (
                data.get("streamgroup")
                or data.get("stream_group")
                or data.get("streamGroup", "")
            )
        self.current.update(data)
        record = {
            key: value for key, value in self.current.items() if not key.startswith("_")
        }
        record.update(
            schema_version=1,
            track_num=max(1, self.index),
            total_tracks=max(1, self.total),
        )
        record["overall_percent"] = (
            (max(1, self.index) - 1) * 100 + record.get("percent", 0)
        ) / max(1, self.total)
        record["state"] = (
            "failed"
            if kind == "track_error"
            else "skipped"
            if kind == "track_skip"
            else "complete"
            if kind == "track_complete"
            else "running"
        )
        now = time.monotonic()
        if (
            kind == "track_progress"
            and self.last_phase == record.get("phase")
            and record.get("phase_percent") != 100
            and now - self.last_sent < self.interval
        ):
            return None
        self.last_phase = record.get("phase")
        self.last_sent = now
        return record
