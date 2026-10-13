"""从 schedule2 备份中选出任务数最多的一份写回 data/schedule2.json。"""
from __future__ import annotations

import json
import os
import shutil
from glob import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WA = os.path.join(ROOT, "dist", "WAHelper", "whatsapp")
DATA = os.path.join(WA, "data")


def _count_jobs(path: str) -> int:
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
        return len(data.get("jobs") or [])
    except (OSError, json.JSONDecodeError):
        return -1


def main() -> int:
    candidates = [os.path.join(DATA, "schedule2.json")]
    candidates += sorted(glob(os.path.join(DATA, "schedule2.json.bak_*")), reverse=True)
    candidates += sorted(glob(os.path.join(DATA, "**", "schedule2.json"), recursive=True))
    best = ""
    best_n = -1
    seen: set[str] = set()
    for p in candidates:
        p = os.path.normpath(p)
        if p in seen or not os.path.isfile(p):
            continue
        seen.add(p)
        n = _count_jobs(p)
        if n > best_n:
            best_n = n
            best = p
    if not best or best_n <= 0:
        print("未找到可用的 schedule2 备份")
        return 1
    dst = os.path.join(DATA, "schedule2.json")
    os.makedirs(DATA, exist_ok=True)
    shutil.copy2(best, dst)
    print(f"已恢复 schedule2：{best_n} 条任务 ← {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
