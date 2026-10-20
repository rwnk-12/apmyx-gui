from contextlib import contextmanager
import hashlib
from pathlib import Path

from creart import it as native_it


_bound = {}


def it(target, **kwargs):
    return _bound[target] if target in _bound else native_it(target, **kwargs)


def value(name, default=None):
    return _bound.get(name, default)


def is_bridge_error(error):
    return bool(value("scratch")) and getattr(error, "code", None) in {
        "authentication_required",
        "wrapper_unavailable",
    }


@contextmanager
def bind(instances):
    previous = dict(_bound)
    _bound.update(instances)
    try:
        yield _bound
    finally:
        _bound.clear()
        _bound.update(previous)


def notify(task=None, **data):
    callback = _bound.get("progress")
    if callback:
        callback(task, **data)


def publish(path, metadata=None):
    callback = _bound.get("publish")
    if callback:
        callback(Path(path), metadata)
        return True
    return False


def paths(destination):
    destination = Path(destination)
    scratch = _bound.get("scratch")
    if scratch:
        key = hashlib.sha256(str(destination.resolve()).encode("utf-8")).hexdigest()
        final = Path(scratch) / (key + destination.suffix)
        _bound["destinations"][final] = destination
        return final, final.with_suffix(".part")
    return destination, destination.with_suffix(".part")
