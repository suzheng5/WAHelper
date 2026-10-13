"""仪表盘：今日提醒计数。"""
from __future__ import annotations

import json
import os
from datetime import date
from threading import Lock

from .config import data_dir, ensure_dirs

_lock = Lock()


def _stats_path() -> str:
    ensure_dirs()
    return os.path.join(data_dir(), "stats.json")


def record_alert() -> None:
    today = str(date.today())
    with _lock:
        data = {"day": today, "count": 0}
        if os.path.isfile(_stats_path()):
            try:
                with open(_stats_path(), "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        if data.get("day") != today:
            data = {"day": today, "count": 0}
        data["count"] = int(data.get("count", 0)) + 1
        tmp = _stats_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _stats_path())


def today_alert_count() -> int:
    today = str(date.today())
    with _lock:
        if not os.path.isfile(_stats_path()):
            return 0
        try:
            with open(_stats_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return 0
        if data.get("day") != today:
            return 0
        return int(data.get("count", 0))
