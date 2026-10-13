"""发消息前「正在输入」时长估算与 TG/WA 发送辅助。

规则（对齐老版）：按正文字数估算时长，约 12 字/秒，夹在 1–8 秒；
整段等待保持 typing/composing，并尽量在同一 action 内完成发送。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

# 约每 12 个字符 1 秒（中英文混合按 len）
_CHARS_PER_SECOND = 12.0
_MIN_TYPING_SECONDS = 1.0
_MAX_TYPING_SECONDS = 8.0
_TYPING_REFRESH_SECONDS = 4.5

AbortCheck = Optional[Callable[[], bool]]
T = TypeVar("T")


def typing_duration_seconds(text: str) -> float:
    """按正文字数估算 typing 展示时长（秒）。"""
    n = len((text or "").strip())
    if n <= 0:
        return 0.0
    sec = n / _CHARS_PER_SECOND
    return max(_MIN_TYPING_SECONDS, min(_MAX_TYPING_SECONDS, sec))


async def _wait_with_abort(duration: float, abort_check: AbortCheck) -> bool:
    if duration <= 0:
        return abort_check is None or not abort_check()
    deadline = time.monotonic() + duration
    while True:
        if abort_check and abort_check():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.4, remaining))
    return abort_check is None or not abort_check()


async def telegram_typing_before_send(
    client: Any, entity: Any, text: str, *, abort_check: AbortCheck = None
) -> bool:
    """Telegram：在 send_message 前持续上报 typing。返回 False 表示应中止发送。"""
    duration = typing_duration_seconds(text)
    if duration <= 0:
        return abort_check is None or not abort_check()
    async with client.action(entity, "typing"):
        return await _wait_with_abort(duration, abort_check)


async def telegram_send_with_typing(
    client: Any,
    entity: Any,
    text: str,
    send_coro_factory: Callable[[], Awaitable[T]],
    *,
    abort_check: AbortCheck = None,
) -> Optional[T]:
    """在同一 typing action 内等待并发送，群里能看到完整「正在输入」。

    返回 send 结果；abort 时返回 None。
    """
    duration = typing_duration_seconds(text)
    async with client.action(entity, "typing"):
        if duration > 0 and not await _wait_with_abort(duration, abort_check):
            return None
        if abort_check and abort_check():
            return None
        return await send_coro_factory()


async def whatsapp_typing_before_send(
    client: Any, jid: Any, text: str, *, abort_check: AbortCheck = None
) -> bool:
    """WhatsApp：在 send_message 前周期性上报 composing。返回 False 表示应中止发送。"""
    from neonize.utils.enum import ChatPresence, ChatPresenceMedia

    duration = typing_duration_seconds(text)
    if duration <= 0:
        return abort_check is None or not abort_check()
    deadline = time.monotonic() + duration
    while True:
        if abort_check and abort_check():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            await client.send_chat_presence(
                jid,
                ChatPresence.CHAT_PRESENCE_COMPOSING,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
            )
        except Exception:
            pass
        await asyncio.sleep(min(_TYPING_REFRESH_SECONDS, remaining))
    return abort_check is None or not abort_check()
