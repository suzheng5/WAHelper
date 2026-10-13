"""任务管理破坏性操作的确认文案与预检（WA/TG 共用）。"""
from __future__ import annotations

from typing import Any, Callable

Translator = Callable[..., str]


def resume_all_confirm_message(
    tr: Translator,
    *,
    resumable: int,
    skipped: int,
    body_key: str = "msgbox.resume_all.body",
) -> str | None:
    """无可恢复任务时返回 None（调用方应直接提示）。"""
    if resumable <= 0:
        return None
    skipped_line = (
        tr("msgbox.resume_all.skipped", skipped=skipped) if skipped > 0 else ""
    )
    return tr(body_key, resumable=resumable, skipped_line=skipped_line)


def next_day_all_confirm_message(
    tr: Translator,
    *,
    candidates: list[Any],
    stale: list[Any],
    target_label: Callable[[Any], str],
    is_running: Callable[[Any], bool] | None = None,
) -> str | None:
    from schedule_folder import (
        format_folder_advance_line,
        format_folder_last_day_delete_line,
    )

    if not candidates and not stale:
        return None
    unnamed = tr("grp.unnamed")
    advance_block = ""
    delete_block = ""
    if candidates:
        running_n = sum(1 for job in candidates if is_running and is_running(job))
        lines = []
        for job in candidates:
            nxt = int(getattr(job, "folder_day_index", 0) or 0) + 1
            files = list(getattr(job, "folder_files", None) or [])
            lines.append(
                format_folder_advance_line(
                    target_label=target_label(job),
                    current_name=getattr(job, "source_name", "") or unnamed,
                    next_name=files[nxt] if nxt < len(files) else "",
                    next_day_one_based=nxt + 1,
                    total_days=len(files),
                )
            )
        intro = tr("msgbox.next_day.interrupt")
        if running_n:
            intro += "\n\n" + tr("msgbox.next_day.running", n=running_n)
        intro += "\n\n" + tr("msgbox.next_day.advance_list") + "\n" + "\n".join(lines)
        advance_block = intro
    if stale:
        del_lines = []
        for job in stale:
            idx = max(0, int(getattr(job, "folder_day_index", 0) or 0))
            files = list(getattr(job, "folder_files", None) or [])
            del_lines.append(
                format_folder_last_day_delete_line(
                    target_label=target_label(job),
                    current_name=getattr(job, "source_name", "") or unnamed,
                    day_one_based=idx + 1,
                    total_days=len(files),
                )
            )
        block = tr("msgbox.next_day.delete_list") + "\n" + "\n".join(del_lines)
        delete_block = ("\n\n" + block) if advance_block else block
    return tr(
        "msgbox.next_day.body",
        advance_block=advance_block,
        delete_block=delete_block,
    )


def manual_next_day_confirm_message(tr: Translator, job: Any, target: str) -> str:
    nxt = int(getattr(job, "folder_day_index", 0) or 0) + 1
    files = list(getattr(job, "folder_files", None) or [])
    return tr(
        "msgbox.manual_day.confirm",
        target=target,
        current=getattr(job, "source_name", "") or tr("grp.unnamed"),
        next_file=files[nxt] if nxt < len(files) else "",
        day=nxt + 1,
        total=len(files),
    )


def schedule_doc_path() -> str:
    import os

    from paths import app_root, resource_path

    for path in (
        resource_path("docs", "定时任务导入说明与示例.txt"),
        os.path.join(app_root(), "docs", "定时任务导入说明与示例.txt"),
        os.path.join(app_root(), "定时任务导入说明与示例.txt"),
    ):
        if os.path.isfile(path):
            return path
    return os.path.join(app_root(), "docs", "定时任务导入说明与示例.txt")


def open_schedule_doc() -> str:
    import os
    import webbrowser

    path = schedule_doc_path()
    if os.path.isfile(path):
        webbrowser.open(path)
    return path


def audit_status_value(status: Any) -> str:
    """从 Enum / 字符串 / WatchAuditRow 取出审计状态码。"""
    if status is None:
        return ""
    if hasattr(status, "status") and not isinstance(status, (str, bytes)):
        status = getattr(status, "status", status)
    value = getattr(status, "value", None)
    if value is None:
        value = status
    return str(value or "").strip().lower()


def audit_status_label(tr: Translator, status: Any, detail: str = "") -> str:
    """规则页等处的说明文案；ok/skip 为空。"""
    value = audit_status_value(status)
    if value in ("", "ok", "skip"):
        return ""
    if value == "absent":
        return tr("audit.not_in_group_short")
    if value == "error":
        msg = detail.strip() or tr("audit.parse_fail")
        return tr("audit.check_fail_short") + (f" ({msg})" if msg else "")
    if value == "offline":
        return tr("audit.offline_short")
    return ""


def audit_contact_badge(tr: Translator, status: Any) -> str:
    """通讯录列表短标记：检测过后 ok 也要可见，避免「没反应」。"""
    value = audit_status_value(status)
    if value == "ok":
        return tr("grp.in_group_badge")
    if value == "absent":
        return tr("grp.not_in_group_badge")
    if value == "error":
        return tr("grp.audit_fail_badge")
    if value == "offline":
        return tr("grp.audit_offline_badge")
    return ""


def audit_contact_colors(status: Any) -> tuple[str | None, str | None]:
    """返回 (前景色, 背景色)；无标记时均为 None。"""
    value = audit_status_value(status)
    if value == "ok":
        return "#34d399", "#143528"
    if value in ("absent", "error", "offline"):
        return "#ef4444", "#3a1a1a"
    return None, None
