import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import platform
import re
import sys
import threading

from .resources import app_dir

SECRETS = [
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "<hidden-token>"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1<hidden>"),
    (re.compile(r"(?i)((?:media-user-token|authorization-token|api[-_]?key|password|pass)['\"]?\s*[:=]\s*['\"]?)[^\s'\",;}&]+"), r"\1<hidden>"),
    (re.compile(r"(?i)((?:media-user-token|authorization|x-api-key)['\"]?\s*:\s*['\"])[^'\"]+"), r"\1<hidden>"),
]


def log_dir():
    return app_dir() / "logs"


def log_path():
    return log_dir() / "apmyx.log"


def redact(text):
    for pattern, replacement in SECRETS:
        text = pattern.sub(replacement, text)
    home = str(Path.home())
    return text.replace(home, "~") if home and len(home) > 3 else text


def origin(traceback):
    while traceback and traceback.tb_next:
        traceback = traceback.tb_next
    if not traceback:
        return None
    code = traceback.tb_frame.f_code
    return f"{Path(code.co_filename).stem}.{code.co_name}:{traceback.tb_lineno}"


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        if not hasattr(record, "where"):
            record.where = f"{record.module}.{record.funcName}:{record.lineno}"
        return redact(super().format(record))


class SessionOrWarning(logging.Filter):
    def filter(self, record):
        if record.levelno >= logging.ERROR and not record.exc_info:
            current = sys.exc_info()
            if current[0] is not None and not issubclass(current[0], KeyboardInterrupt):
                record.exc_info = current
        return record.levelno >= logging.WARNING or getattr(record, "session", False)


def log_unhandled(exc_type, exc_value, exc_traceback, where="thread"):
    if issubclass(exc_type, KeyboardInterrupt):
        return
    logging.getLogger("apmyx").critical(
        "Unhandled exception in %s", where,
        exc_info=(exc_type, exc_value, exc_traceback),
        extra={"where": origin(exc_traceback) or "unhandled"},
    )


def install_qt_handler():
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return
    levels = {
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    qt_logger = logging.getLogger("qt")

    def handler(kind, context, message):
        level = levels.get(kind)
        if level is not None:
            where = f"qt.{context.function or context.category or 'message'}"
            if context.file:
                where += f" ({Path(context.file).name}:{context.line})"
            qt_logger.log(level, message, extra={"where": where})

    qInstallMessageHandler(handler)


def setup_file_logging(version):
    try:
        log_dir().mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        return None
    handler.setLevel(logging.INFO)
    handler.addFilter(SessionOrWarning())
    handler.setFormatter(RedactingFormatter("[%(asctime)s] %(levelname)s %(where)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    threading.excepthook = lambda args: log_unhandled(args.exc_type, args.exc_value, args.exc_traceback, f"thread {args.thread.name if args.thread else '?'}")
    install_qt_handler()
    frozen = "installed build" if getattr(sys, "frozen", False) else "source"
    logging.getLogger("apmyx").info(
        "===== apmyx %s started (%s, %s %s, Python %s) =====",
        version, frozen, platform.system(), platform.release(), platform.python_version(),
        extra={"session": True, "where": "apmyx"},
    )
    return handler
