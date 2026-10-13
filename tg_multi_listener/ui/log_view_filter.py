"""Telegram 界面日志展示过滤。"""
from __future__ import annotations

from typing import List, Sequence


def _message_part(line: str) -> str:
    text = (line or "").strip()
    if " | " in text:
        return text.split(" | ", 2)[-1].strip()
    return text


def is_visible_in_log_view(line: str) -> bool:
    msg = _message_part(line)
    if not msg:
        return True
    low = msg.lower()
    if "点赞" in msg or "reaction" in low or "like" in low:
        return "完成" in msg or "done" in low or "complete" in low
    return True


def filter_lines_for_log_view(lines: Sequence[str]) -> List[str]:
    return [ln for ln in lines if is_visible_in_log_view(ln)]
