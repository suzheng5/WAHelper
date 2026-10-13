"""把 userdata_preserve/telegram 的配置与任务同步到 dist/WAHelper/telegram（不动 sessions）。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESERVE = os.path.join(ROOT, "userdata_preserve", "telegram")
TARGET = os.path.join(ROOT, "dist", "WAHelper", "telegram")
BACKUP = os.path.join(
    ROOT,
    "userdata_preserve",
    f"telegram_dist_before_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
)


def _count(path: str) -> dict:
    out: dict = {}
    cfg = os.path.join(path, "config.json")
    sched = os.path.join(path, "data", "schedules.json")
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            data = json.load(f)
        out["api_id"] = data.get("api_id")
        out["accounts"] = len(data.get("accounts") or [])
        out["address_book"] = len(data.get("address_book") or [])
    if os.path.isfile(sched):
        with open(sched, encoding="utf-8-sig") as f:
            jobs = json.load(f)
        out["schedules"] = len(jobs) if isinstance(jobs, list) else 0
    return out


def main() -> int:
    if not os.path.isfile(os.path.join(PRESERVE, "config.json")):
        print(f"缺少 preserve 配置：{PRESERVE}")
        return 1
    if not os.path.isdir(TARGET):
        os.makedirs(TARGET, exist_ok=True)
        print(f"已创建目录：{TARGET}")

    if os.path.isdir(TARGET):
        shutil.copytree(TARGET, BACKUP, dirs_exist_ok=True)
        print(f"已备份当前 dist 数据：{BACKUP}")

    before = _count(TARGET)
    shutil.copy2(os.path.join(PRESERVE, "config.json"), os.path.join(TARGET, "config.json"))
    for name in ("data", "sessions"):
        src = os.path.join(PRESERVE, name)
        dst = os.path.join(TARGET, name)
        if not os.path.isdir(src):
            continue
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    after = _count(TARGET)
    print(json.dumps({"before": before, "after": after}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
