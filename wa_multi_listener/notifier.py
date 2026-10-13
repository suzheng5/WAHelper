"""消息与阶段提醒：出现时置前一次，随后保持可并行操作。"""
from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from i18n import t
from wa_ui.theme import COLORS
from wa_ui.window_policy import close_window, present_once

_ALERT_GEOMETRY = "460x260"
_ALERT_MINSIZE = (400, 220)
_STAGE_GEOMETRY = "460x240"
_STAGE_MINSIZE = (400, 200)
_LABEL_WRAP = 400


def _setup_popup_window(win: ctk.CTkToplevel, master: ctk.CTk) -> None:
    """提醒出现时置前一次；不 grab、不长期置顶。"""
    present_once(win, parent=master, bell=True, focus=False)


class AlertPopup(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk,
        *,
        chat_title: str,
        sender_name: str,
        message_text: str,
        chat_jid: Optional[str] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self._on_close = on_close
        self.title(t("alert.title_wa"))
        self.configure(fg_color=COLORS["bg"])
        self.attributes("-alpha", 0.0)
        self.resizable(True, True)
        self.minsize(*_ALERT_MINSIZE)
        self.geometry(_ALERT_GEOMETRY)
        _setup_popup_window(self, master)

        wrap = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        wrap.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wrap,
            text=chat_title or t("alert.session"),
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=_LABEL_WRAP,
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))

        ctk.CTkLabel(
            wrap,
            text=sender_name or t("alert.user"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=_LABEL_WRAP,
        ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        box = ctk.CTkTextbox(
            wrap,
            height=88,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=COLORS["bg"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        box.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
        box.insert("1.0", message_text or "")
        box.configure(state="disabled")

        ctk.CTkButton(
            wrap,
            text=t("alert.close"),
            width=100,
            fg_color=COLORS["border"],
            hover_color=COLORS["card"],
            command=self._close,
        ).grid(row=3, column=0, sticky="w", padx=14, pady=(0, 12))

        self._fade_in_step(0)

    def _fade_in_step(self, step: int) -> None:
        alpha = min(1.0, step * 0.12)
        self.attributes("-alpha", alpha)
        if alpha < 1.0:
            self.after(20, lambda: self._fade_in_step(step + 1))

    def _close(self) -> None:
        try:
            if self._on_close:
                self._on_close()
        finally:
            close_window(self)


class StageReminderPopup(ctk.CTkToplevel):
    """定时任务 !提醒! 阶段：置顶弹窗。"""

    def __init__(self, master: ctk.CTk, *, title: str, subtitle: str, body: str) -> None:
        super().__init__(master)
        self.title(title or t("stage.default_title"))
        self.configure(fg_color=COLORS["bg"])
        self.attributes("-alpha", 0.0)
        self.resizable(True, True)
        self.minsize(*_STAGE_MINSIZE)
        self.geometry(_STAGE_GEOMETRY)
        _setup_popup_window(self, master)

        wrap = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        wrap.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            wrap,
            text=title or t("stage.default_title"),
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=COLORS["accent"],
            anchor="w",
            justify="left",
            wraplength=_LABEL_WRAP,
        ).grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 2))

        if subtitle:
            ctk.CTkLabel(
                wrap,
                text=subtitle,
                font=ctk.CTkFont(size=12),
                text_color=COLORS["muted"],
                anchor="w",
                justify="left",
                wraplength=_LABEL_WRAP,
            ).grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 6))

        box = ctk.CTkTextbox(
            wrap,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=COLORS["bg"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
            height=88,
        )
        box.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
        box.insert("1.0", body or "")
        box.configure(state="disabled")

        ctk.CTkButton(
            wrap,
            text=t("stage.got_it"),
            width=100,
            fg_color=COLORS["accent"],
            hover_color="#1da851",
            command=self._close,
        ).grid(row=3, column=0, sticky="w", padx=14, pady=(0, 12))
        self._fade_in_step(0)

    def _fade_in_step(self, step: int) -> None:
        alpha = min(1.0, step * 0.12)
        self.attributes("-alpha", alpha)
        if alpha < 1.0:
            self.after(20, lambda: self._fade_in_step(step + 1))

    def _close(self) -> None:
        close_window(self)


def show_stage_reminder(master: ctk.CTk, *, title: str, subtitle: str, body: str) -> None:
    try:
        StageReminderPopup(master, title=title, subtitle=subtitle, body=body)
    except Exception:
        pass
