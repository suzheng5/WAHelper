"""将旧 TG 登录线程入口桥接到 Qt 主线程弹窗。"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QInputDialog, QLineEdit, QWidget


class QtAfterRoot(QObject):
    """提供 telethon_auth 所需的 ``after`` 最小接口。"""

    invoke = Signal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.invoke.connect(lambda fn: fn())

    def after(self, _delay_ms: int, callback: Callable[[], None]) -> None:
        self.invoke.emit(callback)


class QtLoginUIBridge(QObject):
    """后台线程阻塞等待 Qt 主线程收集手机号、验证码或密码。"""

    request = Signal(object)

    def __init__(self, parent: Optional[QWidget]) -> None:
        super().__init__(parent)
        self._parent = parent
        self.request.connect(self._show)

    def ask_string(
        self,
        title: str,
        prompt: str,
        placeholder: str = "",
        secret: bool = False,
        timeout_sec: float = 900.0,
    ) -> Optional[str]:
        done = threading.Event()
        result: dict[str, Optional[str]] = {"value": None}
        self.request.emit((title, prompt, placeholder, secret, done, result))
        if not done.wait(timeout=max(0.1, timeout_sec)):
            return None
        value = result["value"]
        return value.strip() if value and value.strip() else None

    def _show(self, payload: tuple[Any, ...]) -> None:
        title, prompt, placeholder, secret, done, result = payload
        mode = QLineEdit.Password if secret else QLineEdit.Normal
        text, ok = QInputDialog.getText(
            self._parent, title, prompt, mode, placeholder
        )
        result["value"] = text if ok else None
        done.set()


def run_login_with_qt(
    auth_module: Any,
    parent: QWidget,
    account: Any,
    config: Any,
    on_done: Callable[[bool, str], None],
    *,
    pre_login: Optional[Callable[[], None]] = None,
) -> None:
    """复用 telethon_auth 登录内核，仅替换其 UI bridge。"""
    root = QtAfterRoot(parent)
    bridge = QtLoginUIBridge(parent)
    original = auth_module.LoginUIBridge
    auth_module.LoginUIBridge = lambda _root: bridge

    def finish(ok: bool, message: str) -> None:
        auth_module.LoginUIBridge = original
        on_done(ok, message)
        root.deleteLater()
        bridge.deleteLater()

    try:
        auth_module.run_login_in_thread(
            root, account, config, finish, pre_login=pre_login
        )
    except Exception:
        auth_module.LoginUIBridge = original
        raise
