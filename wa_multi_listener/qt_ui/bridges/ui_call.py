"""把任意线程回调安全投递到 Qt 主线程。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from .signal_bridge import UiSignalBridge

_APP_BRIDGE: UiSignalBridge | None = None


def ensure_ui_bridge(owner: QObject) -> UiSignalBridge:
    bridge = getattr(owner, "_ui_signal_bridge", None)
    if isinstance(bridge, UiSignalBridge):
        return bridge
    bridge = UiSignalBridge(owner)
    owner._ui_signal_bridge = bridge
    return bridge


def _app_bridge() -> UiSignalBridge | None:
    global _APP_BRIDGE
    app = QApplication.instance()
    if app is None:
        return None
    if _APP_BRIDGE is None or _APP_BRIDGE.parent() is not app:
        _APP_BRIDGE = UiSignalBridge(app)
    return _APP_BRIDGE


def call_on_ui(owner: QObject | None, callback: Callable[[], Any]) -> None:
    """在主线程执行 callback；owner 缺失时退到 QApplication 桥。"""
    if owner is not None:
        ensure_ui_bridge(owner).post_callable(callback)
        return
    bridge = _app_bridge()
    if bridge is not None:
        bridge.post_callable(callback)
        return
    callback()
