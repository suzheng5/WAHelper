"""后台线程到 Qt 主线程的统一 Signal 桥。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal, Slot


class UiSignalBridge(QObject):
    """所有 ``post_*`` 方法均可由任意线程安全调用。"""

    callable_requested = Signal(object)
    alert = Signal(object)
    reminder = Signal(object)
    progress = Signal(object)
    backend_state = Signal(object)
    jobs_changed = Signal(object)
    log = Signal(object)
    dispatch_error = Signal(str, object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.callable_requested.connect(
            self._invoke_callable,
            Qt.ConnectionType.QueuedConnection,
        )

    def post_callable(self, callback: Callable[[], Any]) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        self.callable_requested.emit(callback)

    def post_alert(self, value: object) -> None:
        self.alert.emit(value)

    def post_reminder(self, value: object) -> None:
        self.reminder.emit(value)

    def post_progress(self, value: object) -> None:
        self.progress.emit(value)

    def post_backend_state(self, value: object) -> None:
        self.backend_state.emit(value)

    def post_jobs_changed(self, value: object) -> None:
        self.jobs_changed.emit(value)

    def post_log(self, value: object) -> None:
        self.log.emit(value)

    @Slot(object)
    def _invoke_callable(self, callback: Callable[[], Any]) -> None:
        try:
            callback()
        except Exception as exc:
            self.dispatch_error.emit("callable", exc)
