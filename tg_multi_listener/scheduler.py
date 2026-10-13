"""文档式循环发送任务：按随机分钟间隔发送，可暂停/继续/自动暂停。"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from telethon import TelegramClient

from .compat_config import (
    Account,
    AppConfig,
    SCHEDULE_FILE,
    chat_peer_ids_for_match,
    ensure_dirs,
    format_job_targets_label,
    load_config,
    record_address_book_last_schedule,
    resolve_job_chat_targets,
    telegram_chat_matches_address_ref,
)
from .job_file_cache import load_jobs_cached, runner_loop_sleep_seconds, set_jobs_cache
from .logger_util import debug, error, info, warning
from .watch_read_tracker import TgWatchReadTracker, mark_watch_read_before_send

from i18n.job_card import format_job_status_label
from i18n.pause_reason import (
    CODE_AWAIT_IMAGE_SEND,
    CODE_JOIN_GROUP_FAILED,
    CODE_LISTEN_HIT,
    CODE_MANUAL,
    CODE_MIGRATED,
    CODE_NEW_JOB,
    CODE_ROUND_COMPLETE,
    CODE_STAGE_LISTEN_HIT,
    CODE_STAGE_REMINDER,
    CODE_STARTUP_DOC,
    is_await_image_send,
    pause_reason_is,
    resolve_listen_pause_reason,
)


async def send_telegram_message_resilient(client: TelegramClient, entity: Any, text: str, *, attempts: int = 6) -> Any:
    """发送消息；遇 session SQLite「database is locked」时短暂退避重试（多开/外占库时常见）。"""
    delay = 0.2
    last: Optional[BaseException] = None
    for i in range(max(1, attempts)):
        try:
            return await client.send_message(entity, text)
        except Exception as exc:
            last = exc
            msg = str(exc).lower()
            if "database is locked" in msg or "unable to open database" in msg:
                if i + 1 < attempts:
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.8, 2.5)
                    continue
            raise
    if last:
        raise last


async def send_telegram_file_resilient(
    client: TelegramClient,
    entity: Any,
    file_path: str,
    *,
    caption: str = "",
    attempts: int = 6,
) -> Any:
    """发送图片/文件；遇 session SQLite locked 时短暂退避重试。"""
    delay = 0.2
    last: Optional[BaseException] = None
    cap = (caption or "").strip() or None
    for i in range(max(1, attempts)):
        try:
            return await client.send_file(entity, file_path, caption=cap)
        except Exception as exc:
            last = exc
            msg = str(exc).lower()
            if "database is locked" in msg or "unable to open database" in msg:
                if i + 1 < attempts:
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.8, 2.5)
                    continue
            raise
    if last:
        raise last


async def _resolve_entity_for_send(client: TelegramClient, chat_ref: Union[int, str]) -> Any:
    """把群 ID（整数）或 @用户名 / t.me / 邀请链接等解析为可发送对象。"""
    if isinstance(chat_ref, str):
        s = chat_ref.strip()
        if not s:
            raise ValueError("empty chat ref")
        if (s.startswith("-") and len(s) > 1 and s[1:].isdigit()) or (s.isdigit() and not s.startswith("@")):
            chat_ref = int(s)
        else:
            from .group_auto_join import tg_invite_hash

            inv = tg_invite_hash(s)
            if inv:
                from telethon.tl.functions.messages import CheckChatInviteRequest
                from telethon.tl.types import ChatInviteAlready

                res = await client(CheckChatInviteRequest(inv))
                if isinstance(res, ChatInviteAlready) and getattr(res, "chat", None) is not None:
                    return res.chat
                raise ValueError("尚未加入该邀请链接对应的群（请等待自动入群或手动加入）")
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


@dataclass
class DocMessage:
    account_id: str
    content: str
    is_reminder: bool = False
    reminder_note: str = ""
    """本条执行完后，等待多少分钟再执行下一条（最后一条可忽略）。"""
    delay_after_minutes: float = 0.0
    """TXT 中的原文账号（与 account_id 一致）；实际发送可用 send_as_account_id 覆盖。"""
    original_account_id: str = ""
    send_as_account_id: str = ""
    """True 表示本条 间隔= 来自 TXT；否则发完后用任务级固定间隔。"""
    interval_from_txt: bool = False
    want_reactions: bool = False
    """TXT「类型=发图」：不发送正文，暂停待任务管理一键发图。"""
    is_image_send: bool = False

    def effective_send_account_id(self) -> str:
        return (self.send_as_account_id or self.original_account_id or self.account_id or "").strip()

    def original_label(self) -> str:
        return (self.original_account_id or self.account_id or "").strip()

    def is_non_send_step(self) -> bool:
        return bool(self.is_reminder or self.is_image_send)


@dataclass
class ScheduledJob:
    id: str
    enabled: bool
    chat_ids: List[int]
    interval_min_minutes: float
    interval_max_minutes: float
    source_path: str
    source_name: str
    items: List[DocMessage] = field(default_factory=list)
    # 非空时发送目标以通讯录为准（chat_ids 仍保留数字 ID 便于监听命中暂停）
    chat_entry_ids: List[str] = field(default_factory=list)
    cursor: int = 0
    state: str = "running"  # running | paused
    pause_reason: str = ""
    next_send_ts: float = 0.0
    remaining_seconds: float = 0.0
    last_send_ts: float = 0.0
    last_error: str = ""
    # txt：每条 间隔= ；fixed：界面填写的 X-X 分钟（TXT 未写间隔时）
    interval_mode: str = "txt"
    # file=单 TXT；folder=文件夹内按天 TXT（folder_files 为相对路径列表）
    source_kind: str = "file"
    folder_path: str = ""
    folder_files: List[str] = field(default_factory=list)
    folder_day_index: int = 0

    @staticmethod
    def new(
        chat_ids: List[int],
        source_path: str,
        items: List[DocMessage],
        chat_entry_ids: Optional[List[str]] = None,
        *,
        interval_min_minutes: float = 0.0,
        interval_max_minutes: float = 0.0,
        interval_mode: str = "txt",
        start_paused: bool = True,
    ) -> "ScheduledJob":
        source_name = os.path.basename(source_path) or "未命名文档"
        ce = [str(x) for x in (chat_entry_ids or []) if str(x).strip()]
        paused = bool(start_paused)
        return ScheduledJob(
            id=uuid.uuid4().hex[:12],
            enabled=True,
            chat_ids=[int(x) for x in chat_ids],
            interval_min_minutes=float(interval_min_minutes),
            interval_max_minutes=float(interval_max_minutes),
            interval_mode=str(interval_mode or "txt"),
            source_path=source_path,
            source_name=source_name,
            items=items,
            chat_entry_ids=ce,
            cursor=0,
            state="paused" if paused else "running",
            pause_reason=NEW_JOB_PAUSE_REASON if paused else "",
            next_send_ts=0.0 if paused else time.time(),
        )

    def item_count(self) -> int:
        return len(self.items)

    def send_progress(self) -> tuple[int, int, int]:
        """返回 (待发消息总数, 已发消息数, 剩余待发消息数)；不含阶段提醒/发图步。"""
        total = sum(1 for it in self.items if not it.is_non_send_step())
        c = max(0, min(int(self.cursor), len(self.items)))
        done = sum(1 for it in self.items[:c] if not it.is_non_send_step())
        return total, done, max(0, total - done)

    def current_item(self) -> Optional[DocMessage]:
        if not self.items:
            return None
        if self.cursor < 0 or self.cursor >= len(self.items):
            return None
        return self.items[self.cursor]


def _job_to_dict(j: ScheduledJob) -> Dict:
    d = asdict(j)
    d["items"] = [asdict(x) for x in j.items]
    return d


def _doc_from_dict(x: Dict[str, Any], *, legacy_gap_min: float = 5.0, legacy_gap_max: float = 5.0) -> Optional[DocMessage]:
    if not isinstance(x, dict):
        return None
    acc = str(x.get("account_id", "")).strip()
    orig = str(x.get("original_account_id", "") or acc).strip()
    send = str(x.get("send_as_account_id", "") or orig or acc).strip()
    txt = str(x.get("content", "")).strip()
    is_rem = bool(x.get("is_reminder", False))
    note = str(x.get("reminder_note", "") or "").strip()
    delay_raw = x.get("delay_after_minutes")
    if delay_raw is not None and str(delay_raw).strip() != "":
        try:
            delay_m = max(0.0, float(delay_raw))
        except (TypeError, ValueError):
            delay_m = max(0.1, float(legacy_gap_min))
    else:
        lo = max(0.1, float(legacy_gap_min))
        hi = max(lo, float(legacy_gap_max))
        delay_m = random.uniform(lo, hi) if hi > lo else lo
    from_txt = bool(x.get("interval_from_txt", False))
    want_rx = bool(x.get("want_reactions", False))
    is_img = bool(x.get("is_image_send", False))
    if is_rem:
        return DocMessage(
            account_id=acc,
            content=txt,
            is_reminder=True,
            reminder_note=note,
            delay_after_minutes=delay_m,
            original_account_id=orig,
            send_as_account_id=send,
            interval_from_txt=from_txt,
            want_reactions=want_rx,
            is_image_send=False,
        )
    if is_img and (orig or acc):
        return DocMessage(
            account_id=orig or acc,
            content="",
            is_reminder=False,
            reminder_note=note,
            delay_after_minutes=delay_m,
            original_account_id=orig or acc,
            send_as_account_id=send or orig or acc,
            interval_from_txt=from_txt,
            want_reactions=False,
            is_image_send=True,
        )
    if acc and txt:
        return DocMessage(
            account_id=orig or acc,
            content=txt,
            is_reminder=False,
            reminder_note="",
            delay_after_minutes=delay_m,
            original_account_id=orig or acc,
            send_as_account_id=send or orig or acc,
            interval_from_txt=from_txt,
            want_reactions=want_rx,
            is_image_send=False,
        )
    return None


def migrate_schedule2_into_schedules_once() -> int:
    """将旧版 schedule2.json 任务合并进 schedules.json（仅执行一次）。"""
    from .compat_config import SCHEDULE2_FILE

    if not os.path.isfile(SCHEDULE2_FILE):
        return 0
    marker = SCHEDULE2_FILE + ".migrated"
    if os.path.isfile(marker):
        return 0
    try:
        from .schedule2_runner import load_schedule2_jobs
    except ImportError:
        return 0
    s2_jobs = load_schedule2_jobs()
    if not s2_jobs:
        try:
            with open(marker, "w", encoding="utf-8") as f:
                f.write("empty\n")
        except OSError:
            pass
        return 0
    jobs = _load_jobs_raw()
    existing = {j.id for j in jobs}
    added = 0
    for sj in s2_jobs:
        if sj.id in existing:
            continue
        items: List[DocMessage] = []
        for r in sj.rows:
            items.append(
                DocMessage(
                    account_id=r.original_account_id or r.send_as_account_id,
                    content=r.content,
                    is_reminder=r.is_reminder,
                    reminder_note=r.reminder_note,
                    delay_after_minutes=0.0,
                    original_account_id=r.original_account_id,
                    send_as_account_id=r.send_as_account_id,
                    interval_from_txt=False,
                    want_reactions=bool(getattr(r, "want_reactions", False)),
                )
            )
        if not items:
            continue
        jobs.append(
            ScheduledJob(
                id=sj.id,
                enabled=sj.enabled,
                chat_ids=list(sj.chat_ids),
                interval_min_minutes=float(sj.interval_min_minutes),
                interval_max_minutes=float(sj.interval_max_minutes),
                interval_mode="fixed",
                source_path=sj.source_path,
                source_name=sj.source_name,
                items=items,
                chat_entry_ids=list(sj.chat_entry_ids),
                cursor=sj.cursor,
                state=sj.state if sj.state in ("running", "paused") else "paused",
                pause_reason=sj.pause_reason or CODE_MIGRATED,
                next_send_ts=sj.next_send_ts,
                remaining_seconds=sj.remaining_seconds,
                last_send_ts=sj.last_send_ts,
                last_error=sj.last_error,
            )
        )
        added += 1
    if added:
        save_jobs(jobs)
        info(f"已将 {added} 个旧「定时任务2」合并到「定时任务」。")
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(f"migrated {added}\n")
    except OSError:
        pass
    return added


def _load_jobs_raw() -> List[ScheduledJob]:
    ensure_dirs()
    if not os.path.isfile(SCHEDULE_FILE):
        return []
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    jobs: List[ScheduledJob] = []
    if not isinstance(raw, list):
        return jobs
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            # 兼容旧版按时任务：跳过旧结构。
            if "items" not in row:
                continue
            items_raw = row.get("items", [])
            items: List[DocMessage] = []
            min_m = float(row.get("interval_min_minutes", 5.0))
            max_m = float(row.get("interval_max_minutes", min_m))
            if min_m <= 0:
                min_m = 0.1
            if max_m < min_m:
                max_m = min_m
            for x in items_raw:
                dm = _doc_from_dict(
                    x if isinstance(x, dict) else {},
                    legacy_gap_min=min_m,
                    legacy_gap_max=max_m,
                )
                if dm is not None:
                    items.append(dm)
            if not items:
                continue
            chats_raw = row.get("chat_ids")
            chat_ids: List[int] = []
            if isinstance(chats_raw, list):
                chat_ids = [int(x) for x in chats_raw]
            elif "chat_id" in row:
                chat_ids = [int(row["chat_id"])]
            ce_raw = row.get("chat_entry_ids")
            chat_entry_ids: List[str] = []
            if isinstance(ce_raw, list):
                chat_entry_ids = [str(x) for x in ce_raw if str(x).strip()]
            if not chat_ids and not chat_entry_ids:
                continue
            jobs.append(
                ScheduledJob(
                    id=str(row.get("id", uuid.uuid4().hex[:12])),
                    enabled=bool(row.get("enabled", True)),
                    chat_ids=chat_ids,
                    interval_min_minutes=min_m,
                    interval_max_minutes=max_m,
                    source_path=str(row.get("source_path", "")),
                    source_name=str(row.get("source_name", "")) or os.path.basename(str(row.get("source_path", ""))),
                    items=items,
                    chat_entry_ids=chat_entry_ids,
                    cursor=max(0, int(row.get("cursor", 0))),
                    state=str(row.get("state", "running")) if str(row.get("state", "running")) in ("running", "paused") else "running",
                    pause_reason=str(row.get("pause_reason", "")),
                    next_send_ts=float(row.get("next_send_ts", 0.0)),
                    remaining_seconds=max(0.0, float(row.get("remaining_seconds", 0.0))),
                    last_send_ts=float(row.get("last_send_ts", 0.0)),
                    last_error=str(row.get("last_error", "")),
                    interval_mode=str(row.get("interval_mode", "txt") or "txt"),
                    source_kind=str(row.get("source_kind", "file") or "file"),
                    folder_path=str(row.get("folder_path", "") or ""),
                    folder_files=[
                        str(x) for x in (row.get("folder_files") or []) if str(x).strip()
                    ],
                    folder_day_index=max(0, int(row.get("folder_day_index", 0) or 0)),
                )
            )
        except (TypeError, ValueError, KeyError):
            continue
    return jobs


def load_jobs(*, force: bool = False) -> List[ScheduledJob]:
    migrate_schedule2_into_schedules_once()
    return load_jobs_cached(SCHEDULE_FILE, _load_jobs_raw, force=force)


def save_jobs(jobs: List[ScheduledJob]) -> None:
    from json_atomic import atomic_write_json

    ensure_dirs()
    atomic_write_json(SCHEDULE_FILE, [_job_to_dict(j) for j in jobs])
    set_jobs_cache(SCHEDULE_FILE, jobs)


def save_jobs_patch(updated: List[ScheduledJob]) -> None:
    """仅合并写入有变动的任务，避免后台循环用旧快照覆盖 UI 刚保存的「实际发送账号」等设置。"""
    if not updated:
        return
    fresh = load_jobs()
    by_id = {j.id: j for j in fresh}
    order = [j.id for j in fresh]
    for j in updated:
        existing = by_id.get(j.id)
        if existing is not None:
            from schedule_folder import merge_folder_job_patch

            j = merge_folder_job_patch(existing, j)
        by_id[j.id] = j
        if j.id not in order:
            order.append(j.id)
    save_jobs([by_id[jid] for jid in order])


def _reload_folder_day_items_tg(job: ScheduledJob, cfg: AppConfig, rel_name: str) -> tuple[bool, str]:
    from .group_owner import apply_main_account_mapping, clone_doc_items, doc_has_main_account_placeholder
    from .schedule_txt_import import import_doc_items

    from schedule_folder import read_folder_txt_utf8

    text, err = read_folder_txt_utf8(job.folder_path, rel_name)
    if err:
        return False, err
    valid = {a.id for a in cfg.accounts if getattr(a, "enabled", True)}
    items, _errors = import_doc_items(text, valid_accounts=valid, require_per_item_interval=False)
    sends = [it for it in items if not it.is_reminder]
    if not sends:
        return False, "TXT 中没有可发送条目"
    if doc_has_main_account_placeholder(items):
        emap = {e.id: e for e in cfg.address_book}
        owner = ""
        for eid in job.chat_entry_ids:
            ent = emap.get(eid)
            if ent:
                owner = (ent.owner_account_id or "").strip()
                break
        if not owner:
            return False, "未在通讯录设置归属账号"
        if owner not in valid:
            return False, f"归属账号「{owner}」未启用"
        job_items = clone_doc_items(items)
        if apply_main_account_mapping(job_items, owner) == 0:
            return False, "文档中未找到 账号=主号（或主账号）条目"
        items = job_items
    abs_path = os.path.join(os.path.abspath(job.folder_path), rel_name)
    job.items = items
    job.source_path = abs_path
    job.source_name = os.path.basename(abs_path) or rel_name
    return True, ""


def advance_scheduled_folder_day(job: ScheduledJob, cfg: AppConfig) -> tuple[bool, str]:
    """文件夹任务进入下一天：加载下一份 TXT 并开始发送（会中断当前天）。"""
    from schedule_folder import can_advance_folder_day

    if not can_advance_folder_day(job):
        return False, "已是最后一天或不是文件夹任务"
    next_index = int(job.folder_day_index) + 1
    from schedule_folder import resolve_folder_day_filename

    rel = resolve_folder_day_filename(job.folder_path, job.folder_files[next_index])
    ok, err = _reload_folder_day_items_tg(job, cfg, rel)
    if not ok:
        return False, err
    job.folder_files[next_index] = rel
    job.folder_day_index = next_index
    job.cursor = 0
    job.enabled = True
    job.state = "running"
    job.pause_reason = ""
    from schedule_folder import random_folder_advance_delay_seconds

    job.next_send_ts = time.time() + random_folder_advance_delay_seconds()
    job.remaining_seconds = 0.0
    job.last_error = ""
    return True, ""


def reload_scheduled_folder_scripts(job: ScheduledJob, cfg: AppConfig) -> tuple[bool, str]:
    """重新扫描文件夹并重读「当前天」TXT（不切天、不改暂停/启用），光标钳制到新长度。"""
    from schedule_folder import is_folder_job, rescan_folder_files_keep_day, resolve_folder_day_filename

    if not is_folder_job(job):
        return False, "不是文件夹任务"
    ordered, new_idx, err = rescan_folder_files_keep_day(job)
    if err:
        return False, err
    rel = resolve_folder_day_filename(job.folder_path, ordered[new_idx])
    ok, rerr = _reload_folder_day_items_tg(job, cfg, rel)
    if not ok:
        return False, rerr
    job.folder_files = list(ordered)
    job.folder_files[new_idx] = rel
    job.folder_day_index = new_idx
    n = len(job.items or [])
    job.cursor = max(0, min(int(job.cursor or 0), n))
    job.last_error = ""
    return True, ""


def reload_scheduled_file_script(job: ScheduledJob, cfg: AppConfig) -> tuple[bool, str]:
    """重读单 TXT 任务话术，保留并钳制 cursor。"""
    from .group_owner import apply_main_account_mapping, clone_doc_items, doc_has_main_account_placeholder
    from .schedule_txt_import import import_doc_items

    path = (job.source_path or "").strip()
    if not path:
        return False, "任务未记录 TXT 路径"
    if not os.path.isfile(path):
        return False, f"找不到 TXT：{path}"
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as exc:
        return False, f"读取失败：{exc}"
    valid = {a.id for a in cfg.accounts if getattr(a, "enabled", True)}
    items, _errors = import_doc_items(
        text, valid_accounts=valid, require_per_item_interval=False
    )
    sends = [it for it in items if not it.is_reminder]
    if not sends:
        return False, "TXT 中没有可发送条目"
    if doc_has_main_account_placeholder(items):
        emap = {e.id: e for e in cfg.address_book}
        owner = ""
        for eid in job.chat_entry_ids:
            ent = emap.get(eid)
            if ent:
                owner = (ent.owner_account_id or "").strip()
                break
        if not owner:
            return False, "未在通讯录设置归属账号"
        if owner not in valid:
            return False, f"归属账号「{owner}」未启用"
        job_items = clone_doc_items(items)
        if apply_main_account_mapping(job_items, owner) == 0:
            return False, "文档中未找到 账号=主号（或主账号）条目"
        items = job_items
    job.items = items
    job.source_name = os.path.basename(path) or job.source_name
    n = len(job.items or [])
    job.cursor = max(0, min(int(job.cursor or 0), n))
    job.last_error = ""
    return True, ""


def reload_scheduled_job_scripts(job: ScheduledJob, cfg: AppConfig) -> tuple[bool, str]:
    """重读任务当前话术：文件夹=当前天；单文件=source_path。从原步数继续。"""
    from schedule_folder import is_folder_job

    if is_folder_job(job):
        return reload_scheduled_folder_scripts(job, cfg)
    return reload_scheduled_file_script(job, cfg)


def bulk_reload_scheduled_job_scripts(
    jobs: Optional[List[ScheduledJob]] = None,
    cfg: Optional[AppConfig] = None,
) -> tuple[int, int, List[str]]:
    """批量重读全部任务当前话术。返回 (成功, 失败, 失败摘要)。"""
    if cfg is None:
        cfg = load_config()
    if jobs is None:
        jobs = load_jobs()
    ok_n = fail_n = 0
    fails: List[str] = []
    touched: List[ScheduledJob] = []
    for j in jobs:
        path = (getattr(j, "source_path", "") or "").strip()
        folder = (getattr(j, "folder_path", "") or "").strip()
        if not path and not folder:
            continue
        ok, err = reload_scheduled_job_scripts(j, cfg)
        if ok:
            ok_n += 1
            touched.append(j)
        else:
            fail_n += 1
            if len(fails) < 8:
                fails.append(f"{j.source_name or j.id}: {err}")
    if touched:
        save_jobs_patch(touched)
    return ok_n, fail_n, fails


STARTUP_PAUSE_REASON = CODE_STARTUP_DOC
NEW_JOB_PAUSE_REASON = CODE_NEW_JOB
STAGE_REMINDER_PAUSE_REASON = CODE_STAGE_REMINDER
AWAIT_IMAGE_SEND_PAUSE_REASON = CODE_AWAIT_IMAGE_SEND
JOIN_GROUP_FAILED_PAUSE_REASON = CODE_JOIN_GROUP_FAILED
LISTEN_HIT_PAUSE_REASON = CODE_LISTEN_HIT
STAGE_LISTEN_HIT_PAUSE_REASON = CODE_STAGE_LISTEN_HIT

# 点「继续/开始」或阶段提醒后继续：随机 30–60 秒再发，避免多任务同一时刻并发。
RESUME_RANDOM_DELAY_MIN_SEC = 30.0
RESUME_RANDOM_DELAY_MAX_SEC = 60.0
# 多群同时到点时并发处理；同一账号保留较小并发，避免几十个任务串行排队数分钟。
GLOBAL_SEND_CONCURRENCY = 16
PER_ACCOUNT_SEND_CONCURRENCY = 4


def _doc_job_by_id(job_id: str, jobs: Optional[List[ScheduledJob]] = None) -> Optional[ScheduledJob]:
    if jobs is None:
        jobs = load_jobs()
    return next((x for x in jobs if x.id == job_id), None)


def is_doc_job_send_allowed(job_id: str) -> bool:
    j = _doc_job_by_id(job_id)
    return bool(j and j.enabled and j.state != "paused")


def _safe_patch_doc_jobs(updated: List[ScheduledJob]) -> None:
    to_write: List[ScheduledJob] = []
    fresh_by_id = {j.id: j for j in load_jobs()}
    for j in updated:
        fresh = fresh_by_id.get(j.id)
        if fresh is not None and fresh.state == "paused" and j.state != "paused":
            continue
        to_write.append(j)
    if to_write:
        save_jobs_patch(to_write)


def _random_resume_delay_seconds() -> float:
    return random.uniform(RESUME_RANDOM_DELAY_MIN_SEC, RESUME_RANDOM_DELAY_MAX_SEC)


def _first_send_step_index(job: ScheduledJob) -> Optional[int]:
    for i, it in enumerate(job.items):
        if not it.is_non_send_step():
            return i
    return None


def _resume_delay_seconds(job: ScheduledJob) -> float:
    reason = (job.pause_reason or "").strip()
    if pause_reason_is(reason, CODE_STAGE_REMINDER) or is_await_image_send(reason):
        return _random_resume_delay_seconds()
    if job.last_send_ts <= 0:
        fi = _first_send_step_index(job)
        if fi is not None and job.cursor == fi:
            return _random_resume_delay_seconds()
    remain = job.remaining_seconds if job.remaining_seconds > 0 else 0.0
    if remain <= 0:
        remain = _delay_seconds_after_item(job, job.cursor)
    return _clamp_remain_seconds(remain)


def pause_all_doc_jobs_on_startup(reason: str = STARTUP_PAUSE_REASON) -> int:
    """每次启动应用时将仍在「运行中」的文档任务全部改为暂停，避免 exe/崩溃恢复后自动发消息。"""
    jobs = load_jobs()
    now = time.time()
    cnt = 0
    touched: List[ScheduledJob] = []
    for j in jobs:
        if not j.enabled or not j.items:
            continue
        if j.state == "paused":
            continue
        remain = j.remaining_seconds
        if remain <= 0:
            if j.next_send_ts > 0:
                remain = max(1.0, j.next_send_ts - now)
            else:
                remain = _delay_seconds_after_item(j, j.cursor)
        j.remaining_seconds = _clamp_remain_seconds(remain)
        j.state = "paused"
        j.pause_reason = reason
        touched.append(j)
        cnt += 1
    if touched:
        save_jobs_patch(touched)
        info(f"启动时已暂停 {cnt} 个文档定时任务（需手动点「继续」）。")
    return cnt


def _delay_seconds_after_item(job: ScheduledJob, item_index: int) -> float:
    """本条执行完后的等待秒数：优先 TXT 间隔=，否则用任务固定间隔 X-X 分钟。"""
    if not job.items:
        return 60.0
    idx = max(0, min(int(item_index), len(job.items) - 1))
    item = job.items[idx]
    if getattr(item, "interval_from_txt", False):
        minutes = max(0.0, float(item.delay_after_minutes))
    elif job.interval_max_minutes > 0 or job.interval_min_minutes > 0:
        lo = max(0.1, float(job.interval_min_minutes))
        hi = max(lo, float(job.interval_max_minutes or lo))
        minutes = random.uniform(lo, hi) if hi > lo else lo
    else:
        minutes = max(0.0, float(item.delay_after_minutes))
    if minutes <= 0:
        return 0.0
    return minutes * 60.0


def job_doc_completed(j: ScheduledJob) -> bool:
    """文档任务是否已跑完一轮（cursor 已到末尾）。"""
    return j.item_count() > 0 and j.cursor >= j.item_count()


def bulk_resume_job_counts(jobs: Optional[List[ScheduledJob]] = None) -> tuple[int, int]:
    """返回 (可恢复数, 已完成跳过数)。"""
    if jobs is None:
        jobs = load_jobs()
    resumable = 0
    skipped = 0
    for j in jobs:
        if j.item_count() <= 0:
            continue
        if job_doc_completed(j):
            skipped += 1
            continue
        if j.state == "paused":
            resumable += 1
    return resumable, skipped


def _clamp_remain_seconds(secs: float) -> float:
    return max(0.0, float(secs))


def _next_delay_seconds(job: ScheduledJob) -> float:
    """下一条前的等待：取当前游标对应条目的间隔。"""
    return _delay_seconds_after_item(job, job.cursor)


class ScheduleRunner:
    """文档定时任务逻辑；由 TelethonCoordinator 在同一 asyncio 循环内调用 _async_main。"""

    def __init__(self) -> None:
        self._running = False
        self._accounts: Dict[str, Account] = {}
        self._api_id: int = 0
        self._api_hash: str = ""
        self._shared_clients: Optional[Dict[str, TelegramClient]] = None
        self._account_locks: Dict[str, Any] = {}
        self._send_slots: Optional[asyncio.Semaphore] = None
        self._async_loop: Optional[asyncio.AbstractEventLoop] = None
        self._reminder_callback: Optional[Callable[[ScheduledJob, DocMessage, int], None]] = None
        self._read_tracker: Optional[TgWatchReadTracker] = None

    def bind_read_tracker(self, tracker: Optional[TgWatchReadTracker]) -> None:
        self._read_tracker = tracker

    def _emit_reminder(
        self,
        job: ScheduledJob,
        item: DocMessage,
        step_one_based: int,
        paused_count: int = 0,
        affected_job_ids: Optional[List[str]] = None,
    ) -> None:
        cb = self._reminder_callback
        if not cb:
            return
        ids = list(dict.fromkeys(affected_job_ids or []))
        if job.id not in ids:
            ids.append(job.id)
        try:
            cb(job, item, step_one_based, paused_count, ids)
        except TypeError:
            try:
                cb(job, item, step_one_based, paused_count)
            except TypeError:
                try:
                    cb(job, item, step_one_based)
                except Exception as exc:
                    error(f"阶段提醒回调异常：{exc}")
            except Exception as exc:
                error(f"阶段提醒回调异常：{exc}")
        except Exception as exc:
            error(f"阶段提醒回调异常：{exc}")

    def set_reminder_callback(self, fn: Optional[Callable[[ScheduledJob, DocMessage, int], None]]) -> None:
        self._reminder_callback = fn

    def bind_telegram_clients(self, clients: Dict[str, TelegramClient]) -> None:
        self._shared_clients = dict(clients)
        prev = getattr(self, "_account_locks", None) or {}
        # 重连补号时复用已有锁，避免在线账号发送中途被换锁
        self._account_locks = {
            key: (
                prev[key]
                if key in prev
                else asyncio.Semaphore(PER_ACCOUNT_SEND_CONCURRENCY)
            )
            for key in self._shared_clients
        }
        if self._send_slots is None:
            self._send_slots = asyncio.Semaphore(GLOBAL_SEND_CONCURRENCY)
        try:
            self._async_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._async_loop = None

    def unbind_telegram_clients(self) -> None:
        self._shared_clients = None
        self._account_locks = {}
        self._send_slots = None
        self._async_loop = None

    def refresh_config(self, cfg: AppConfig) -> None:
        """热更新内存中的账号/api 快照，不中断 _async_main 循环。"""
        self._accounts = {a.id: a for a in cfg.accounts}
        self._api_id = int(cfg.api_id)
        self._api_hash = str(cfg.api_hash or "")

    def start(self, cfg: AppConfig) -> None:
        self.stop()
        self.refresh_config(cfg)
        info("定时任务已就绪（由统一会话线程执行）")

    def stop(self) -> None:
        self._running = False

    def pause_job(self, job_id: str, reason: str = CODE_MANUAL) -> bool:
        jobs = load_jobs()
        now = time.time()
        changed = False
        for j in jobs:
            if j.id != job_id or not j.enabled:
                continue
            if j.state != "paused":
                remain = j.remaining_seconds
                if remain <= 0:
                    if j.next_send_ts > 0:
                        remain = max(1.0, j.next_send_ts - now)
                    else:
                        remain = _delay_seconds_after_item(j, j.cursor)
                j.remaining_seconds = _clamp_remain_seconds(remain)
                j.state = "paused"
                j.pause_reason = reason
                changed = True
        if changed:
            save_jobs_patch([j for j in jobs if j.id == job_id])
        return changed

    def resume_job(self, job_id: str) -> bool:
        jobs = load_jobs()
        now = time.time()
        changed = False
        for j in jobs:
            if j.id != job_id:
                continue
            if not j.enabled:
                j.enabled = True
                changed = True
            if j.item_count() > 0 and j.cursor >= j.item_count():
                j.cursor = 0
                changed = True
            if j.state != "paused":
                continue
            delay = _resume_delay_seconds(j)
            j.next_send_ts = now + delay
            j.remaining_seconds = 0.0
            j.pause_reason = ""
            j.state = "running"
            changed = True
        if changed:
            save_jobs_patch([j for j in jobs if j.id == job_id])
        return changed

    def finish_job_after_last_image(self, job_id: str) -> bool:
        """发图步为最后一步且已发出：标记一轮完成。"""
        from i18n.pause_reason import CODE_ROUND_COMPLETE

        jobs = load_jobs()
        touched: Optional[ScheduledJob] = None
        for j in jobs:
            if j.id != job_id:
                continue
            j.enabled = False
            j.state = "paused"
            j.pause_reason = CODE_ROUND_COMPLETE
            j.next_send_ts = 0.0
            j.remaining_seconds = 0.0
            touched = j
            break
        if touched is not None:
            save_jobs_patch([touched])
            return True
        return False

    async def run_bulk_image_send(
        self,
        job_ids: List[str],
        image_path: str = "",
        *,
        image_paths: Optional[List[str]] = None,
        on_progress: Optional[Callable[[int, int, Any], None]] = None,
        sync_to_customer: bool = False,
        customer_extra_text: str = "",
    ) -> Tuple[int, int, int]:
        """在 Telethon 会话循环内：按 job_ids 发图（可 1–3 张），成功则自动 resume。返回 (ok, fail, resumed)。"""
        from .one_click_image import bulk_send_images_and_resume, is_job_awaiting_image

        cfg = load_config()
        jobs_all = load_jobs()
        by_id = {j.id: j for j in jobs_all}
        jobs = [by_id[i] for i in job_ids if i in by_id and is_job_awaiting_image(by_id[i])]
        if not jobs:
            return 0, 0, 0
        shared = self._shared_clients or {}
        return await bulk_send_images_and_resume(
            jobs=jobs,
            cfg=cfg,
            shared_clients=shared,
            account_locks=self._account_locks,
            image_path=image_path,
            image_paths=image_paths,
            resume_job=self.resume_job,
            finish_job_if_exhausted=self.finish_job_after_last_image,
            on_progress=on_progress,
            sync_to_customer=sync_to_customer,
            customer_extra_text=customer_extra_text,
        )

    def resume_all_jobs(self) -> int:
        """恢复所有暂停中的文档任务（跳过已完成；重跑请点单卡「重新开始」）。"""
        jobs = load_jobs()
        now = time.time()
        touched: List[ScheduledJob] = []
        for j in jobs:
            if j.item_count() <= 0:
                continue
            if job_doc_completed(j):
                continue
            if not j.enabled:
                j.enabled = True
            if j.state != "paused":
                continue
            delay = _resume_delay_seconds(j)
            j.next_send_ts = now + delay
            j.remaining_seconds = 0.0
            j.pause_reason = ""
            j.state = "running"
            touched.append(j)
        if touched:
            save_jobs_patch(touched)
        return len(touched)

    def pause_jobs_by_chat(
        self,
        chat_id: int,
        reason: str,
        *,
        raw_chat_id: Optional[int] = None,
        event_username: Optional[str] = None,
        event_title: Optional[str] = None,
    ) -> List[str]:
        jobs = load_jobs()
        cfg = load_config()
        now = time.time()
        cid = int(chat_id)
        raw_c = int(raw_chat_id) if raw_chat_id is not None else cid

        variants = set(chat_peer_ids_for_match(cid)) | set(chat_peer_ids_for_match(raw_c))
        by_eid = {e.id: e for e in cfg.address_book}

        def job_has_chat(j: ScheduledJob) -> bool:
            targets = resolve_job_chat_targets(cfg, j)
            nums: List[int] = []
            for t in targets:
                if isinstance(t, int):
                    nums.append(int(t))
                else:
                    try:
                        nums.append(int(str(t).strip()))
                    except ValueError:
                        pass
            for n in nums:
                if variants.intersection(chat_peer_ids_for_match(int(n))):
                    return True
            for x in j.chat_ids:
                if variants.intersection(chat_peer_ids_for_match(int(x))):
                    return True
            if event_username or event_title:
                for eid in j.chat_entry_ids:
                    ent = by_eid.get(str(eid))
                    if not ent:
                        continue
                    if telegram_chat_matches_address_ref(
                        ent.chat_ref,
                        peer_id=cid,
                        raw_chat_id=raw_c,
                        event_username=event_username,
                        event_title=event_title,
                    ):
                        return True
            return False

        touched: List[ScheduledJob] = []
        for j in jobs:
            if not job_has_chat(j):
                continue
            changed = False
            if j.state != "paused":
                # 运行中任务记录剩余时间；已停止任务仅刷新暂停原因用于高亮展示
                if j.enabled:
                    remain = j.remaining_seconds
                    if remain <= 0:
                        if j.next_send_ts > 0:
                            remain = max(1.0, j.next_send_ts - now)
                        else:
                            remain = _delay_seconds_after_item(j, j.cursor)
                    j.remaining_seconds = _clamp_remain_seconds(remain)
                j.state = "paused"
                changed = True
            effective = reason
            if pause_reason_is(reason, CODE_LISTEN_HIT):
                effective = resolve_listen_pause_reason(
                    enabled=j.enabled,
                    previous_reason=j.pause_reason,
                    listen_reason=reason,
                )
            if j.pause_reason != effective:
                j.pause_reason = effective
                changed = True
            if changed:
                touched.append(j)
        if touched:
            save_jobs_patch(touched)
        return [j.id for j in touched]

    def pause_jobs_for_job_targets(self, cfg: AppConfig, job: ScheduledJob, reason: str) -> List[str]:
        """暂停该任务及发到相同群目标的其它文档任务。"""
        jobs = load_jobs()
        now = time.time()
        targets = resolve_job_chat_targets(cfg, job)
        target_nums: List[int] = []
        for t in targets:
            if isinstance(t, int):
                target_nums.append(int(t))
            else:
                try:
                    target_nums.append(int(str(t).strip()))
                except ValueError:
                    pass
        entry_set = {str(x) for x in (job.chat_entry_ids or []) if str(x).strip()}

        def job_shares_target(j: ScheduledJob) -> bool:
            if j.id == job.id:
                return True
            if entry_set and entry_set.intersection({str(x) for x in (j.chat_entry_ids or []) if str(x).strip()}):
                return True
            j_targets = resolve_job_chat_targets(cfg, j)
            for a in target_nums:
                for b in j_targets:
                    if isinstance(b, int):
                        if set(chat_peer_ids_for_match(int(a))).intersection(chat_peer_ids_for_match(int(b))):
                            return True
                    else:
                        try:
                            bn = int(str(b).strip())
                            if set(chat_peer_ids_for_match(int(a))).intersection(chat_peer_ids_for_match(bn)):
                                return True
                        except ValueError:
                            if str(a) == str(b).strip():
                                return True
            return False

        touched: List[ScheduledJob] = []
        for j in jobs:
            if not j.enabled or j.state == "paused" or not job_shares_target(j):
                continue
            remain = j.remaining_seconds
            if remain <= 0:
                if j.next_send_ts > 0:
                    remain = max(1.0, j.next_send_ts - now)
                else:
                    remain = _delay_seconds_after_item(j, j.cursor)
            j.remaining_seconds = _clamp_remain_seconds(remain)
            j.state = "paused"
            j.pause_reason = reason
            touched.append(j)
        if touched:
            save_jobs_patch(touched)
        return [j.id for j in touched]

    async def _async_main(self) -> None:
        while self._running:
            try:
                now = time.time()
                jobs = load_jobs()
                dirty: Dict[str, ScheduledJob] = {}
                pending: List[
                    Tuple[
                        ScheduledJob,
                        DocMessage,
                        List[Union[int, str]],
                        str,
                        "asyncio.Task[bool]",
                    ]
                ] = []
                for j in jobs:
                    if not self._running:
                        break
                    if not j.enabled:
                        continue
                    if not j.items:
                        continue
                    if j.state == "paused":
                        continue

                    if j.next_send_ts <= 0:
                        j.next_send_ts = now + _random_resume_delay_seconds()
                        dirty[j.id] = j
                        continue
                    if now < j.next_send_ts:
                        continue

                    item = j.current_item()
                    if item is None:
                        # 已到文档末尾：自动停止该任务，不再重复轮播。
                        j.enabled = False
                        j.state = "paused"
                        j.pause_reason = CODE_ROUND_COMPLETE
                        j.next_send_ts = 0.0
                        dirty[j.id] = j
                        continue
                    if item.is_reminder:
                        step = j.cursor + 1
                        j.cursor += 1
                        j.last_send_ts = time.time()
                        j.last_error = ""
                        if j.cursor >= len(j.items):
                            j.enabled = False
                            j.state = "paused"
                            j.pause_reason = CODE_ROUND_COMPLETE
                            j.next_send_ts = 0.0
                            j.remaining_seconds = 0.0
                        else:
                            remain = (
                                max(1.0, j.next_send_ts - now)
                                if j.next_send_ts > now
                                else _delay_seconds_after_item(
                                    j, j.cursor - 1 if j.cursor > 0 else 0
                                )
                            )
                            j.remaining_seconds = _clamp_remain_seconds(remain)
                            j.state = "paused"
                            j.pause_reason = STAGE_REMINDER_PAUSE_REASON
                            j.next_send_ts = 0.0
                        dirty[j.id] = j
                        save_jobs_patch([j])
                        cfg_rem = load_config()
                        related_ids = self.pause_jobs_for_job_targets(cfg_rem, j, STAGE_REMINDER_PAUSE_REASON)
                        grp = format_job_targets_label(cfg_rem, j)
                        info(
                            f"文档任务阶段提醒：{j.id} 群={grp} 文档={j.source_name} 步={step}"
                            + (f"；已暂停 {len(related_ids)} 个相关任务" if related_ids else "")
                        )
                        affected = list(dict.fromkeys([j.id, *related_ids]))
                        self._emit_reminder(j, item, step, len(related_ids), affected_job_ids=affected)
                        continue
                    if getattr(item, "is_image_send", False):
                        step = j.cursor + 1
                        j.cursor += 1
                        j.last_send_ts = time.time()
                        j.last_error = ""
                        remain = (
                            max(1.0, j.next_send_ts - now)
                            if j.next_send_ts > now
                            else _delay_seconds_after_item(
                                j, j.cursor - 1 if j.cursor > 0 else 0
                            )
                        )
                        j.remaining_seconds = _clamp_remain_seconds(remain)
                        j.state = "paused"
                        j.pause_reason = AWAIT_IMAGE_SEND_PAUSE_REASON
                        j.next_send_ts = 0.0
                        # 即使是最后一步：仍待发图，发完后再标一轮完成
                        dirty[j.id] = j
                        save_jobs_patch([j])
                        cfg_img = load_config()
                        grp = format_job_targets_label(cfg_img, j)
                        note = (item.reminder_note or "").strip()
                        info(
                            f"文档任务待发图：{j.id} 群={grp} 文档={j.source_name} 步={step}"
                            f" 账号={item.original_label()}"
                            + (f" 备注={note}" if note else "")
                            + "；请在任务管理点「一键发送图片」"
                        )
                        continue
                    cfg = load_config()
                    targets = resolve_job_chat_targets(cfg, j)
                    if not targets:
                        warning(f"文档任务跳过：任务 {j.id} 无法解析发送目标（检查通讯录是否仍存在对应条目）")
                        j.last_error = "发送目标无效"
                        j.next_send_ts = time.time() + _delay_seconds_after_item(j, j.cursor)
                        dirty[j.id] = j
                        continue
                    from .group_owner import send_account_for_job_item

                    acc_send = send_account_for_job_item(cfg, j, item)
                    if not is_doc_job_send_allowed(j.id):
                        continue
                    abort_check = lambda jid=j.id: not is_doc_job_send_allowed(jid)
                    task = asyncio.create_task(
                        self._send_one_to_many(
                            targets,
                            acc_send,
                            item.content,
                            job_id=j.id,
                            want_reactions=bool(getattr(item, "want_reactions", False)),
                            job=j,
                            cfg=cfg,
                            abort_check=abort_check,
                        )
                    )
                    pending.append((j, item, targets, acc_send, task))

                if pending:
                    results = await asyncio.gather(
                        *(row[4] for row in pending),
                        return_exceptions=True,
                    )
                    for (j, item, targets, acc_send, _task), result in zip(
                        pending, results
                    ):
                        if isinstance(result, BaseException):
                            send_exc = result
                            from .group_auto_join import AutoJoinFailed

                            if isinstance(send_exc, AutoJoinFailed):
                                step = j.cursor + 1
                                j.state = "paused"
                                j.pause_reason = JOIN_GROUP_FAILED_PAUSE_REASON
                                j.next_send_ts = 0.0
                                j.remaining_seconds = 0.0
                                j.last_error = str(send_exc)
                                dirty[j.id] = j
                                save_jobs_patch([j])
                                warning(
                                    f"文档任务入群失败已暂停：{j.source_name} "
                                    f"账号={send_exc.account_id} 群={send_exc.chat_ref} {send_exc}"
                                )
                                note = (
                                    f"账号「{send_exc.account_id}」入群失败\n"
                                    f"群：{send_exc.chat_ref}\n{send_exc}"
                                )
                                fake = DocMessage(
                                    account_id=send_exc.account_id or acc_send,
                                    content="",
                                    reminder_note=note,
                                    original_account_id=send_exc.account_id
                                    or acc_send,
                                )
                                self._emit_reminder(
                                    j,
                                    fake,
                                    step,
                                    0,
                                    affected_job_ids=[j.id],
                                )
                                continue
                            error(
                                f"文档任务发送异常：任务={j.id} "
                                f"账号={acc_send} 错误={send_exc}"
                            )
                            ok = False
                        else:
                            ok = bool(result)

                        if not is_doc_job_send_allowed(j.id):
                            info(
                                f"文档任务发送已取消：{j.source_name}"
                                "（监听命中已暂停）"
                            )
                            continue
                        sent_idx = j.cursor
                        if ok:
                            j.cursor += 1
                            j.last_send_ts = time.time()
                            j.last_error = ""
                            record_address_book_last_schedule(
                                j.chat_entry_ids, j.source_name
                            )
                            info(
                                f"文档任务已发送：{j.source_name} "
                                f"发送方={acc_send} "
                                f"原文={item.original_label()} "
                                f"目标数={len(targets)}"
                            )
                            if j.cursor >= len(j.items):
                                j.enabled = False
                                j.state = "paused"
                                j.pause_reason = CODE_ROUND_COMPLETE
                                j.next_send_ts = 0.0
                                dirty[j.id] = j
                                continue
                        else:
                            j.last_error = "发送失败，已按本条间隔重试"
                        j.next_send_ts = (
                            time.time()
                            + _delay_seconds_after_item(j, sent_idx)
                        )
                        dirty[j.id] = j

                if dirty:
                    _safe_patch_doc_jobs(list(dirty.values()))
                sleep_sec = runner_loop_sleep_seconds(
                    jobs,
                    now,
                    step_count=lambda x: x.item_count(),
                )
                await asyncio.sleep(sleep_sec)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                error(f"文档定时循环异常：{exc}")
                await asyncio.sleep(1.5)

    async def _send_one_to_many(
        self,
        chat_refs: List[Union[int, str]],
        account_id: str,
        content: str,
        *,
        job_id: str = "",
        want_reactions: bool = False,
        job: Optional[ScheduledJob] = None,
        cfg: Optional[AppConfig] = None,
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        account_id = (account_id or "").strip()
        if abort_check and abort_check():
            return False
        if not self._api_id or not self._api_hash.strip():
            warning("文档任务发送跳过：未配置共用 api_id / api_hash")
            return False
        acc = self._accounts.get(account_id)
        if acc is None or not acc.enabled:
            warning(f"文档任务发送跳过：账号 {account_id} 不存在或未启用")
            return False
        shared = self._shared_clients
        if not shared:
            error("文档任务发送失败：尚未绑定 Telegram 会话（请确认程序已正常连接账号）")
            return False
        client = shared.get(account_id)
        if client is None:
            warning(f"文档任务发送跳过：账号 {account_id} 未连接（请检查是否已登录）")
            return False
        lock = self._account_locks.get(account_id)
        if lock is None:
            lock = asyncio.Semaphore(PER_ACCOUNT_SEND_CONCURRENCY)
            self._account_locks[account_id] = lock
        send_slots = self._send_slots
        if send_slots is None:
            send_slots = asyncio.Semaphore(GLOBAL_SEND_CONCURRENCY)
            self._send_slots = send_slots
        async with send_slots, lock:
            try:
                if not await client.is_user_authorized():
                    warning(f"文档任务发送跳过：账号 {account_id} 未登录")
                    return False
                ok = False
                enabled_ids = {aid for aid, a in self._accounts.items() if a.enabled}
                for cref in chat_refs:
                    if abort_check and abort_check():
                        return False
                    try:
                        from .group_auto_join import AutoJoinAborted, ensure_tg_sender_in_group

                        try:
                            await ensure_tg_sender_in_group(
                                client, account_id, cref, abort_check=abort_check
                            )
                        except AutoJoinAborted:
                            return False
                        entity = await _resolve_entity_for_send(client, cref)
                        await mark_watch_read_before_send(
                            client, account_id, entity, self._read_tracker
                        )
                        from send_typing_util import telegram_send_with_typing

                        msg = await telegram_send_with_typing(
                            client,
                            entity,
                            content,
                            lambda: send_telegram_message_resilient(
                                client, entity, content
                            ),
                            abort_check=abort_check,
                        )
                        if msg is None:
                            return False
                        ok = True
                        if want_reactions and msg is not None and cfg is not None and job is not None:
                            from schedule_reactions import (
                                resolve_main_account_for_job_target,
                                schedule_telegram_reactions,
                            )

                            main_acc = resolve_main_account_for_job_target(cfg, job, cref)
                            schedule_telegram_reactions(
                                shared_clients=shared,
                                account_locks=self._account_locks,
                                chat_ref=cref,
                                msg_id=int(getattr(msg, "id", 0) or 0),
                                sender_account_id=account_id,
                                main_account_id=main_acc,
                                enabled_account_ids=enabled_ids,
                            )
                    except Exception as exc:
                        from .group_auto_join import AutoJoinFailed

                        if isinstance(exc, AutoJoinFailed):
                            raise
                        hint = ""
                        if "Could not find the input entity" in str(exc) or "PeerChannel" in str(exc):
                            hint = (
                                " 提示：请用该账号在 Telegram 里打开该群/频道至少一次，"
                                "或确认账号仍在群内；私密频道需已加入。"
                            )
                        jid = f"任务={job_id} " if job_id else ""
                        error(f"文档任务发送失败：{jid}账号={account_id} 群={cref} 错误={exc}{hint}")
                    if len(chat_refs) > 1:
                        await asyncio.sleep(0.2)
                return ok
            except Exception as exc:
                from .group_auto_join import AutoJoinFailed

                if isinstance(exc, AutoJoinFailed):
                    raise
                error(f"文档任务发送失败：账号={account_id} 群组发送异常 错误={exc}")
                return False
