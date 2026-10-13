"""
安全回退 TG 文件夹任务：仅当「当前 day 为 11–13、cursor=0」且
同文件夹上一天存在 stage_reminder 且 cursor 一致时，才退回并对齐进度。
对不齐的任务一律跳过。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

TG_ROOT = Path(r"c:\Users\USER\Desktop\AI\wa_multi_listener\dist\WAHelper\telegram")
SCHEDULE = TG_ROOT / "data" / "schedules.json"

os.environ["TG_HELPER_DATA_ROOT"] = str(TG_ROOT)

# 保证可导入整合包与 tg_multi_listener
_AI = Path(r"c:\Users\USER\Desktop\AI")
_WA = _AI / "wa_multi_listener"
for p in (_WA, _AI):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from tg_multi_listener.compat_config import load_config  # noqa: E402
from tg_multi_listener.scheduler import (  # noqa: E402
    _reload_folder_day_items_tg,
    load_jobs,
    save_jobs,
)


def day_1based(j) -> int:
    return int(getattr(j, "folder_day_index", 0) or 0) + 1


def main() -> int:
    if not SCHEDULE.is_file():
        print(f"找不到 {SCHEDULE}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = SCHEDULE.with_name(f"schedules.json.bak_rollback_{stamp}")
    shutil.copy2(SCHEDULE, bak)
    print(f"已备份：{bak}")

    jobs = load_jobs(force=True)
    cfg = load_config()

    # 参照：同文件夹、上一天、阶段提醒、cursor>0
    refs_by_folder_day: dict[tuple[str, int], list] = {}
    for j in jobs:
        if (getattr(j, "source_kind", "") or "") != "folder":
            continue
        if (j.pause_reason or "") != "stage_reminder":
            continue
        cur = int(j.cursor or 0)
        if cur <= 0:
            continue
        fp = (j.folder_path or "").strip()
        d = day_1based(j)
        refs_by_folder_day.setdefault((fp, d), []).append(j)

    plan: list[tuple] = []
    skipped: list[str] = []

    for j in jobs:
        if (getattr(j, "source_kind", "") or "") != "folder":
            continue
        d = day_1based(j)
        # 用户说 10–13 左右；误切后多在 11–13 的第一步
        if d < 11 or d > 13:
            continue
        if int(j.cursor or 0) != 0:
            skipped.append(f"跳过 {j.id[:8]} d={d} cursor={j.cursor}（不是第一步）")
            continue
        # 已停止的不碰（round_complete 等）
        if (j.state or "") == "paused" and (j.pause_reason or "") in (
            "round_complete",
        ):
            skipped.append(f"跳过 {j.id[:8]} d={d}（已结束）")
            continue

        prev_day = d - 1
        fp = (j.folder_path or "").strip()
        peers = refs_by_folder_day.get((fp, prev_day), [])
        if not peers:
            skipped.append(
                f"跳过 {j.id[:8]} d={d}→{prev_day} src={j.source_name}（无同文件夹上一天阶段提醒可对齐）"
            )
            continue
        cursors = [int(p.cursor or 0) for p in peers]
        # 必须所有参照 cursor 一致，否则宁可不退
        cnt = Counter(cursors)
        if len(cnt) != 1:
            skipped.append(
                f"跳过 {j.id[:8]} d={d}→{prev_day}（参照 cursor 不一致 {sorted(cnt)}）"
            )
            continue
        align_cur = cursors[0]
        plan.append((j, prev_day, align_cur, peers[0]))

    print(f"\n可安全回退：{len(plan)} 个")
    for j, prev_day, align_cur, peer in plan:
        print(
            f"  {j.id}  {j.source_name}  day {day_1based(j)}→{prev_day}  "
            f"cursor 0→{align_cur}  pause→stage_reminder  "
            f"(参照 {peer.id[:8]})"
        )
    print(f"\n跳过：{len(skipped)} 个")
    for line in skipped:
        print(f"  {line}")

    if not plan:
        print("\n没有可对齐的任务，不做任何修改。")
        return 0

    changed = []
    for j, prev_day, align_cur, _peer in plan:
        prev_idx = prev_day - 1
        if prev_idx < 0 or prev_idx >= len(j.folder_files or []):
            print(f"失败 {j.id}: folder_files 无第 {prev_day} 天")
            continue
        from schedule_folder import resolve_folder_day_filename

        rel = resolve_folder_day_filename(j.folder_path, j.folder_files[prev_idx])
        ok, err = _reload_folder_day_items_tg(j, cfg, rel)
        if not ok:
            print(f"失败 {j.id}: 加载 TXT 失败：{err}")
            continue
        n_items = len(j.items or [])
        if align_cur < 0 or align_cur > n_items:
            print(
                f"失败 {j.id}: 对齐 cursor={align_cur} 超出条目数 {n_items}，跳过"
            )
            continue
        j.folder_files[prev_idx] = rel
        j.folder_day_index = prev_idx
        j.cursor = align_cur
        j.enabled = True
        j.state = "paused"
        j.pause_reason = "stage_reminder"
        j.next_send_ts = 0.0
        j.remaining_seconds = 0.0
        j.last_error = ""
        changed.append(j)
        print(
            f"已回退 {j.id[:8]} → 第{prev_day}天/{j.source_name} cursor={align_cur} 阶段提醒暂停"
        )

    if not changed:
        print("全部失败，保留原文件（备份仍在）。")
        return 1

    save_jobs(jobs)
    print(f"\n已写入 {SCHEDULE}（成功 {len(changed)} 个）")
    print("请重新打开程序查看任务管理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
