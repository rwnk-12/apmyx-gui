import json
import os
from pathlib import Path
import re

import yaml

from .common import BackendError, binary, run_process, save_folder, tcp_check


class Adapter:
    def status(self, settings):
        host, port = settings["decrypt-m3u8-port"].rsplit(":", 1)
        tcp_check(host, port)
        if settings.get("get-m3u8-from-device", True):
            host, port = settings["get-m3u8-port"].rsplit(":", 1)
            tcp_check(host, port)
        return {"online": True, "authentication": "unverified"}

    def run(self, request, events):
        settings = request["settings"]
        if request["operation"] == "status":
            return self.status(settings)
        executable = binary("legacy", "downloader")
        is_video = "/music-video/" in request.get("url", "")
        is_aac_lc = request.get("quality", "ALAC").upper() == "AAC" and settings.get(
            "aac-type", "aac-lc"
        ).lower() in {"aac", "aac-lc"}
        if request["operation"] == "download" and not (is_video or is_aac_lc):
            self.status(settings)
        scratch = Path(request["scratch"])
        config = dict(settings)
        for key in (
            "alac-save-folder",
            "aac-save-folder",
            "atmos-save-folder",
            "mv-save-folder",
        ):
            config[key] = str(save_folder(config, key))
        if "/playlist/" in request.get("url", "") and config.get("playlist-song-file-format"):
            config["song-file-format"] = config["playlist-song-file-format"]
        (scratch / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        command = [executable]
        operation = request["operation"]
        if operation == "probe":
            command += ["--json-output"]
        else:
            command += ["--codec-preference", request.get("quality", "ALAC")]
            if "/music-video/" in request["url"]:
                command += ["--music-video"]
            if "/song/" in request["url"] or "?i=" in request["url"]:
                command += ["--song"]
        command.append(request["url"])
        env = {
            **os.environ,
            "APMYX_BRIDGE": "1",
            "APMYX_SHARED_TAGGING": "1",
            "APMYX_TRACK_IDS": ",".join(request.get("track_ids") or []),
        }
        metadata, summary, buffer = None, None, []
        capture = False
        saw_progress = False

        def consume(line, is_error):
            nonlocal capture, metadata, summary, saw_progress
            if line == "AMDL_JSON_START":
                capture = True
            elif line == "AMDL_JSON_END":
                capture = False
                metadata = json.loads("\n".join(buffer))
            elif capture:
                buffer.append(line)
            elif line.startswith("AMDL_SUMMARY::"):
                summary = json.loads(line.split("::", 1)[1])
            elif line.startswith("AMDL_ARTIFACT::"):
                events.tag_file(json.loads(line.split("::", 1)[1]))
            elif line.startswith("AMDL_PROGRESS::"):
                saw_progress = True
                events.emit("progress", data=json.loads(line.split("::", 1)[1]))
            elif operation == "download" and re.search(
                r"(connection refused|actively refused|no connection could be made|i/o timeout|connection reset)",
                line,
                re.I,
            ):
                raise BackendError(
                    "wrapper_unavailable", "Legacy wrapper connection failed.", True
                )
            elif line:
                events.emit("log", message=line, level="error" if is_error else "info")

        code = run_process(command, scratch, consume, env=env)
        if code:
            raise BackendError(
                "backend_failed", f"Legacy downloader exited with code {code}."
            )
        if operation == "probe":
            if metadata is None:
                raise BackendError(
                    "invalid_response", "Legacy downloader did not return metadata."
                )
            events.emit("metadata", data=metadata)
            return metadata
        if summary is None or summary.get("Error", 0) or not saw_progress:
            raise BackendError(
                "download_failed", "Legacy download did not complete successfully."
            )
        return summary
