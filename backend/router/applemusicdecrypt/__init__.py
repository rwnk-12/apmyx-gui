import asyncio
from pathlib import Path
import sys

from ..common import BackendError, PROVIDERS, RUNTIME, http_json
from .config import parse_endpoint, storefront_for, wrapper_headers


def load_paths():
    runtime = RUNTIME
    source = PROVIDERS / "applemusicdecrypt"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    if source.is_dir() and str(source) not in sys.path:
        sys.path.append(str(source))


def check_native():
    load_paths()
    try:
        import temari

        path = Path(temari.default_library_path())
        if not path.is_file():
            raise BackendError(
                "missing_dependency",
                "The Wrapper Lite downloader's Temari library is missing. Rebuild the backend runtime.",
            )
        temari.load(str(path))
    except (ImportError, OSError, RuntimeError) as exc:
        if isinstance(exc, BackendError):
            raise
        raise BackendError(
            "missing_dependency",
            "The Wrapper Lite downloader's Temari library could not be loaded. Rebuild the backend runtime.",
        ) from exc


class Adapter:
    def status(self, settings):
        parse_endpoint(settings)
        headers = wrapper_headers(settings)
        check_native()
        status = http_json(settings["applemusicdecrypt-url"], "/status", headers=headers)
        if not isinstance(status, dict) or "code" not in status:
            raise BackendError(
                "invalid_response", "Wrapper-lite returned a malformed status envelope."
            )
        if status.get("code") != 0:
            message = status.get("msg", "Wrapper-lite is not ready.")
            code = (
                "authentication_required"
                if any(
                    value in message.lower() for value in ("account", "auth", "login")
                )
                else "wrapper_unavailable"
            )
            raise BackendError(code, message, code == "wrapper_unavailable")
        data = status.get("data", {})
        if not isinstance(data, dict) or not isinstance(data.get("regions", []), list):
            raise BackendError(
                "invalid_response", "Wrapper-lite returned malformed account status."
            )
        regions = data.get("regions", [])
        if not all(isinstance(region, str) for region in regions):
            raise BackendError(
                "invalid_response", "Wrapper-lite returned malformed account regions."
            )
        if any(len(region) != 2 or not region.isascii() or not region.isalpha() for region in regions):
            raise BackendError("invalid_response", "Wrapper-lite returned invalid storefront codes.")
        regions = sorted({region.lower() for region in regions})
        if not regions:
            raise BackendError(
                "authentication_required",
                "Sign in to Wrapper Lite before downloading.",
            )
        return {
            "online": True,
            "regions": regions,
            "engine": "AppleMusicDecrypt",
            "revision": "0301e8e4123cf3d7f8477ecfb3ec26ce05871574",
        }

    def run(self, request, events):
        status = self.status(request["settings"])
        if request["operation"] == "status":
            return status
        storefront_for(request, status["regions"])
        from .engine import execute

        return asyncio.run(execute(request, events))
