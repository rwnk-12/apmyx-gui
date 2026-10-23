import asyncio
import logging

from PyQt6 import sip
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QRunnable, QThreadPool

_wrapper_pool = None


def wrapper_pool():
    global _wrapper_pool
    if _wrapper_pool is None or sip.isdeleted(_wrapper_pool):
        _wrapper_pool = QThreadPool()
    return _wrapper_pool


class SearchWorkerSignals(QObject):
    finished = pyqtSignal()
    search_results_loaded = pyqtSignal(dict)
    search_results_appended = pyqtSignal(str, list)
    category_search_results_loaded = pyqtSignal(str, list)
    status_updated = pyqtSignal(str, str)
    artwork_results_appended = pyqtSignal(list)


class SearchWorker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = SearchWorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def safe_emit(self, signal, *args):
        if not self._cancelled:
            try:
                signal.emit(*args)
            except RuntimeError:
                pass

    @pyqtSlot()
    def run(self):
        try:
            if self._cancelled:
                return

            self.fn(self, self.signals, *self.args, **self.kwargs)
        except Exception as e:
            if not self._cancelled:
                logging.exception(
                    "Error in worker function %s",
                    getattr(self.fn, "__name__", type(self.fn).__name__),
                )
                self.safe_emit(
                    self.signals.status_updated, f"Worker error: {e}", "error"
                )
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    @pyqtSlot()
    def run(self):

        if asyncio.iscoroutinefunction(self.fn):
            asyncio.run(self.fn(*self.args, **self.kwargs))
        else:
            self.fn(*self.args, **self.kwargs)
