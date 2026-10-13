"""JSON 任务列表读缓存：按文件 mtime 复用内存，写入后同步。"""
from __future__ import annotations

import os
import threading
from typing import Callable, List, TypeVar

T = TypeVar("T")

_lock = threading.RLock()
_mtime: float = -1.0
_jobs: List[T] = []
_loaded: bool = False


def job_file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path) if os.path.isfile(path) else 0.0
    except OSError:
        return 0.0


def load_jobs_cached(
    path: str,
    read_disk: Callable[[], List[T]],
    *,
    force: bool = False,
) -> List[T]:
    global _mtime, _jobs, _loaded
    with _lock:
        mt = job_file_mtime(path)
        if not force and _loaded and mt == _mtime:
            return _jobs
        _jobs = read_disk()
        _mtime = mt
        _loaded = True
        return _jobs


def set_jobs_cache(path: str, jobs: List[T]) -> None:
    global _mtime, _jobs, _loaded
    with _lock:
        _jobs = jobs
        _mtime = job_file_mtime(path)
        _loaded = True


def invalidate_jobs_cache() -> None:
    global _mtime, _loaded
    with _lock:
        _mtime = -1.0
        _loaded = False


def runner_loop_sleep_seconds(
    jobs: List[T],
    now: float,
    *,
    step_count: Callable[[T], int],
    min_sleep: float = 0.8,
    max_sleep: float = 30.0,
    wake_ahead: float = 1.0,
) -> float:
    """根据最近 next_send_ts 自适应休眠，等待期间降低轮询频率。"""
    earliest: float | None = None
    needs_soon = False
    for j in jobs:
        if not getattr(j, "enabled", False):
            continue
        if getattr(j, "state", "") == "paused":
            continue
        if step_count(j) <= 0:
            continue
        nts = float(getattr(j, "next_send_ts", 0.0) or 0.0)
        if nts <= 0:
            needs_soon = True
            break
        if nts > now:
            earliest = nts if earliest is None else min(earliest, nts)
    if needs_soon:
        return min_sleep
    if earliest is None:
        return max_sleep
    wait = earliest - now - wake_ahead
    if wait <= 0:
        return min_sleep
    return max(min_sleep, min(wait, max_sleep))
