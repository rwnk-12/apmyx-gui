from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import psutil

from . import wrapper_lite

LABELS = {"applemusicdecrypt": "Wrapper Lite", "wrapper-v2": "Wrapper v2", "legacy": "Legacy wrapper"}
CONTAINERS = {"applemusicdecrypt": "apmyx-wrapper-lite", "wrapper-v2": "apmyx-wrapper-v2", "legacy": "apmyx-legacy"}
DOCKER_PATHS = [
    Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Docker/Docker/resources/bin/docker.exe",
    Path(os.environ.get("LOCALAPPDATA", "~")).expanduser() / "Programs/DockerDesktop/resources/bin/docker.exe",
    Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
    Path("/usr/local/bin/docker"),
]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
started = {}
pending = {}


@dataclass
class State:
    wrapper: str
    port: int = None
    running: str = None
    detail: str = ""
    start_plan: tuple = None
    stop_plan: tuple = None
    message: str = ""

    @property
    def label(self):
        return LABELS.get(self.wrapper, "Wrapper")

    @property
    def local(self):
        return self.port is not None


def endpoint(wrapper, settings):
    if wrapper == "applemusicdecrypt":
        return wrapper_lite.local_port(str(settings.get("applemusicdecrypt-url") or ""))
    if wrapper == "wrapper-v2":
        return wrapper_lite.local_port(str(settings.get("wrapper-v2-url") or ""))
    if wrapper == "legacy":
        host, _, port = str(settings.get("decrypt-m3u8-port") or "").rpartition(":")
        if host in wrapper_lite.LOCAL_HOSTS and port.isdigit():
            return int(port)
    return None


def port_open(port, timeout=0.3):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def docker_cli():
    found = shutil.which("docker.exe" if sys.platform == "win32" else "docker")
    if found:
        return found
    return next((str(path) for path in DOCKER_PATHS if path.is_file()), None)


