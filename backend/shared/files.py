import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from .folders import save_folders


def prefix(request):
    key = hashlib.sha256(
        str(request.get("request_id", "")).encode("utf-8")
    ).hexdigest()[:16]
    return ".apmyx-" + key + "-"


def manifest(request, scratch):
    return Path(request.get("work_dir") or scratch) / "publish-cleanup.jsonl"


def publish_file(source, destination, request):
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(
            "The output file was created by another job before publication."
        )
    temporary = destination.with_name(prefix(request) + uuid.uuid4().hex + ".part")
    ledger = manifest(request, request["scratch"])
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(str(temporary)) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, destination)
        source.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_publications(request, scratch):
    ledger = manifest(request, scratch)
    if not ledger.is_file():
        return
    settings = request.get("settings", {})
    roots = save_folders(settings)
    for line in ledger.read_text(encoding="utf-8").splitlines():
        try:
            path = Path(json.loads(line)).resolve()
            if (
                path.name.startswith(prefix(request))
                and path.suffix == ".part"
                and any(path.is_relative_to(root) for root in roots)
            ):
                path.unlink(missing_ok=True)
        except (ValueError, TypeError, OSError):
            continue
    ledger.unlink(missing_ok=True)
