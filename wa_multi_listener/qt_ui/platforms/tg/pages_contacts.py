"""通讯录与监听规则页面。"""
from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...common.column_widths import bind_resizable_columns
from ...common.theme import style_button
from .common import DataTable, Translator, action_row, button, call_guarded, page_title


class TgContactDialog(QDialog):
    """添加/修改：无群 ID 框，邀请链接由软件解析并记住。"""

    def __init__(
        self,
        tr: Translator,
        owners: list[str],
        contact: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("grp.title"))
        self.setMinimumSize(560, 420)
        self.resize(600, 460)
        self._existing_chat_ref = (
            str(getattr(contact, "chat_ref", "") or "") if contact else ""
        )
        self._original_invite = (
            str(getattr(contact, "invite_link", "") or "") if contact else ""
        )
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)
        self.remark = QLineEdit(getattr(contact, "remark", "") if contact else "")
        self.remark.setMinimumHeight(32)
        self.watch_user = QLineEdit(
            getattr(contact, "watch_user", "") if contact else ""
        )
        self.watch_user.setMinimumHeight(32)
        self.invite = QLineEdit(
            getattr(contact, "invite_link", "") if contact else ""
        )
        self.invite.setPlaceholderText(tr("grp.tg_chat_ph"))
        self.invite.setMinimumHeight(36)
        self.listen = QCheckBox(tr("grp.listen"))
        self.listen.setChecked(
            bool(getattr(contact, "listen_enabled", True)) if contact else True
        )
        self.owner = QComboBox()
        self.owner.setMinimumHeight(32)
        self.owner.addItem("")
        self.owner.addItems(owners)
        owner_id = (
            str(getattr(contact, "owner_account_id", "") or "") if contact else ""
        )
        if owner_id:
            self.owner.setCurrentText(owner_id)
        form.addRow(tr("grp.remark"), self.remark)
        form.addRow(tr("grp.user"), self.watch_user)
        form.addRow(tr("qt.tg.invite_link"), self.invite)
        form.addRow(tr("grp.owner"), self.owner)
        form.addRow("", self.listen)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict[str, Any]:
        invite = self.invite.text().strip()
        chat_ref = (
            ""
            if invite != self._original_invite.strip()
            else self._existing_chat_ref
        )
        return {
            "remark": self.remark.text().strip(),
            "chat_ref": chat_ref,
            "watch_user": self.watch_user.text().strip(),
            "owner_account_id": self.owner.currentText().strip(),
            "invite_link": invite,
            "listen_enabled": self.listen.isChecked(),
        }


