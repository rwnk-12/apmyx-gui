import hashlib
import json
import logging
import time

from ..config import load_config
from ..resources import app_dir
from ..workers import Worker

SNOOZE = 24 * 60 * 60
CACHE_KEYS = ("release", "checked_at")


def parse_version(value):
    text = str(value or "").strip().lstrip("vV")
    core, _, prerelease = text.partition("-")
    parts = core.split(".")
    if not core or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    numbers += [0] * (3 - len(numbers))
    return tuple(numbers), prerelease


def is_newer(latest, current):
    latest, current = parse_version(latest), parse_version(current)
    if latest is None or current is None:
        return False
    if latest[0] != current[0]:
        return latest[0] > current[0]
    return bool(current[1]) and not latest[1]


def pick_asset(assets):
    usable = [asset for asset in assets or [] if asset.get("browser_download_url")]
    ranked = sorted(
        usable,
        key=lambda asset: (
            asset["name"].lower().endswith(".exe") and "setup" in asset["name"].lower(),
            asset["name"].lower().endswith(".zip") and "win" in asset["name"].lower(),
            asset["name"].lower().endswith(".zip"),
        ),
        reverse=True,
    )
    for asset in ranked:
        name = asset["name"].lower()
        if name.endswith((".zip", ".exe")):
            digest = str(asset.get("digest") or "")
            return {
                "name": asset["name"],
                "url": asset["browser_download_url"],
                "size": int(asset.get("size") or 0),
                "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
            }
    return None


def release_info(data):
    return {
        "version": str(data.get("tag_name") or "").lstrip("vV"),
        "url": data.get("html_url") or "",
        "notes": data.get("body") or "",
        "asset": pick_asset(data.get("assets")),
    }


def state_path():
    return app_dir() / "update-state.json"


def load_state():
    try:
        state = json.loads(state_path().read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state):
    try:
        state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        logging.warning(f"Could not save update state: {exc}")


def save_state(**changes):
    write_state({**load_state(), **changes})


def clear_cached_release():
    state = load_state()
    if any(key in state for key in CACHE_KEYS):
        write_state({key: value for key, value in state.items() if key not in CACHE_KEYS})


def skip_version(version):
    save_state(skipped=version)


def snooze():
    save_state(snoozed_until=time.time() + SNOOZE)


def download(session, asset, folder, progress=lambda done, total: None):
    target = folder / asset["name"]
    partial = target.with_name(target.name + ".partial")
    digest = hashlib.sha256()
    done = 0
    try:
        with session.get(asset["url"], stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or asset.get("size") or 0)
            with open(partial, "wb") as handle:
                for block in response.iter_content(1 << 16):
                    handle.write(block)
                    digest.update(block)
                    done += len(block)
                    progress(done, total)
        if asset.get("sha256") and digest.hexdigest() != asset["sha256"].lower():
            raise ValueError("The download did not match its published SHA-256 and was deleted.")
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


class UpdatesMixin:
    def checkforupdates(self):
        worker = Worker(self._check_for_updates_worker)
        self.thread_pool.start(worker)

    def _latest_release(self):
        clear_cached_release()
        api_url = f"https://api.github.com/repos/{self.REPO_OWNER}/{self.REPO_NAME}/releases/latest"
        response = self.session.get(api_url, timeout=10)
        if response.status_code != 200:
            logging.warning(f"GitHub API failed for update check: {response.status_code}")
            return None
        return release_info(response.json())

    def _check_for_updates_worker(self):
        try:
            if not load_config().get("check-updates", True):
                return
            release = self._latest_release()
            if not release or not is_newer(release["version"], self.VERSION):
                return
            state = load_state()
            if state.get("skipped") == release["version"] or time.time() < float(state.get("snoozed_until") or 0):
                return
            self.update_available.emit(release)
        except Exception as e:
            logging.warning(f"Update check error: {e}")

    def is_newer_version(self, latest, current):
        return is_newer(latest, current)
