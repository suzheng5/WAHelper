"""PySide6 UI 可依赖的业务边界，不暴露具体业务实现。"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from qt_ui.core.models import (
    AlertViewModel,
    BackendStateViewModel,
    JobsChangedViewModel,
    LogViewModel,
    ProgressViewModel,
    ReminderViewModel,
)


@runtime_checkable
class UiHostProtocol(Protocol):
    """业务适配器向界面发布不可变状态。"""

    def run_on_ui(self, callback: Callable[[], object]) -> None: ...

    def publish_alert(self, value: AlertViewModel) -> None: ...

    def publish_reminder(self, value: ReminderViewModel) -> None: ...

    def publish_progress(self, value: ProgressViewModel) -> None: ...

    def publish_backend_state(self, value: BackendStateViewModel) -> None: ...

    def publish_jobs_changed(self, value: JobsChangedViewModel) -> None: ...

    def publish_log(self, value: LogViewModel) -> None: ...


@runtime_checkable
class RuntimeProtocol(Protocol):
    """已封装配置的后台生命周期命令。"""

    def start(self) -> None: ...

    def stop(self, join_timeout: float = 10.0) -> None: ...

    def reload(self) -> None: ...

    def is_running(self) -> bool: ...

    def snapshot(self) -> BackendStateViewModel: ...


@runtime_checkable
class TaskCommandsProtocol(Protocol):
    """任务管理界面可调用的稳定命令集合。"""

    def jobs_snapshot(self) -> JobsChangedViewModel: ...

    def pause_job(self, job_id: str, reason_code: str) -> bool: ...

    def resume_job(self, job_id: str) -> bool: ...

    def stop_job(self, job_id: str) -> bool: ...

    def delete_job(self, job_id: str) -> bool: ...

    def pause_all(self, reason_code: str) -> int: ...

    def resume_all(self) -> int: ...

    def reload_jobs(self) -> JobsChangedViewModel: ...


@runtime_checkable
class WaUiHostProtocol(UiHostProtocol, Protocol):
    pass


@runtime_checkable
class TgUiHostProtocol(UiHostProtocol, Protocol):
    pass


@runtime_checkable
class WaRuntimeProtocol(RuntimeProtocol, Protocol):
    pass


@runtime_checkable
class TgRuntimeProtocol(RuntimeProtocol, Protocol):
    pass


@runtime_checkable
class WaTaskCommandsProtocol(TaskCommandsProtocol, Protocol):
    pass


@runtime_checkable
class TgTaskCommandsProtocol(TaskCommandsProtocol, Protocol):
    pass


__all__ = [
    "RuntimeProtocol",
    "TaskCommandsProtocol",
    "TgRuntimeProtocol",
    "TgTaskCommandsProtocol",
    "TgUiHostProtocol",
    "UiHostProtocol",
    "WaRuntimeProtocol",
    "WaTaskCommandsProtocol",
    "WaUiHostProtocol",
]
