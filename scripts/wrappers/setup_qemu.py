import argparse
import getpass
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPOSITORY = SCRIPTS.parents[1]
RUNTIME = REPOSITORY / "backend" / "wrapper-runtime" / "wrapper-lite-qemu"
REQUIRED = ("qemu/bin/qemu-system-x86_64", "qemu/bin/bios-256k.bin", "qemu/vmlinuz-lite-qemu",
            "qemu/lite-initramfs.cpio.gz", "qemu/data.img")


class SetupError(Exception):
    pass


def status(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def platform_key():
    system, machine = platform.system(), platform.machine().lower()
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "linux-x86_64"
    if system == "Linux" and machine in ("aarch64", "arm64"):
        return "linux-aarch64"
    if system == "Darwin" and machine == "arm64":
        return "macos-aarch64"
    if system == "Windows":
        raise SetupError("Use setup-wrapper-lite-qemu.cmd on Windows.")
    raise SetupError(f"No Wrapper Lite QEMU package exists for {system} {machine}. "
                     "Use a hosted wrapper or run one on another machine.")


def source():
    data = json.loads((SCRIPTS / "qemu" / "source.json").read_text(encoding="utf-8"))
    return data, data["platforms"][platform_key()]


def download(url, path, sha256, size):
    if path.is_file() and path.stat().st_size == size and hash_file(path) == sha256:
        return
    partial = path.with_name(path.name + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "apmyx-setup"})
    digest, received, next_report = hashlib.sha256(), 0, 0
    with urllib.request.urlopen(request, timeout=60) as response, open(partial, "wb") as output:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            output.write(block)
            digest.update(block)
            received += len(block)
            if received > size:
                raise SetupError("The QEMU package is larger than its pinned size.")
            if received >= next_report:
                status(f"Downloading Wrapper Lite QEMU package... {received * 100 // size}%")
                next_report += size // 10
    if received != size or digest.hexdigest() != sha256:
        partial.unlink(missing_ok=True)
        raise SetupError("The QEMU package failed verification and was deleted.")
    os.replace(partial, path)


def hash_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(archive, destination):
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            target = (destination / info.filename).resolve()
            if root != target and root not in target.parents:
                raise SetupError(f"Unsafe path in QEMU package: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SetupError(f"Symbolic link in QEMU package: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(info) as source_file, open(target, "wb") as output:
                shutil.copyfileobj(source_file, output)
            if mode & 0o111:
                target.chmod(0o755)


def cpio_entry(name, data, mode):
    fields = (1, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name) + 1, 0)
    header = b"070701" + "".join(f"{value:08x}" for value in fields).encode("ascii")
    entry = header + name.encode("ascii") + b"\0"
    entry += b"\0" * (-len(entry) % 4)
    entry += data + b"\0" * (-len(data) % 4)
    return entry


def build_initramfs(original, init_script, destination):
    script = init_script.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")
    archive = cpio_entry("init", script, 0o100755) + cpio_entry("TRAILER!!!", b"", 0)
    partial = destination.with_name(destination.name + ".partial")
    with open(partial, "wb") as output:
        with open(original, "rb") as source_file:
            shutil.copyfileobj(source_file, output)
        with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed:
            compressed.write(archive)
    os.replace(partial, destination)


def install(local_package=None):
    manifest, package = source()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    archive = RUNTIME / "package.zip"
    if local_package:
        status("Using an unpinned local QEMU package. Its contents are not verified against source.json.")
        shutil.copyfile(local_package, archive)
        package = {"sha256": hash_file(archive)}
    else:
        download(package["url"], archive, package["sha256"], package["size"])
    status("Extracting the verified QEMU package...")
    extract(archive, RUNTIME / "package")
    for name in REQUIRED:
        if not (RUNTIME / "package" / name).is_file():
            raise SetupError(f"The pinned QEMU package is missing {name}.")
    session = RUNTIME / "session"
    session.mkdir(exist_ok=True)
    session.chmod(0o700)
    disk = session / "data.img"
    if not disk.exists():
        shutil.copyfile(RUNTIME / "package" / "qemu" / "data.img", disk)
    disk.chmod(0o600)
    build_initramfs(RUNTIME / "package" / "qemu" / "lite-initramfs.cpio.gz", SCRIPTS / "qemu" / "init",
                    RUNTIME / "apmyx-initramfs.cpio.gz")
    (RUNTIME / "installed.json").write_text(json.dumps({
        "revision": manifest["revision"], "sha256": package["sha256"], "platform": platform_key(),
    }), encoding="utf-8")


