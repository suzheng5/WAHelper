"""定时任务：多文档轮播，支持按原文账号批量改实际发送账号，多任务并行。"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple

from neonize.aioze.client import NewAClient

from config import (
    Account,
    AppConfig,
    SCHEDULE2_FILE,
    ensure_dirs,
    format_job_targets_label,
    load_config,
    record_address_book_last_schedule,
    resolve_job_chat_targets,
)
from job_file_cache import load_jobs_cached, runner_loop_sleep_seconds, set_jobs_cache
from logger_util import debug, error, info, warning
from schedule_account import (
    address_owner_map,
    resolve_send_account_id,
    row_needs_per_group_owner,
)
from scheduler import DocMessage
from wa_jid import chat_matches_keys, jid_from_chat_key, keys_for_chat_ref
from wa_send import send_text_to_chat, send_text_to_chats
from watch_read_tracker import WaWatchReadTracker, mark_watch_read_before_send
from i18n import t
from i18n.job_card import format_job_status_label
from i18n.pause_reason import (
    CODE_AWAIT_IMAGE_SEND,
    CODE_JOIN_GROUP_FAILED,
    CODE_LISTEN_HIT,
    CODE_MANUAL,
    CODE_NEW_JOB,
    CODE_ROUND_COMPLETE,
    CODE_SHUTDOWN_TASKMGR,
    CODE_STAGE_LISTEN_HIT,
    CODE_STAGE_REMINDER,
    CODE_STARTUP_TASKMGR,
    compose_listen_pause_reason,
    is_await_image_send,
    pause_reason_is,
    resolve_listen_pause_reason,
)


@dataclass
class Schedule2Row:
    id: str
    original_account_id: str
    send_as_account_id: str
    content: str
    is_reminder: bool = False
    reminder_note: str = ""
    """本条执行完后的等待分钟数；None 表示使用任务界面默认间隔（随机）。"""
    delay_after_minutes: Optional[float] = None
    want_reactions: bool = False
    """TXT「类型=发图」：不发送正文，暂停待任务管理一键发图。"""
    is_image_send: bool = False

    def is_non_send_step(self) -> bool:
        return bool(self.is_reminder or self.is_image_send)


@dataclass
class Schedule2Job:
    id: str
    enabled: bool
    chat_ids: List[str]
    interval_min_minutes: float
    interval_max_minutes: float
    source_path: str
    source_name: str
    rows: List[Schedule2Row] = field(default_factory=list)
    chat_entry_ids: List[str] = field(default_factory=list)
    """通讯录条目 id → 该群「主号」实际发送账号（多群任务自动填充）。"""
    owner_by_entry_id: Dict[str, str] = field(default_factory=dict)
    cursor: int = 0
    state: str = "running"
    pause_reason: str = ""
    next_send_ts: float = 0.0
    remaining_seconds: float = 0.0
    last_send_ts: float = 0.0
    last_error: str = ""
    source_kind: str = "file"
    folder_path: str = ""
    folder_files: List[str] = field(default_factory=list)
    folder_day_index: int = 0

    @staticmethod
    def new(
        chat_ids: List[str],
        min_minutes: float,
        max_minutes: float,
        source_path: str,
        rows: List[Schedule2Row],
        chat_entry_ids: Optional[List[str]] = None,
    ) -> "Schedule2Job":
        source_name = os.path.basename(source_path) or "未命名文档"
        ce = [str(x) for x in (chat_entry_ids or []) if str(x).strip()]
        return Schedule2Job(
            id=uuid.uuid4().hex[:12],
            enabled=True,
            chat_ids=[str(x) for x in chat_ids],
            interval_min_minutes=float(min_minutes),
            interval_max_minutes=float(max_minutes),
            source_path=source_path,
            source_name=source_name,
            rows=rows,
            chat_entry_ids=ce,
            cursor=0,
            state="paused",
            pause_reason=NEW_JOB_PAUSE_REASON_S2,
            next_send_ts=0.0,
            remaining_seconds=0.0,
        )

    def row_count(self) -> int:
        return len(self.rows)


def _job_to_dict(j: Schedule2Job) -> Dict[str, Any]:
    d = asdict(j)
    d["rows"] = [asdict(r) for r in j.rows]
    return d


def _row_from_dict(d: Dict[str, Any]) -> Optional[Schedule2Row]:
    if not isinstance(d, dict):
        return None
    rid = str(d.get("id", "")).strip() or uuid.uuid4().hex[:12]
    return Schedule2Row(
        id=rid,
        original_account_id=str(d.get("original_account_id", "") or ""),
        send_as_account_id=str(d.get("send_as_account_id", "") or "").strip()
        or str(d.get("original_account_id", "") or ""),
        content=str(d.get("content", "") or ""),
        is_reminder=bool(d.get("is_reminder", False)),
        reminder_note=str(d.get("reminder_note", "") or ""),
        delay_after_minutes=_delay_minutes_from_raw(d.get("delay_after_minutes")),
        want_reactions=bool(d.get("want_reactions", False)),
        is_image_send=bool(d.get("is_image_send", False)),
    )


def _delay_minutes_from_raw(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _job_from_dict(row: Dict[str, Any]) -> Optional[Schedule2Job]:
    if not isinstance(row, dict):
        return None
    rows: List[Schedule2Row] = []
    for x in row.get("rows", []):
        r = _row_from_dict(x if isinstance(x, dict) else {})
        if r is not None:
            rows.append(r)
    if not rows:
        return None
    jid = str(row.get("id", "")).strip() or uuid.uuid4().hex[:12]
    ce = [str(x) for x in row.get("chat_entry_ids", []) if str(x).strip()]
    cid_raw = row.get("chat_ids", [])
    cids: List[str] = []
    if isinstance(cid_raw, list):
        cids = [str(x) for x in cid_raw if str(x).strip()]
    if not cids and not ce:
        return None
    min_m = float(row.get("interval_min_minutes", 5.0))
    max_m = float(row.get("interval_max_minutes", min_m))
    if min_m <= 0:
        min_m = 0.1
    if max_m < min_m:
        max_m = min_m
    return Schedule2Job(
        id=jid,
        enabled=bool(row.get("enabled", True)),
        chat_ids=cids,
        interval_min_minutes=min_m,
        interval_max_minutes=max_m,
        source_path=str(row.get("source_path", "")),
        source_name=str(row.get("source_name", "")) or os.path.basename(str(row.get("source_path", ""))),
        rows=rows,
        chat_entry_ids=ce,
        owner_by_entry_id={
            str(k): str(v)
            for k, v in (row.get("owner_by_entry_id") or {}).items()
            if str(k).strip() and str(v).strip()
        },
        cursor=max(0, int(row.get("cursor", 0))),
        state=str(row.get("state", "running")) if str(row.get("state", "running")) in ("running", "paused") else "paused",
        pause_reason=str(row.get("pause_reason", "")),
        next_send_ts=float(row.get("next_send_ts", 0.0)),
        remaining_seconds=max(0.0, float(row.get("remaining_seconds", 0.0))),
        last_send_ts=float(row.get("last_send_ts", 0.0)),
        last_error=str(row.get("last_error", "")),
        source_kind=str(row.get("source_kind", "file") or "file"),
        folder_path=str(row.get("folder_path", "") or ""),
        folder_files=[str(x) for x in (row.get("folder_files") or []) if str(x).strip()],
        folder_day_index=max(0, int(row.get("folder_day_index", 0) or 0)),
    )


def _load_schedule2_jobs_from_disk() -> List[Schedule2Job]:
    ensure_dirs()
    if not os.path.isfile(SCHEDULE2_FILE):
        return []
    try:
        with open(SCHEDULE2_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    jobs: List[Schedule2Job] = []
    if isinstance(raw, list):
        for row in raw:
            j = _job_from_dict(row if isinstance(row, dict) else {})
            if j is not None:
                jobs.append(j)
    return jobs


def load_schedule2_jobs(*, force: bool = False) -> List[Schedule2Job]:
    return load_jobs_cached(SCHEDULE2_FILE, _load_schedule2_jobs_from_disk, force=force)


def save_schedule2_jobs(jobs: List[Schedule2Job]) -> None:
    from json_atomic import atomic_write_json

    ensure_dirs()
    atomic_write_json(SCHEDULE2_FILE, [_job_to_dict(j) for j in jobs])
    set_jobs_cache(SCHEDULE2_FILE, jobs)


def save_schedule2_jobs_patch(updated: List[Schedule2Job]) -> None:
    """仅合并写入有变动的任务，避免全量覆盖与 UI/后台竞态。"""
    if not updated:
        return
    fresh = load_schedule2_jobs()
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
    save_schedule2_jobs([by_id[jid] for jid in order])


def _doc_items_to_s2_rows(items: List[DocMessage]) -> List[Schedule2Row]:
    from schedule_account import mark_row_primary_auto

    rows: List[Schedule2Row] = []
    for it in items:
        orig, send = mark_row_primary_auto(it.account_id, it.account_id)
        rows.append(
            Schedule2Row(
                id=uuid.uuid4().hex[:12],
                original_account_id=orig,
                send_as_account_id=send,
                content=it.content,
                is_reminder=it.is_reminder,
                reminder_note=it.reminder_note,
                delay_after_minutes=it.delay_after_minutes,
                want_reactions=bool(getattr(it, "want_reactions", False)),
                is_image_send=bool(getattr(it, "is_image_send", False)),
            )
        )
    return rows


def _reload_folder_day_items_s2(job: Schedule2Job, cfg: AppConfig, rel_name: str) -> tuple[bool, str]:
    from schedule_folder import read_folder_txt_utf8
    from schedule_txt_import import import_doc_items

    text, err = read_folder_txt_utf8(job.folder_path, rel_name)
    if err:
        return False, err
    items, _errs = import_doc_items(text, valid_accounts=None)
    if not items:
        return False, "TXT 无有效条目"
    rows = _doc_items_to_s2_rows(items)
    if row_needs_per_group_owner(rows):
        emap = {e.id: e for e in cfg.address_book}
        for eid in job.chat_entry_ids:
            ent = emap.get(eid)
            if not ent or not (ent.owner_account_id or "").strip():
                return False, "未在通讯录设置主号/归属账号"
    job.rows = rows
    abs_path = os.path.join(os.path.abspath(job.folder_path), rel_name)
    job.source_path = abs_path
    job.source_name = os.path.basename(abs_path) or rel_name
    return True, ""


def reload_schedule2_folder_scripts(job: Schedule2Job, cfg: AppConfig) -> tuple[bool, str]:
    """
    重新扫描文件夹并重读「当前天」TXT 话术（不切天、不改变暂停/启用状态）。
    光标钳制到新条目数内，避免改稿后越界。
    """
    from schedule_folder import is_folder_job, read_folder_txt_utf8, rescan_folder_files_keep_day
    from schedule_txt_import import import_doc_items

    if not is_folder_job(job):
        return False, "不是文件夹任务"
    ordered, new_idx, err = rescan_folder_files_keep_day(job)
    if err:
        return False, err
    rel = ordered[new_idx]
    text, rerr = read_folder_txt_utf8(job.folder_path, rel)
    if rerr:
        return False, rerr
    items, _errs = import_doc_items(text, valid_accounts=None)
    if not items:
        return False, "TXT 无有效条目"
    rows = _doc_items_to_s2_rows(items)
    if row_needs_per_group_owner(rows):
        emap = {e.id: e for e in cfg.address_book}
        for eid in job.chat_entry_ids:
            ent = emap.get(eid)
            if not ent or not (ent.owner_account_id or "").strip():
                return False, "未在通讯录设置主号/归属账号"
    # 解析成功后再写回，避免半更新
    job.folder_files = list(ordered)
    job.folder_day_index = new_idx
    job.rows = rows
    abs_path = os.path.join(os.path.abspath(job.folder_path), rel)
    # 与磁盘实际文件名对齐
    from schedule_folder import resolve_folder_day_filename

    real_rel = resolve_folder_day_filename(job.folder_path, rel)
    job.folder_files[new_idx] = real_rel
    abs_path = os.path.join(os.path.abspath(job.folder_path), real_rel)
    job.source_path = abs_path
    job.source_name = os.path.basename(abs_path) or real_rel
    n = len(job.rows or [])
    job.cursor = max(0, min(int(job.cursor or 0), n))
    job.last_error = ""
    return True, ""


def bulk_reload_schedule2_folder_scripts(
    jobs: Optional[List[Schedule2Job]] = None,
    cfg: Optional[AppConfig] = None,
) -> tuple[int, int, List[str]]:
    """批量重读文件夹话术。返回 (成功数, 失败数, 失败摘要前几条)。"""
    from schedule_folder import is_folder_job

    if cfg is None:
        cfg = load_config()
    if jobs is None:
        jobs = load_schedule2_jobs()
    ok_n = fail_n = 0
    fails: List[str] = []
    touched = False
    for j in jobs:
        if not is_folder_job(j):
            continue
        ok, err = reload_schedule2_folder_scripts(j, cfg)
        if ok:
            ok_n += 1
            touched = True
        else:
            fail_n += 1
            if len(fails) < 8:
                fails.append(f"{j.source_name or j.id}: {err}")
    if touched:
        save_schedule2_jobs(list(jobs))
    return ok_n, fail_n, fails


def advance_schedule2_folder_day(job: Schedule2Job, cfg: AppConfig) -> tuple[bool, str]:
    from schedule_folder import can_advance_folder_day

    if not can_advance_folder_day(job):
        return False, "已是最后一天或不是文件夹任务"
    next_index = int(job.folder_day_index) + 1
    from schedule_folder import resolve_folder_day_filename

    rel = resolve_folder_day_filename(job.folder_path, job.folder_files[next_index])
    ok, err = _reload_folder_day_items_s2(job, cfg, rel)
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


STARTUP_PAUSE_REASON_S2 = CODE_STARTUP_TASKMGR
SHUTDOWN_PAUSE_REASON_S2 = CODE_SHUTDOWN_TASKMGR
NEW_JOB_PAUSE_REASON_S2 = CODE_NEW_JOB
STAGE_REMINDER_PAUSE_REASON_S2 = CODE_STAGE_REMINDER
JOIN_GROUP_FAILED_PAUSE_REASON_S2 = CODE_JOIN_GROUP_FAILED
AWAIT_IMAGE_SEND_PAUSE_REASON_S2 = CODE_AWAIT_IMAGE_SEND
LISTEN_HIT_PAUSE_REASON_S2 = CODE_LISTEN_HIT
STAGE_LISTEN_HIT_PAUSE_REASON_S2 = CODE_STAGE_LISTEN_HIT

RESUME_RANDOM_DELAY_MIN_SEC = 30.0
RESUME_RANDOM_DELAY_MAX_SEC = 60.0


def _schedule2_job_by_id(job_id: str, jobs: Optional[List[Schedule2Job]] = None) -> Optional[Schedule2Job]:
    if jobs is None:
        jobs = load_schedule2_jobs()
    return next((x for x in jobs if x.id == job_id), None)


def is_schedule2_job_send_allowed(job_id: str) -> bool:
    j = _schedule2_job_by_id(job_id)
    return bool(j and j.enabled and j.state != "paused")


def _safe_patch_schedule2_jobs(updated: List[Schedule2Job]) -> None:
    to_write: List[Schedule2Job] = []
    fresh_by_id = {j.id: j for j in load_schedule2_jobs()}
    for j in updated:
        fresh = fresh_by_id.get(j.id)
        if fresh is not None and fresh.state == "paused" and j.state != "paused":
            continue
        to_write.append(j)
    if to_write:
        save_schedule2_jobs_patch(to_write)


def _random_resume_delay_seconds() -> float:
    return random.uniform(RESUME_RANDOM_DELAY_MIN_SEC, RESUME_RANDOM_DELAY_MAX_SEC)


def _first_send_row_index(job: Schedule2Job) -> Optional[int]:
    for i, row in enumerate(job.rows):
        if not row.is_reminder:
            return i
    return None


def _resume_delay_seconds(job: Schedule2Job) -> float:
    if pause_reason_is(job.pause_reason, CODE_STAGE_REMINDER) or is_await_image_send(job.pause_reason):
        return _random_resume_delay_seconds()
    if job.last_send_ts <= 0:
        fi = _first_send_row_index(job)
        if fi is not None and job.cursor == fi:
            return _random_resume_delay_seconds()
    remain = job.remaining_seconds if job.remaining_seconds > 0 else 0.0
    if remain <= 0:
        ri = _pending_delay_row_index(job)
        remain = _next_delay_seconds(job, ri if ri >= 0 else None)
    return _clamp_secs(job, remain, _pending_delay_row_index(job))


def schedule2_job_is_running(j: Schedule2Job) -> bool:
    return bool(j.enabled) and j.state == "running"


def schedule2_job_completed(j: Schedule2Job) -> bool:
    return j.row_count() > 0 and j.cursor >= j.row_count()


def bulk_resume_schedule2_counts(jobs: Optional[List[Schedule2Job]] = None) -> tuple[int, int]:
    """返回 (可恢复数, 已完成跳过数)。"""
    if jobs is None:
        jobs = load_schedule2_jobs()
    now = time.time()
    resumable = 0
    skipped = 0
    for j in jobs:
        if j.row_count() <= 0:
            continue
        if schedule2_job_completed(j):
            skipped += 1
            continue
        if j.state == "paused":
            resumable += 1
        elif j.state == "running" and (j.next_send_ts <= 0 or j.next_send_ts <= now):
            resumable += 1
    return resumable, skipped


def schedule2_job_status_label(j: Schedule2Job) -> str:
    return format_job_status_label(
        enabled=bool(j.enabled),
        state=j.state,
        pause_reason=j.pause_reason or "",
    )


def schedule2_job_step_label(j: Schedule2Job) -> str:
    total = j.row_count()
    if total <= 0:
        return t("job_step.none")
    if is_await_image_send(j.pause_reason or ""):
        step_no = max(1, int(j.cursor or 0))
        return t("job_step.image", cur=min(step_no, total), total=total)
    if j.cursor >= total:
        return t("job_step.done", cur=total, total=total)
    step_no = j.cursor + 1
    row = j.rows[j.cursor]
    if row.is_reminder:
        return t("job_step.reminder", cur=step_no, total=total)
    if getattr(row, "is_image_send", False):
        return t("job_step.image", cur=step_no, total=total)
    preview = (row.content or "").replace("\n", " ").strip()[:28]
    return t("job_step.item", cur=step_no, total=total, preview=preview or t("job_step.ellipsis"))


def schedule2_job_target_remarks(cfg: AppConfig, j: Schedule2Job) -> str:
    emap = {e.id: e for e in cfg.address_book}
    names = [(emap[eid].remark or eid).strip() for eid in j.chat_entry_ids if eid in emap]
    if names:
        if len(names) <= 4:
            return "、".join(names)
        return t("job_target.more", names="、".join(names[:4]), n=len(names))
    return format_job_targets_label(cfg, j) or t("job_target.unset")


def pause_all_schedule2_jobs_on_startup(reason: str = STARTUP_PAUSE_REASON_S2) -> int:
    jobs = load_schedule2_jobs()
    now = time.time()
    cnt = 0
    for j in jobs:
        if not j.enabled or not j.rows or j.state == "paused":
            continue
        remain = j.remaining_seconds
        if remain <= 0:
            remain = max(1.0, j.next_send_ts - now) if j.next_send_ts > 0 else _next_delay_seconds(j)
        j.remaining_seconds = _clamp_secs(j, remain, _pending_delay_row_index(j))
        j.state = "paused"
        j.pause_reason = reason
        cnt += 1
    if cnt > 0:
        save_schedule2_jobs(jobs)
        info(f"启动时已暂停 {cnt} 个定时任务（需手动点「继续」）。")
    return cnt


def _job_default_delay_seconds(job: Schedule2Job) -> float:
    min_s = max(1.0, job.interval_min_minutes * 60.0)
    max_s = max(min_s, job.interval_max_minutes * 60.0)
    return random.uniform(min_s, max_s)


def _delay_seconds_after_row(job: Schedule2Job, completed_row_index: int) -> float:
    """本条（已执行）指定的间隔；无 TXT 间隔时用界面默认随机间隔。"""
    if not job.rows or completed_row_index < 0 or completed_row_index >= len(job.rows):
        return _job_default_delay_seconds(job)
    row = job.rows[completed_row_index]
    if row.delay_after_minutes is not None:
        return max(0.0, float(row.delay_after_minutes)) * 60.0
    return _job_default_delay_seconds(job)


def _pending_delay_row_index(job: Schedule2Job) -> int:
    """下一动作前的等待取自上一条已执行条目；cursor=0 时尚未发过。"""
    return job.cursor - 1 if job.cursor > 0 else -1


def _delay_bounds_seconds(job: Schedule2Job, row_index: int) -> tuple[float, float]:
    if row_index < 0 or row_index >= len(job.rows):
        lo = max(1.0, job.interval_min_minutes * 60.0)
        hi = max(lo, job.interval_max_minutes * 60.0)
        return lo, hi
    if job.rows[row_index].delay_after_minutes is not None:
        s = max(0.0, float(job.rows[row_index].delay_after_minutes)) * 60.0
        return s, s
    lo = max(1.0, job.interval_min_minutes * 60.0)
    hi = max(lo, job.interval_max_minutes * 60.0)
    return lo, hi


def _clamp_secs(job: Schedule2Job, secs: float, row_index: int = -1) -> float:
    lo, hi = _delay_bounds_seconds(job, row_index)
    return min(max(secs, lo), hi)


def _next_delay_seconds(job: Schedule2Job, completed_row_index: Optional[int] = None) -> float:
    if completed_row_index is None:
        ri = _pending_delay_row_index(job)
        if ri < 0:
            return _job_default_delay_seconds(job)
        return _delay_seconds_after_row(job, ri)
    return _delay_seconds_after_row(job, completed_row_index)


def job_interval_mode_label(job: Schedule2Job) -> str:
    n_txt = sum(1 for r in job.rows if r.delay_after_minutes is not None)
    if n_txt >= len(job.rows) and job.rows:
        return "TXT 每条间隔"
    if n_txt > 0:
        return f"TXT+默认（{n_txt}/{len(job.rows)} 条有间隔=）"
    return f"默认 {job.interval_min_minutes:g}-{job.interval_max_minutes:g} 分"


def _job_targets(cfg: AppConfig, j: Schedule2Job) -> List[str]:
    fake = SimpleNamespace(chat_entry_ids=j.chat_entry_ids, chat_ids=j.chat_ids)
    return resolve_job_chat_targets(cfg, fake)


def _targets_share_chat(cfg: AppConfig, targets_a: List[str], targets_b: List[str]) -> bool:
    for a in targets_a:
        keys_a = keys_for_chat_ref(a)
        if not keys_a:
            continue
        for b in targets_b:
            if keys_a & keys_for_chat_ref(b):
                return True
    return False


def _job_has_chat(j: Schedule2Job, cfg: AppConfig, chat_key: str, *, event_title: Optional[str] = None) -> bool:
    ev_jid = jid_from_chat_key(chat_key)
    if ev_jid is None:
        return False
    job_targets = _job_targets(cfg, j)
    for t in job_targets:
        if chat_matches_keys(keys_for_chat_ref(t), ev_jid):
            return True
    for x in j.chat_ids:
        if chat_matches_keys(keys_for_chat_ref(str(x)), ev_jid):
            return True
    if event_title:
        for t in job_targets:
            if event_title.strip() and t.strip().lower() == event_title.strip().lower():
                return True
    return False


def pause_jobs_for_targets(
    targets: List[str], reason: str, *, except_job_id: Optional[str] = None
) -> List[str]:
    """暂停所有发送到相同群目标的定时任务（含当前任务，阶段提醒后需手动点「继续」）。"""
    if not targets:
        return []
    jobs = load_schedule2_jobs()
    cfg = load_config()
    now = time.time()
    touched: List[Schedule2Job] = []
    for j in jobs:
        if except_job_id and j.id == except_job_id:
            continue
        if not j.enabled or j.state == "paused":
            continue
        if not _targets_share_chat(cfg, targets, _job_targets(cfg, j)):
            continue
        remain = j.remaining_seconds
        if remain <= 0:
            remain = max(1.0, j.next_send_ts - now) if j.next_send_ts > 0 else _next_delay_seconds(j)
        j.remaining_seconds = _clamp_secs(j, remain, _pending_delay_row_index(j))
        j.state = "paused"
        j.pause_reason = reason
        touched.append(j)
    if touched:
        save_schedule2_jobs_patch(touched)
    return [j.id for j in touched]


class Schedule2Runner:
    def __init__(self) -> None:
        self._running = False
        self._accounts: Dict[str, Account] = {}
        self._shared_clients: Optional[Dict[str, NewAClient]] = None
        self._account_locks: Dict[str, asyncio.Lock] = {}
        self._reminder_callback: Optional[Callable[..., None]] = None
        self._read_tracker: Optional[WaWatchReadTracker] = None

    def bind_read_tracker(self, tracker: Optional[WaWatchReadTracker]) -> None:
        self._read_tracker = tracker

    def set_reminder_callback(self, fn: Optional[Callable[..., None]]) -> None:
        self._reminder_callback = fn

    def refresh_accounts(self, cfg: Optional[AppConfig] = None) -> None:
        """从最新 config 刷新账号表（新登录/新添加账号后必须调用）。"""
        if cfg is None:
            cfg = load_config()
        self._accounts = {a.id: a for a in cfg.accounts}

    def bind_clients(self, clients: Dict[str, NewAClient]) -> None:
        self._shared_clients = dict(clients)
        # 保留已有锁，避免其它账号发送中途锁被替换导致并发写库
        new_locks: Dict[str, asyncio.Lock] = {}
        for k in self._shared_clients:
            new_locks[k] = self._account_locks.get(k) or asyncio.Lock()
        self._account_locks = new_locks
        self.refresh_accounts()

    def unbind_clients(self) -> None:
        self._shared_clients = None
        self._account_locks = {}

    async def _send_row_to_job_targets(
        self,
        job: Schedule2Job,
        row: Schedule2Row,
        cfg: AppConfig,
        *,
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """按群发送：主号条目使用通讯录当前选择的归属账号。"""
        emap = {e.id: e for e in cfg.address_book}
        owners = address_owner_map(cfg)
        entry_ids = [str(eid) for eid in job.chat_entry_ids if str(eid).strip()]
        if not entry_ids:
            fake = SimpleNamespace(chat_entry_ids=[], chat_ids=job.chat_ids)
            targets = resolve_job_chat_targets(cfg, fake)
            if not targets:
                return False
            acc = resolve_send_account_id(row, "", owners, self._accounts)
            return await self._send_one_to_many(
                targets,
                acc,
                row.content,
                want_reactions=row.want_reactions,
                main_account_id="",
                abort_check=abort_check,
            )

        if row_needs_per_group_owner([row]):
            for eid in entry_ids:
                if not owners.get(eid):
                    ent = emap.get(eid)
                    name = (ent.remark if ent else eid) or eid
                    warning(f"定时任务「{job.source_name}」：群「{name}」未在通讯录选择主号/归属账号，跳过本轮")
                    return False
        all_ok = True
        any_ok = False
        for eid in entry_ids:
            if abort_check and abort_check():
                return False
            ent = emap.get(eid)
            if not ent or not (ent.chat_ref or "").strip():
                all_ok = False
                continue
            acc_send = resolve_send_account_id(row, eid, owners, self._accounts)
            if not acc_send:
                warning(f"定时任务：群「{ent.remark}」未解析到发送账号（原文={row.original_account_id}）")
                all_ok = False
                continue
            ok = await self._send_one_to_many(
                [ent.chat_ref.strip()],
                acc_send,
                row.content,
                want_reactions=row.want_reactions,
                main_account_id=owners.get(eid, ""),
                abort_check=abort_check,
            )
            any_ok = any_ok or ok
            if not ok:
                all_ok = False
        return all_ok and any_ok

    def start(self, cfg: AppConfig) -> None:
        self.stop()
        self.refresh_accounts(cfg)
        info("定时任务已就绪（多任务并行）")

    def stop(self) -> None:
        self._running = False

    def pause_job(self, job_id: str, reason: str = CODE_MANUAL) -> bool:
        jobs = load_schedule2_jobs()
        now = time.time()
        touched: Optional[Schedule2Job] = None
        for j in jobs:
            if j.id != job_id or not j.enabled or j.state == "paused":
                continue
            remain = j.remaining_seconds
            if remain <= 0:
                remain = max(1.0, j.next_send_ts - now) if j.next_send_ts > 0 else _next_delay_seconds(j)
            j.remaining_seconds = _clamp_secs(j, remain, _pending_delay_row_index(j))
            j.state = "paused"
            j.pause_reason = reason
            touched = j
            break
        if touched is not None:
            save_schedule2_jobs_patch([touched])
        return touched is not None

    def resume_job(self, job_id: str) -> bool:
        jobs = load_schedule2_jobs()
        now = time.time()
        touched: Optional[Schedule2Job] = None
        changed = False
        for j in jobs:
            if j.id != job_id:
                continue
            touched = j
            if not j.enabled:
                j.enabled = True
                changed = True
            if j.row_count() > 0 and j.cursor >= j.row_count():
                j.cursor = 0
                changed = True
            if j.state != "paused":
                break
            delay = _resume_delay_seconds(j)
            j.next_send_ts = now + delay
            j.remaining_seconds = 0.0
            j.pause_reason = ""
            j.state = "running"
            changed = True
            break
        if touched is not None and changed:
            save_schedule2_jobs_patch([touched])
        return changed

    def finish_job_after_last_image(self, job_id: str) -> bool:
        """发图步为最后一步且已发出：标记一轮完成。"""
        jobs = load_schedule2_jobs()
        touched: Optional[Schedule2Job] = None
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
            save_schedule2_jobs_patch([touched])
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
        """在 WA 会话循环内：按 job_ids 发图（可 1–3 张），成功则自动 resume。"""
        from one_click_image import bulk_send_images_and_resume, is_job_awaiting_image

        cfg = load_config()
        jobs_all = load_schedule2_jobs()
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

    def _schedule_job_resume(
        self, j: Schedule2Job, now: float, *, restart_if_completed: bool = False
    ) -> None:
        if restart_if_completed and j.cursor >= j.row_count() and j.row_count() > 0:
            j.cursor = 0
        delay = _resume_delay_seconds(j)
        j.next_send_ts = now + delay
        j.remaining_seconds = 0.0
        j.pause_reason = ""
        j.state = "running"

    def resume_all_jobs(self) -> int:
        """恢复暂停中的任务（跳过已完成）；并修复异常退出后仍为 running 但未调度的任务。"""
        jobs = load_schedule2_jobs()
        now = time.time()
        n = 0
        for j in jobs:
            if j.row_count() <= 0:
                continue
            if schedule2_job_completed(j):
                continue
            if not j.enabled:
                j.enabled = True
            if j.state == "paused":
                self._schedule_job_resume(j, now)
                n += 1
                continue
            if j.state == "running":
                # 强关进程时可能未写入 paused，界面仍显示运行中但一键开始会跳过
                if j.next_send_ts <= 0 or j.next_send_ts <= now:
                    self._schedule_job_resume(j, now)
                    n += 1
        if n > 0:
            save_schedule2_jobs(jobs)
        if n > 0 and not self._running:
            warning(
                "任务状态已保存为运行中，但后台调度线程尚未就绪；"
                "请等待 WhatsApp 账号连接成功，或点「保存并重载服务」。"
            )
        return n

    def pause_by_chat(self, chat_key: str, reason: str, *, event_title: Optional[str] = None) -> List[str]:
        jobs = load_schedule2_jobs()
        cfg = load_config()
        now = time.time()
        touched: List[Schedule2Job] = []
        for j in jobs:
            if not _job_has_chat(j, cfg, chat_key, event_title=event_title):
                continue
            changed = False
            if j.state != "paused":
                # 运行中任务按剩余时间进入暂停；已停止任务仅更新暂停原因与卡片颜色
                if j.enabled:
                    remain = j.remaining_seconds
                    if remain <= 0:
                        remain = max(1.0, j.next_send_ts - now) if j.next_send_ts > 0 else _next_delay_seconds(j)
                    j.remaining_seconds = _clamp_secs(j, remain, _pending_delay_row_index(j))
                j.state = "paused"
                changed = True
            effective = reason
            if reason == LISTEN_HIT_PAUSE_REASON_S2:
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
            save_schedule2_jobs_patch(touched)
        return [j.id for j in touched]

    def _emit_reminder(
        self, job: Schedule2Job, step: int, note: str, *, paused_count: int = 0, affected_job_ids: Optional[List[str]] = None
    ) -> None:
        cb = self._reminder_callback
        if not cb:
            return
        ids = list(dict.fromkeys(affected_job_ids or []))
        if job.id not in ids:
            ids.append(job.id)
        try:
            cb(job, step, note, paused_count, ids)
        except TypeError:
            try:
                cb(job, step, note, paused_count)
            except TypeError:
                try:
                    cb(job.source_name, step, note, paused_count)
                except TypeError:
                    try:
                        cb(job.source_name, step, note)
                    except Exception as exc:
                        error(f"阶段提醒回调异常：{exc}")
                except Exception as exc:
                    error(f"阶段提醒回调异常：{exc}")
            except Exception as exc:
                error(f"阶段提醒回调异常：{exc}")
        except Exception as exc:
            error(f"阶段提醒回调异常：{exc}")

    async def _async_main(self) -> None:
        while self._running:
            try:
                now = time.time()
                jobs = load_schedule2_jobs()
                dirty: Dict[str, Schedule2Job] = {}
                for j in jobs:
                    if not self._running:
                        break
                    if not j.enabled or not j.rows:
                        continue
                    if j.state == "paused":
                        continue
                    if j.next_send_ts <= 0:
                        j.next_send_ts = now + _random_resume_delay_seconds()
                        dirty[j.id] = j
                        continue
                    if now < j.next_send_ts:
                        continue
                    if j.cursor < 0 or j.cursor >= len(j.rows):
                        j.enabled = False
                        j.state = "paused"
                        j.pause_reason = CODE_ROUND_COMPLETE
                        j.next_send_ts = 0.0
                        dirty[j.id] = j
                        continue
                    row = j.rows[j.cursor]
                    done_idx = j.cursor
                    if row.is_reminder:
                        step = j.cursor + 1
                        note = (row.reminder_note or "").strip()
                        j.cursor += 1
                        j.last_send_ts = time.time()
                        j.last_error = ""
                        if j.cursor >= len(j.rows):
                            j.enabled = False
                            j.state = "paused"
                            j.pause_reason = CODE_ROUND_COMPLETE
                            j.next_send_ts = 0.0
                            j.remaining_seconds = 0.0
                        else:
                            remain = (
                                max(1.0, j.next_send_ts - now)
                                if j.next_send_ts > now
                                else _next_delay_seconds(j, done_idx)
                            )
                            j.remaining_seconds = _clamp_secs(
                                j, remain, _pending_delay_row_index(j)
                            )
                            j.state = "paused"
                            j.pause_reason = STAGE_REMINDER_PAUSE_REASON_S2
                            j.next_send_ts = 0.0
                        dirty[j.id] = j
                        save_schedule2_jobs_patch([j])
                        cfg_rem = load_config()
                        targets = _job_targets(cfg_rem, j)
                        related_ids = pause_jobs_for_targets(
                            targets,
                            STAGE_REMINDER_PAUSE_REASON_S2,
                        )
                        if related_ids:
                            info(f"阶段提醒：已暂停 {len(related_ids)} 个相关定时任务")
                        grp = format_job_targets_label(cfg_rem, j)
                        info(f"定时任务阶段提醒：群={grp} 文档={j.source_name} 步={step}")
                        affected = list(dict.fromkeys([j.id, *related_ids]))
                        self._emit_reminder(j, step, note, paused_count=len(related_ids), affected_job_ids=affected)
                        continue
                    if getattr(row, "is_image_send", False):
                        step = j.cursor + 1
                        j.cursor += 1
                        j.last_send_ts = time.time()
                        j.last_error = ""
                        remain = (
                            max(1.0, j.next_send_ts - now)
                            if j.next_send_ts > now
                            else _next_delay_seconds(j, done_idx)
                        )
                        j.remaining_seconds = _clamp_secs(
                            j, remain, _pending_delay_row_index(j)
                        )
                        j.state = "paused"
                        j.pause_reason = AWAIT_IMAGE_SEND_PAUSE_REASON_S2
                        j.next_send_ts = 0.0
                        dirty[j.id] = j
                        save_schedule2_jobs_patch([j])
                        cfg_img = load_config()
                        grp = format_job_targets_label(cfg_img, j)
                        note = (row.reminder_note or "").strip()
                        info(
                            f"定时任务待发图：群={grp} 文档={j.source_name} 步={step}"
                            f" 账号={row.original_account_id or row.send_as_account_id}"
                            + (f" 备注={note}" if note else "")
                            + "；请在任务管理点「一键发送图片」"
                        )
                        continue
                    cfg = load_config()
                    if not j.chat_entry_ids and not j.chat_ids:
                        j.last_error = "发送目标无效"
                        j.next_send_ts = time.time() + _next_delay_seconds(j, done_idx)
                        dirty[j.id] = j
                        continue
                    if not is_schedule2_job_send_allowed(j.id):
                        continue
                    abort_check = lambda jid=j.id: not is_schedule2_job_send_allowed(jid)
                    try:
                        ok = await self._send_row_to_job_targets(
                            j, row, cfg, abort_check=abort_check
                        )
                    except Exception as send_exc:
                        from group_auto_join import AutoJoinFailed

                        if isinstance(send_exc, AutoJoinFailed):
                            step = j.cursor + 1
                            j.state = "paused"
                            j.pause_reason = JOIN_GROUP_FAILED_PAUSE_REASON_S2
                            j.next_send_ts = 0.0
                            j.remaining_seconds = 0.0
                            j.last_error = str(send_exc)
                            dirty[j.id] = j
                            save_schedule2_jobs_patch([j])
                            warning(
                                f"定时任务入群失败已暂停：{j.source_name} "
                                f"账号={send_exc.account_id} 群={send_exc.chat_ref} {send_exc}"
                            )
                            note = (
                                f"账号「{send_exc.account_id}」入群失败\n"
                                f"群：{send_exc.chat_ref}\n{send_exc}"
                            )
                            self._emit_reminder(
                                j, step, note, paused_count=0, affected_job_ids=[j.id]
                            )
                            continue
                        raise
                    if not is_schedule2_job_send_allowed(j.id):
                        info(f"定时任务发送已取消：{j.source_name}（监听命中已暂停）")
                        continue
                    if ok:
                        j.cursor += 1
                        j.last_send_ts = time.time()
                        j.last_error = ""
                        record_address_book_last_schedule(j.chat_entry_ids, j.source_name)
                        owners_now = address_owner_map(cfg)
                        acc_hint = (
                            "主号按群→" + "、".join(f"{owners_now.get(e, '?')}" for e in j.chat_entry_ids[:5])
                            if row_needs_per_group_owner([row])
                            else (row.send_as_account_id or row.original_account_id)
                        )
                        debug(
                            f"定时任务已发送：{j.source_name} 发送方={acc_hint} 原文={row.original_account_id}"
                        )
                        if j.cursor >= len(j.rows):
                            j.enabled = False
                            j.state = "paused"
                            j.pause_reason = CODE_ROUND_COMPLETE
                            j.next_send_ts = 0.0
                    else:
                        j.last_error = "发送失败，已按下一轮间隔重试"
                    if j.next_send_ts != 0.0:
                        j.next_send_ts = time.time() + _next_delay_seconds(j, done_idx)
                    dirty[j.id] = j
                if dirty:
                    _safe_patch_schedule2_jobs(list(dirty.values()))
                sleep_sec = runner_loop_sleep_seconds(
                    jobs,
                    now,
                    step_count=lambda x: x.row_count(),
                )
                await asyncio.sleep(sleep_sec)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                error(f"定时任务循环异常：{exc}")
                await asyncio.sleep(1.5)

    async def _send_one_to_many(
        self,
        chat_refs: List[str],
        account_id: str,
        content: str,
        *,
        want_reactions: bool = False,
        main_account_id: str = "",
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> bool:
        account_id = (account_id or "").strip()
        if abort_check and abort_check():
            return False
        self.refresh_accounts()
        acc = self._accounts.get(account_id)
        if acc is None:
            warning(
                f"定时任务发送跳过：账号「{account_id}」不在账号列表"
                "（请先在「账号管理」添加该简称）"
            )
            return False
        if not acc.enabled:
            warning(f"定时任务发送跳过：账号「{account_id}」已取消勾选启用")
            return False
        shared = self._shared_clients
        if not shared:
            error("定时任务发送失败：尚未连接 WhatsApp")
            return False
        client = shared.get(account_id)
        if client is None:
            warning(f"定时任务发送跳过：账号「{account_id}」未在线（请先扫码登录并保存重载）")
            return False
        lock = self._account_locks.get(account_id) or asyncio.Lock()
        async with lock:
            try:
                ok = False
                enabled_ids = {aid for aid, a in self._accounts.items() if a.enabled}
                for cref in chat_refs:
                    if abort_check and abort_check():
                        return False
                    from group_auto_join import AutoJoinAborted, ensure_wa_sender_in_group

                    try:
                        await ensure_wa_sender_in_group(
                            client, account_id, cref, abort_check=abort_check
                        )
                    except AutoJoinAborted:
                        return False
                    await mark_watch_read_before_send(client, account_id, cref, self._read_tracker)
                    sent_ok, meta = await send_text_to_chat(
                        client, cref, content, abort_check=abort_check
                    )
                    if sent_ok:
                        ok = True
                    if want_reactions and meta is not None:
                        from wa_reactions import schedule_whatsapp_reactions
                        from config import load_config

                        main_acc = (main_account_id or "").strip()
                        if not main_acc:
                            # 切换批超群号后：按 chat_ref 从通讯录再取归属
                            try:
                                cfg_now = load_config()
                                for ent in cfg_now.address_book:
                                    if (ent.chat_ref or "").strip() == cref:
                                        main_acc = (ent.owner_account_id or "").strip()
                                        break
                            except Exception:
                                main_acc = ""
                            schedule_whatsapp_reactions(
                                shared_clients=shared,
                                account_locks=self._account_locks,
                                chat_jid=meta.chat_jid,
                                message_id=meta.message_id,
                                message_sender_jid=meta.message_sender_jid,
                                message_sender_jids=list(
                                    getattr(meta, "message_sender_jids", None) or []
                                ),
                                sender_account_id=account_id,
                                main_account_id=main_acc,
                                enabled_account_ids=enabled_ids,
                            )
                return ok
            except Exception as exc:
                from group_auto_join import AutoJoinFailed

                if isinstance(exc, AutoJoinFailed):
                    raise
                error(f"定时任务发送异常：账号={account_id} 错误={exc}")
                return False
