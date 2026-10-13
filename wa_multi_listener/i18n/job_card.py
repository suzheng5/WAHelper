"""任务卡片状态文案（含 pause_reason 翻译）。"""
from __future__ import annotations

from typing import Any, Optional

from i18n.pause_reason import display_pause_reason


def operator_note_for_items(items: Any, *, cursor: int = 0, max_len: int = 56) -> str:
    """阶段提醒 / 发图步骤上的备注（仅给人看，不跟消息发）。优先最近已走过的备注。"""
    seq = list(items or [])
    notes: list[str] = []
    for it in seq:
        if not (getattr(it, "is_reminder", False) or getattr(it, "is_image_send", False)):
            continue
        note = (getattr(it, "reminder_note", None) or "").strip()
        if note:
            notes.append(note)
    if not notes:
        return ""
    idx = max(0, int(cursor or 0) - 1)
    for k in range(min(idx, len(seq) - 1), -1, -1):
        it = seq[k]
        if getattr(it, "is_reminder", False) or getattr(it, "is_image_send", False):
            note = (getattr(it, "reminder_note", None) or "").strip()
            if note:
                return note[:max_len]
    return notes[0][:max_len]


def format_job_status_label(
    *,
    enabled: bool,
    state: str,
    pause_reason: str = "",
    stopped_reason_max: int = 24,
    paused_reason_max: int = 28,
) -> str:
    from i18n import t

    if not enabled:
        raw = (pause_reason or "").strip()
        if raw:
            reason = display_pause_reason(raw, max_len=stopped_reason_max)
            return t("job_card.stopped_with_reason", reason=reason)
        return t("job_card.stopped")
    if state == "paused":
        reason = display_pause_reason(pause_reason or "", max_len=paused_reason_max)
        return t("job_card.paused_with_reason", reason=reason)
    return t("job_card.running")
