"""将旧 TG 登录线程入口桥接到 Qt 主线程弹窗。"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QWidget,
)

from i18n import t

from ...common.dialogs import BaseDialog

RESEND_TOKEN = "__RESEND__"
QR_TOKEN = "__QR__"


class QtAfterRoot(QObject):
    """提供 telethon_auth 所需的 ``after`` 最小接口。"""

    invoke = Signal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.invoke.connect(lambda fn: fn())

    def after(self, _delay_ms: int, callback: Callable[[], None]) -> None:
        self.invoke.emit(callback)


class _MethodDialog(BaseDialog):
    def __init__(self, parent: Optional[QWidget], title: str, prompt: str) -> None:
        super().__init__(parent, title=title, width=520, height=260)
        self.choice: Optional[str] = None
        label = QLabel(prompt, self)
        label.setWordWrap(True)
        self.content_layout.addWidget(label)
        self.add_action(t("common.cancel"), self.reject)
        self.add_action(t("login.tg.method_qr"), self._pick_qr)
        self.add_action(t("login.tg.method_sms"), self._pick_sms, primary=True)

    def _pick_sms(self) -> None:
        self.choice = "sms"
        self.accept()

    def _pick_qr(self) -> None:
        self.choice = "qr"
        self.accept()


class _CodeDialog(BaseDialog):
    def __init__(self, parent: Optional[QWidget], title: str, prompt: str) -> None:
        super().__init__(parent, title=title, width=520, height=280)
        self.value: Optional[str] = None
        label = QLabel(prompt, self)
        label.setWordWrap(True)
        self.content_layout.addWidget(label)
        self.editor = QLineEdit(self)
        self.content_layout.addWidget(self.editor)
        self.add_action(t("login.tg.resend_sms"), self._resend)
        self.add_action(t("login.tg.use_qr"), self._qr)
        self.add_action(t("common.cancel"), self.reject)
        self.add_action(t("common.confirm"), self._ok, primary=True)
        self.editor.returnPressed.connect(self._ok)
        self.editor.setFocus()

    def _ok(self) -> None:
        text = self.editor.text().strip()
        if not text:
            return
        self.value = text
        self.accept()

    def _resend(self) -> None:
        self.value = RESEND_TOKEN
        self.accept()

    def _qr(self) -> None:
        self.value = QR_TOKEN
        self.accept()


class _QrDialog(BaseDialog):
    def __init__(self, parent: Optional[QWidget], on_cancel: Callable[[], None]) -> None:
        super().__init__(parent, title=t("login.tg.qr_title"), width=380, height=460)
        self._on_cancel = on_cancel
        self._hint = QLabel(t("login.tg.qr_hint"), self)
        self._hint.setWordWrap(True)
        self.content_layout.addWidget(self._hint)
        self._image = QLabel(self)
        self._image.setMinimumSize(260, 260)
        self.content_layout.addWidget(self._image)
        self.add_action(t("common.cancel"), self.reject)
        self.rejected.connect(on_cancel)
        self.setModal(True)

    def set_image(self, png: bytes, hint: str) -> None:
        self._hint.setText(hint)
        pix = QPixmap()
        pix.loadFromData(png)
        if not pix.isNull():
            self._image.setPixmap(
                pix.scaled(
                    260,
                    260,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class QtLoginUIBridge(QObject):
    """后台线程阻塞等待 Qt 主线程收集手机号、验证码或密码。"""

    request = Signal(object)
    method_request = Signal(object)
    code_request = Signal(object)
    qr_show = Signal(bytes, str)
    qr_close = Signal()

    def __init__(self, parent: Optional[QWidget]) -> None:
        super().__init__(parent)
        self._parent = parent
        self._qr_cancel = threading.Event()
        self._qr_dialog: Optional[_QrDialog] = None
        self.request.connect(self._show)
        self.method_request.connect(self._show_method)
        self.code_request.connect(self._show_code)
        self.qr_show.connect(self._on_qr_show)
        self.qr_close.connect(self._on_qr_close)

    def ask_string(
        self,
        title: str,
        prompt: str,
        placeholder: str = "",
        secret: bool = False,
        timeout_sec: float = 900.0,
        initial: str = "",
    ) -> Optional[str]:
        done = threading.Event()
        result: dict[str, Optional[str]] = {"value": None}
        self.request.emit((title, prompt, placeholder, secret, initial, done, result))
        if not done.wait(timeout=max(0.1, timeout_sec)):
            return None
        value = result["value"]
        return value.strip() if value and value.strip() else None

    def ask_method(self, title: str, prompt: str, timeout_sec: float = 900.0) -> Optional[str]:
        done = threading.Event()
        result: dict[str, Optional[str]] = {"value": None}
        self.method_request.emit((title, prompt, done, result))
        if not done.wait(timeout=max(0.1, timeout_sec)):
            return None
        return result["value"]

    def ask_code(self, title: str, prompt: str, timeout_sec: float = 900.0) -> Optional[str]:
        done = threading.Event()
        result: dict[str, Optional[str]] = {"value": None}
        self.code_request.emit((title, prompt, done, result))
        if not done.wait(timeout=max(0.1, timeout_sec)):
            return None
        return result["value"]

    def show_qr(self, png: bytes, hint: str) -> None:
        self._qr_cancel.clear()
        self.qr_show.emit(png, hint)

    def update_qr(self, png: bytes, hint: str) -> None:
        self.qr_show.emit(png, hint)

    def is_qr_cancelled(self) -> bool:
        return self._qr_cancel.is_set()

    def close_qr(self) -> None:
        self.qr_close.emit()

    def _show(self, payload: tuple[Any, ...]) -> None:
        from PySide6.QtWidgets import QInputDialog

        title, prompt, placeholder, secret, initial, done, result = payload
        mode = QLineEdit.Password if secret else QLineEdit.Normal
        text, ok = QInputDialog.getText(
            self._parent, title, prompt, mode, initial or placeholder
        )
        result["value"] = text if ok else None
        done.set()

    def _show_method(self, payload: tuple[Any, ...]) -> None:
        title, prompt, done, result = payload
        dialog = _MethodDialog(self._parent, title, prompt)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        result["value"] = dialog.choice if accepted else None
        done.set()

    def _show_code(self, payload: tuple[Any, ...]) -> None:
        title, prompt, done, result = payload
        dialog = _CodeDialog(self._parent, title, prompt)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        result["value"] = dialog.value if accepted else None
        done.set()

    def _on_qr_show(self, png: bytes, hint: str) -> None:
        if self._qr_dialog is None:
            self._qr_dialog = _QrDialog(self._parent, self._qr_cancel.set)
            self._qr_dialog.show()
        self._qr_dialog.set_image(png, hint)

    def _on_qr_close(self) -> None:
        dialog = self._qr_dialog
        self._qr_dialog = None
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()


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
