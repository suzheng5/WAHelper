"""WA：待发图任务匹配、按天归类、串行 send_image（对齐 TG 一键发图）。"""
from __future__ import annotations

import asyncio
import os
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from i18n.pause_reason import is_await_image_send

from config import AppConfig, resolve_job_chat_targets
from logger_util import info, warning
from schedule_account import address_owner_map, resolve_send_account_id
from schedule2_runner import Schedule2Job, Schedule2Row
from wa_send import send_image_to_chat, send_text_to_chat

IMAGE_SEND_GAP_MIN_SEC = 2.0
IMAGE_SEND_GAP_MAX_SEC = 5.0
MULTI_IMAGE_GAP_SEC = 10.0
MAX_BULK_IMAGES = 3
# 群发图完成后 → 等此秒数再给客户私发图片
CUSTOMER_IMAGE_DELAY_SEC = 60.0
# 客户图片发完后 → 等此秒数再发可选附加文字
CUSTOMER_TEXT_DELAY_SEC = 30.0


@dataclass
class ImageDayGroup:
    """同一天的待发图任务。day_1based=0 表示非文件夹。"""

    day_1based: int
    jobs: List[Schedule2Job] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"day:{self.day_1based}" if self.day_1based > 0 else "other"


def pending_image_step(job: Schedule2Job) -> Optional[Schedule2Row]:
    """暂停后 cursor 已越过发图步：取 cursor-1；否则若当前步仍是发图则取当前。"""
    rows = job.rows or []
    c = int(job.cursor or 0)
    if c > 0 and c <= len(rows):
        it = rows[c - 1]
        if getattr(it, "is_image_send", False):
            return it
    if 0 <= c < len(rows):
        it = rows[c]
        if getattr(it, "is_image_send", False):
            return it
    return None


def is_job_awaiting_image(job: Schedule2Job) -> bool:
    if not job or not job.enabled:
        return False
    if (job.state or "") != "paused":
        return False
    if not is_await_image_send(job.pause_reason or ""):
        return False
    return pending_image_step(job) is not None


def collect_awaiting_image_jobs(jobs: List[Schedule2Job]) -> List[Schedule2Job]:
    return [j for j in jobs if is_job_awaiting_image(j)]


def notes_for_awaiting_jobs(jobs: List[Schedule2Job], *, max_total: int = 80) -> str:
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


def group_awaiting_by_day(jobs: List[Schedule2Job]) -> List[ImageDayGroup]:
    buckets: Dict[int, List[Schedule2Job]] = defaultdict(list)
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


def customer_pairs_for_job(
    job: Schedule2Job,
    cfg: AppConfig,
    step: Schedule2Row,
    accounts: Dict[str, Any],
) -> List[Tuple[str, str]]:
    """返回 (客户私聊标识=手机号, 发送账号) 列表。"""
    owners = address_owner_map(cfg)
    emap = {e.id: e for e in cfg.address_book}
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for eid in [str(x) for x in (job.chat_entry_ids or []) if str(x).strip()]:
        ent = emap.get(eid)
        if not ent:
            continue
        wu = (ent.watch_user or "").strip()
        if not wu:
            continue
        digits = "".join(c for c in wu if c.isdigit())
        if not digits or digits in seen:
            continue
        acc = resolve_send_account_id(step, eid, owners, accounts)
        if not acc:
            continue
        seen.add(digits)
        out.append((digits, acc))
    return out


async def _send_paths_to_pairs(
    *,
    paths: List[str],
    pairs: List[Tuple[str, str]],
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    caption: str = "",
    multi_image_gap_sec: float = MULTI_IMAGE_GAP_SEC,
) -> Tuple[bool, str, str]:
    """向若干 (chat_ref, account) 发图。返回 (ok, last_err, last_acc)。"""
    if not paths or not pairs:
        return False, "no_targets", ""
    last_err = ""
    ok_images = 0
    last_acc = pairs[0][1]
    for img_i, path in enumerate(paths):
        img_ok = False
        for cref, acc in pairs:
            last_acc = acc
            client = shared_clients.get(acc)
            if client is None:
                last_err = "offline"
                continue
            lock = account_locks.get(acc)
            if lock is None:
                lock = asyncio.Lock()
                account_locks[acc] = lock
            async with lock:
                try:
                    if await send_image_to_chat(client, cref, path, caption=caption):
                        img_ok = True
                except Exception as exc:
                    last_err = str(exc)
            if len(pairs) > 1:
                await asyncio.sleep(0.2)
        if img_ok:
            ok_images += 1
        else:
            break
        if img_i + 1 < len(paths):
            await asyncio.sleep(max(0.0, float(multi_image_gap_sec)))
    return ok_images == len(paths), last_err, last_acc


