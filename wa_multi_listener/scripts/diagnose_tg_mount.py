"""模拟 Qt 挂载 TG 面板后的连接流程（不启动 GUI）。"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TG = os.path.join(ROOT, "dist", "WAHelper", "telegram")
REPO = os.path.normpath(os.path.join(ROOT, ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, ROOT)
os.environ["TG_HELPER_DATA_ROOT"] = TG

OUT = os.path.join(TG, "logs", "tg_mount_diag.txt")


def main() -> int:
    from startup_bootstrap import bootstrap_tg_logging, bootstrap_tg_runtime
    from tg_multi_listener.config import load_config
    from tg_multi_listener.listener import ListenerController
    from tg_multi_listener.scheduler import ScheduleRunner
    from tg_multi_listener.telethon_coordinator import TelethonCoordinator

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bootstrap_tg_runtime()
    bootstrap_tg_logging()
    cfg = load_config()
    listener = ListenerController()
    scheduler = ScheduleRunner()
    coord = TelethonCoordinator(listener, scheduler)
    listener.start(cfg, lambda _x: None)
    scheduler.start(cfg)
    if not coord.start(cfg):
        open(OUT, "w", encoding="utf-8").write("coordinator.start() returned False\n")
        return 2

    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        n = len(coord.connected_account_ids())
        if n > 0:
            break
        time.sleep(1)

    ids = sorted(coord.connected_account_ids())
    lines = [
        f"api_id={cfg.api_id}",
        f"enabled_accounts={sum(1 for a in cfg.accounts if a.enabled)}",
        f"connected={len(ids)}",
        f"sample={ids[:5]}",
        f"running={coord.is_running()}",
    ]
    open(OUT, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    coord.stop(join_timeout=15)
    return 0 if ids else 1


if __name__ == "__main__":
    raise SystemExit(main())
