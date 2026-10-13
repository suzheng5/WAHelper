"""扫码登录弹窗：展示 QR 图片。"""
from __future__ import annotations

import io
from typing import Callable, Optional

import customtkinter as ctk
import segno
from PIL import Image

from i18n import t
from wa_ui.theme import COLORS
from wa_ui.window_policy import close_window, present_once


class QrLoginDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        account_id: str,
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_cancel = on_cancel
        self.title(t("qr.title", account=account_id))
        self.configure(fg_color=COLORS["bg"])
        self.geometry("420x480")
        self.resizable(False, False)

        frm = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            frm,
            text=t("qr.wa_session_hint"),
            text_color=COLORS["text"],
            justify="center",
        ).pack(padx=16, pady=(16, 8))

        self._img_label = ctk.CTkLabel(frm, text=t("qr.waiting"), width=280, height=280, fg_color=COLORS["bg"])
        self._img_label.pack(padx=16, pady=8)
        self._ctk_image: Optional[ctk.CTkImage] = None
        self._status_label = ctk.CTkLabel(frm, text="", text_color=COLORS["muted"])
        self._status_label.pack(padx=16, pady=(0, 8))

        btn_row = ctk.CTkFrame(frm, fg_color="transparent")
        btn_row.pack(pady=(8, 16))
        ctk.CTkButton(btn_row, text=t("common.cancel"), width=100, fg_color=COLORS["border"], command=self._cancel).pack(side="left")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        present_once(self, parent=master, focus=True)
        try:
            self.grab_set()
        except Exception:
            pass

    def set_status(self, text: str) -> None:
        try:
            self._status_label.configure(text=text)
        except Exception:
            pass

    def update_qr(self, data: bytes) -> None:
        try:
            payload = data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
            qr = segno.make_qr(payload)
            buf = io.BytesIO()
            qr.save(buf, kind="png", scale=8, border=2)
            buf.seek(0)
            img = Image.open(buf).convert("RGBA")
            self._ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=(260, 260))
            self._img_label.configure(image=self._ctk_image, text="")
        except Exception:
            self._img_label.configure(text=t("qr.gen_fail"))

    def _cancel(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_cancel()
        close_window(self)