async def _send_text_to_pairs(
    *,
    text: str,
    pairs: List[Tuple[str, str]],
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
) -> Tuple[bool, str]:
    body = (text or "").strip()
    if not body:
        return True, ""
    last_err = ""
    any_ok = False
    for cref, acc in pairs:
        client = shared_clients.get(acc)
        if client is None:
            last_err = "offline"
            continue
        lock = account_locks.get(acc)
        if lock is None:
            lock = asyncio.Lock()
            account_locks[acc] = lock
        async with lock:
            try:
                ok, _ = await send_text_to_chat(client, cref, body)
                if ok:
                    any_ok = True
                else:
                    last_err = last_err or "send_text_fail"
            except Exception as exc:
                last_err = str(exc)
        if len(pairs) > 1:
            await asyncio.sleep(0.2)
    return any_ok, last_err


async def send_image_for_job(
    *,
    job: Schedule2Job,
    cfg: AppConfig,
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    accounts: Dict[str, Any],
    image_path: str = "",
    image_paths: Optional[List[str]] = None,
    caption_override: Optional[str] = None,
    multi_image_gap_sec: float = MULTI_IMAGE_GAP_SEC,
) -> ImageSendOneResult:
    """向任务群发送 1–3 张图（不含客户同步；同步由 bulk 全局分阶段执行）。"""
    paths = normalize_bulk_image_paths(image_paths, image_path=image_path)
    if not paths:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_image_file")
    step = pending_image_step(job)
    if step is None:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_image_step")

    owners = address_owner_map(cfg)
    emap = {e.id: e for e in cfg.address_book}
    entry_ids = [str(eid) for eid in (job.chat_entry_ids or []) if str(eid).strip()]
    pairs: List[Tuple[str, str]] = []
    if entry_ids:
        for eid in entry_ids:
            ent = emap.get(eid)
            if not ent or not (ent.chat_ref or "").strip():
                continue
            acc = resolve_send_account_id(step, eid, owners, accounts)
            if not acc:
                continue
            pairs.append((ent.chat_ref.strip(), acc))
    else:
        targets = resolve_job_chat_targets(cfg, job)
        acc = resolve_send_account_id(step, "", owners, accounts)
        if not acc or not targets:
            return ImageSendOneResult(job_id=job.id, ok=False, error="no_account_or_targets")
        for cref in targets:
            pairs.append((cref, acc))

    if not pairs:
        return ImageSendOneResult(job_id=job.id, ok=False, error="no_targets")

    cap = (caption_override or "").strip() if caption_override is not None else ""
    ok, last_err, last_acc = await _send_paths_to_pairs(
        paths=paths,
        pairs=pairs,
        shared_clients=shared_clients,
        account_locks=account_locks,
        caption=cap,
        multi_image_gap_sec=multi_image_gap_sec,
    )
    if not ok:
        return ImageSendOneResult(
            job_id=job.id,
            ok=False,
            error=last_err or "group_image_fail",
            account_id=last_acc,
        )
    info(
        f"[WA] 一键发图成功：任务={job.source_name} 账号={last_acc} "
        f"图片={len(paths)} 目标数={len(pairs)}"
    )
    return ImageSendOneResult(job_id=job.id, ok=True, account_id=last_acc)