def acceleration(requested):
    if requested != "auto":
        return requested
    if platform.system() == "Linux" and os.access("/dev/kvm", os.R_OK | os.W_OK):
        return "kvm"
    return "tcg"


def qemu_binary():
    if platform.system() != "Darwin":
        return RUNTIME / "package" / "qemu" / "bin" / "qemu-system-x86_64", True
    found = shutil.which("qemu-system-x86_64") or next(
        (path for path in ("/opt/homebrew/bin/qemu-system-x86_64", "/usr/local/bin/qemu-system-x86_64")
         if os.access(path, os.X_OK)), None)
    if not found:
        raise SetupError("QEMU is required on macOS. Install Homebrew (https://brew.sh), then run: brew install qemu")
    return Path(found), False


def qemu_environment():
    environment = dict(os.environ)
    if not qemu_binary()[1]:
        return environment
    assets = RUNTIME / "package" / "qemu"
    libraries = [str(assets / name) for name in ("lib", "bin")
                 if (assets / name).is_dir() and not (assets / name / "libc.so.6").exists()]
    if platform.system() == "Linux" and libraries:
        environment["LD_LIBRARY_PATH"] = ":".join(libraries + [environment.get("LD_LIBRARY_PATH", "")]).rstrip(":")
    if any((assets / "bin" / name).exists() for name in ("accel-tcg-x86_64.so", "accel-tcg-i386.so")):
        environment["QEMU_MODULE_DIR"] = str(assets / "bin")
    return environment


def qemu_arguments(http_port, monitor_port, accel, login=False, serial_port=None):
    assets = RUNTIME / "package" / "qemu"
    cmdline = "console=ttyS0 quiet net.ifnames=0 biosdevname=0 noapic"
    if login:
        cmdline += " apmyx_login=1"
    disk = str(RUNTIME / "session" / "data.img").replace(",", ",,")
    serial = "file:" + str(RUNTIME / "service-output.log")
    if login:
        serial = f"tcp:127.0.0.1:{serial_port},server=on,wait=on"
    binary, bundled = qemu_binary()
    firmware = ["-L", str(assets / "bin")] if bundled else []
    return [
        str(binary), *firmware,
        "-accel", accel, "-cpu", "host" if accel == "kvm" else "max", "-m", "512", "-smp", "2",
        "-kernel", str(assets / "vmlinuz-lite-qemu"), "-initrd", str(RUNTIME / "apmyx-initramfs.cpio.gz"),
        "-append", cmdline, "-display", "none", "-serial", serial, "-monitor", "none", "-no-reboot",
        "-nic", f"user,model=e1000,hostfwd=tcp:127.0.0.1:{http_port}-:12340",
        "-drive", f"file={disk},format=raw,if=virtio,cache=directsync",
        "-qmp", f"tcp:127.0.0.1:{monitor_port},server=on,wait=off",
    ]


def free_port(*taken):
    while True:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        if port not in taken:
            return port


def assert_port_available(port):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            raise SetupError(f"Port {port} is already in use. Stop the other wrapper or choose --http-port.") from None


