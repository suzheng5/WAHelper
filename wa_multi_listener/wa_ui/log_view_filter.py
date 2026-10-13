"""日志面板展示过滤。"""
from __future__ import annotations

from typing import List, Sequence


def _message_part(line: str) -> str:
    text = (line or "").strip()
    if " | " in text:
        return text.split(" | ", 2)[-1].strip()
    return text


def is_visible_reaction_log(msg: str) -> bool:
    """点赞相关日志：展示完成/失败/跳过/已排程，隐藏逐次 debug 尝试。"""
    low = (msg or "").lower()
    if "点赞" not in msg and "reaction" not in low and "like" not in low:
        return True
    if "尝试失败" in msg or "participant=" in low:
        return False
    return any(
        key in msg or key in low
        for key in (
            "完成",
            "失败",
            "跳过",
            "已排程",
            "done",
            "fail",
            "skip",
            "complete",
            "schedul",
        )
    )


def is_visible_in_log_view(line: str) -> bool:
    msg = _message_part(line)
    if not msg:
        return True
    return is_visible_reaction_log(msg)


def filter_lines_for_log_view(lines: Sequence[str]) -> List[str]:
    return [ln for ln in lines if is_visible_in_log_view(ln)]


# 兼容旧名
is_visible_in_wa_log_view = is_visible_in_log_view
filter_lines_for_wa_log_view = filter_lines_for_log_view
