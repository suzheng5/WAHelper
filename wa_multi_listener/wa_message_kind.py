"""WhatsApp 消息类型粗判（监听过滤用）。"""
from __future__ import annotations

from typing import Any


def is_wa_reaction_message(message: Any) -> bool:
    """客户/任意账号发出的表情反应（含加密反应），不是普通文本消息。"""
    if message is None:
        return False
    rm = getattr(message, "reactionMessage", None)
    if rm is not None and getattr(rm, "ListFields", None) and rm.ListFields():
        return True
    erm = getattr(message, "encReactionMessage", None)
    if erm is not None and getattr(erm, "ListFields", None) and erm.ListFields():
        return True
    return False