def process_identity(pid):
    result = subprocess.run(["ps", "-o", "lstart=", "-o", "command=", "-p", str(pid)],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def running_process():
    state_path = RUNTIME / "process.json"
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    identity = process_identity(state["pid"])
    if not identity:
        return None
    if identity != state["identity"]:
        raise SetupError("Saved QEMU process identity does not match. No process was stopped.")
    return state


def start(http_port, accel, login=False):
    assert_port_available(http_port)
    monitor_port = free_port(http_port)
    serial_port = free_port(http_port, monitor_port)
    arguments = qemu_arguments(http_port, monitor_port, acceleration(accel), login, serial_port)
    prefix = "login" if login else "service"
    with open(RUNTIME / f"{prefix}-host.log", "wb") as out, open(RUNTIME / f"{prefix}-error.log", "wb") as err:
        process = subprocess.Popen(arguments, env=qemu_environment(), stdin=subprocess.DEVNULL,
                                   stdout=out, stderr=err, start_new_session=True)
    time.sleep(0.2)
    (RUNTIME / "process.json").write_text(json.dumps({
        "pid": process.pid, "identity": process_identity(process.pid),
        "http_port": http_port, "monitor_port": monitor_port,
    }), encoding="utf-8")
    process.serial_port = serial_port
    return process


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def monitor(port, command, arguments=None):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        stream = connection.makefile("rw", encoding="utf-8", newline="\n")
        if "QMP" not in json.loads(stream.readline()):
            raise SetupError("QEMU monitor returned an invalid greeting.")
        for request in ({"execute": "qmp_capabilities"}, {"execute": command, "arguments": arguments or {}}):
            stream.write(json.dumps(request) + "\n")
            stream.flush()
            while True:
                line = stream.readline()
                if not line:
                    raise SetupError("QEMU monitor disconnected.")
                response = json.loads(line)
                if "error" in response:
                    raise SetupError("QEMU monitor rejected the shutdown request.")
                if "return" in response:
                    break


def stop():
    state = running_process()
    if state:
        status("Shutting down the QEMU guest and saving its session...")
        try:
            monitor(state["monitor_port"], "human-monitor-command", {"command-line": "sendkey ctrl-alt-delete"})
        except (OSError, SetupError):
            if alive(state["pid"]):
                raise
        deadline = time.time() + 90
        while alive(state["pid"]) and time.time() < deadline:
            time.sleep(0.2)
        if alive(state["pid"]):
            raise SetupError("The guest did not shut down cleanly. QEMU was left running to preserve its session disk.")
    (RUNTIME / "process.json").unlink(missing_ok=True)


def wrapper_status(http_port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/status", timeout=3) as response:
            data = json.load(response)
        regions = data["data"]["regions"]
        if data.get("code") != 0 or not isinstance(regions, list) or not all(isinstance(r, str) and r for r in regions):
            raise ValueError
        return True, bool(regions)
    except Exception:
        return False, False


def wait_ready(http_port, timeout=300):
    deadline, next_update = time.time() + timeout, 0
    while time.time() < deadline:
        state = running_process()
        if not state:
            raise SetupError("QEMU exited during startup. Check service-error.log in the QEMU runtime folder.")
        ready, authenticated = wrapper_status(http_port)
        if ready:
            return authenticated
        if time.time() >= next_update:
            status("Waiting for the QEMU guest HTTP service...")
            next_update = time.time() + 10
        time.sleep(0.5)
    raise SetupError("QEMU did not become ready in time. Check its runtime logs or retry with --accel tcg.")


def login(http_port, accel):
    username = input("Apple ID email: ").strip()
    password = getpass.getpass("Apple ID password: ")
    if not username or re.search(r"[:\r\n]", username) or not password:
        raise SetupError("Enter a nonempty Apple ID and password.")
    if re.search(r"[\r\n]", password):
        raise SetupError("The wrapper cannot accept a password containing a newline.")
    process = start(http_port, accel, login=True)
    connection = None
    sent = complete = False
    try:
        deadline = time.time() + 15
        while connection is None:
            if process.poll() is not None:
                raise SetupError("QEMU exited before its login console became available.")
            try:
                connection = socket.create_connection(("127.0.0.1", process.serial_port), timeout=1)
            except OSError:
                if time.time() > deadline:
                    raise SetupError("QEMU login console did not become available.") from None
                time.sleep(0.1)
        connection.settimeout(None)
        reader = connection.makefile("r", encoding="utf-8", errors="replace", newline="\n")
        codes, deadline = 0, time.time() + 300
        status("Waiting for the QEMU login guest...")
        for line in reader:
            if time.time() > deadline:
                break
            if not sent and "[apmyx] credentials-ready" in line:
                connection.sendall(f"{username}\n{password}\n".encode("utf-8"))
                password, sent = None, True
                status("Signing in to Wrapper Lite...")
            if re.search(r"2FA:\s*true", line):
                codes += 1
                if codes > 3:
                    raise SetupError("Apple verification did not complete. Rerun with --action login.")
                status("Apple requested a verification code.")
                code = input("Apple verification code: ").strip()
                if not re.fullmatch(r"\d{6}", code):
                    raise SetupError("Enter the six-digit Apple verification code.")
                connection.sendall(f"{code}\n".encode("ascii"))
            if "[apmyx] login-complete" in line:
                complete = True
            if "[apmyx] login-failed" in line or "[apmyx] session-disk-failed" in line:
                raise SetupError("Apple sign-in failed. Check your credentials and account status, then rerun with --action login.")
        process.wait(timeout=30)
        if not (sent and complete and process.returncode == 0):
            raise SetupError("Apple sign-in failed or timed out. Rerun with --action login.")
    finally:
        password = None
        if connection is not None:
            connection.close()
        if process.poll() is None:
            stop()
        (RUNTIME / "process.json").unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Wrapper Lite QEMU launcher for macOS and Linux.")
    parser.add_argument("--action", choices=("setup", "install", "start", "stop", "login", "status"), default="setup")
    parser.add_argument("--http-port", type=int, default=12340)
    parser.add_argument("--accel", choices=("auto", "kvm", "tcg"), default="auto")
    parser.add_argument("--package", type=Path, help="install this locally built package zip instead of the pinned download")
    args = parser.parse_args()
    if not 1 <= args.http_port <= 65535:
        parser.error("--http-port must be between 1 and 65535")
    port_given = "--http-port" in sys.argv
    import fcntl

    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = open(RUNTIME / ".setup.lock", "w")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SetupError("Another Wrapper Lite QEMU setup command is running.") from None
        platform_key()
        if args.action != "stop":
            qemu_binary()
        state = running_process()
        http_port = state["http_port"] if state and not port_given else args.http_port
        if args.action == "stop":
            stop()
            status("Wrapper Lite QEMU stopped. Your login is saved.")
            return 0
        if args.action == "status":
            if not state:
                raise SetupError("Wrapper Lite QEMU is stopped. Use --action start.")
            ready, authenticated = wrapper_status(state["http_port"])
            if not (ready and authenticated):
                raise SetupError("Wrapper Lite QEMU is not authenticated and ready. Use --action login.")
            status(f"Wrapper Lite QEMU is ready at http://127.0.0.1:{state['http_port']}.")
            return 0
        if args.action == "install":
            install(args.package)
            status("Wrapper Lite QEMU package installed.")
            return 0
        if state and args.action != "login":
            if port_given and args.http_port != state["http_port"]:
                raise SetupError("QEMU is already running on another port. Use --action stop before changing ports.")
            authenticated = wait_ready(http_port)
        else:
            if state:
                stop()
            if args.action == "setup":
                install(args.package)
            if not (RUNTIME / "installed.json").is_file():
                raise SetupError("Run setup-wrapper-lite-qemu.sh without --action to install the package first.")
            if args.action == "login":
                login(http_port, args.accel)
            start(http_port, args.accel)
            authenticated = wait_ready(http_port)
        if not authenticated and args.action == "setup":
            stop()
            login(http_port, args.accel)
            start(http_port, args.accel)
            authenticated = wait_ready(http_port)
        if not authenticated and args.action != "start":
            raise SetupError("Wrapper Lite has no authenticated session. Use --action login.")
        status(f"Wrapper Lite QEMU is running at http://127.0.0.1:{http_port}.")
        if authenticated:
            print("Select Wrapper Lite in GUI Settings > Wrapper.")
        print("Use this launcher with --action start, stop, login, or status next time.")
        return 0
    except (SetupError, OSError, KeyboardInterrupt) as exc:
        print(f"Setup failed: {exc or 'interrupted'}", file=sys.stderr)
        return 1
    finally:
        lock.close()


if __name__ == "__main__":
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
