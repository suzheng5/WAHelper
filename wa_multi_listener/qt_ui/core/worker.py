"""基于 QThreadPool 的非阻塞后台任务执行器。"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


@dataclass(frozen=True, slots=True)
class WorkerError:
    exception_type: str
    message: str
    traceback_text: str


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    progress = Signal(object)
    done = Signal()
    _completed = Signal(object)


class WorkerTask(QRunnable):
    """在工作线程调用普通函数，结果仅通过信号返回。"""

    def __init__(
        self,
        function: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        *,
        inject_progress: bool,
    ) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self._function = function
        self._args = args
        self._kwargs = kwargs
        self._inject_progress = inject_progress

    @Slot()
    def run(self) -> None:
        kwargs = dict(self._kwargs)
        if self._inject_progress:
            kwargs["progress"] = self.signals.progress.emit
        try:
            self.signals.result.emit(self._function(*self._args, **kwargs))
        except Exception as exc:
            self.signals.error.emit(
                WorkerError(
                    exception_type=type(exc).__name__,
                    message=str(exc),
                    traceback_text=traceback.format_exc(),
                )
            )
        finally:
            self.signals.done.emit()
            self.signals._completed.emit(self)


class WorkerRunner(QObject):
    """创建并持有任务，防止任务完成信号送达前被回收。"""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self._pool = pool or QThreadPool.globalInstance()
        self._active: set[WorkerTask] = set()

    def submit(
        self,
        function: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[WorkerError], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        on_done: Callable[[], None] | None = None,
        inject_progress: bool = False,
        **kwargs: Any,
    ) -> WorkerTask:
        task = WorkerTask(
            function,
            args,
            kwargs,
            inject_progress=inject_progress,
        )
        if on_result is not None:
            task.signals.result.connect(on_result)
        if on_error is not None:
            task.signals.error.connect(on_error)
        if on_progress is not None:
            task.signals.progress.connect(on_progress)
        if on_done is not None:
            task.signals.done.connect(on_done)
        task.signals._completed.connect(self._release)
        self._active.add(task)
        self._pool.start(task)
        return task

    @Slot(object)
    def _release(self, task: WorkerTask) -> None:
        self._active.discard(task)

    @property
    def active_count(self) -> int:
        return len(self._active)
