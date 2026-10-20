from ..common import BackendError


class Observer:
    def __init__(self, events):
        self.events = events
        self.reset()

    def reset(self):
        self.task = None
        self.skipped = False
        self.bytes = 0
        self.segments = 0
        self.total_segments = 0
        self.stream = None

    def __call__(self, task=None, **data):
        if task is not None:
            self.task = task
            status = str(task.status)
            if status == "ALREADY_EXIST":
                self.skipped = True
                return
            phase = {
                "PARSING": "preparing",
                "DOWNLOADING": "processing",
                "DECRYPTING": "decrypting",
                "SAVING": "remuxing",
            }.get(status)
            if not phase:
                return
            info = task.m3u8Info
            if info and info.codec_id != self.stream:
                self.stream = info.codec_id
                self.events.emit(
                    "progress",
                    data={"type": "trackstream", "streamgroup": info.codec_id},
                )
            percent = (
                task.progress * 100
                if phase == "processing" and task.progress is not None
                else None
            )
            record = {
                "phase": phase,
                "phase_percent": percent,
                "downloaded_bytes": task.downloaded_bytes,
                "total_bytes": task.total_bytes,
            }
        else:
            if data.get("phase") == "skipped":
                self.skipped = True
                return
            self.bytes += data.get("downloaded_bytes", 0)
            self.segments += data.get("segments", 0)
            self.total_segments = data.get("total_segments", self.total_segments)
            record = {
                "phase": data.get("phase", "processing"),
                "phase_percent": self.segments / self.total_segments * 100
                if self.total_segments and self.segments
                else None,
                "downloaded_bytes": self.bytes,
            }
        self.events.emit("progress", data={"type": "track_progress", **record})

    def failure(self):
        if self.task is not None and (
            str(self.task.status) == "FAILED" or self.task.error
        ):
            if isinstance(self.task.error, BackendError):
                return self.task.error
            return self.task.error or RuntimeError(
                "Wrapper Lite did not finish this track."
            )
        return None
