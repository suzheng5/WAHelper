"""发送前自动入群：仅补本条发送账号；不在群则等 30 秒再用邀请链接加入。"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional, Set, Tuple, TYPE_CHECKING

from neonize.proto.Neonize_pb2 import JID

from logger_util import info, warning
from wa_jid import (
    invite_code_from_link,
    jid_nonempty,
    jid_to_key,
    keys_for_match,
    register_resolved_chat,
)
from wa_send import resolve_chat_jid

if TYPE_CHECKING:
    from neonize.aioze.client import NewAClient

JOIN_WAIT_SEC = 30.0

# (account_id, cache_key) 本进程内已确认在群，避免每条消息都等 30 秒
_joined_ok: Set[Tuple[str, str]] = set()


class AutoJoinFailed(Exception):
    """入群失败，调用方应暂停任务并提示。"""

    def __init__(
        self,
        message: str,
        *,
        account_id: str = "",
        chat_ref: str = "",
    ) -> None:
        super().__init__(message)
        self.account_id = (account_id or "").strip()
        self.chat_ref = (chat_ref or "").strip()


class AutoJoinAborted(Exception):
    """等待入群期间任务已暂停/取消，不视为入群失败。"""


def _cache_key(chat_ref: str) -> str:
    cref = (chat_ref or "").strip()
    code = invite_code_from_link(cref)
    if code:
        return f"inv:{code.lower()}"
    return cref.lower()


def clear_joined_cache() -> None:
    _joined_ok.clear()


def find_invite_code_for_chat_ref(chat_ref: str) -> Optional[str]:
    """从 chat_ref 本身、通讯录 invite_link 或同群条目解析邀请码。"""
    cref = (chat_ref or "").strip()
    code = invite_code_from_link(cref)
    if code:
        return code
    try:
        from config import find_wa_invite_link_for_chat_ref, load_config

        link = find_wa_invite_link_for_chat_ref(load_config(), cref)
    except Exception:
        link = ""
    return invite_code_from_link(link) if link else None


def _persist_after_join(group_jid: JID, invite_code: str, chat_ref: str) -> None:
    try:
        from config import persist_wa_resolved_jid

        key = jid_to_key(group_jid) if jid_nonempty(group_jid) else ""
        if not key:
            return
        inv = (chat_ref or "").strip()
        if not invite_code_from_link(inv):
            inv = f"https://chat.whatsapp.com/{invite_code}"
        persist_wa_resolved_jid(key, invite_ref=inv)
    except Exception as exc:
        warning(f"[WA] 写回群 JID/邀请链接失败：{exc}")


async def sleep_abortable(
    seconds: float,
    abort_check: Optional[Callable[[], bool]] = None,
) -> None:
    """可中断睡眠；若 abort_check 为真则抛 AutoJoinAborted。"""
    end = time.monotonic() + max(0.0, float(seconds))
    while True:
        if abort_check and abort_check():
            raise AutoJoinAborted("任务已暂停，取消自动入群")
        left = end - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(1.0, left))


async def _jid_in_joined_groups(client: "NewAClient", group_jid: JID) -> Optional[bool]:
    try:
        groups = await client.get_joined_groups()
    except Exception:
        return None
    want = set(keys_for_match(group_jid))
    try:
        for gi in groups:
            gj = getattr(gi, "JID", None)
            if jid_nonempty(gj) and want.intersection(keys_for_match(gj)):
                return True
    except TypeError:
        return None
    return False


async def _me_in_group_info(client: "NewAClient", group_jid: JID) -> Optional[bool]:
    try:
        gi = await asyncio.wait_for(client.get_group_info(group_jid), timeout=20.0)
    except Exception:
        return False
    me = getattr(client, "me", None)
    if me is None or not jid_nonempty(me):
        return None
    my_key = jid_to_key(me)
    parts = getattr(gi, "Participants", None)
    if parts is None:
        return None
    try:
        for p in parts:
            if isinstance(p, JID) and jid_nonempty(p) and jid_to_key(p) == my_key:
                return True
            pj = getattr(p, "JID", None)
            if jid_nonempty(pj) and jid_to_key(pj) == my_key:
                return True
            pl = getattr(p, "LID", None)
            if jid_nonempty(pl) and jid_to_key(pl) == my_key:
                return True
    except TypeError:
        return None
    return False


async def is_account_in_group(client: "NewAClient", chat_ref: str) -> bool:
    cref = (chat_ref or "").strip()
    if not cref:
        return False
    try:
        group_jid = await resolve_chat_jid(client, cref)
    except Exception:
        return False
    if not jid_nonempty(group_jid):
        return False
    joined = await _jid_in_joined_groups(client, group_jid)
    if joined is True:
        return True
    in_info = await _me_in_group_info(client, group_jid)
    if in_info is True:
        return True
    if joined is False and in_info is False:
        return False
    if joined is False:
        return False
    if in_info is False:
        return False
    return False


async def ensure_wa_sender_in_group(
    client: "NewAClient",
    account_id: str,
    chat_ref: str,
    *,
    abort_check: Optional[Callable[[], bool]] = None,
) -> None:
    """
    确保本条发送账号已在目标群。
    已在群：直接返回；不在：等 JOIN_WAIT_SEC 后用邀请链接加入。
    失败抛 AutoJoinFailed；等待中任务取消抛 AutoJoinAborted。
    """
    aid = (account_id or "").strip()
    cref = (chat_ref or "").strip()
    if not aid or not cref:
        return
    if abort_check and abort_check():
        raise AutoJoinAborted("任务已暂停，取消自动入群")

    ck = (aid, _cache_key(cref))
    if ck in _joined_ok:
        return

    if await is_account_in_group(client, cref):
        _joined_ok.add(ck)
        # 已在群但 chat_ref 已是 JID：若通讯录仍有邀请链接则登记解析关系
        code_exist = find_invite_code_for_chat_ref(cref)
        if code_exist:
            try:
                jid_now = await resolve_chat_jid(client, cref)
                if jid_nonempty(jid_now):
                    register_resolved_chat(f"https://chat.whatsapp.com/{code_exist}", jid_now)
                    _persist_after_join(jid_now, code_exist, cref)
            except Exception:
                pass
        return

    code = find_invite_code_for_chat_ref(cref)
    if not code:
        raise AutoJoinFailed(
            "通讯录无群邀请链接，无法自动入群"
            "（若群栏已是 @g.us，请再粘贴一次 chat.whatsapp.com 邀请链接后保存）",
            account_id=aid,
            chat_ref=cref,
        )

    info(
        f"[WA] 自动入群：账号「{aid}」不在群「{cref}」，"
        f"等待 {JOIN_WAIT_SEC:g} 秒后用邀请链接加入…"
    )
    await sleep_abortable(JOIN_WAIT_SEC, abort_check)
    if abort_check and abort_check():
        raise AutoJoinAborted("任务已暂停，取消自动入群")

    try:
        jid = await client.join_group_with_link(code)
    except Exception as exc:
        msg = str(exc) or exc.__class__.__name__
        low = msg.lower()
        if "pending" in low or "approval" in low or "审核" in msg:
            detail = f"入群需管理员审核或链接异常：{msg}"
        else:
            detail = f"邀请链接入群失败：{msg}"
        raise AutoJoinFailed(detail, account_id=aid, chat_ref=cref) from exc

    if jid_nonempty(jid):
        register_resolved_chat(cref, jid)
        try:
            register_resolved_chat(f"https://chat.whatsapp.com/{code}", jid)
        except Exception:
            pass
        _persist_after_join(jid, code, cref)

    await asyncio.sleep(1.0)
    if await is_account_in_group(client, cref):
        _joined_ok.add(ck)
        info(f"[WA] 自动入群成功：账号「{aid}」群「{cref}」")
        return

    # join 成功但成员表未立刻同步时，仍以 join 返回为准记入缓存
    if jid_nonempty(jid):
        warning(
            f"[WA] 自动入群：账号「{aid}」已调用加入，成员表暂未确认，继续尝试发送"
        )
        _joined_ok.add(ck)
        return

    raise AutoJoinFailed(
        "入群后仍无法确认已在群内（可能需管理员审核）",
        account_id=aid,
        chat_ref=cref,
    )
