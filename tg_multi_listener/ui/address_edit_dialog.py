"""通讯录单条编辑弹窗（列表页只读，详情在此修改）。"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, List, Optional

import customtkinter as ctk

from i18n import t
from i18n.ui_helpers import msg_askyesno, msg_warning
from wa_ui.window_policy import close_window, present_once
from ..compat_config import AddressEntry, parse_chat_ref_input, parse_watch_user_input
from .theme import COLORS


class AddressEditDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: ctk.CTk | ctk.CTkFrame,
        *,
        entry: AddressEntry,
        owner_values: List[str],
        on_save: Callable[[AddressEntry], None],
        on_delete: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._entry = entry
        self._entry_id = entry.id
        self._on_save = on_save
        self._on_delete = on_delete
        title_name = (entry.remark or entry.id).strip() or entry.id
        self.title(t("addr_edit.title", name=title_name))
        self.configure(fg_color=COLORS["bg"])
        self.geometry("480x520")
        self.resizable(False, False)

        outer = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        outer.pack(fill="both", expand=True, padx=14, pady=14)
        frm = outer

        pad = {"anchor": "w", "padx": 14}
        ctk.CTkLabel(frm, text=t("addr_edit.remark_label"), text_color=COLORS["muted"]).pack(**pad, pady=(14, 4))
        self._remark = ctk.CTkEntry(frm, placeholder_text=t("addr_edit.remark_ph"))
        self._remark.insert(0, entry.remark or "")
        self._remark.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(frm, text=t("grp.group"), text_color=COLORS["muted"]).pack(**pad, pady=(4, 4))
        self._chat = ctk.CTkEntry(frm, placeholder_text=t("addr_edit.chat_ph"))
        self._chat.insert(0, entry.chat_ref or "")
        self._chat.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(frm, text=t("addr_edit.user_label"), text_color=COLORS["muted"]).pack(**pad, pady=(4, 4))
        self._user = ctk.CTkEntry(frm, placeholder_text=t("addr_edit.user_ph"))
        self._user.insert(0, entry.watch_user or "")
        self._user.pack(fill="x", padx=14, pady=(0, 8))

        self._listen_var = ctk.BooleanVar(value=bool(entry.listen_enabled))
        ctk.CTkCheckBox(
            frm,
            text=t("addr_edit.listen"),
            variable=self._listen_var,
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=14, pady=(4, 8))

        own_row = ctk.CTkFrame(frm, fg_color="transparent")
        own_row.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkLabel(own_row, text=t("grp.owner_account"), text_color=COLORS["muted"]).pack(side="left", padx=(0, 8))
        owner_vals = ([t("grp.please_select")] + owner_values) if owner_values else [t("grp.please_select")]
        self._owner = ctk.CTkComboBox(own_row, width=180, values=owner_vals)
        cur = (entry.owner_account_id or "").strip()
        if cur and cur in owner_values:
            self._owner.set(cur)
        elif owner_values:
            self._owner.set(owner_values[0])
        else:
            self._owner.set(t("grp.please_select"))
        self._owner.pack(side="left")

        btn_row = ctk.CTkFrame(frm, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(12, 14))
        ctk.CTkButton(
            btn_row,
            text=t("addr_edit.delete_btn"),
            width=100,
            fg_color=COLORS["danger"],
            hover_color="#b63a3a",
            command=self._confirm_delete,
        ).pack(side="left")
        ctk.CTkButton(btn_row, text=t("common.cancel"), width=88, fg_color=COLORS["border"], command=self._close).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btn_row, text=t("common.save"), width=88, fg_color=COLORS["accent"], command=self._save).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        present_once(self, parent=master, focus=True)
        try:
            self.grab_set()
            self._remark.focus()
        except Exception:
            pass

    def _validate(self) -> Optional[AddressEntry]:
        remark = self._remark.get().strip()
        chat = self._chat.get().strip()
        user = self._user.get().strip()
        listen_on = bool(self._listen_var.get())
        if not remark or not chat:
            msg_warning(self, "msgbox.cannot_save.title", "addr_edit.save_required")
            return None
        try:
            parse_chat_ref_input(chat)
        except ValueError:
            msg_warning(self, "msgbox.cannot_save.title", "addr_edit.chat_invalid")
            return None
        if listen_on:
            if not user:
                msg_warning(self, "msgbox.cannot_save.title", "addr_edit.watch_required")
                return None
            try:
                parse_watch_user_input(user)
            except ValueError:
                msg_warning(self, "msgbox.cannot_save.title", "addr_edit.watch_invalid")
                return None
        elif user:
            try:
                parse_watch_user_input(user)
            except ValueError:
                msg_warning(self, "msgbox.cannot_save.title", "addr_edit.user_invalid")
                return None
        owner = self._owner.get().strip()
        if owner in ("", "—", t("grp.please_select")):
            msg_warning(self, "msgbox.cannot_save.title", "addr_edit.owner_required")
            return None
        return replace(
            self._entry,
            remark=remark,
            chat_ref=chat,
            watch_user=user,
            listen_enabled=listen_on,
            owner_account_id=owner,
        )

    def _save(self) -> None:
        updated = self._validate()
        if updated is None:
            return
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_save(updated)
        close_window(self)

    def _confirm_delete(self) -> None:
        if not msg_askyesno(self, "addr_edit.delete_title", "addr_edit.delete_confirm"):
            return
        try:
            self.grab_release()
        except Exception:
            pass
        self._on_delete()
        close_window(self)

    def _close(self) -> None:
        close_window(self)
