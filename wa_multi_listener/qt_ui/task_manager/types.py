"""共享任务管理组件的数据契约；业务层负责持久化和执行动作。"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    platform: str
    title: str
    target: str = ""
    source_name: str = ""
    running: bool = False
    enabled: bool = True
    status: str = ""
    step: str = ""
    pause_reason: str = ""
    last_error: str = ""
    reminder_note: str = ""
    cursor: int = 0
    total: int = 0
    folder_day: int = 0
    folder_total: int = 0
    is_folder: bool = False
    source_order: int = 0

    @property
    def search_text(self) -> str:
        return " ".join(
            str(value)
            for value in (
                self.task_id,
                self.platform,
                self.title,
                self.target,
                self.source_name,
                self.status,
                self.step,
                self.pause_reason,
                self.last_error,
                self.reminder_note,
            )
        ).casefold()

    @property
    def can_advance_day(self) -> bool:
        return self.is_folder and self.folder_total > 0 and self.folder_day < self.folder_total

    def patched(self, changes: Mapping[str, Any]) -> "TaskRecord":
        allowed = {field.name for field in fields(self)}
        unknown = set(changes) - allowed
        if unknown:
            raise KeyError(f"unknown TaskRecord fields: {sorted(unknown)}")
        if "task_id" in changes and str(changes["task_id"]) != self.task_id:
            raise ValueError("patch cannot change task_id")
        return replace(self, **changes)


@runtime_checkable
class TaskManagerActions(Protocol):
    """宿主实现动作；组件不读取或写入任何业务 JSON。"""

    def toggle_task(self, task_id: str) -> None: ...

    def delete_task(self, task_id: str) -> None: ...

    def next_day_task(self, task_id: str) -> None: ...

    def resume_all(self) -> None: ...

    def next_day_all(self) -> None: ...

    def manual_next_day_mode_changed(self, enabled: bool) -> None: ...

    def delete_all(self) -> None: ...

    def reload_wa_folders(self) -> None: ...

    def send_images(self) -> None: ...

    def send_images_sync(self) -> None: ...
