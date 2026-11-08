"""Background workers: run SynthesisService.render (and exports) off the UI thread."""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

NETWORK_MSG = "Cần kết nối Internet cho giọng neural, hoặc chọn giọng offline."
_NETWORK_HINTS = ("internet", "network", "connect", "connection", "timeout", "timed out",
                  "dns", "ssl", "resolve", "unreachable", "websocket", "aiohttp", "kết nối")


def friendly_error(exc: BaseException) -> str:
    """Vietnamese, user-facing message for an exception from the backend."""
    msg = str(exc) or exc.__class__.__name__
    low = (msg + " " + exc.__class__.__name__).lower()
    if isinstance(exc, (ConnectionError, TimeoutError)) or any(h in low for h in _NETWORK_HINTS):
        return NETWORK_MSG
    if isinstance(exc, ModuleNotFoundError):
        return (f"Thiếu thành phần “{exc.name or msg}”. "
                "Hãy cài đặt lại ứng dụng hoặc chọn giọng khác.")
    if isinstance(exc, PermissionError):
        return f"Không có quyền ghi/đọc tệp: {msg}"
    if isinstance(exc, OSError):
        return f"Lỗi tệp hoặc hệ thống: {msg}"
    try:
        from ..core import EngineError
        if isinstance(exc, EngineError):
            return f"Bộ đọc gặp lỗi: {msg}"
    except Exception:  # pragma: no cover
        pass
    return f"Đã xảy ra lỗi: {msg}"


def _is_cancelled_exc(exc: BaseException) -> bool:
    return exc.__class__.__name__ == "Cancelled"


class RenderWorker(QObject):
    """Calls ``service.render(text, voice_id, prosody, language, progress, is_cancelled)``."""

    progress = Signal(int, int, str)   # done, total, current text
    finished = Signal(object)          # RenderResult
    failed = Signal(str, str)          # friendly message, technical details
    cancelled = Signal()

    def __init__(self, service, text: str, voice_id, prosody, language, tag: str = "render"):
        super().__init__()
        self.service = service
        self.text = text
        self.voice_id = voice_id
        self.prosody = prosody
        self.language = language
        self.tag = tag
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.render(
                self.text, self.voice_id, self.prosody, self.language,
                progress=lambda i, n, t: self.progress.emit(int(i), int(n), str(t or "")),
                is_cancelled=self.is_cancelled,
            )
        except BaseException as exc:  # noqa: BLE001 – surface everything to the UI
            if _is_cancelled_exc(exc) or self.is_cancelled():
                self.cancelled.emit()
            else:
                self.failed.emit(friendly_error(exc), traceback.format_exc())
            return
        if self.is_cancelled():
            self.cancelled.emit()
        else:
            self.finished.emit(result)


class TaskWorker(QObject):
    """Runs any callable in a thread (used for exporting)."""

    finished = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal()
    progress = Signal(int, int, str)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self.fn = fn

    def cancel(self) -> None:  # tasks are short; cancel is best-effort
        pass

    @Slot()
    def run(self) -> None:
        try:
            out = self.fn()
        except BaseException as exc:  # noqa: BLE001
            self.failed.emit(friendly_error(exc), traceback.format_exc())
            return
        self.finished.emit(out)


def start_in_thread(worker: QObject, parent: QObject | None = None) -> QThread:
    """Move ``worker`` to a new QThread, start it, and clean up when done."""
    thread = QThread(parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for sig in (worker.finished, worker.failed, worker.cancelled):
        sig.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
