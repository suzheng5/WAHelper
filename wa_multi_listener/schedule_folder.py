"""定时任务文件夹源：扫描、排序、展示文案。"""
from __future__ import annotations

import os
import random
import re
from typing import Any, List, Optional, Tuple

from i18n import t

_FOLDER_TXT_NUM = re.compile(r"^(\d+)")

# 「一键开始下一天」后各任务独立随机延迟，避免同时发送
FOLDER_ADVANCE_DELAY_MIN_SEC = 10.0
FOLDER_ADVANCE_DELAY_MAX_SEC = 60.0
# 一键下一天：每批处理任务数及批间暂停（秒），减轻并发与写入竞态
FOLDER_BULK_ADVANCE_BATCH_SIZE = 10
FOLDER_BULK_ADVANCE_BATCH_PAUSE_SEC = 3.0


def random_folder_advance_delay_seconds() -> float:
    return random.uniform(FOLDER_ADVANCE_DELAY_MIN_SEC, FOLDER_ADVANCE_DELAY_MAX_SEC)


def scan_schedule_folder(folder_path: str) -> Tuple[List[str], List[str]]:
    """扫描文件夹内 TXT：仅保留文件名以数字开头的，按数字升序。"""
    root = os.path.abspath((folder_path or "").strip())
    if not root or not os.path.isdir(root):
        return [], [t("folder.scan_not_dir")]
    numbered: dict[int, str] = {}
    errors: List[str] = []
    for name in os.listdir(root):
        if not name.lower().endswith(".txt"):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        stem = os.path.splitext(name)[0]
        m = _FOLDER_TXT_NUM.match(stem)
        if not m:
            continue
        num = int(m.group(1))
        if num in numbered:
            errors.append(t("folder.scan_dup_day", num=num, a=numbered[num], b=name))
        else:
            numbered[num] = name
    if errors:
        return [], errors
    if not numbered:
        return [], [t("folder.scan_no_numbered")]
    ordered = [numbered[k] for k in sorted(numbered.keys())]
    return ordered, []

def folder_txt_abs_path(folder_path: str, rel_name: str) -> str:
    return os.path.join(os.path.abspath(folder_path), rel_name)


def resolve_folder_day_filename(folder_path: str, rel_name: str) -> str:
    """按天数编号匹配磁盘上的实际 TXT 名（兼容「3灰飞」与「3 灰飞」等差异）。"""
    root = os.path.abspath((folder_path or "").strip())
    rel = (rel_name or "").strip()
    if not root or not rel:
        return rel_name
    if os.path.isfile(os.path.join(root, rel)):
        return rel
    stem = os.path.splitext(rel)[0]
    m = _FOLDER_TXT_NUM.match(stem)
    if not m or not os.path.isdir(root):
        return rel
    day = m.group(1)
    for name in os.listdir(root):
        if not name.lower().endswith(".txt"):
            continue
        ns = os.path.splitext(name)[0]
        nm = _FOLDER_TXT_NUM.match(ns)
        if nm and nm.group(1) == day:
            return name
    return rel


def read_folder_txt_utf8(folder_path: str, rel_name: str) -> Tuple[str, str]:
    """返回 (文本内容, 错误信息)。"""
    rel_name = resolve_folder_day_filename(folder_path, rel_name)
    path = folder_txt_abs_path(folder_path, rel_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), ""
    except UnicodeDecodeError:
        return "", t("folder.read_decode_fail")
    except OSError as exc:
        return "", t("folder.read_fail", err=exc)


def folder_day_number_from_name(rel_name: str) -> Optional[int]:
    """从「4.txt / 11女二退.txt」解析天数编号；失败返回 None。"""
    stem = os.path.splitext((rel_name or "").strip())[0]
    m = _FOLDER_TXT_NUM.match(stem)
    if not m:
        return None
    return int(m.group(1))


