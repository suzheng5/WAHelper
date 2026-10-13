"""TG：待发图任务匹配、按天归类、串行 send_file。"""
from __future__ import annotations

import asyncio
import os
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from i18n.pause_reason import CODE_AWAIT_IMAGE_SEND, is_await_image_send

from .compat_config import AppConfig, resolve_job_chat_targets
from .group_owner import send_account_for_job_item
from .logger_util import info, warning
from .scheduler import (
    ScheduledJob,
    _resolve_entity_for_send,
    send_telegram_file_resilient,
    send_telegram_message_resilient,
)

IMAGE_SEND_GAP_MIN_SEC = 2.0
IMAGE_SEND_GAP_MAX_SEC = 5.0
# 同一任务内多张图：分开发送的固定间隔
MULTI_IMAGE_GAP_SEC = 10.0
MAX_BULK_IMAGES = 3
CUSTOMER_IMAGE_DELAY_SEC = 60.0
CUSTOMER_TEXT_DELAY_SEC = 30.0


@dataclass
class ImageDayGroup:
    """同一天的待发图任务。day_1based=0 表示非文件夹。"""

    day_1based: int
    jobs: List[ScheduledJob] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"day:{self.day_1based}" if self.day_1based > 0 else "other"


def pending_image_step(job: ScheduledJob) -> Optional[DocMessage]:
    """暂停后 cursor 已越过发图步：取 cursor-1；否则若当前步仍是发图则取当前。"""
    items = job.items or []
    c = int(job.cursor or 0)
    if c > 0 and c <= len(items):
        it = items[c - 1]
        if getattr(it, "is_image_send", False):
            return it
    if 0 <= c < len(items):
        it = items[c]
        if getattr(it, "is_image_send", False):
            return it
    return None


def is_job_awaiting_image(job: ScheduledJob) -> bool:
    if not job or not job.enabled:
        return False
    if (job.state or "") != "paused":
        return False
    if not is_await_image_send(job.pause_reason or ""):
        return False
    return pending_image_step(job) is not None


def collect_awaiting_image_jobs(jobs: List[ScheduledJob]) -> List[ScheduledJob]:
    return [j for j in jobs if is_job_awaiting_image(j)]


def notes_for_awaiting_jobs(jobs: List[ScheduledJob], *, max_total: int = 80) -> str:
    """同一天待发图任务的备注汇总（去重，仅本人可见，不发图）。"""
    seen: List[str] = []
    for j in jobs or []:
        step = pending_image_step(j)
        if step is None:
            continue
        note = (getattr(step, "reminder_note", None) or "").strip()
        if note and note not in seen:
            seen.append(note)
    if not seen:
        return ""
    text = " / ".join(seen)
    if len(text) > max_total:
        text = text[: max(0, max_total - 1)] + "…"
    return text


def group_awaiting_by_day(jobs: List[ScheduledJob]) -> List[ImageDayGroup]:
    """文件夹任务按 folder_day_index+1 归类；非文件夹归 day=0。"""
    buckets: Dict[int, List[ScheduledJob]] = defaultdict(list)
    for j in jobs:
        if (getattr(j, "source_kind", "") or "") == "folder":
            day = int(getattr(j, "folder_day_index", 0) or 0) + 1
        else:
            day = 0
        buckets[day].append(j)
    out: List[ImageDayGroup] = []
    for day in sorted(buckets.keys(), key=lambda d: (d == 0, d)):
        out.append(ImageDayGroup(day_1based=day, jobs=buckets[day]))
    return out


@dataclass
class ImageSendOneResult:
    job_id: str
    ok: bool
    error: str = ""
    target: str = ""
    account_id: str = ""


def normalize_bulk_image_paths(
    image_paths: Optional[List[str]] = None,
    *,
    image_path: str = "",
) -> List[str]:
    """合并单路径/多路径，去重并校验文件存在，最多 MAX_BULK_IMAGES 张。"""
    raw: List[str] = []
    if image_paths:
        raw.extend(image_paths)
    if (image_path or "").strip():
        raw.append(image_path.strip())
    out: List[str] = []
    seen: set[str] = set()
    for p in raw:
        ap = os.path.abspath((p or "").strip())
        if not ap or ap in seen:
            continue
        if not os.path.isfile(ap):
            continue
        seen.add(ap)
        out.append(ap)
        if len(out) >= MAX_BULK_IMAGES:
            break
    return out


