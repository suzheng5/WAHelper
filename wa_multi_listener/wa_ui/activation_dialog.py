"""WS 助手激活对话框。"""
from __future__ import annotations

import customtkinter as ctk

from i18n import t
from license_service import activate, get_machine_id
from wa_ui.theme import COLORS


class ActivationDialog(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.activated = False
        self.title(t("activation.title"))
        self.geometry("480x400")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 480) // 2
        y = (self.winfo_screenheight() - 400) // 2
        self.geometry(f"+{x}+{y}")
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(
            self,
            text=t("activation.brand"),
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["text"],
        ).pack(pady=(28, 4))
        ctk.CTkLabel(
            self,
            text=t("activation.hint"),
            font=ctk.CTkFont(size=13),
            text_color=COLORS["muted"],
            wraplength=420,
        ).pack(pady=(0, 18))

        machine_id = get_machine_id()
        id_frame = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=8)
        id_frame.pack(fill="x", padx=40, pady=(0, 16))
        ctk.CTkLabel(
            id_frame,
            text=t("activation.machine_id"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=15, pady=(10, 5))
        id_entry = ctk.CTkEntry(
            id_frame,
            height=36,
            font=ctk.CTkFont(size=14, family="Consolas"),
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["accent"],
        )
        id_entry.pack(fill="x", padx=15, pady=(0, 8))
        id_entry.insert(0, machine_id)
        id_entry.configure(state="readonly")

        def copy_id() -> None:
            self.clipboard_clear()
            self.clipboard_append(machine_id)
            copy_btn.configure(text=t("common.copied"))
            self.after(1500, lambda: copy_btn.configure(text=t("common.copy")))

        copy_btn = ctk.CTkButton(
            id_frame,
            text=t("common.copy"),
            width=80,
            height=30,
            fg_color=COLORS["border"],
            hover_color=COLORS["muted"],
            command=copy_id,
        )
        copy_btn.pack(anchor="e", padx=15, pady=(0, 10))

        ctk.CTkLabel(self, text=t("activation.code"), font=ctk.CTkFont(size=14), text_color=COLORS["muted"]).pack(
            anchor="w", padx=40, pady=(0, 5)
        )
        self.code_entry = ctk.CTkEntry(
            self,
            height=42,
            font=ctk.CTkFont(size=16),
            fg_color=COLORS["card"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            placeholder_text_color=COLORS["muted"],
            placeholder_text=t("activation.code_ph"),
        )
        self.code_entry.pack(fill="x", padx=40, pady=(0, 8))
        self.code_entry.bind("<Return>", lambda _e: self._do_activate())

        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12), text_color=COLORS["danger"])
        self.status_label.pack(pady=(0, 8))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=40, pady=(8, 28))
        self.activate_btn = ctk.CTkButton(
            btn_row,
            text=t("activation.activate"),
            width=180,
            height=42,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=COLORS["success"],
            hover_color=COLORS["accent"],
            command=self._do_activate,
        )
        self.activate_btn.pack(side="left", expand=True, padx=(0, 10))
        ctk.CTkButton(
            btn_row,
            text=t("activation.exit"),
            width=180,
            height=42,
            font=ctk.CTkFont(size=16),
            fg_color=COLORS["border"],
            hover_color=COLORS["muted"],
            command=self.quit,
        ).pack(side="right", expand=True, padx=(10, 0))

    def _do_activate(self) -> None:
        code = self.code_entry.get().strip()
        if not code:
            self.status_label.configure(text=t("activation.enter_code"), text_color=COLORS["danger"])
            return
        self.activate_btn.configure(state="disabled", text=t("activation.verifying"))
        self.update()
        success, message = activate(code)
        if success:
            self.status_label.configure(text=message, text_color=COLORS["success"])
            self.activated = True
            self.after(1200, self.destroy)
        else:
            self.status_label.configure(text=message, text_color=COLORS["danger"])
            self.activate_btn.configure(state="normal", text=t("activation.activate"))


def ensure_activated() -> bool:
    from license_service import check_license

    is_valid, _msg, _expires = check_license()
    if is_valid:
        return True
    dialog = ActivationDialog()
    dialog.mainloop()
    return bool(dialog.activated)
