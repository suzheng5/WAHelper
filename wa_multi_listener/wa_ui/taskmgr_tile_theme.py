"""任务管理卡片配色：运行 / 监听暂停 / 阶段提醒+监听 / 已停止 / 其它暂停。"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, TypedDict

import customtkinter as ctk

from i18n.pause_reason import (
    CODE_AWAIT_IMAGE_SEND,
    CODE_JOIN_GROUP_FAILED,
    CODE_LISTEN_HIT,
    CODE_STAGE_LISTEN_HIT,
    CODE_STAGE_REMINDER,
    CODE_STOPPED_LISTEN_HIT,
    compose_listen_pause_reason,
    normalize_pause_reason,
    resolve_listen_pause_reason,
)

TaskmgrBucket = str  # running | listen_pause | stage_listen_pause | stopped_listen_pause | other_pause | stopped

# 向后兼容：旧代码 import 的常量现为原因码
STAGE_LISTEN_HIT_PAUSE_REASON = CODE_STAGE_LISTEN_HIT
STOPPED_LISTEN_HIT_PAUSE_REASON = CODE_STOPPED_LISTEN_HIT

_TASKMGR_FONTS: dict[str, ctk.CTkFont] | None = None


class TaskmgrTilePalette(TypedDict):
    fg: str
    border: str
    status: str
    body: str
    file: str
    title: str
    hint: str


_RUNNING: TaskmgrTilePalette = {
    "fg": "#1a4d32",
    "border": "#2ecc71",
    "status": "#9dffca",
    "body": "#f5fffa",
    "file": "#def7e9",
    "title": "#ffffff",
    "hint": "#e9e9e9",
}

_STOPPED: TaskmgrTilePalette = {
    "fg": "#2a3038",
    "border": "#4a5160",
    "status": "#9aa3b2",
    "body": "#b0b7c3",
    "file": "#949bab",
    "title": "#c5cad3",
    "hint": "#8b919c",
}

_LISTEN_PAUSE: TaskmgrTilePalette = {
    "fg": "#3a3018",
    "border": "#c9a227",
    "status": "#ffe7a8",
    "body": "#fff3d6",
    "file": "#f0d998",
    "title": "#ffffff",
    "hint": "#ececec",
}

_STAGE_LISTEN_PAUSE: TaskmgrTilePalette = {
    "fg": "#2a1848",
    "border": "#9b59b6",
    "status": "#e8c8ff",
    "body": "#f3e8ff",
    "file": "#d4b8f0",
    "title": "#ffffff",
    "hint": "#ececec",
}

_STOPPED_LISTEN_PAUSE: TaskmgrTilePalette = {
    "fg": "#123a4a",
    "border": "#1abc9c",
    "status": "#b8fff0",
    "body": "#e0faf5",
    "file": "#a8e8dc",
    "title": "#ffffff",
    "hint": "#ececec",
}

_OTHER_PAUSE: TaskmgrTilePalette = {
    "fg": "#5c2424",
    "border": "#e74c3c",
    "status": "#ffd7d7",
    "body": "#fff5f5",
    "file": "#ffe8e8",
    "title": "#ffffff",
    "hint": "#e9e9e9",
}


def _code(pause_reason: str) -> str:
    return normalize_pause_reason(pause_reason)


def _is_stopped_listen_pause(pause_reason: str) -> bool:
    return _code(pause_reason) == CODE_STOPPED_LISTEN_HIT


def _is_listen_hit_pause(pause_reason: str) -> bool:
    c = _code(pause_reason)
    if c in (CODE_STAGE_LISTEN_HIT, CODE_STOPPED_LISTEN_HIT):
        return False
    return c == CODE_LISTEN_HIT


def _is_stage_listen_pause(pause_reason: str) -> bool:
    return _code(pause_reason) == CODE_STAGE_LISTEN_HIT


def _is_stage_reminder_pause(pause_reason: str) -> bool:
    return _code(pause_reason) == CODE_STAGE_REMINDER


def _is_join_group_failed_pause(pause_reason: str) -> bool:
    return _code(pause_reason) == CODE_JOIN_GROUP_FAILED


def _is_await_image_pause(pause_reason: str) -> bool:
    """纯待发图（红）；不含「待发图+监听」（紫）。"""
    return _code(pause_reason) == CODE_AWAIT_IMAGE_SEND


def _is_await_image_listen_pause(pause_reason: str) -> bool:
    from i18n.pause_reason import CODE_AWAIT_IMAGE_LISTEN_HIT

    return _code(pause_reason) == CODE_AWAIT_IMAGE_LISTEN_HIT


def taskmgr_display_sort_tier(*, running: bool, enabled: bool, pause_reason: str = "") -> int:
    """任务管理页排序层级（越小越靠前）：监听类 > 阶段提醒/待发图 > 其它暂停 > 其余。"""
    if (
        _is_stage_listen_pause(pause_reason)
        or _is_stopped_listen_pause(pause_reason)
        or _is_listen_hit_pause(pause_reason)
        or _is_await_image_listen_pause(pause_reason)
    ):
        return 0
    if running:
        return 3
    if not enabled:
        return 3
    if _is_stage_reminder_pause(pause_reason) or _is_await_image_pause(pause_reason) or _is_join_group_failed_pause(
        pause_reason
    ):
        return 1
    return 2


def taskmgr_needs_attention(*, running: bool, enabled: bool, pause_reason: str = "") -> bool:
    """是否置顶（监听命中含已停止；阶段提醒/其它暂停仅 enabled 且未运行）。"""
    return taskmgr_display_sort_tier(
        running=running,
        enabled=enabled,
        pause_reason=pause_reason,
    ) < 3


def taskmgr_sort_jobs_for_display(
    jobs: Iterable[Any],
    *,
    is_running: Callable[[Any], bool],
) -> list[Any]:
    """置顶需人工处理的任务；同层内保持 schedules.json 原顺序。"""
    indexed = list(enumerate(jobs))

    def _key(item: tuple[int, Any]) -> tuple[int, int]:
        i, j = item
        tier = taskmgr_display_sort_tier(
            running=is_running(j),
            enabled=bool(getattr(j, "enabled", False)),
            pause_reason=(getattr(j, "pause_reason", None) or ""),
        )
        return (tier, i)

    return [j for _, j in sorted(indexed, key=_key)]


def taskmgr_job_bucket(*, running: bool, enabled: bool, pause_reason: str = "") -> TaskmgrBucket:
    if running:
        return "running"
    if _is_stage_listen_pause(pause_reason) or _is_await_image_listen_pause(pause_reason):
        return "stage_listen_pause"
    if _is_stopped_listen_pause(pause_reason):
        return "stopped_listen_pause"
    if _is_listen_hit_pause(pause_reason):
        return "listen_pause"
    if not enabled:
        return "stopped"
    # 纯待发图 / 阶段提醒 → 红（other_pause）
    return "other_pause"


def taskmgr_tile_palette(*, running: bool, enabled: bool, pause_reason: str = "") -> TaskmgrTilePalette:
    bucket = taskmgr_job_bucket(running=running, enabled=enabled, pause_reason=pause_reason)
    if bucket == "running":
        return dict(_RUNNING)
    if bucket == "stage_listen_pause":
        return dict(_STAGE_LISTEN_PAUSE)
    if bucket == "stopped_listen_pause":
        return dict(_STOPPED_LISTEN_PAUSE)
    if bucket == "listen_pause":
        return dict(_LISTEN_PAUSE)
    if bucket == "stopped":
        return dict(_STOPPED)
    return dict(_OTHER_PAUSE)


def taskmgr_count_jobs(
    jobs: Iterable[Any],
    *,
    is_running: Callable[[Any], bool],
) -> dict[str, int]:
    counts = {
        "total": 0,
        "running": 0,
        "listen_pause": 0,
        "stage_listen_pause": 0,
        "stopped_listen_pause": 0,
        "other_pause": 0,
        "stopped": 0,
    }
    for j in jobs:
        counts["total"] += 1
        bucket = taskmgr_job_bucket(
            running=is_running(j),
            enabled=bool(getattr(j, "enabled", False)),
            pause_reason=(getattr(j, "pause_reason", None) or ""),
        )
        counts[bucket] += 1
    return counts


def format_taskmgr_count_summary(counts: dict[str, int]) -> str:
    from i18n import t

    total = counts.get("total", 0)
    if total <= 0:
        return t("taskmgr.count.total", total=0)
    parts = [t("taskmgr.count.total", total=total)]
    for key, label_key in (
        ("running", "taskmgr.count.running"),
        ("stage_listen_pause", "taskmgr.count.stage_listen_pause"),
        ("stopped_listen_pause", "taskmgr.count.stopped_listen_pause"),
        ("listen_pause", "taskmgr.count.listen_pause"),
        ("other_pause", "taskmgr.count.other_pause"),
        ("stopped", "taskmgr.count.stopped"),
    ):
        n = counts.get(key, 0)
        if n:
            parts.append(f"{t(label_key)} {n}")
    return " · ".join(parts)


def taskmgr_fonts() -> dict[str, ctk.CTkFont]:
    global _TASKMGR_FONTS
    if _TASKMGR_FONTS is None:
        family = "Microsoft YaHei UI"
        _TASKMGR_FONTS = {
            "title": ctk.CTkFont(family=family, size=15, weight="bold"),
            "status": ctk.CTkFont(family=family, size=12, weight="bold"),
            "body": ctk.CTkFont(family=family, size=12),
            "reminder": ctk.CTkFont(family=family, size=12, weight="bold"),
            "hint": ctk.CTkFont(family=family, size=11),
            "btn": ctk.CTkFont(family=family, size=11, weight="bold"),
        }
    return _TASKMGR_FONTS


def taskmgr_card_status_text(status: str, step: str) -> str:
    """状态 + 步骤合并为一行块，减少卡片内 Label 数量。"""
    status = (status or "").strip()
    step = (step or "").strip()
    if status and step:
        return f"{status}\n{step}"
    return status or step
