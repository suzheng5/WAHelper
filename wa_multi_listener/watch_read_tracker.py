"""监听目标消息：收到时记账，定时发送前由发送账号标已读（每号每条最多一次）。"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import RLock
from typing import Deque, Dict, List, Optional, Set, Tuple

from neonize.aioze.client import NewAClient
from neonize.proto.Neonize_pb2 import JID
from neonize.utils.enum import ReceiptType
from neonize.utils.jid import JIDToNonAD, jid_is_lid

from logger_util import debug, info, warning
from wa_jid import (
    keys_for_chat_ref,
    keys_for_match,
    jid_from_chat_key,
    jid_nonempty,
    jid_to_key,
)
from wa_send import resolve_chat_jid

_MAX_PENDING_PER_CHAT = 64
_MAX_MARKED = 8000


def _gus_base(jid_key: str) -> str:
    ck = (jid_key or "").lower()
    if "@g.us" not in ck:
        return ""
    return ck.split("@", 1)[0].split("-", 1)[0]


def _expand_chat_keys(keys: Set[str]) -> Set[str]:
    out: Set[str] = set()
    for k in keys:
        ck = (k or "").strip().lower()
        if not ck:
            continue
        out.add(ck)
        jid = jid_from_chat_key(ck)
        if jid is not None and jid_nonempty(jid):
            out.update(x.lower() for x in keys_for_match(jid))
    return out


def _pending_matches_chat(stored_key: str, query_keys: Set[str]) -> bool:
    """recorded chat_key 与发送目标 keys 是否同一会话（含 @g.us 变体）。"""
    sk = (stored_key or "").strip().lower()
    if not sk or not query_keys:
        return False
    q = _expand_chat_keys(query_keys)
    if sk in q:
        return True
    sj = jid_from_chat_key(sk)
    if sj is not None and jid_nonempty(sj):
        if set(x.lower() for x in keys_for_match(sj)) & q:
            return True
    sb = _gus_base(sk)
    if sb and any(_gus_base(x) == sb for x in q):
        return True
    return False


@dataclass
class WaPendingWatchMessage:
    chat_key: str
    msg_id: str
    chat_jid: JID
    sender_jid: JID
    ts: float
    """备选发送者 JID（如 LID 对应的手机号），mark_read 失败时轮换尝试。"""
    sender_alts: List[JID] = field(default_factory=list)


class WaWatchReadTracker:
    def __init__(self) -> None:
        self._lock = RLock()
        self._pending: Dict[str, List[WaPendingWatchMessage]] = {}
        self._marked: Set[Tuple[str, str, str]] = set()
        self._marked_order: Deque[Tuple[str, str, str]] = deque()

    def record(
        self,
        *,
        chat_key: str,
        msg_id: str,
        chat_jid: JID,
        sender_jid: JID,
        sender_alts: Optional[List[JID]] = None,
    ) -> None:
        ck = (chat_key or "").strip().lower()
        mid = (msg_id or "").strip()
        if not ck or not mid or not jid_nonempty(chat_jid) or not jid_nonempty(sender_jid):
            return
        alts: List[JID] = []
        for j in sender_alts or []:
            if jid_nonempty(j) and jid_to_key(j) != jid_to_key(sender_jid):
                alts.append(JIDToNonAD(j))
        with self._lock:
            lst = self._pending.setdefault(ck, [])
            if any(x.msg_id == mid for x in lst):
                return
            lst.append(
                WaPendingWatchMessage(
                    chat_key=ck,
                    msg_id=mid,
                    chat_jid=JIDToNonAD(chat_jid),
                    sender_jid=JIDToNonAD(sender_jid),
                    ts=time.time(),
                    sender_alts=alts,
                )
            )
            if len(lst) > _MAX_PENDING_PER_CHAT:
                self._pending[ck] = lst[-_MAX_PENDING_PER_CHAT:]

    def pick_for_send(self, account_id: str, chat_keys: Set[str]) -> Optional[WaPendingWatchMessage]:
        found = self.pick_all_for_send(account_id, chat_keys)
        return found[0] if found else None

    def pick_all_for_send(self, account_id: str, chat_keys: Set[str]) -> List[WaPendingWatchMessage]:
        """同一会话下、该账号尚未标过已读的全部待处理消息（按时间升序）。"""
        aid = (account_id or "").strip()
        if not aid or not chat_keys:
            return []
        out: List[WaPendingWatchMessage] = []
        with self._lock:
            for stored_key, lst in list(self._pending.items()):
                if not _pending_matches_chat(stored_key, chat_keys):
                    continue
                for p in lst:
                    if (aid, p.chat_key, p.msg_id) not in self._marked:
                        out.append(p)
        out.sort(key=lambda x: x.ts)
        return out

    def _trim_marked_locked(self) -> None:
        while len(self._marked_order) > _MAX_MARKED:
            old = self._marked_order.popleft()
            self._marked.discard(old)

    def mark_done(self, account_id: str, chat_key: str, msg_id: str) -> None:
        aid = (account_id or "").strip()
        ck = (chat_key or "").strip().lower()
        mid = (msg_id or "").strip()
        if not aid or not ck or not mid:
            return
        with self._lock:
            key = (aid, ck, mid)
            if key in self._marked:
                return
            self._marked.add(key)
            self._marked_order.append(key)
            self._trim_marked_locked()


async def _resolve_chat_keys(client: NewAClient, chat_ref: str) -> Set[str]:
    keys = keys_for_chat_ref(chat_ref)
    if keys:
        return keys
    try:
        jid = await resolve_chat_jid(client, chat_ref)
        return set(keys_for_match(jid))
    except Exception:
        return set()


def _sender_candidates(pending: WaPendingWatchMessage) -> List[JID]:
    """LID 优先试手机号 SenderAlt，再试主 sender。"""
    ordered: List[JID] = []
    primary = pending.sender_jid
    alts = list(pending.sender_alts or [])
    if jid_is_lid(primary):
        ordered.extend(alts)
        ordered.append(primary)
    else:
        ordered.append(primary)
        ordered.extend(alts)
    seen: Set[str] = set()
    out: List[JID] = []
    for j in ordered:
        if not jid_nonempty(j):
            continue
        k = jid_to_key(j)
        if k in seen:
            continue
        seen.add(k)
        out.append(j)
    return out


async def mark_wa_watch_message_read(client: NewAClient, pending: WaPendingWatchMessage) -> bool:
    last_err = ""
    for sender in _sender_candidates(pending):
        try:
            await client.mark_read(
                pending.msg_id,
                chat=pending.chat_jid,
                sender=sender,
                receipt=ReceiptType.READ,
            )
            return True
        except Exception as exc:
            last_err = str(exc)
            continue
    warning(
        f"监听目标已读标记失败（不影响发送）：群={pending.chat_key} "
        f"msg={pending.msg_id} {last_err}"
    )
    return False


async def mark_wa_watch_messages_read_batch(
    client: NewAClient,
    pendings: List[WaPendingWatchMessage],
) -> List[WaPendingWatchMessage]:
    """尽量一次标多条；失败则逐条回退。返回成功已读的 pending。"""
    if not pendings:
        return []
    # 同 chat + 同主 sender 可批量
    by_pair: Dict[Tuple[str, str], List[WaPendingWatchMessage]] = {}
    for p in pendings:
        key = (p.chat_key, jid_to_key(p.sender_jid))
        by_pair.setdefault(key, []).append(p)

    ok_list: List[WaPendingWatchMessage] = []
    for _key, group in by_pair.items():
        # 优先用候选 sender 里第一个能成功批量的
        ids = [p.msg_id for p in group]
        sample = group[0]
        batch_ok = False
        for sender in _sender_candidates(sample):
            try:
                await client.mark_read(
                    *ids,
                    chat=sample.chat_jid,
                    sender=sender,
                    receipt=ReceiptType.READ,
                )
                ok_list.extend(group)
                batch_ok = True
                break
            except Exception:
                continue
        if batch_ok:
            continue
        for p in group:
            if await mark_wa_watch_message_read(client, p):
                ok_list.append(p)
    return ok_list


async def mark_watch_read_before_send(
    client: NewAClient,
    account_id: str,
    chat_ref: str,
    tracker: Optional[WaWatchReadTracker],
) -> None:
    if tracker is None:
        return
    keys = await _resolve_chat_keys(client, chat_ref)
    if not keys:
        debug(f"发送前已读跳过：无法解析会话键 chat_ref={chat_ref!r}")
        return
    pendings = tracker.pick_all_for_send(account_id, keys)
    if not pendings:
        return
    succeeded = await mark_wa_watch_messages_read_batch(client, pendings)
    for p in succeeded:
        tracker.mark_done(account_id, p.chat_key, p.msg_id)
    if succeeded:
        info(
            f"发送前已读：账号={account_id} 会话={pendings[0].chat_key} "
            f"成功 {len(succeeded)}/{len(pendings)} 条"
        )
    elif pendings:
        warning(
            f"发送前已读未成功：账号={account_id} 会话键={sorted(keys)[:3]} "
            f"待处理={len(pendings)}"
        )
