"""退回昨天剩余的第12/13天（第一步/第二步）任务到前一天并尽量对齐进度。"""
from __future__ import annotations

import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

TG_ROOT = Path(r"c:\Users\USER\Desktop\AI\wa_multi_listener\dist\WAHelper\telegram")
SCHEDULE = TG_ROOT / "data" / "schedules.json"
os.environ["TG_HELPER_DATA_ROOT"] = str(TG_ROOT)

_AI = Path(r"c:\Users\USER\Desktop\AI")
_WA = _AI / "wa_multi_listener"
for p in (_WA, _AI):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from schedule_folder import read_folder_txt_utf8, resolve_folder_day_filename  # noqa: E402
from tg_multi_listener.compat_config import load_config  # noqa: E402
from tg_multi_listener.schedule_txt_import import import_doc_items  # noqa: E402
from tg_multi_listener.scheduler import (  # noqa: E402
    _reload_folder_day_items_tg,
    load_jobs,
    save_jobs,
)


def day_1based(j) -> int:
    return int(getattr(j, "folder_day_index", 0) or 0) + 1


def first_stage_cursor(folder_path: str, rel_name: str) -> tuple[int | None, int]:
    """返回 (对齐 cursor, 条目数)。无提醒则 cursor=None。"""
    text, err = read_folder_txt_utf8(folder_path, rel_name)
    if err:
        return None, 0
    items, _ = import_doc_items(text, valid_accounts=None, require_per_item_interval=False)
    n = len(items or [])
    rem = [i for i, it in enumerate(items or []) if getattr(it, "is_reminder", False)]
    if not rem:
        return None, n
    # 历史数据：stage_reminder 暂停时 cursor = 首个提醒下标 + 1
    return rem[0] + 1, n


def main() -> int:
    if not SCHEDULE.is_file():
        print(f"找不到 {SCHEDULE}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = SCHEDULE.with_name(f"schedules.json.bak_rollback2_{stamp}")
    shutil.copy2(SCHEDULE, bak)
    print(f"已备份：{bak}")

    jobs = load_jobs(force=True)
    cfg = load_config()

    # 昨天剩下的：第12/13天，cursor 0 或 1
    cands = []
    for j in jobs:
        if (getattr(j, "source_kind", "") or "") != "folder":
            continue
        d = day_1based(j)
        c = int(j.cursor or 0)
        if d not in (12, 13):
            continue
        if c > 1:
            print(f"跳过 {j.id[:8]} d={d} cursor={c}（不是第一步/第二步）")
            continue
        if (j.pause_reason or "") == "round_complete":
            print(f"跳过 {j.id[:8]} d={d}（已结束）")
            continue
        cands.append(j)

    print(f"候选 {len(cands)} 个")
    if not cands:
        print("没有可退回的任务")
        return 0

    changed = []
    skipped = []
    for j in cands:
        prev_day = day_1based(j) - 1
        prev_idx = prev_day - 1
        if prev_idx < 0 or prev_idx >= len(j.folder_files or []):
            skipped.append(f"{j.id[:8]} 无第{prev_day}天文件")
            continue
        rel = resolve_folder_day_filename(j.folder_path, j.folder_files[prev_idx])
        align_cur, n_items = first_stage_cursor(j.folder_path, rel)
        ok, err = _reload_folder_day_items_tg(j, cfg, rel)
        if not ok:
            skipped.append(f"{j.id[:8]} 加载失败：{err}")
            continue

        if align_cur is not None:
            if align_cur < 0 or align_cur > len(j.items or []):
                skipped.append(
                    f"{j.id[:8]} 对齐 cursor={align_cur} 超出条目 {len(j.items or [])}"
                )
                continue
            cursor = align_cur
            pause = "stage_reminder"
            note = f"阶段提醒对齐 cursor={cursor}"
        else:
            # 上一天 TXT 无阶段提醒（如 12.txt）：退回后从当天开头暂停
            cursor = 0
            pause = "startup_doc"
            note = "无阶段提醒，退回后从头暂停"

        j.folder_files[prev_idx] = rel
        j.folder_day_index = prev_idx
        j.cursor = cursor
        j.enabled = True
        j.state = "paused"
        j.pause_reason = pause
        j.next_send_ts = 0.0
        j.remaining_seconds = 0.0
        j.last_error = ""
        changed.append(j)
        print(
            f"已回退 {j.id[:8]} {j.source_name} → 第{prev_day}天/{rel} "
            f"cursor={cursor} pause={pause}（{note}）"
        )

    if skipped:
        print("跳过：")
        for s in skipped:
            print(" ", s)

    if not changed:
        print("全部失败，未改文件")
        return 1

    save_jobs(jobs)
    print(f"\n成功 {len(changed)} 个，已写入 {SCHEDULE}")
    print("请重新打开程序查看。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