def index_for_day_number(files: List[str], day_num: int) -> Optional[int]:
    for i, name in enumerate(files or []):
        n = folder_day_number_from_name(name)
        if n is not None and n == day_num:
            return i
    return None


def rescan_folder_files_keep_day(job: Any) -> Tuple[List[str], int, str]:
    """
    重新扫描文件夹 TXT 列表，尽量保持当前「天数编号」。
    返回 (新文件列表, 新下标, 错误)。
    """
    path = str(getattr(job, "folder_path", "") or "").strip()
    ordered, errors = scan_schedule_folder(path)
    if errors:
        return [], 0, errors[0]
    if not ordered:
        return [], 0, t("folder.scan_no_numbered")
    old_files = list(getattr(job, "folder_files", None) or [])
    old_idx = max(0, int(getattr(job, "folder_day_index", 0) or 0))
    day_num: Optional[int] = None
    if 0 <= old_idx < len(old_files):
        day_num = folder_day_number_from_name(old_files[old_idx])
    new_idx = 0
    if day_num is not None:
        found = index_for_day_number(ordered, day_num)
        new_idx = found if found is not None else min(old_idx, len(ordered) - 1)
    else:
        new_idx = min(old_idx, len(ordered) - 1)
    return ordered, new_idx, ""


def is_folder_job(job: Any) -> bool:
    kind = str(getattr(job, "source_kind", "file") or "file").strip()
    if kind == "folder":
        return True
    # 兼容旧数据：有 folder_files 即视为文件夹任务
    files = getattr(job, "folder_files", None) or []
    path = str(getattr(job, "folder_path", "") or "").strip()
    return bool(files) and bool(path)


def folder_day_total(job: Any) -> int:
    files = getattr(job, "folder_files", None) or []
    return len(files)


def can_advance_folder_day(job: Any) -> bool:
    if not is_folder_job(job):
        return False
    total = folder_day_total(job)
    if total <= 0:
        return False
    idx = int(getattr(job, "folder_day_index", 0) or 0)
    return idx < total - 1


def merge_folder_job_patch(existing: Any, patch: Any) -> Any:
    """合并任务补丁：防止后台调度用旧 folder_day_index 覆盖 UI 刚切换的天数。"""
    if not is_folder_job(existing):
        return patch
    ex_idx = int(getattr(existing, "folder_day_index", 0) or 0)
    pt_idx = int(getattr(patch, "folder_day_index", 0) or 0)
    if pt_idx < ex_idx:
        patch.folder_day_index = ex_idx
        patch.folder_files = list(getattr(existing, "folder_files", None) or [])
        patch.source_name = getattr(existing, "source_name", "")
        patch.source_path = getattr(existing, "source_path", "")
        if hasattr(existing, "items"):
            patch.items = existing.items
        if hasattr(existing, "rows"):
            patch.rows = existing.rows
    return patch


def split_folder_jobs_for_bulk_advance(jobs: List[Any]) -> Tuple[List[Any], List[Any]]:
    """一键下一天：返回 (可进入下一天, 已在最后一天将删除)。"""
    advanceable: List[Any] = []
    at_last_day: List[Any] = []
    for j in jobs:
        if not is_folder_job(j):
            continue
        if can_advance_folder_day(j):
            advanceable.append(j)
        else:
            at_last_day.append(j)
    return advanceable, at_last_day


def format_folder_last_day_delete_line(*, target_label: str, current_name: str, day_one_based: int, total_days: int) -> str:
    return t(
        "folder.last_day_delete",
        target=target_label,
        current=current_name,
        day=day_one_based,
        total=total_days,
    )


def _job_step_count(job: Any) -> int:
    items = getattr(job, "items", None)
    if items is not None:
        return len(items)
    rows = getattr(job, "rows", None)
    if rows is not None:
        return len(rows)
    return 0


