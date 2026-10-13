"""应用退出：停止监听/定时/登录后台并清理 WhatsApp 连接与子进程。"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Optional

from logger_util import info, warning

if TYPE_CHECKING:
    from listener import ListenerController
    from schedule2_runner import Schedule2Runner
    from wa_coordinator import WaCoordinator

_shutdown_lock = threading.Lock()
_shutdown_done = False

# 关闭窗口用短超时：随后 force_process_exit / os._exit 会收掉残留线程
EXIT_JOIN_TIMEOUT = 2.0

_WA_THREAD_PREFIXES = (
    "wa-coordinator",
    "wa-login",
    "wa-post-login",
    "wa-reload",
)


def track_background_thread(t: threading.Thread) -> threading.Thread:
    if not t.name or t.name.startswith("Thread-"):
        t.name = f"wa-bg-{t.ident or id(t)}"
    return t


def _cancel_login(login_cancel: Optional[threading.Event]) -> None:
    if login_cancel is not None:
        login_cancel.set()


def _join_wa_threads(timeout: float) -> None:
    targets = [
        t
        for t in threading.enumerate()
        if t is not threading.current_thread()
        and t.is_alive()
        and (t.name or "").startswith(_WA_THREAD_PREFIXES)
    ]
    if not targets:
        return
    deadline = time.monotonic() + max(0.05, timeout)
    per = max(0.05, (deadline - time.monotonic()) / len(targets))
    for t in targets:
        remain = deadline - time.monotonic()
        if remain <= 0:
            break
        t.join(timeout=min(per, remain))
        if t.is_alive():
            warning(f"后台线程未在时限内结束：{t.name}")


def _kill_child_processes_windows() -> None:
    """尽快结束本进程子进程；优先 taskkill，避免拉起 PowerShell。"""
    if sys.platform != "win32":
        return
    pid = os.getpid()
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except Exception:
        try:
            ps = (
                f"Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.ParentProcessId -eq {pid} }} | "
                f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force "
                f"-ErrorAction SilentlyContinue }}"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                timeout=3,
                check=False,
            )
        except Exception as exc:
            warning(f"清理子进程时：{exc}")


def _stop_neonize_clients() -> None:
    from wa_client import stop_all_clients_sync

    try:
        stop_all_clients_sync(linger_sec=0.1)
    except Exception as exc:
        warning(f"停止 WhatsApp 连接时：{exc}")


def shutdown_application(
    *,
    coord: Optional["WaCoordinator"] = None,
    listener: Optional["ListenerController"] = None,
    schedule2: Optional["Schedule2Runner"] = None,
    login_cancel: Optional[threading.Event] = None,
    join_timeout: float = EXIT_JOIN_TIMEOUT,
    kill_children: bool = False,
) -> None:
    """幂等：尽快停后台。默认短超时，适合关窗（进程随后会强制退出）。"""
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    t0 = time.monotonic()
    info("正在关闭 WhatsApp 助手…")
    _cancel_login(login_cancel)

    if listener is not None:
        try:
            listener.stop()
        except Exception as exc:
            warning(f"停止监听时：{exc}")

    if schedule2 is not None:
        try:
            schedule2.stop()
        except Exception as exc:
            warning(f"停止定时任务时：{exc}")
        try:
            from schedule2_runner import (
                SHUTDOWN_PAUSE_REASON_S2,
                pause_all_schedule2_jobs_on_startup,
            )

            pause_all_schedule2_jobs_on_startup(SHUTDOWN_PAUSE_REASON_S2)
        except Exception as exc:
            warning(f"保存定时任务暂停状态时：{exc}")

    if coord is not None:
        try:
            # 关窗不走二次 asyncio.run(stop)，避免再卡数秒
            coord.stop(join_timeout=join_timeout, fallback_stop=False)
        except TypeError:
            try:
                coord.stop(join_timeout=join_timeout)
            except Exception as exc:
                warning(f"停止会话协调器时：{exc}")
        except Exception as exc:
            warning(f"停止会话协调器时：{exc}")
    else:
        _stop_neonize_clients()

    _join_wa_threads(min(1.0, max(0.1, join_timeout)))
    if kill_children:
        _kill_child_processes_windows()
    info(f"后台服务已停止（耗时 {time.monotonic() - t0:.1f}s）")


def force_process_exit() -> None:
    """确保进程立即退出（避免 neonize/Go 非守护线程挂住）。"""
    os._exit(0)