def _dedupe_customer_pairs(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for cref, acc in pairs:
        key = (cref or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append((key, acc))
    return out


async def _send_pairs_one_by_one(
    *,
    pairs: List[Tuple[str, str]],
    shared_clients: Dict[str, Any],
    account_locks: Dict[str, asyncio.Lock],
    paths: Optional[List[str]] = None,
    text: str = "",
    multi_image_gap_sec: float = MULTI_IMAGE_GAP_SEC,
    gap_min: float = IMAGE_SEND_GAP_MIN_SEC,
    gap_max: float = IMAGE_SEND_GAP_MAX_SEC,
) -> Tuple[bool, str]:
    """逐个客户发送图片或文字；客户之间间隔 gap。"""
    if not pairs:
        return False, "no_targets"
    body = (text or "").strip()
    use_image = bool(paths)
    if not use_image and not body:
        return True, ""
    any_ok = False
    last_err = ""
    for i, (cref, acc) in enumerate(pairs):
        if use_image:
            ok, err, _ = await _send_paths_to_pairs(
                paths=paths or [],
                pairs=[(cref, acc)],
                shared_clients=shared_clients,
                account_locks=account_locks,
                caption="",
                multi_image_gap_sec=multi_image_gap_sec,
            )
            if ok:
                any_ok = True
            else:
                last_err = err or last_err or "customer_image_fail"
        else:
            ok, err = await _send_text_to_pairs(
                text=body,
                pairs=[(cref, acc)],
                shared_clients=shared_clients,
                account_locks=account_locks,
            )
            if ok:
                any_ok = True
            else:
                last_err = err or last_err or "customer_text_fail"
        if i + 1 < len(pairs):
            await asyncio.sleep(random.uniform(gap_min, gap_max))
    return any_ok, last_err


def _resume_one_job(
    job: Schedule2Job,
    *,
    resume_job: Callable[[str], bool],
    finish_job_if_exhausted: Optional[Callable[[str], bool]],
) -> bool:
    if job.cursor >= job.row_count() and finish_job_if_exhausted:
        return bool(finish_job_if_exhausted(job.id))
    return bool(resume_job(job.id))


async def bulk_send_images_and_resume(
    *,
    jobs: List[Schedule2Job],
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
    sync_to_customer=True 时全局分阶段：
    全部群图 → 等 customer_image_delay_sec → 逐个客户私发图
    → 等 customer_text_delay_sec →（有附加文字则）逐个客户私发文字。
    """
    paths = normalize_bulk_image_paths(image_paths, image_path=image_path)
    if not paths:
        return 0, len(jobs), 0
    accounts: Dict[str, Any] = {}
    try:
        for a in cfg.accounts:
            accounts[a.id] = a
    except Exception:
        accounts = {}

    mode = "并同步客户" if sync_to_customer else "仅群图"
    info(f"[WA] 一键发图开始：{mode} 任务={len(jobs)} 图片={len(paths)}")

    total = len(jobs)
    group_ok_jobs: List[Schedule2Job] = []
    job_results: Dict[str, ImageSendOneResult] = {}
    job_customers: Dict[str, List[Tuple[str, str]]] = {}

    # 阶段 1：先发完所有群的图片
    for i, job in enumerate(jobs):
        res = await send_image_for_job(
            job=job,
            cfg=cfg,
            shared_clients=shared_clients,
            account_locks=account_locks,
            accounts=accounts,
            image_paths=paths,
            multi_image_gap_sec=multi_image_gap_sec,
        )
        job_results[job.id] = res
        if on_progress:
            try:
                on_progress(i + 1, total, res)
            except Exception:
                pass
        if res.ok:
            group_ok_jobs.append(job)
            if sync_to_customer:
                step = pending_image_step(job)
                if step is not None:
                    job_customers[job.id] = customer_pairs_for_job(job, cfg, step, accounts)
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

    cust_pairs = _dedupe_customer_pairs(
        [p for jid in (j.id for j in group_ok_jobs) for p in job_customers.get(jid, [])]
    )
    if not group_ok_jobs:
        return 0, total, 0
    if not cust_pairs:
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
        f"[WA] 全部群图已发完（成功 {len(group_ok_jobs)}/{total}），"
        f"{customer_image_delay_sec:g} 秒后逐个向客户私发图片（共 {len(cust_pairs)} 人）"
    )
    await asyncio.sleep(max(0.0, float(customer_image_delay_sec)))
    ok_c, err_c = await _send_pairs_one_by_one(
        pairs=cust_pairs,
        shared_clients=shared_clients,
        account_locks=account_locks,
        paths=paths,
        multi_image_gap_sec=multi_image_gap_sec,
        gap_min=gap_min,
        gap_max=gap_max,
    )
    if not ok_c:
        warning(f"[WA] 客户私发图片失败：{err_c}")
        fail_n = 0
        for job in jobs:
            res = job_results[job.id]
            if not res.ok:
                fail_n += 1
                continue
            job_results[job.id] = ImageSendOneResult(
                job_id=job.id,
                ok=False,
                error=err_c or "customer_image_fail",
                account_id=res.account_id,
            )
            fail_n += 1
        return 0, fail_n, 0

    info(f"[WA] 一键发图同步客户：客户图片私发完成 共 {len(cust_pairs)} 人")

    extra = (customer_extra_text or "").strip()
    if extra:
        info(
            f"[WA] 客户图片已发完，{customer_text_delay_sec:g} 秒后逐个私发附加文字"
        )
        await asyncio.sleep(max(0.0, float(customer_text_delay_sec)))
        ok_t, err_t = await _send_pairs_one_by_one(
            pairs=cust_pairs,
            shared_clients=shared_clients,
            account_locks=account_locks,
            text=extra,
            gap_min=gap_min,
            gap_max=gap_max,
        )
        if not ok_t:
            warning(f"[WA] 客户附加文字发送失败：{err_t}")
            fail_n = 0
            for job in jobs:
                res = job_results[job.id]
                if not res.ok:
                    fail_n += 1
                    continue
                if not job_customers.get(job.id):
                    job_results[job.id] = ImageSendOneResult(
                        job_id=job.id,
                        ok=False,
                        error="no_customer",
                        account_id=res.account_id,
                    )
                    fail_n += 1
                    continue
                job_results[job.id] = ImageSendOneResult(
                    job_id=job.id,
                    ok=False,
                    error=err_t or "customer_text_fail",
                    account_id=res.account_id,
                )
                fail_n += 1
            return 0, fail_n, 0

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
