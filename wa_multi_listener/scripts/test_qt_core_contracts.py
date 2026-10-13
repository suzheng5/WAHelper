"""Qt 核心契约、跨线程桥与 worker 回归测试。"""
from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QThread, Slot
from PySide6.QtWidgets import QApplication

from qt_ui.bridges import UiSignalBridge
from qt_ui.core import AlertViewModel, WorkerError, WorkerRunner, pause_then_queue_alert
from services.contracts import WaRuntimeProtocol, WaTaskCommandsProtocol, WaUiHostProtocol


def wait_until(app: QApplication, predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


class SignalSink(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[tuple[str, object]] = []
        self.threads: list[QThread] = []

    def _add(self, kind: str, value: object) -> None:
        self.received.append((kind, value))
        self.threads.append(QThread.currentThread())

    @Slot(object)
    def on_alert(self, value: object) -> None:
        self._add("alert", value)

    @Slot(object)
    def on_reminder(self, value: object) -> None:
        self._add("reminder", value)

    @Slot(object)
    def on_progress(self, value: object) -> None:
        self._add("progress", value)

    @Slot(object)
    def on_backend(self, value: object) -> None:
        self._add("backend", value)

    @Slot(object)
    def on_jobs(self, value: object) -> None:
        self._add("jobs", value)

    @Slot(object)
    def on_log(self, value: object) -> None:
        self._add("log", value)


class WorkerSink(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[object] = []
        self.errors: list[WorkerError] = []
        self.done_count = 0
        self.callback_threads: list[QThread] = []

    @Slot(object)
    def on_result(self, value: object) -> None:
        self.results.append(value)
        self.callback_threads.append(QThread.currentThread())

    @Slot(object)
    def on_error(self, value: WorkerError) -> None:
        self.errors.append(value)
        self.callback_threads.append(QThread.currentThread())

    @Slot()
    def on_done(self) -> None:
        self.done_count += 1
        self.callback_threads.append(QThread.currentThread())


class QtCoreContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_cross_thread_bridge_delivers_on_ui_thread(self) -> None:
        bridge = UiSignalBridge()
        sink = SignalSink()
        bridge.alert.connect(sink.on_alert)
        bridge.reminder.connect(sink.on_reminder)
        bridge.progress.connect(sink.on_progress)
        bridge.backend_state.connect(sink.on_backend)
        bridge.jobs_changed.connect(sink.on_jobs)
        bridge.log.connect(sink.on_log)
        callable_threads: list[QThread] = []

        def send() -> None:
            bridge.post_callable(lambda: callable_threads.append(QThread.currentThread()))
            bridge.post_alert("a")
            bridge.post_reminder("r")
            bridge.post_progress("p")
            bridge.post_backend_state("b")
            bridge.post_jobs_changed("j")
            bridge.post_log("l")

        thread = threading.Thread(target=send)
        thread.start()
        thread.join()
        self.assertTrue(wait_until(self.app, lambda: len(sink.received) == 6 and callable_threads))
        self.assertEqual({kind for kind, _ in sink.received}, {
            "alert", "reminder", "progress", "backend", "jobs", "log",
        })
        self.assertTrue(all(thread is self.app.thread() for thread in sink.threads))
        self.assertIs(callable_threads[0], self.app.thread())

    def test_pause_finishes_before_queued_alert(self) -> None:
        bridge = UiSignalBridge()
        order: list[str] = []

        class AlertSink(QObject):
            @Slot(object)
            def receive(self, _value: object) -> None:
                order.append("alert")

        sink = AlertSink()
        bridge.alert.connect(sink.receive)

        def invoke() -> None:
            result = pause_then_queue_alert(
                "payload",
                lambda _alert: order.append("pause") or ("job-1",),
                bridge.post_alert,
            )
            self.assertEqual(result, ("job-1",))

        thread = threading.Thread(target=invoke)
        thread.start()
        thread.join()
        self.assertEqual(order, ["pause"])
        self.assertTrue(wait_until(self.app, lambda: order == ["pause", "alert"]))

    def test_worker_reports_error_and_done_without_ui_blocking(self) -> None:
        runner = WorkerRunner()
        sink = WorkerSink()
        worker_threads: list[QThread] = []

        def succeed() -> int:
            worker_threads.append(QThread.currentThread())
            return 42

        def fail() -> None:
            worker_threads.append(QThread.currentThread())
            raise ValueError("boom")

        runner.submit(
            succeed,
            on_result=sink.on_result,
            on_error=sink.on_error,
            on_done=sink.on_done,
        )
        runner.submit(
            fail,
            on_result=sink.on_result,
            on_error=sink.on_error,
            on_done=sink.on_done,
        )
        self.assertTrue(wait_until(self.app, lambda: sink.done_count == 2))
        self.assertEqual(sink.results, [42])
        self.assertEqual(len(sink.errors), 1)
        self.assertEqual(sink.errors[0].exception_type, "ValueError")
        self.assertTrue(all(thread is not self.app.thread() for thread in worker_threads))
        self.assertTrue(all(thread is self.app.thread() for thread in sink.callback_threads))
        self.assertEqual(runner.active_count, 0)

    def test_view_models_are_frozen_and_protocols_are_explicit(self) -> None:
        value = AlertViewModel("wa", "chat", "title", "sender", "message")
        with self.assertRaises(FrozenInstanceError):
            value.chat_id = "changed"  # type: ignore[misc]
        self.assertTrue(WaUiHostProtocol)
        self.assertTrue(WaRuntimeProtocol)
        self.assertTrue(WaTaskCommandsProtocol)


if __name__ == "__main__":
    unittest.main(verbosity=2)
