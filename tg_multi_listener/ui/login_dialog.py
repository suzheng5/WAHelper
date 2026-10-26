"""主线程弹窗：供后台登录线程阻塞获取手机号 / 验证码 / 密码。"""
from __future__ import annotations

import io
import threading
from typing import Callable, Optional

import customtkinter as ctk

from i18n import t
from wa_ui.window_policy import close_window, present_once
from .theme import COLORS

RESEND_TOKEN = "__RESEND__"
QR_TOKEN = "__QR__"


class StringInputDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        title: str,
        prompt: str,
        placeholder: str = "",
        secret: bool = False,
        initial: str = "",
        on_submit: Callable[[Optional[str]], None],
    ) -> None:
        super().__init__(master)
        self._on_submit = on_submit
        self.title(title)
        self.configure(fg_color=COLORS["bg"])
        self.geometry("440x200")
        self.resizable(False, False)

        frm = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(frm, text=prompt, text_color=COLORS["text"], wraplength=400, justify="left").pack(
            anchor="w", padx=14, pady=(14, 8)
        )
        show_char = "*" if secret else ""
        self._entry = ctk.CTkEntry(frm, width=380, placeholder_text=placeholder or None, show=show_char)
        self._entry.pack(padx=14, pady=4)
        if initial:
            self._entry.insert(0, initial)
        self._entry.focus()

        btn = ctk.CTkFrame(frm, fg_color="transparent")
        btn.pack(fill="x", padx=14, pady=14)

        def ok() -> None:
            v = self._entry.get().strip()
            self._finish(v if v else None)

        def cancel() -> None:
            self._finish(None)

        ctk.CTkButton(btn, text=t("common.cancel"), width=100, fg_color=COLORS["border"], command=cancel).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn, text=t("common.confirm"), width=100, fg_color=COLORS["accent"], command=ok).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", cancel)
        self.bind("<Return>", lambda _e: ok())
        present_once(self, parent=master, focus=True)
        try:
            self.grab_set()
        except Exception:
            pass

    def _finish(self, value: Optional[str]) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_submit(value)
        close_window(self)


class MethodChoiceDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        title: str,
        prompt: str,
        on_submit: Callable[[Optional[str]], None],
    ) -> None:
        super().__init__(master)
        self._on_submit = on_submit
        self.title(title)
        self.configure(fg_color=COLORS["bg"])
        self.geometry("460x220")
        self.resizable(False, False)

        frm = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        frm.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(frm, text=prompt, text_color=COLORS["text"], wraplength=410, justify="left").pack(
            anchor="w", padx=14, pady=(14, 16)
        )
        btn = ctk.CTkFrame(frm, fg_color="transparent")
        btn.pack(fill="x", padx=14, pady=10)
        ctk.CTkButton(btn, text=t("login.tg.method_sms"), width=170, fg_color=COLORS["accent"], command=lambda: self._finish("sms")).pack(side="left")
        ctk.CTkButton(btn, text=t("login.tg.method_qr"), width=170, command=lambda: self._finish("qr")).pack(side="left", padx=(8, 0))
        ctk.CTkButton(btn, text=t("common.cancel"), width=90, fg_color=COLORS["border"], command=lambda: self._finish(None)).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))
        present_once(self, parent=master, focus=True)
        try:
            self.grab_set()
        except Exception:
            pass

    def _finish(self, value: Optional[str]) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_submit(value)
        close_window(self)


class CodeInputDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        title: str,
        prompt: str,
        on_submit: Callable[[Optional[str]], None],
    ) -> None:
        super().__init__(master)
        self._on_submit = on_submit
        self.title(title)
        self.configure(fg_color=COLORS["bg"])
        self.geometry("480x240")
        self.resizable(False, False)

        frm = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        frm.pack(fill="both", expand=True, padx=14, pady=14)
        ctk.CTkLabel(frm, text=prompt, text_color=COLORS["text"], wraplength=430, justify="left").pack(
            anchor="w", padx=14, pady=(14, 8)
        )
        self._entry = ctk.CTkEntry(frm, width=400)
        self._entry.pack(padx=14, pady=4)
        self._entry.focus()
        btn = ctk.CTkFrame(frm, fg_color="transparent")
        btn.pack(fill="x", padx=14, pady=12)

        def ok() -> None:
            v = self._entry.get().strip()
            self._finish(v if v else None)

        ctk.CTkButton(btn, text=t("common.confirm"), width=90, fg_color=COLORS["accent"], command=ok).pack(side="right")
        ctk.CTkButton(btn, text=t("common.cancel"), width=80, fg_color=COLORS["border"], command=lambda: self._finish(None)).pack(side="right", padx=(0, 8))
        ctk.CTkButton(btn, text=t("login.tg.resend_sms"), width=110, command=lambda: self._finish(RESEND_TOKEN)).pack(side="left")
        ctk.CTkButton(btn, text=t("login.tg.use_qr"), width=90, command=lambda: self._finish(QR_TOKEN)).pack(side="left", padx=(8, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: self._finish(None))
        self.bind("<Return>", lambda _e: ok())
        present_once(self, parent=master, focus=True)
        try:
            self.grab_set()
        except Exception:
            pass

    def _finish(self, value: Optional[str]) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_submit(value)
        close_window(self)


class QrLoginDialog(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk, *, on_cancel: Callable[[], None]) -> None:
        super().__init__(master)
        self._on_cancel = on_cancel
        self._photo = None
        self.title(t("login.tg.qr_title"))
        self.configure(fg_color=COLORS["bg"])
        self.geometry("360x430")
        self.resizable(False, False)
        frm = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        frm.pack(fill="both", expand=True, padx=14, pady=14)
        self._hint = ctk.CTkLabel(frm, text=t("login.tg.qr_hint"), text_color=COLORS["text"], wraplength=300, justify="left")
        self._hint.pack(anchor="w", padx=14, pady=(14, 8))
        self._image = ctk.CTkLabel(frm, text="")
        self._image.pack(pady=8)
        ctk.CTkButton(frm, text=t("common.cancel"), width=100, fg_color=COLORS["border"], command=self._cancel).pack(pady=10)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        present_once(self, parent=master, focus=True)

    def set_image(self, png: bytes, hint: str) -> None:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(png))
            self._photo = ctk.CTkImage(light_image=img, dark_image=img, size=(240, 240))
            self._image.configure(image=self._photo, text="")
        except Exception:
            self._image.configure(text=t("login.tg.qr_unavailable"))
        self._hint.configure(text=hint)

    def _cancel(self) -> None:
        self._on_cancel()
        close_window(self)


class LoginUIBridge:
    """在非主线程中调用 ask_*，通过主线程弹窗获取输入。"""

    def __init__(self, root: ctk.CTk) -> None:
        self._root = root
        self._qr_cancel = threading.Event()
        self._qr_dialog: Optional[QrLoginDialog] = None

    def ask_string(
        self,
        title: str,
        prompt: str,
        placeholder: str = "",
        secret: bool = False,
        timeout_sec: float = 900.0,
        initial: str = "",
    ) -> Optional[str]:
        holder: dict[str, Optional[str]] = {"v": "__pending__"}
        done = threading.Event()

        def on_submit(val: Optional[str]) -> None:
            holder["v"] = val
            done.set()

        def open_dlg() -> None:
            StringInputDialog(
                self._root,
                title=title,
                prompt=prompt,
                placeholder=placeholder,
                secret=secret,
                initial=initial,
                on_submit=on_submit,
            )

        self._root.after(0, open_dlg)
        done.wait(timeout=timeout_sec)
        v = holder["v"]
        if v == "__pending__":
            return None
        return v

    def ask_method(self, title: str, prompt: str, timeout_sec: float = 900.0) -> Optional[str]:
        holder: dict[str, Optional[str]] = {"v": "__pending__"}
        done = threading.Event()

        def on_submit(val: Optional[str]) -> None:
            holder["v"] = val
            done.set()

        self._root.after(0, lambda: MethodChoiceDialog(self._root, title=title, prompt=prompt, on_submit=on_submit))
        done.wait(timeout=timeout_sec)
        v = holder["v"]
        return None if v == "__pending__" else v

    def ask_code(self, title: str, prompt: str, timeout_sec: float = 900.0) -> Optional[str]:
        holder: dict[str, Optional[str]] = {"v": "__pending__"}
        done = threading.Event()

        def on_submit(val: Optional[str]) -> None:
            holder["v"] = val
            done.set()

        self._root.after(0, lambda: CodeInputDialog(self._root, title=title, prompt=prompt, on_submit=on_submit))
        done.wait(timeout=timeout_sec)
        v = holder["v"]
        return None if v == "__pending__" else v

    def show_qr(self, png: bytes, hint: str) -> None:
        self._qr_cancel.clear()

        def open_dlg() -> None:
            if self._qr_dialog is None:
                self._qr_dialog = QrLoginDialog(self._root, on_cancel=self._qr_cancel.set)
            self._qr_dialog.set_image(png, hint)

        self._root.after(0, open_dlg)

    def update_qr(self, png: bytes, hint: str) -> None:
        def apply() -> None:
            if self._qr_dialog is not None:
                self._qr_dialog.set_image(png, hint)

        self._root.after(0, apply)

    def is_qr_cancelled(self) -> bool:
        return self._qr_cancel.is_set()

    def close_qr(self) -> None:
        def close() -> None:
            dlg = self._qr_dialog
            self._qr_dialog = None
            if dlg is not None:
                close_window(dlg)

        self._root.after(0, close)
