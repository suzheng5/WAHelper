"""WhatsApp 手机号 + 配对码登录弹窗。"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from i18n import t
from wa_ui.theme import COLORS
from wa_ui.window_policy import close_window, present_once


class PhoneLoginDialog(ctk.CTkToplevel):
    """
    流程：
    1) 输入含国家码的手机号 → 点开始登录
    2) 显示 8 位配对码（XXXX-XXXX）→ 用户在手机 WhatsApp 输入
    """

    def __init__(
        self,
        master: ctk.CTk,
        *,
        account_id: str,
        on_start: Callable[[str], None],
        on_cancel: Callable[[], None],
        initial_phone: str = "",
    ) -> None:
        super().__init__(master)
        self._on_start = on_start
        self._on_cancel = on_cancel
        self._started = False

        self.title(t("phone_login.title", account=account_id))
        self.configure(fg_color=COLORS["bg"])
        self.geometry("460x520")
        self.resizable(False, False)

        frm = ctk.CTkFrame(
            self,
            fg_color=COLORS["card"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
        )
        frm.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            frm,
            text=t("phone_login.hint"),
            text_color=COLORS["text"],
            justify="left",
            wraplength=400,
        ).pack(padx=16, pady=(16, 8), anchor="w")

        self._phone = ctk.CTkEntry(
            frm,
            placeholder_text=t("phone_login.phone_ph"),
            height=36,
            width=360,
        )
        self._phone.pack(padx=16, pady=(4, 8))
        if (initial_phone or "").strip():
            self._phone.insert(0, initial_phone.strip())

        self._btn_start = ctk.CTkButton(
            frm,
            text=t("phone_login.start"),
            width=160,
            fg_color=COLORS["accent"],
            command=self._start,
        )
        self._btn_start.pack(pady=(4, 12))

        ctk.CTkLabel(
            frm,
            text=t("phone_login.code_label"),
            text_color=COLORS["muted"],
        ).pack(padx=16, pady=(8, 4))

        self._code_label = ctk.CTkLabel(
            frm,
            text=t("phone_login.code_waiting"),
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=COLORS["accent"],
            height=48,
        )
        self._code_label.pack(padx=16, pady=(0, 8))

        ctk.CTkLabel(
            frm,
            text=t("phone_login.code_howto"),
            text_color=COLORS["muted"],
            justify="left",
            wraplength=400,
        ).pack(padx=16, pady=(0, 8), anchor="w")

        self._status_label = ctk.CTkLabel(frm, text="", text_color=COLORS["muted"], wraplength=400)
        self._status_label.pack(padx=16, pady=(4, 8))

        btn_row = ctk.CTkFrame(frm, fg_color="transparent")
        btn_row.pack(pady=(8, 16))
        ctk.CTkButton(
            btn_row,
            text=t("common.cancel"),
            width=100,
            fg_color=COLORS["border"],
            command=self._cancel,
        ).pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        present_once(self, parent=master, focus=True)
        try:
            self.grab_set()
        except Exception:
            pass
        self.after(100, lambda: self._phone.focus_set())

    def set_status(self, text: str) -> None:
        try:
            self._status_label.configure(text=text or "")
        except Exception:
            pass

    def set_pairing_code(self, code: str) -> None:
        try:
            self._code_label.configure(text=(code or "").strip() or t("phone_login.code_waiting"))
            self._phone.configure(state="disabled")
            self._btn_start.configure(state="disabled")
        except Exception:
            pass

    def _start(self) -> None:
        if self._started:
            return
        phone = (self._phone.get() or "").strip()
        if not phone:
            self.set_status(t("phone_login.phone_required"))
            return
        self._started = True
        try:
            self._btn_start.configure(state="disabled")
            self._phone.configure(state="disabled")
        except Exception:
            pass
        self.set_status(t("phone_login.starting"))
        try:
            self._on_start(phone)
        except Exception as exc:
            self._started = False
            try:
                self._btn_start.configure(state="normal")
                self._phone.configure(state="normal")
            except Exception:
                pass
            self.set_status(str(exc))

    def _cancel(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_cancel()
        close_window(self)