def docker(*args, timeout=30):
    cli = docker_cli()
    if not cli:
        return None, ""
    try:
        result = subprocess.run([cli, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return result.returncode, (result.stdout or result.stderr).strip()


def timestamp(value):
    try:
        moment = datetime.fromisoformat(value[:26].rstrip("Z")).replace(tzinfo=timezone.utc)
        return moment.timestamp() if moment.year > 1970 else 0.0
    except (TypeError, ValueError, OverflowError, OSError):
        return 0.0


def containers(wrapper, port):
    code, names = docker("ps", "-a", "--format", "{{.Names}}")
    if code != 0:
        return None
    names = names.split()
    if not names:
        return []
    code, details = docker("inspect", "--format",
                           "{{.Name}}|{{.State.Running}}|{{json .HostConfig.PortBindings}}|{{.State.StartedAt}}|{{.State.FinishedAt}}",
                           *names)
    if code != 0:
        return []
    found = []
    for line in details.splitlines():
        name, running, bindings, started_at, finished_at = (line.split("|", 4) + [""] * 5)[:5]
        name = name.lstrip("/")
        try:
            ports = {int(item["HostPort"]) for values in (json.loads(bindings) or {}).values() for item in values or [] if item.get("HostPort")}
        except (ValueError, TypeError, AttributeError):
            ports = set()
        if port in ports or name == CONTAINERS.get(wrapper):
            found.append((name, running == "true", max(timestamp(started_at), timestamp(finished_at))))
    return found


def qemu_processes(port):
    own_pid = None
    if wrapper_lite.running():
        try:
            own_pid = int(json.loads((wrapper_lite.runtime_dir() / "process.json").read_text(encoding="utf-8-sig"))["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        name = (process.info.get("name") or "").lower()
        arguments = process.info.get("cmdline") or []
        if not name.startswith("qemu-system") or not any(f"hostfwd=tcp:127.0.0.1:{port}-" in item for item in arguments):
            continue
        monitor = None
        if "-qmp" in arguments:
            value = arguments[arguments.index("-qmp") + 1] if arguments.index("-qmp") + 1 < len(arguments) else ""
            if value.startswith("tcp:"):
                monitor = int(value.split(":")[2].split(",")[0])
        found.append((process.pid, monitor, process.pid == own_pid))
    return found


def launcher_last_used():
    runtime = wrapper_lite.runtime_dir()
    stamps = [path.stat().st_mtime for path in (runtime / "service-output.log", runtime / "installed.json") if path.is_file()]
    return max(stamps, default=0.0)


def detect(wrapper, settings):
    state = State(wrapper, endpoint(wrapper, settings))
    if not state.local:
        return state
    port = state.port
    docker_found = containers(wrapper, port)
    running_containers = [item for item in docker_found or [] if item[1]]
    qemu = qemu_processes(port) if wrapper == "applemusicdecrypt" else []
    if running_containers:
        name = running_containers[0][0]
        state.running, state.detail, state.stop_plan = "docker", f"Docker container {name}", ("docker", name)
    elif qemu:
        pid, monitor, own = qemu[0]
        if own:
            state.running, state.detail, state.stop_plan = "qemu", "QEMU", ("launcher",)
        else:
            state.running, state.detail = "qemu", "QEMU, started outside this apmyx folder"
            state.stop_plan = ("qmp", pid, monitor)
    elif port_open(port):
        state.running, state.detail = "other", "started outside apmyx"
    if state.running:
        state.message = f"{state.label} is running ({state.detail})."
        if not state.stop_plan:
            state.message += " apmyx can't tell what started it, so stop it where you started it."
        return state
    options = []
    if wrapper == "applemusicdecrypt" and wrapper_lite.installed():
        options.append((launcher_last_used(), ("launcher",), "QEMU"))
    for name, _, last_used in docker_found or []:
        options.append((last_used, ("docker", name), f"Docker container {name}"))
    if options:
        _, state.start_plan, target = max(options, key=lambda option: option[0])
        state.message = f"{state.label} is stopped. Start uses {target}."
        return state
    if wrapper == "applemusicdecrypt":
        script = "setup-wrapper-lite-qemu.cmd" if sys.platform == "win32" else "./setup-wrapper-lite-qemu.sh"
        state.message = f"{state.label} isn't set up yet. Run {script} once to install it and sign in."
    else:
        state.message = f"No {state.label} install was found. Start it the way you set it up, then press Check connection."
    if docker_found is None and docker_cli():
        state.message += " Docker Desktop isn't running, so Docker wrappers can't be found."
    return state


def answering(wrapper, port):
    if wrapper == "legacy":
        return port_open(port)
    path = "/status" if wrapper == "applemusicdecrypt" else "/"
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3).close()
        return True
    except urllib.error.HTTPError:
        return True
    except (OSError, http.client.HTTPException):
        return False


def wait_until_answering(wrapper, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if answering(wrapper, port):
            return True
        time.sleep(1)
    return False


def qmp_shutdown(monitor):
    with socket.create_connection(("127.0.0.1", monitor), timeout=10) as connection:
        stream = connection.makefile("rw", encoding="utf-8")
        stream.readline()
        for request in ({"execute": "qmp_capabilities"},
                        {"execute": "human-monitor-command", "arguments": {"command-line": "sendkey ctrl-alt-delete"}}):
            stream.write(json.dumps(request) + "\n")
            stream.flush()
            stream.readline()


def start(state):
    if state.running:
        return None, f"{state.label} is already running ({state.detail})."
    plan = state.start_plan
    if not plan:
        return None, state.message
    pending[state.wrapper] = (plan, state.port)
    try:
        if plan[0] == "launcher":
            succeeded, message = wrapper_lite.start(state.port)
        else:
            code, output = docker("start", plan[1], timeout=120)
            succeeded = code == 0 and wait_until_answering(state.wrapper, state.port, 120)
            message = (f"{state.label} is running (Docker container {plan[1]})." if succeeded
                       else f"Could not start Docker container {plan[1]}. {output or 'Is Docker Desktop running?'}")
    finally:
        pending.pop(state.wrapper, None)
    if succeeded:
        started[state.wrapper] = (plan, state.port)
    return succeeded, message


def stop(state):
    if not state.running:
        return None, f"{state.label} is already stopped."
    plan = state.stop_plan
    if not plan:
        return None, state.message
    if plan[0] == "launcher":
        succeeded, message = wrapper_lite.stop(state.port)
    elif plan[0] == "docker":
        code, output = docker("stop", plan[1], timeout=120)
        succeeded = code == 0
        message = f"{state.label} stopped (Docker container {plan[1]})." if succeeded else f"Could not stop Docker container {plan[1]}. {output}"
    else:
        _, pid, monitor = plan
        try:
            if monitor:
                qmp_shutdown(monitor)
            process = psutil.Process(pid)
            process.wait(90)
            succeeded, message = True, f"{state.label} stopped (QEMU). Its login is saved."
        except psutil.TimeoutExpired:
            psutil.Process(pid).terminate()
            succeeded, message = True, f"{state.label} did not shut down in time, so it was closed."
        except psutil.NoSuchProcess:
            succeeded, message = True, f"{state.label} stopped (QEMU). Its login is saved."
        except OSError as exc:
            succeeded, message = False, f"Could not stop {state.label}: {exc}"
    if succeeded:
        started.pop(state.wrapper, None)
    return succeeded, message


def detached(arguments, cwd=None):
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if sys.platform == "win32" else 0
    subprocess.Popen(arguments, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=flags, start_new_session=sys.platform != "win32")


def stop_started():
    stopped = []
    for wrapper, (plan, port) in list({**started, **pending}.items()):
        if plan[0] == "launcher":
            detached(wrapper_lite.command("stop", port), cwd=wrapper_lite.app_root())
            wrapper_lite.started_by_app = False
            stopped.append(wrapper)
        elif plan[0] == "docker" and docker_cli():
            detached([docker_cli(), "stop", plan[1]])
            stopped.append(wrapper)
        started.pop(wrapper, None)
        pending.pop(wrapper, None)
    return stopped
