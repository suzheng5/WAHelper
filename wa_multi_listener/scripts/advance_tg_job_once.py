"""手动将马克8764 / Krispy 3K 任务从第 2 天切到第 3 天（修正 TXT 文件名空格）。"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

WA_ROOT = Path(__file__).resolve().parents[1]
AI_ROOT = WA_ROOT.parent
TG_DATA = WA_ROOT / "dist" / "WAHelper" / "telegram"
JOB_ID = "d1d0ed72f5bb"

for p in (str(AI_ROOT), str(WA_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ["TG_HELPER_DATA_ROOT"] = str(TG_DATA)

from json_atomic import atomic_write_json
from schedule_folder import random_folder_advance_delay_seconds
from tg_multi_listener.compat_config import ensure_dirs, load_config
from tg_multi_listener.scheduler import ScheduledJob, _job_to_dict, load_jobs

_DAY_FILE = re.compile(r"^(\d+)")


def _job_from_row(row: dict) -> ScheduledJob | None:
    from tg_multi_listener.scheduler import _doc_from_dict

    items = []
    for x in row.get("items") or []:
        it = _doc_from_dict(x)
        if it:
            items.append(it)
    try:
        return ScheduledJob(
            id=str(row["id"]),
            enabled=bool(row.get("enabled", False)),
            chat_ids=[int(x) for x in row.get("chat_ids") or []],
            interval_min_minutes=float(row.get("interval_min_minutes", 0)),
            interval_max_minutes=float(row.get("interval_max_minutes", 0)),
            source_path=str(row.get("source_path", "")),
            source_name=str(row.get("source_name", "")),
            items=items,
            chat_entry_ids=[str(x) for x in row.get("chat_entry_ids") or []],
            cursor=int(row.get("cursor", 0)),
            state=str(row.get("state", "paused")),
            pause_reason=str(row.get("pause_reason", "")),
            next_send_ts=float(row.get("next_send_ts", 0)),
            remaining_seconds=float(row.get("remaining_seconds", 0)),
            last_send_ts=float(row.get("last_send_ts", 0)),
            last_error=str(row.get("last_error", "")),
            interval_mode=str(row.get("interval_mode", "txt")),
            source_kind=str(row.get("source_kind", "file")),
            folder_path=str(row.get("folder_path", "")),
            folder_files=[str(x) for x in row.get("folder_files") or []],
            folder_day_index=int(row.get("folder_day_index", 0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _resolve_folder_file(folder_path: str, rel_name: str) -> str:
    full = os.path.join(folder_path, rel_name)
    if os.path.isfile(full):
        return rel_name
    m = _DAY_FILE.match(os.path.splitext(rel_name)[0])
    if not m:
        return rel_name
    day = m.group(1)
    for name in os.listdir(folder_path):
        if not name.lower().endswith(".txt"):
            continue
        stem = os.path.splitext(name)[0]
        if _DAY_FILE.match(stem) and _DAY_FILE.match(stem).group(1) == day:
            return name
    return rel_name


def main() -> int:
    from tg_multi_listener.scheduler import _reload_folder_day_items_tg

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = WA_ROOT / "backup" / f"backup_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    sched_path = TG_DATA / "data" / "schedules.json"
    shutil.copy2(sched_path, backup_dir / "schedules.json")

    cfg = load_config()
    jobs = load_jobs()
    target = next((j for j in jobs if j.id == JOB_ID), None)
    if target is None:
        raise SystemExit(f"未找到任务 {JOB_ID}")

    next_index = int(target.folder_day_index) + 1
    if next_index >= len(target.folder_files):
        raise SystemExit("已是最后一天")

    rel = _resolve_folder_file(target.folder_path, target.folder_files[next_index])
    print(f"切换前：{target.source_name} 第 {target.folder_day_index + 1} 天")
    print(f"加载 TXT：{rel!r}")

    ok, err = _reload_folder_day_items_tg(target, cfg, rel)
    if not ok:
        raise SystemExit(f"加载失败：{err}")

    target.folder_files[next_index] = rel
    target.folder_day_index = next_index
    target.cursor = 0
    target.enabled = True
    target.state = "running"
    target.pause_reason = ""
    target.next_send_ts = time.time() + random_folder_advance_delay_seconds()
    target.remaining_seconds = 0.0
    target.last_error = ""

    by_id = {j.id: j for j in jobs}
    by_id[target.id] = target
    ensure_dirs()
    atomic_write_json(str(sched_path), [_job_to_dict(by_id[j.id]) for j in jobs])

    print(
        f"切换后：{target.source_name} 第 {target.folder_day_index + 1}/{len(target.folder_files)} 天 "
        f"共 {len(target.items)} 步，enabled={target.enabled} state={target.state}"
    )
    print(f"备份：{backup_dir / 'schedules.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
