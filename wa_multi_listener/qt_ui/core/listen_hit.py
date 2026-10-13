"""监听命中的同步暂停与异步告警编排。"""
from __future__ import annotations

from typing import Callable, TypeVar

AlertT = TypeVar("AlertT")
PauseResultT = TypeVar("PauseResultT")


def pause_then_queue_alert(
    alert: AlertT,
    pause_callback: Callable[[AlertT], PauseResultT],
    queue_alert: Callable[[AlertT], None],
) -> PauseResultT:
    """先完整执行暂停，再将告警交给 UI 队列。

    暂停异常会继续向调用方抛出，但告警仍会入队，避免遗漏监听事件。
    """
    try:
        return pause_callback(alert)
    finally:
        queue_alert(alert)