def customer_refs_for_job(cfg: AppConfig, job: ScheduledJob) -> List[str]:
    """通讯录条目上的监听用户（客户）标识列表。"""
    emap = {e.id: e for e in cfg.address_book}
    out: List[str] = []
    seen: set[str] = set()
    for eid in [str(x) for x in (getattr(job, "chat_entry_ids", None) or []) if str(x).strip()]:
        ent = emap.get(eid)
        if not ent:
            continue
        wu = (ent.watch_user or "").strip()
        if not wu or wu.lower() in seen:
            continue
        seen.add(wu.lower())
        out.append(wu)
    return out


async def send_image_for_job(
    *,
    job: ScheduledJob,
    cfg: AppConfig,
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    image_path: str = "",
    image_paths: Optional[List[str]] = None,
    caption_override: Optional[str] = None,
    multi_image_gap_sec: float = MULTI_IMAGE_GAP_SEC,
) -> ImageSendOneResult:
    """向任务目标发送 1–3 张图（不含客户同步；同步由 bulk 全局分阶段执行）。"""
    paths = normalize_bulk_image_paths(image_paths, image_path=image_path)
    if not paths:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_image_file")
    step = pending_image_step(job)
    if step is None:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_image_step")
    targets = resolve_job_chat_targets(cfg, job)
    if not targets:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_targets")
    acc = send_account_for_job_item(cfg, job, step)
    if not acc:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_account")
    client = shared_clients.get(acc)
    if client is None:
        return ImageSendOneResult(job_id=job.id, ok=False, error="offline", account_id=acc)

    cap = (caption_override or "").strip() if caption_override is not None else ""
    lock = account_locks.get(acc)
    if lock is None:
        lock = asyncio.Lock()
        account_locks[acc] = lock
    last_err = ""

    async def _send_paths_to_refs(refs: List[Any], *, caption: str) -> bool:
        nonlocal last_err
        ok_images = 0
        for img_i, path in enumerate(paths):
            img_ok = False
            for cref in refs:
                try:
                    entity = await _resolve_entity_for_send(client, cref)
                    await send_telegram_file_resilient(client, entity, path, caption=caption)
                    img_ok = True
                except Exception as exc:
                    last_err = str(exc)
                if len(refs) > 1:
                    await asyncio.sleep(0.2)
            if img_ok:
                ok_images += 1
            else:
                break
            if img_i + 1 < len(paths):
                await asyncio.sleep(max(0.0, float(multi_image_gap_sec)))
        return ok_images == len(paths)

    async with lock:
        try:
            if not await client.is_user_authorized():
                return ImageSendOneResult(job_id=job.id, ok=False, error="unauthorized", account_id=acc)
            if not await _send_paths_to_refs(targets, caption=cap):
                return ImageSendOneResult(
                    job_id=job.id,
                    ok=False,
                    error=last_err or "group_image_fail",
                    account_id=acc,
                )
            info(
                f"[TG] 一键发图成功：任务={job.source_name} 账号={acc} "
                f"图片={len(paths)} 目标数={len(targets)}"
            )
            return ImageSendOneResult(job_id=job.id, ok=True, account_id=acc)
        except Exception as exc:
            last_err = str(exc)
    return ImageSendOneResult(
        job_id=job.id,
        ok=False,
        error=last_err or "send_fail",
        account_id=acc,
    )