class ContactsPage(QWidget):
    def __init__(self, presenter: Any, tr: Translator) -> None:
        super().__init__()
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(page_title(tr, "nav.grp"))
        hint = QLabel(tr("grp.hint_toolbar_tg"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._btn_add = QPushButton(tr("common.add"))
        style_button(self._btn_add, "primary")
        self._btn_add.setMaximumWidth(90)
        self._btn_add.clicked.connect(self._add)
        self._btn_edit = QPushButton(tr("grp.edit_btn"))
        style_button(self._btn_edit, "default")
        self._btn_edit.clicked.connect(self._edit)
        self._btn_delete = QPushButton(tr("common.delete"))
        style_button(self._btn_delete, "danger")
        self._btn_delete.clicked.connect(self._remove)
        self._btn_up = QPushButton(tr("qt.tg.move_up"))
        style_button(self._btn_up, "ghost")
        self._btn_up.clicked.connect(lambda: self._move(-1))
        self._btn_down = QPushButton(tr("qt.tg.move_down"))
        style_button(self._btn_down, "ghost")
        self._btn_down.clicked.connect(lambda: self._move(1))
        toolbar.addWidget(self._btn_add)
        toolbar.addWidget(self._btn_edit)
        toolbar.addWidget(self._btn_delete)
        toolbar.addWidget(self._btn_up)
        toolbar.addWidget(self._btn_down)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.table = DataTable(
            [
                "grp.remark",
                "grp.group",
                "grp.user",
                "grp.owner",
                "grp.listen",
                "sched.last_task_col",
            ],
            tr,
        )
        bind_resizable_columns(
            self.table,
            "tg.contacts",
            [244, 165, 118, 155, 104, 212],
        )
        layout.addWidget(self.table)
        presenter.changed.connect(self.refresh)
        presenter.audit_completed.connect(lambda _=None: self.refresh())
        warning_signal = getattr(presenter, "address_group_warning", None)
        if warning_signal is not None and hasattr(warning_signal, "connect"):
            warning_signal.connect(self._show_group_type_warning)
        self.refresh()

    def _show_group_type_warning(self, label: str, kind: str, peer_id: int) -> None:
        from ...common.dialogs import show_message

        type_name = self.tr(
            "grp.type_basic_group" if kind == "basic_group" else "grp.type_channel"
        )
        show_message(
            self,
            self.tr("grp.upgrade_supergroup_title"),
            self.tr(
                "grp.upgrade_supergroup_body",
                name=label,
                type=type_name,
                peer_id=peer_id,
            ),
        )

    def refresh(self) -> None:
        from ...services.task_confirmations import audit_status_label

        current = self.table.selected_id()
        rows = self.presenter.config.address_book
        filled = []
        for row in rows:
            last = (getattr(row, "last_schedule_source_name", "") or "").strip()
            last_text = (
                self.tr("sched.last_task", name=last).replace(" · ", "").strip()
                if last
                else self.tr("sched.last_task_empty").replace(" · ", "").strip()
            )
            audit = audit_status_label(
                self.tr,
                getattr(self.presenter, "audit_flags", {}).get(row.id, ""),
                getattr(self.presenter, "audit_details", {}).get(row.id, ""),
            )
            remark = row.remark + (audit or "")
            group_text = (row.invite_link or "").strip() or row.chat_ref
            listen_text = (
                self.tr("grp.listen_tag")
                if bool(getattr(row, "listen_enabled", True))
                else self.tr("grp.schedule_only")
            )
            filled.append([
                remark,
                group_text,
                row.watch_user,
                row.owner_account_id,
                listen_text,
                last_text,
            ])
        self.table.fill(filled, [row.id for row in rows])
        if current:
            for index, row in enumerate(rows):
                if row.id == current:
                    self.table.selectRow(index)
                    break

    def _owners(self) -> list[str]:
        return [row.id for row in self.presenter.config.accounts]

    def _selected_row(self) -> Any | None:
        entry_id = self.table.selected_id()
        if not entry_id:
            return None
        return next(
            (x for x in self.presenter.config.address_book if x.id == entry_id),
            None,
        )

    def _add(self) -> None:
        dialog = TgContactDialog(self.tr, self._owners(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        call_guarded(
            self,
            self.tr,
            lambda: self.presenter.add_address(**dialog.values()),
        )

    def _edit(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        dialog = TgContactDialog(self.tr, self._owners(), row, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        call_guarded(
            self,
            self.tr,
            lambda: self.presenter.update_address(row.id, **dialog.values()),
        )

    def _remove(self) -> None:
        entry_id = self.table.selected_id()
        if entry_id:
            self.presenter.remove_address(entry_id)

    def _move(self, delta: int) -> None:
        entry_id = self.table.selected_id()
        if entry_id:
            self.presenter.move_address(entry_id, delta)


class RulesPage(QWidget):
    def __init__(self, presenter: Any, tr: Translator) -> None:
        from ...common.dialogs import show_message
        from ...common.lang_controls import add_language_controls

        super().__init__()
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.addWidget(page_title(tr, "nav.rules"))
        self.enabled = QCheckBox(tr("rules.enable_listen"))
        self.enabled.setChecked(presenter.config.listening_enabled)
        self.popup = QCheckBox(tr("rules.stage_popup"))
        self.popup.setChecked(
            getattr(presenter.config, "stage_reminder_popup_enabled", True)
        )
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 3600)
        self.rate.setValue(presenter.config.rate_limit_seconds)
        form = QFormLayout()
        form.addRow("", self.enabled)
        form.addRow("", self.popup)
        form.addRow(tr("rules.rate_limit"), self.rate)
        add_language_controls(
            form,
            tr=tr,
            parent=self,
            on_saved=lambda text: show_message(
                self, tr, tr("rules.lang_label"), text
            ),
        )
        layout.addLayout(form)
        layout.addWidget(action_row(
            button("common.save", tr, self._save, kind="primary"),
            button("rules.sync_btn", tr, presenter.sync_last_schedule, kind="accent"),
            button("rules.audit_btn", tr, presenter.audit_rules),
        ))
        sync_hint = QLabel(tr("rules.sync_hint"))
        sync_hint.setWordWrap(True)
        sync_hint.setProperty("muted", True)
        layout.addWidget(sync_hint)
        audit_hint = QLabel(tr("rules.audit_hint"))
        audit_hint.setWordWrap(True)
        audit_hint.setProperty("muted", True)
        layout.addWidget(audit_hint)
        self.audit = QLabel(tr("qt.tg.audit_pending"))
        self.audit.setWordWrap(True)
        layout.addWidget(self.audit)
        layout.addStretch(1)
        presenter.audit_completed.connect(self._show_audit)
        presenter.changed.connect(self._reload)

    def _reload(self) -> None:
        cfg = self.presenter.config
        self.enabled.setChecked(cfg.listening_enabled)
        self.popup.setChecked(getattr(cfg, "stage_reminder_popup_enabled", True))
        self.rate.setValue(cfg.rate_limit_seconds)

    def _save(self) -> None:
        self.presenter.save_rules(
            self.enabled.isChecked(),
            self.popup.isChecked(),
            self.rate.value(),
        )

    def _show_audit(self, result: dict[str, Any]) -> None:
        from ...services.task_confirmations import audit_status_label, audit_status_value

        parts = []
        for entry_id, row in result.items():
            value = audit_status_value(row)
            if value in ("", "skip"):
                continue
            detail = str(getattr(row, "detail", "") or "")
            label = audit_status_label(self.tr, value, detail) or value
            parts.append(self.tr("qt.tg.audit_row", entry_id=entry_id, status=label))
        self.audit.setText("\n".join(parts) or self.tr("log.audit_no_targets"))
