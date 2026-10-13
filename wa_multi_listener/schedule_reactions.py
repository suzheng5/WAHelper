"""定时任务：本条消息发送后的延迟表情点赞（排除发送账号，其余角色随机 1–2 人）。"""
from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, List, Set, Tuple, Union


def _tg_log():
    from tg_multi_listener.logger_util import debug, error, info, warning

    return debug, error, info, warning


_HEART = "❤️"
_THUMBS = "👍"
_REACTION_DELAY_MIN_SEC = 60.0
_REACTION_DELAY_MAX_SEC = 600.0
_PENDING_REACTION_TASKS: Set[asyncio.Task[Any]] = set()

# 兼容旧测试/导入名（逻辑已改为按账号简称含「女」「男」匹配）
REACTION_ROLE_LABELS: Tuple[str, ...] = ("女一", "女二", "男二", "主号")


def reaction_delay_seconds() -> float:
    """每条点赞独立随机等待 1–10 分钟（秒）。"""
    return random.uniform(_REACTION_DELAY_MIN_SEC, _REACTION_DELAY_MAX_SEC)


def reaction_emoji_for_account(account_id: str, *, is_main: bool = False) -> str:
    """主号与带「女」的简称 → 爱心；带「男」的简称 → 拇指。"""
    if is_main:
        return _HEART
    aid = (account_id or "").strip()
    if "男" in aid:
        return _THUMBS
    return _HEART


def reaction_emoji_for_role_label(label: str) -> str:
    """兼容旧接口：仅「男*」为拇指，其余爱心；「主号」为爱心。"""
    lab = (label or "").strip()
    if lab == "主号":
        return _HEART
    return reaction_emoji_for_account(lab, is_main=False)


def _account_is_female_like(account_id: str) -> bool:
    return "女" in (account_id or "")


def _account_is_male_like(account_id: str) -> bool:
    return "男" in (account_id or "")


def pick_reaction_accounts(
    *,
    sender_account_id: str,
    main_account_id: str,
    available_account_ids: Set[str],
) -> List[Tuple[str, str]]:
    """
    点赞池：主号 + 简称含「女」或「男」的启用账号；排除本条发送账号。
    返回 (角色标签, 账号简称)；主号槽标签固定为「主号」（爱心）。
    """
    sender = (sender_account_id or "").strip()
    main = (main_account_id or "").strip()
    avail = {(a or "").strip() for a in available_account_ids if (a or "").strip()}
    pool: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    def _add(label: str, acc: str) -> None:
        a = (acc or "").strip()
        if not a or a == sender or a not in avail or a in seen:
            return
        seen.add(a)
        pool.append((label, a))

    # 主号（可对应该群当前归属账号，切换批超群号后仍用通讯录 owner）
    if main:
        _add("主号", main)

    for acc in sorted(avail):
        if acc in seen or acc == sender:
            continue
        if _account_is_female_like(acc) or _account_is_male_like(acc):
            _add(acc, acc)

    if not pool:
        return []
    count = random.randint(1, min(2, len(pool)))
    return random.sample(pool, count)


def _track_reaction_task(task: asyncio.Task[Any]) -> None:
    _PENDING_REACTION_TASKS.add(task)
    task.add_done_callback(_PENDING_REACTION_TASKS.discard)


async def _resolve_telegram_entity_for_send(client: Any, chat_ref: Union[int, str]) -> Any:
    if isinstance(chat_ref, str):
        s = chat_ref.strip()
        if not s:
            raise ValueError("empty chat ref")
        if (s.startswith("-") and len(s) > 1 and s[1:].isdigit()) or (s.isdigit() and not s.startswith("@")):
            chat_ref = int(s)
        else:
            try:
                return await client.get_entity(s)
            except Exception:
                await client.get_dialogs(limit=500)
                return await client.get_entity(s)
    cid = int(chat_ref)
    try:
        return await client.get_entity(cid)
    except Exception:
        await client.get_dialogs(limit=500)
        return await client.get_entity(cid)


async def telegram_react_once(client: Any, entity: Any, msg_id: int, emoji: str) -> None:
    from telethon.tl.functions.messages import SendReactionRequest
    from telethon.tl.types import ReactionEmoji

    await client(
        SendReactionRequest(
            peer=entity,
            msg_id=int(msg_id),
            reaction=[ReactionEmoji(emoticon=emoji)],
        )
    )


