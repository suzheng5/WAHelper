"""TG 后台事件处理；业务状态先落盘，再通知 Qt 主线程。"""
from __future__ import annotations

from typing import Any


def handle_listener_alert(presenter: Any, payload: Any) -> None:
    data = dict(payload) if isinstance(payload, dict) else {}
    try:
        chat_id = int(data.get("chat_id"))
        raw = data.get("chat_id_raw")
        raw_id = int(raw) if raw is not None else None
        username = str(data.get("chat_username") or "").strip() or None
        title = str(data.get("chat_title") or "").strip() or None
        reason = presenter.m.scheduler.LISTEN_HIT_PAUSE_REASON
        presenter.scheduler.pause_jobs_by_chat(
            chat_id,
            reason,
            raw_chat_id=raw_id,
            event_username=username,
            event_title=title,
        )
        if raw_id is not None and raw_id != chat_id:
            presenter.scheduler.pause_jobs_by_chat(
                raw_id,
                reason,
                raw_chat_id=chat_id,
                event_username=username,
                event_title=title,
            )
    finally:
        try:
            from tg_multi_listener.stats import record_alert

            record_alert()
        finally:
            presenter.tasks_changed.emit(presenter.task_records())
            presenter.alert_received.emit(data)
