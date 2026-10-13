"""WhatsApp 定时任务：发送后延迟表情反应（排除发送账号，其余角色随机 1–2 人）。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from neonize.aioze.client import NewAClient
from neonize.proto.Neonize_pb2 import JID
from neonize.utils.jid import JIDToNonAD

from logger_util import debug, info, warning
from schedule_reactions import (
    _track_reaction_task,
    pick_reaction_accounts,
    reaction_delay_seconds,
    reaction_emoji_for_account,
    resolve_main_account_for_job_target,
)
from wa_jid import jid_nonempty, jid_to_key


@dataclass
class WaSentMessageMeta:
    chat_ref: str
    chat_jid: JID
    message_id: str
    message_sender_jid: JID
    """原消息发送者候选 JID（群反应 participant；优先 LID，再手机号）。"""
    message_sender_jids: List[JID] = field(default_factory=list)


async def sender_jids_for_reaction(client: NewAClient) -> List[JID]:
    """
    原消息发送者的多种 JID 形态。

    现代群消息键常用 @lid；若只传 @s.whatsapp.net，WhatsApp 可能静默丢弃反应。
    顺序：本机主 JID → LID → 手机号（去重）。
    """
    try:
        me = await client.get_me()
    except Exception as exc:
        warning(f"[WA] 获取本账号 JID 失败：{exc}")
        return []
    primary = JIDToNonAD(me.JID)
    if not jid_nonempty(primary):
        return []

    ordered: List[JID] = []
    seen: Set[str] = set()

    def _add(j: Optional[JID]) -> None:
        if j is None or not jid_nonempty(j):
            return
        jj = JIDToNonAD(j)
        k = jid_to_key(jj)
        if not k or k in seen:
            return
        seen.add(k)
        ordered.append(jj)

    _add(primary)
    try:
        if primary.Server == "lid":
            _add(await client.get_pn_from_lid(primary))
        else:
            lid = await client.get_lid_from_pn(primary)
            # 群反应优先试 LID（插到 primary 后、PN/其它之前）
            if jid_nonempty(lid):
                lid_n = JIDToNonAD(lid)
                k = jid_to_key(lid_n)
                if k and k not in seen:
                    seen.add(k)
                    # primary 已是手机号时，把 LID 放到最前
                    ordered.insert(0, lid_n)
    except Exception as exc:
        debug(f"[WA] 解析 LID/PN 备用失败（仍用主 JID）：{exc}")
    return ordered


async def canonical_sender_jid_for_reaction(client: NewAClient) -> Optional[JID]:
    """兼容旧调用：返回 sender_jids_for_reaction 的首选。"""
    jids = await sender_jids_for_reaction(client)
    return jids[0] if jids else None


async def whatsapp_send_reaction(
    client: NewAClient,
    chat_jid: JID,
    message_sender_jid: JID,
    message_id: str,
    emoji: str,
    *,
    message_sender_jids: Optional[List[JID]] = None,
) -> None:
    """对指定消息发送表情反应（群聊需原消息发送者的 participant JID，自动轮换 LID/手机号）。"""
    mid = (message_id or "").strip()
    if not mid:
        raise ValueError("message_id 为空")
    chat = JIDToNonAD(chat_jid)
    if not jid_nonempty(chat):
        raise ValueError("chat_jid 无效")

    candidates: List[JID] = []
    seen: Set[str] = set()
    for j in list(message_sender_jids or []) + [message_sender_jid]:
        if j is None or not jid_nonempty(j):
            continue
        jj = JIDToNonAD(j)
        k = jid_to_key(jj)
        if k in seen:
            continue
        seen.add(k)
        candidates.append(jj)
    if not candidates:
        raise ValueError("无法解析原消息发送者 JID")

    last_err: Optional[BaseException] = None
    for sender in candidates:
        try:
            reaction_msg = await client.build_reaction(chat, sender, mid, emoji)
            await client.send_message(chat, reaction_msg)
            return
        except Exception as exc:
            last_err = exc
            debug(
                f"[WA] 点赞尝试失败 participant={jid_to_key(sender)} "
                f"msg={mid}：{exc}"
            )
            continue
    raise RuntimeError(
        f"全部 participant 形态均失败（已试 {len(candidates)} 种）：{last_err}"
    )


async def _run_whatsapp_reaction_delayed(
    *,
    shared_clients: Dict[str, NewAClient],
    account_locks: Dict[str, asyncio.Lock],
    chat_jid: JID,
    message_id: str,
    message_sender_jid: JID,
    message_sender_jids: List[JID],
    acc_id: str,
    label: str,
    delay_sec: float,
) -> None:
    emoji = reaction_emoji_for_account(acc_id, is_main=(label == "主号"))
    try:
        await asyncio.sleep(delay_sec)
        client = shared_clients.get(acc_id)
        if client is None:
            warning(f"[WA] 定时点赞跳过：账号 {acc_id} 未连接（延迟后）")
            return
        lock = account_locks.get(acc_id)
        if lock is None:
            lock = asyncio.Lock()
            account_locks[acc_id] = lock
        async with lock:
            try:
                from group_auto_join import is_account_in_group
                from wa_jid import jid_to_key

                chat_ref = jid_to_key(chat_jid) if chat_jid is not None else ""
                if chat_ref and not await is_account_in_group(client, chat_ref):
                    debug(f"[WA] 定时点赞跳过：账号 {acc_id} 不在群内")
                    return
            except Exception:
                pass
            await whatsapp_send_reaction(
                client,
                chat_jid,
                message_sender_jid,
                message_id,
                emoji,
                message_sender_jids=message_sender_jids,
            )
        info(f"[WA] 定时点赞完成：账号={acc_id} 表情={emoji} 延迟={delay_sec / 60:.1f} 分钟")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        warning(f"[WA] 定时点赞失败：账号={acc_id} 表情={emoji} 错误={exc}")


def schedule_whatsapp_reactions(
    *,
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    chat_jid: JID,
    message_id: str,
    message_sender_jid: JID,
    sender_account_id: str,
    main_account_id: str,
    enabled_account_ids: Set[str],
    message_sender_jids: Optional[List[JID]] = None,
) -> int:
    """为每条消息排程延迟点赞；立即返回，各账号独立随机 1–10 分钟后执行。"""
    mid = (message_id or "").strip()
    if not mid:
        warning("[WA] 定时点赞跳过：无 message_id")
        return 0
    if not jid_nonempty(message_sender_jid) and not (
        message_sender_jids and any(jid_nonempty(j) for j in message_sender_jids)
    ):
        warning("[WA] 定时点赞跳过：无原消息发送者 JID")
        return 0
    reactors = pick_reaction_accounts(
        sender_account_id=sender_account_id,
        main_account_id=main_account_id,
        available_account_ids=enabled_account_ids,
    )
    if not reactors:
        warning(
            "[WA] 定时点赞跳过：无可用点赞账号"
            f"（发送账号={sender_account_id!r} 主号={main_account_id!r} "
            f"在线启用={sorted(enabled_account_ids)}；需有主号或简称含「女」「男」）"
        )
        return 0
    sender_jids = list(message_sender_jids or [])
    if not sender_jids and jid_nonempty(message_sender_jid):
        sender_jids = [message_sender_jid]
    scheduled = 0
    for label, acc_id in reactors:
        if shared_clients.get(acc_id) is None:
            warning(f"[WA] 定时点赞跳过：账号 {acc_id} 未连接")
            continue
        delay_sec = reaction_delay_seconds()
        task = asyncio.create_task(
            _run_whatsapp_reaction_delayed(
                shared_clients=shared_clients,
                account_locks=account_locks,
                chat_jid=chat_jid,
                message_id=mid,
                message_sender_jid=message_sender_jid
                if jid_nonempty(message_sender_jid)
                else sender_jids[0],
                message_sender_jids=sender_jids,
                acc_id=acc_id,
                label=label,
                delay_sec=delay_sec,
            )
        )
        _track_reaction_task(task)
        scheduled += 1
    return scheduled


__all__ = [
    "WaSentMessageMeta",
    "canonical_sender_jid_for_reaction",
    "schedule_whatsapp_reactions",
    "sender_jids_for_reaction",
    "whatsapp_send_reaction",
    "resolve_main_account_for_job_target",
]