async def _run_telegram_reaction_delayed(
    *,
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    chat_ref: Union[int, str],
    msg_id: int,
    acc_id: str,
    label: str,
    delay_sec: float,
) -> None:
    _debug, _error, _info, _warning = _tg_log()
    emoji = reaction_emoji_for_account(acc_id, is_main=(label == "主号"))
    try:
        await asyncio.sleep(delay_sec)
        client = shared_clients.get(acc_id)
        if client is None:
            _warning(f"[TG] 定时点赞跳过：账号 {acc_id} 未连接（延迟后）")
            return
        lock = account_locks.get(acc_id)
        if lock is None:
            lock = asyncio.Lock()
            account_locks[acc_id] = lock
        async with lock:
            if not await client.is_user_authorized():
                _warning(f"[TG] 定时点赞跳过：账号 {acc_id} 未登录（延迟后）")
                return
            try:
                from tg_multi_listener.group_auto_join import is_account_in_group

                if not await is_account_in_group(client, chat_ref):
                    _debug(f"[TG] 定时点赞跳过：账号 {acc_id} 不在群内")
                    return
            except Exception:
                pass
            entity = await _resolve_telegram_entity_for_send(client, chat_ref)
            await telegram_react_once(client, entity, msg_id, emoji)
        _info(f"[TG] 定时点赞完成：账号={acc_id} 表情={emoji} 延迟={delay_sec / 60:.1f} 分钟")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _warning(f"[TG] 定时点赞失败：账号={acc_id} 表情={emoji} 错误={exc}")


def schedule_telegram_reactions(
    *,
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    chat_ref: Union[int, str],
    msg_id: int,
    sender_account_id: str,
    main_account_id: str,
    enabled_account_ids: Set[str],
) -> int:
    """为每条消息排程延迟点赞；立即返回，各账号独立随机 1–10 分钟后执行。"""
    _debug, _error, _info, _warning = _tg_log()
    reactors = pick_reaction_accounts(
        sender_account_id=sender_account_id,
        main_account_id=main_account_id,
        available_account_ids=enabled_account_ids,
    )
    if not reactors:
        _warning(
            "[TG] 定时点赞跳过：无可用点赞账号"
            f"（发送={sender_account_id!r} 主号={main_account_id!r} "
            f"启用={sorted(enabled_account_ids)}；需有主号或简称含「女」「男」）"
        )
        return 0
    scheduled = 0
    for label, acc_id in reactors:
        if shared_clients.get(acc_id) is None:
            _warning(f"[TG] 定时点赞跳过：账号 {acc_id} 未连接")
            continue
        delay_sec = reaction_delay_seconds()
        task = asyncio.create_task(
            _run_telegram_reaction_delayed(
                shared_clients=shared_clients,
                account_locks=account_locks,
                chat_ref=chat_ref,
                msg_id=msg_id,
                acc_id=acc_id,
                label=label,
                delay_sec=delay_sec,
            )
        )
        _track_reaction_task(task)
        scheduled += 1
    return scheduled


# 兼容旧调用名（现为排程，非立即执行）
apply_telegram_scheduled_reactions = schedule_telegram_reactions


def resolve_main_account_for_job_target(cfg: Any, job: Any, chat_ref: Any) -> str:
    """从通讯录解析该发送目标对应的群主号/归属账号。"""
    emap = {e.id: e for e in getattr(cfg, "address_book", []) or []}
    ref_s = str(chat_ref or "").strip()
    for eid in getattr(job, "chat_entry_ids", None) or []:
        ent = emap.get(str(eid))
        if not ent:
            continue
        owner = (getattr(ent, "owner_account_id", None) or "").strip()
        if not owner:
            continue
        ent_ref = (getattr(ent, "chat_ref", None) or "").strip()
        ent_id = str(getattr(ent, "chat_id", None) or "").strip()
        if ref_s and (ref_s == ent_ref or ref_s == ent_id):
            return owner
    for eid in getattr(job, "chat_entry_ids", None) or []:
        ent = emap.get(str(eid))
        if ent:
            owner = (getattr(ent, "owner_account_id", None) or "").strip()
            if owner:
                return owner
    # 文件夹/旧任务无 entry_ids：按 chat_ref 反查通讯录归属（切换批超群号后仍能点赞）
    if ref_s:
        for ent in getattr(cfg, "address_book", []) or []:
            ent_ref = (getattr(ent, "chat_ref", None) or "").strip()
            ent_id = str(getattr(ent, "chat_id", None) or "").strip()
            if ref_s == ent_ref or ref_s == ent_id:
                owner = (getattr(ent, "owner_account_id", None) or "").strip()
                if owner:
                    return owner
    return ""