def _dedupe_customer_refs(refs: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for r in refs:
        key = (r or "").strip()
        if not key:
            continue
        lk = key.lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append(key)
    return out


async def _dm_customers_one_by_one(
    *,
    client: Any,
    refs: List[str],
    paths: Optional[List[str]] = None,
    text: str = "",
    multi_image_gap_sec: float = MULTI_IMAGE_GAP_SEC,
    gap_min: float = IMAGE_SEND_GAP_MIN_SEC,
    gap_max: float = IMAGE_SEND_GAP_MAX_SEC,
) -> Tuple[bool, str]:
    """逐个客户私发图片或文字。"""
    if not refs:
        return False, "no_targets"
    body = (text or "").strip()
    use_image = bool(paths)
    if not use_image and not body:
        return True, ""
    any_ok = False
    last_err = ""
    for i, cref in enumerate(refs):
        try:
            entity = await _resolve_entity_for_send(client, cref)
            if use_image:
                for img_i, path in enumerate(paths or []):
                    await send_telegram_file_resilient(client, entity, path, caption="")
                    if img_i + 1 < len(paths or []):
                        await asyncio.sleep(max(0.0, float(multi_image_gap_sec)))
            else:
                await send_telegram_message_resilient(client, entity, body)
            any_ok = True
        except Exception as exc:
            last_err = str(exc)
        if i + 1 < len(refs):
            await asyncio.sleep(random.uniform(gap_min, gap_max))
    return any_ok, last_err


def _resume_one_job(
    job: ScheduledJob,
    *,
    resume_job: Callable[[str], bool],
    finish_job_if_exhausted: Optional[Callable[[str], bool]],
) -> bool:
    if job.cursor >= job.item_count() and finish_job_if_exhausted:
        return bool(finish_job_if_exhausted(job.id))
    return bool(resume_job(job.id))


async def bulk_send_images_and_resume(
    *,
    jobs: List[ScheduledJob],
    cfg: AppConfig,
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    image_path: str = "",
    image_paths: Optional[List[str]] = None,
    resume_job: Callable[[str], bool],
    finish_job_if_exhausted: Optional[Callable[[str], bool]] = None,
    on_progress: Optional[Callable[[int, int, ImageSendOneResult], None]] = None,
    gap_min: float = IMAGE_SEND_GAP_MIN_SEC,
    gap_max: float = IMAGE_SEND_GAP_MAX_SEC,
    multi_image_gap_sec: float = MULTI_IMAGE_GAP_SEC,
    sync_to_customer: bool = False,
    customer_extra_text: str = "",
    customer_image_delay_sec: float = CUSTOMER_IMAGE_DELAY_SEC,
    customer_text_delay_sec: float = CUSTOMER_TEXT_DELAY_SEC,
) -> Tuple[int, int, int]:
    """
    返回 (ok, fail, resumed)。
    sync_to_customer=True：全部群图 → 等 → 逐个客户图 → 等 →（可选）逐个客户文字。
    """
    paths = normalize_bulk_image_paths(image_paths, image_path=image_path)
    if not paths:
        return 0, len(jobs), 0

    mode = "并同步客户" if sync_to_customer else "仅群图"
    info(f"[TG] 一键发图开始：{mode} 任务={len(jobs)} 图片={len(paths)}")

    total = len(jobs)
    group_ok_jobs: List[ScheduledJob] = []
    job_results: Dict[str, ImageSendOneResult] = {}
    job_customers: Dict[str, List[str]] = {}
    job_account: Dict[str, str] = {}

    for i, job in enumerate(jobs):
        res = await send_image_for_job(
            job=job,
            cfg=cfg,
            shared_clients=shared_clients,
            account_locks=account_locks,
            image_paths=paths,
            multi_image_gap_sec=multi_image_gap_sec,
        )
        job_results[job.id] = res
        if res.account_id:
            job_account[job.id] = res.account_id
        if on_progress:
            try:
                on_progress(i + 1, total, res)
            except Exception:
                pass
        if res.ok:
            group_ok_jobs.append(job)
            if sync_to_customer:
                job_customers[job.id] = customer_refs_for_job(cfg, job)
        if i + 1 < total:
            await asyncio.sleep(random.uniform(gap_min, gap_max))

    if not sync_to_customer:
        ok_n = fail_n = resumed = 0
        for job in jobs:
            res = job_results[job.id]
            if res.ok:
                ok_n += 1
                if _resume_one_job(
                    job,
                    resume_job=resume_job,
                    finish_job_if_exhausted=finish_job_if_exhausted,
                ):
                    resumed += 1
            else:
                fail_n += 1
        info(
            f"[PING] 一键发图完成并已继续任务："
            f"成功={ok_n} 失败={fail_n} 已继续={resumed}"
        )
        return ok_n, fail_n, resumed

    if not group_ok_jobs:
        return 0, total, 0

    # 按账号分组客户，逐账号串行私发（同一账号内逐个客户）
    by_acc: Dict[str, List[str]] = defaultdict(list)
    for job in group_ok_jobs:
        acc = job_account.get(job.id) or job_results[job.id].account_id
        if not acc:
            continue
        for r in job_customers.get(job.id, []):
            by_acc[acc].append(r)
    for acc in list(by_acc.keys()):
        by_acc[acc] = _dedupe_customer_refs(by_acc[acc])

    total_cust = sum(len(v) for v in by_acc.values())
    if total_cust <= 0:
        fail_n = 0
        for job in jobs:
            res = job_results[job.id]
            if not res.ok:
                fail_n += 1
                continue
            job_results[job.id] = ImageSendOneResult(
                job_id=job.id, ok=False, error="no_customer", account_id=res.account_id
            )
            fail_n += 1
        return 0, fail_n, 0

    info(
        f"[TG] 全部群图已发完（成功 {len(group_ok_jobs)}/{total}），"
        f"{customer_image_delay_sec:g} 秒后逐个向客户私发图片（共 {total_cust} 人）"
    )
    await asyncio.sleep(max(0.0, float(customer_image_delay_sec)))

    cust_img_ok = False
    last_err = ""
    for acc, refs in by_acc.items():
        client = shared_clients.get(acc)
        if client is None:
            last_err = "offline"
            continue
        lock = account_locks.get(acc)
        if lock is None:
            lock = asyncio.Lock()
            account_locks[acc] = lock
        async with lock:
            ok, err = await _dm_customers_one_by_one(
                client=client,
                refs=refs,
                paths=paths,
                multi_image_gap_sec=multi_image_gap_sec,
                gap_min=gap_min,
                gap_max=gap_max,
            )
            if ok:
                cust_img_ok = True
            else:
                last_err = err or last_err
    if not cust_img_ok:
        warning(f"[TG] 客户私发图片失败：{last_err}")
        for job in jobs:
            res = job_results[job.id]
            if res.ok:
                job_results[job.id] = ImageSendOneResult(
                    job_id=job.id,
                    ok=False,
                    error=last_err or "customer_image_fail",
                    account_id=res.account_id,
                )
        return 0, len(jobs), 0

    info(f"[TG] 一键发图同步客户：客户图片私发完成 共 {total_cust} 人")
    extra = (customer_extra_text or "").strip()
    if extra:
        info(f"[TG] 客户图片已发完，{customer_text_delay_sec:g} 秒后逐个私发附加文字")
        await asyncio.sleep(max(0.0, float(customer_text_delay_sec)))
        text_ok = False
        for acc, refs in by_acc.items():
            client = shared_clients.get(acc)
            if client is None:
                last_err = "offline"
                continue
            lock = account_locks.get(acc)
            if lock is None:
                lock = asyncio.Lock()
                account_locks[acc] = lock
            async with lock:
                ok, err = await _dm_customers_one_by_one(
                    client=client,
                    refs=refs,
                    text=extra,
                    gap_min=gap_min,
                    gap_max=gap_max,
                )
                if ok:
                    text_ok = True
                else:
                    last_err = err or last_err
        if not text_ok:
            warning(f"[TG] 客户附加文字发送失败：{last_err}")
            for job in jobs:
                res = job_results[job.id]
                if res.ok:
                    job_results[job.id] = ImageSendOneResult(
                        job_id=job.id,
                        ok=False,
                        error=last_err or "customer_text_fail",
                        account_id=res.account_id,
                    )
            return 0, len(jobs), 0

    ok_n = fail_n = resumed = 0
    for job in jobs:
        res = job_results[job.id]
        if not res.ok:
            fail_n += 1
            continue
        if not job_customers.get(job.id):
            fail_n += 1
            continue
        ok_n += 1
        if _resume_one_job(
            job,
            resume_job=resume_job,
            finish_job_if_exhausted=finish_job_if_exhausted,
        ):
            resumed += 1
    info(
        f"[PING] 一键发图并同步客户完成并已继续任务："
        f"成功={ok_n} 失败={fail_n} 已继续={resumed}"
    )
    return ok_n, fail_n, resumed
