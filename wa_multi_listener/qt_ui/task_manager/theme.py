"""将现有任务卡片语义配色适配为 Qt 类型。"""
from __future__ import annotations

from PySide6.QtGui import QColor

try:
    from wa_ui.taskmgr_tile_theme import (
        taskmgr_display_sort_tier,
        taskmgr_job_bucket,
        taskmgr_tile_palette,
    )
except ImportError:  # 以仓库根目录作为包根运行时
    from wa_multi_listener.wa_ui.taskmgr_tile_theme import (
        taskmgr_display_sort_tier,
        taskmgr_job_bucket,
        taskmgr_tile_palette,
    )

from .types import TaskRecord


def bucket(record: TaskRecord) -> str:
    return taskmgr_job_bucket(
        running=record.running,
        enabled=record.enabled,
        pause_reason=record.pause_reason,
    )


def sort_tier(record: TaskRecord) -> int:
    return taskmgr_display_sort_tier(
        running=record.running,
        enabled=record.enabled,
        pause_reason=record.pause_reason,
    )


def palette(record: TaskRecord) -> dict[str, QColor]:
    colors = taskmgr_tile_palette(
        running=record.running,
        enabled=record.enabled,
        pause_reason=record.pause_reason,
    )
    return {name: QColor(value) for name, value in colors.items()}
