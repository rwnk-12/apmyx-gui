import contextlib
import json
import sys
import tempfile

if __package__:
    from .router.common import BackendError, Events, classify_error, validate_request
else:
    from router.common import BackendError, Events, classify_error, validate_request


def adapter_for(wrapper):
    prefix = "backend.router" if __package__ else "router"
    import importlib

    module = {
        "applemusicdecrypt": "applemusicdecrypt",
        "legacy": "legacy",
        "wrapper-v2": "gamdl",
    }.get(wrapper)
    if module is None:
        raise BackendError("invalid_wrapper", "Unknown wrapper selection.")
    return importlib.import_module(f"{prefix}.{module}").Adapter()


def dispatch(request, output=None):
    events = Events(request if isinstance(request, dict) else {}, output)
    try:
        request = validate_request(request)
        events.request = request
        events.progress.request = request
        events.tagger.settings = request["settings"]
        adapter = adapter_for(request["wrapper"])
        with tempfile.TemporaryDirectory(
            prefix="apmyx-", dir=request.get("work_dir")
        ) as scratch:
            request["scratch"] = scratch
            events.tagger.request = request
            with contextlib.redirect_stdout(sys.stderr):
                result = adapter.run(request, events)
        if request["operation"] == "download" and isinstance(result, dict):
            counts = result.get("counts", result)
            if "completed" in result:
                expected = int(result["completed"] or 0)
            else:
                successful = counts.get("Success", counts.get("success", 0))
                expected = max(
                    0, int(successful or 0) - events.progress.skipped_existing
                )
            if len(events.tagger.completed) != expected:
                raise BackendError(
                    "invalid_response",
                    "Downloader did not hand every completed file to the shared tagger. Rebuild the backend.",
                )
            result["artifacts"] = list(events.tagger.completed.values())
        events.emit("complete", success=True, result=result)
        return 0
    except BackendError as exc:
        events.emit("error", code=exc.code, message=str(exc), retryable=exc.retryable)
    except (ImportError, ModuleNotFoundError) as exc:
        events.emit(
            "error",
            code="missing_dependency",
            message=f"Backend dependency unavailable: {exc.name}",
            retryable=False,
        )
    except Exception as exc:
        print(f"Backend error: {type(exc).__name__}: {exc}", file=sys.stderr)
        failure = classify_error(str(exc))
        events.emit(
            "error",
            code=failure.code,
            message=str(failure),
            retryable=failure.retryable,
        )
    events.emit("complete", success=False)
    return 1


def main():
    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(
                encoding="utf-8",
                errors="backslashreplace" if name == "stderr" else "strict",
            )
    try:
        request = json.load(sys.stdin)
    except ValueError:
        request = {}
    return dispatch(request)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
