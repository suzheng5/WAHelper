"""Telegram 发送前自动入群：仅补本条发送账号；不在群则等 30 秒再 join。"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Callable, Optional, Set, Tuple, Union

from telethon import TelegramClient
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
from telethon.tl.types import ChatInviteAlready

from .logger_util import info, warning

JOIN_WAIT_SEC = 30.0

_joined_ok: Set[Tuple[str, str]] = set()


class AutoJoinFailed(Exception):
    def __init__(
        self,
        message: str,
        *,
        account_id: str = "",
        chat_ref: Union[int, str] = "",
    ) -> None:
        super().__init__(message)
        self.account_id = (account_id or "").strip()
        self.chat_ref = chat_ref


class AutoJoinAborted(Exception):
    """等待入群期间任务已暂停/取消。"""


def _cache_key(chat_ref: Union[int, str]) -> str:
    if isinstance(chat_ref, int):
        return f"id:{chat_ref}"
    s = (chat_ref or "").strip().lower()
    h = tg_invite_hash(s)
    if h:
        return f"inv:{h}"
    return s


def clear_joined_cache() -> None:
    _joined_ok.clear()


def tg_invite_hash(ref: str) -> Optional[str]:
    """从 t.me/+HASH / joinchat/HASH / 裸 +HASH 提取邀请 hash。"""
    t = (ref or "").strip()
    if not t:
        return None
    m = re.search(r"joinchat/([^/?#\s]+)", t, flags=re.I)
    if m:
        return m.group(1).strip() or None
    low = t.lower()
    if "t.me/" in low or "telegram.me/" in low:
        split_on = "telegram.me/" if "telegram.me/" in low else "t.me/"
        tail = t.split(split_on, 1)[-1].split("?", 1)[0].strip().strip("/")
        if tail.startswith("+"):
            return tail[1:].strip() or None
        return None
    if t.startswith("+") and len(t) > 1 and "/" not in t:
        return t[1:].strip() or None
    return None


def tg_public_username(ref: str) -> Optional[str]:
    """公开群/频道用户名（无 @）；邀请链接返回 None。"""
    t = (ref or "").strip()
    if not t or tg_invite_hash(t):
        return None
    low = t.lower()
    if "t.me/" in low or "telegram.me/" in low:
        split_on = "telegram.me/" if "telegram.me/" in low else "t.me/"
        tail = t.split(split_on, 1)[-1].split("?", 1)[0].strip().strip("/")
        segs = [s for s in tail.split("/") if s and s.lower() not in ("s", "c")]
        if not segs:
            return None
        name = segs[0]
        if name.startswith("+") or name.lower() == "joinchat":
            return None
        return name
    if t.startswith("@"):
        name = t[1:].strip()
        return name or None
    if t.startswith("-") or t.isdigit():
        return None
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,}", t):
        return t
    return None


async def sleep_abortable(
    seconds: float,
    abort_check: Optional[Callable[[], bool]] = None,
) -> None:
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        if abort_check and abort_check():
            raise AutoJoinAborted("任务已暂停，取消自动入群")
        left = end - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(1.0, left))


async def _resolve_entity_loose(client: TelegramClient, chat_ref: Union[int, str]) -> Any:
    from .scheduler import _resolve_entity_for_send

    return await _resolve_entity_for_send(client, chat_ref)


async def is_account_in_group(client: TelegramClient, chat_ref: Union[int, str]) -> bool:
    href = str(chat_ref).strip() if not isinstance(chat_ref, int) else ""
    inv = tg_invite_hash(href) if href else None
    if inv:
        try:
            res = await client(CheckChatInviteRequest(inv))
            return isinstance(res, ChatInviteAlready) and getattr(res, "chat", None) is not None
        except Exception:
            return False
    try:
        entity = await _resolve_entity_loose(client, chat_ref)
    except Exception:
        return False
    try:
        from telethon.tl.functions.channels import GetParticipantRequest

        me = await client.get_me()
        await client(GetParticipantRequest(entity, me))
        return True
    except Exception as exc:
        name = exc.__class__.__name__
        if "UserNotParticipant" in name or "ChatWriteForbidden" in name:
            return False
        # 普通群可能没有 GetParticipant；能 get_entity 且能发就当在群
        try:
            perms = await client.get_permissions(entity, "me")
            return perms is not None
        except Exception:
            return True


async def _peer_id_from_invite_check(client: TelegramClient, inv: str) -> Optional[int]:
    try:
        from telethon import utils

        res = await client(CheckChatInviteRequest(inv))
        if isinstance(res, ChatInviteAlready) and getattr(res, "chat", None) is not None:
            return int(utils.get_peer_id(res.chat))
    except Exception:
        return None
    return None


def _resolve_join_ref(chat_ref: Union[int, str]) -> Tuple[Union[int, str], str]:
    """
    返回 (用于检测/发送的目标, 用于入群的邀请或公开链接)。
    若 chat_ref 仅为数字 ID，从通讯录找回 invite_link。
    """
    href = str(chat_ref).strip() if not isinstance(chat_ref, int) else ""
    if href and (tg_invite_hash(href) or tg_public_username(href)):
        return chat_ref, href
    try:
        from .compat_config import find_invite_link_for_chat_ref, load_config

        link = find_invite_link_for_chat_ref(load_config(), chat_ref)
    except Exception:
        link = ""
    return chat_ref, (link or "").strip()


async def _do_join(client: TelegramClient, join_ref: str) -> Optional[int]:
    """执行入群；成功时尽量返回 peer_id。"""
    from telethon import utils

    href = (join_ref or "").strip()
    inv = tg_invite_hash(href) if href else None
    if inv:
        try:
            updates = await client(ImportChatInviteRequest(inv))
        except UserAlreadyParticipantError:
            return await _peer_id_from_invite_check(client, inv)
        chats = getattr(updates, "chats", None) or []
        if chats:
            try:
                return int(utils.get_peer_id(chats[0]))
            except Exception:
                pass
        return await _peer_id_from_invite_check(client, inv)
    uname = tg_public_username(href) if href else None
    if uname:
        entity = await client.get_entity(uname)
        try:
            await client(JoinChannelRequest(entity))
        except UserAlreadyParticipantError:
            pass
        try:
            return int(utils.get_peer_id(entity))
        except Exception:
            return None
    raise AutoJoinFailed(
        "群标识为数字 ID 且无邀请/公开链接，无法自动入群（请在通讯录填写 t.me/+ 邀请链接或公开 @用户名）",
        chat_ref=join_ref,
    )


def _persist_peer(peer_id: Optional[int], invite_ref: str) -> None:
    if peer_id is None:
        return
    try:
        from .compat_config import persist_resolved_chat_id

        persist_resolved_chat_id(int(peer_id), invite_ref=invite_ref or "")
    except Exception as exc:
        warning(f"[TG] 写回群 ID 失败：{exc}")


async def ensure_tg_sender_in_group(
    client: TelegramClient,
    account_id: str,
    chat_ref: Union[int, str],
    *,
    abort_check: Optional[Callable[[], bool]] = None,
) -> None:
    aid = (account_id or "").strip()
    if not aid:
        return
    if abort_check and abort_check():
        raise AutoJoinAborted("任务已暂停，取消自动入群")

    target_ref, join_ref = _resolve_join_ref(chat_ref)
    ck = (aid, _cache_key(target_ref))
    if join_ref:
        ck2 = (aid, _cache_key(join_ref))
    else:
        ck2 = ck
    if ck in _joined_ok or ck2 in _joined_ok:
        return

    # 已在群：若仍是邀请链接则解析写回 ID
    in_via = join_ref or target_ref
    if await is_account_in_group(client, in_via) or (
        in_via != target_ref and await is_account_in_group(client, target_ref)
    ):
        _joined_ok.add(ck)
        _joined_ok.add(ck2)
        inv = tg_invite_hash(join_ref) if join_ref else tg_invite_hash(str(target_ref))
        if inv:
            pid = await _peer_id_from_invite_check(client, inv)
            _persist_peer(pid, join_ref or str(target_ref))
        return

    can_join = bool(tg_invite_hash(join_ref) or tg_public_username(join_ref))
    if not can_join:
        raise AutoJoinFailed(
            "账号不在群且通讯录无邀请/公开链接，无法自动入群",
            account_id=aid,
            chat_ref=chat_ref,
        )

    info(
        f"[TG] 自动入群：账号「{aid}」不在群「{chat_ref}」，"
        f"等待 {JOIN_WAIT_SEC:g} 秒后加入…"
    )
    await sleep_abortable(JOIN_WAIT_SEC, abort_check)
    if abort_check and abort_check():
        raise AutoJoinAborted("任务已暂停，取消自动入群")

    try:
        peer_id = await _do_join(client, join_ref)
    except AutoJoinFailed:
        raise
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        low = msg.lower()
        if "request" in low and "pending" in low:
            detail = f"入群需管理员审核：{msg}"
        else:
            detail = f"入群失败：{msg}"
        raise AutoJoinFailed(detail, account_id=aid, chat_ref=chat_ref) from exc

    _persist_peer(peer_id, join_ref)

    await asyncio.sleep(1.0)
    if await is_account_in_group(client, join_ref) or await is_account_in_group(client, target_ref):
        _joined_ok.add(ck)
        _joined_ok.add(ck2)
        info(f"[TG] 自动入群成功：账号「{aid}」群「{chat_ref}」")
        return

    warning(f"[TG] 自动入群：账号「{aid}」已调用加入，成员状态暂未确认，继续尝试发送")
    _joined_ok.add(ck)
    _joined_ok.add(ck2)