def is_folder_job_fully_completed(job: Any) -> bool:
    """文件夹任务：已到最后一天且当天条目已全部发完。"""
    if not is_folder_job(job):
        return False
    total = folder_day_total(job)
    if total <= 0:
        return False
    idx = int(getattr(job, "folder_day_index", 0) or 0)
    if idx < total - 1:
        return False
    steps = _job_step_count(job)
    if steps <= 0:
        return False
    cursor = max(0, int(getattr(job, "cursor", 0) or 0))
    return cursor >= steps


def job_eligible_for_bulk_delete(job: Any) -> bool:
    """一键删除：单 TXT 任务；或文件夹任务且全部天数已发完。"""
    if not is_folder_job(job):
        return True
    return is_folder_job_fully_completed(job)


def bulk_delete_job_summary(jobs: List[Any]) -> tuple[int, int, int, List[Any], List[Any]]:
    """返回 (单TXT数, 已完成文件夹数, 保留文件夹数, 待删列表, 保留列表)。"""
    to_delete: List[Any] = []
    kept: List[Any] = []
    single_txt = 0
    folder_done = 0
    folder_kept = 0
    for j in jobs:
        if job_eligible_for_bulk_delete(j):
            to_delete.append(j)
            if is_folder_job(j):
                folder_done += 1
            else:
                single_txt += 1
        else:
            kept.append(j)
            if is_folder_job(j):
                folder_kept += 1
    return single_txt, folder_done, folder_kept, to_delete, kept


def format_bulk_delete_confirm_message(
    *,
    single_txt: int,
    folder_done: int,
    folder_kept: int,
    total_delete: int,
) -> str:
    parts: List[str] = [t("folder.bulk_delete_header", total=total_delete)]
    if single_txt > 0:
        parts.append(t("folder.bulk_delete_single", n=single_txt))
    if folder_done > 0:
        parts.append(t("folder.bulk_delete_folder_done", n=folder_done))
    msg = "\n".join(parts)
    if folder_kept > 0:
        msg += t("folder.bulk_delete_keep", n=folder_kept)
    msg += t("folder.bulk_delete_confirm")
    return msg


def schedule_kind_badge(job: Any) -> str:
    """任务类型短标签，用于群名后区分单 TXT 与文件夹任务。"""
    if is_folder_job(job):
        total = folder_day_total(job)
        if total > 0:
            idx = max(0, int(getattr(job, "folder_day_index", 0) or 0))
            return t("folder.badge_folder_day", cur=idx + 1, total=total)
        return t("folder.badge_folder")
    return t("folder.badge_single")


def _job_has_chat_entry(job: Any, entry_id: str) -> bool:
    eid = str(entry_id or "").strip()
    if not eid:
        return False
    ids = {str(x).strip() for x in (getattr(job, "chat_entry_ids", None) or []) if str(x).strip()}
    return eid in ids


def entry_schedule_kind_hint(jobs: List[Any], entry_id: str) -> str:
    """定时任务页：某通讯录群若有对应任务，返回类型标签；无任务则返回空串。"""
    for j in jobs:
        if _job_has_chat_entry(j, entry_id):
            return schedule_kind_badge(j)
    return ""


def taskmgr_job_file_label(job: Any) -> str:
    """任务卡片「文档：」行文案（位置不变，文件夹任务附加天数）。"""
    name = (getattr(job, "source_name", None) or "").strip() or t("folder.job_unnamed")
    if is_folder_job(job):
        total = folder_day_total(job)
        if total > 0:
            idx = max(0, int(getattr(job, "folder_day_index", 0) or 0))
            return t("folder.job_file_day", name=name, cur=idx + 1, total=total)
    return t("folder.job_file", name=name)


def format_folder_advance_line(
    *,
    target_label: str,
    current_name: str,
    next_name: str,
    next_day_one_based: int,
    total_days: int,
) -> str:
    return t(
        "folder.advance_line",
        target=target_label,
        current=current_name,
        next=next_name,
        day=next_day_one_based,
        total=total_days,
    )
