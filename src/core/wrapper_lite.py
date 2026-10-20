import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .resources import app_dir

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
started_by_app = False


def app_root() -> Path:
    return app_dir()


def runtime_dir() -> Path:
    return app_root() / "backend" / "wrapper-runtime" / "wrapper-lite-qemu"


def local_port(url: str):
    try:
        parts = urlsplit(url or "")
        if parts.scheme != "http" or parts.hostname not in LOCAL_HOSTS:
            return None
        return parts.port or 80
    except ValueError:
        return None


def installed() -> bool:
    launcher = "setup-qemu.ps1" if sys.platform == "win32" else "setup_qemu.py"
    return (runtime_dir() / "installed.json").is_file() and (app_root() / "scripts" / "wrappers" / launcher).is_file()


def running() -> bool:
    state = runtime_dir() / "process.json"
    if not state.is_file():
        return False
    try:
        pid = int(json.loads(state.read_text(encoding="utf-8-sig"))["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    import psutil

    return psutil.pid_exists(pid)


def command(action: str, port: int) -> list:
    root = app_root()
    if sys.platform == "win32":
        return ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
                str(root / "scripts" / "wrappers" / "setup-qemu.ps1"), "-Action", action.capitalize(),
                "-HttpPort", str(port)]
    return ["sh", str(root / "setup-wrapper-lite-qemu.sh"), "--action", action, "--http-port", str(port)]


def run(action: str, port: int, timeout: int = 300):
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with tempfile.TemporaryFile() as output:
        try:
            result = subprocess.run(command(action, port), cwd=app_root(), stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=timeout, creationflags=flags)
        except subprocess.TimeoutExpired:
            return False, f"Wrapper Lite did not {action} in time."
        except OSError as exc:
            return False, str(exc)
        output.seek(0)
        text = output.read().decode("utf-8", errors="replace")
    lines = [re.sub(r"^\[\d\d:\d\d:\d\d\]\s*", "", line.strip()).replace(" You can close this window.", "")
             for line in text.splitlines() if line.strip()]
    failure = next((line for line in reversed(lines) if line.startswith("Setup failed:")), None)
    if result.returncode != 0:
        return False, (failure or (lines[-1] if lines else f"Wrapper Lite {action} failed.")).removeprefix("Setup failed: ")
    return True, next((line for line in reversed(lines) if "Wrapper Lite QEMU" in line), f"Wrapper Lite {action} finished.")


def start(port: int):
    global started_by_app
    was_running = running()
    succeeded, message = run("start", port)
    if succeeded and not was_running:
        started_by_app = True
    return succeeded, message


def stop(port: int):
    global started_by_app
    succeeded, message = run("stop", port)
    if succeeded:
        started_by_app = False
    return succeeded, message


def stop_if_started(port: int):
    if not started_by_app:
        return False
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if sys.platform == "win32" else 0
    subprocess.Popen(command("stop", port), cwd=app_root(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=sys.platform != "win32")
    return True
