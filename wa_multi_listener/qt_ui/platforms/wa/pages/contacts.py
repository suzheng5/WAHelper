"""通讯录 View：弹窗添加/修改；工具栏操作选中行。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....common.column_widths import bind_resizable_columns
from ....common.theme import style_button
from ..contracts import ConfigView, ContactItem, Translator
from ..presenter import WaPresenter


class ContactDialog(QDialog):
    """添加/修改：无群 ID 框，邀请链接由软件解析并记住。"""

    def __init__(
        self,
        tr: Translator,
        owners: list[str],
        contact: ContactItem | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("grp.title"))
        self.setMinimumSize(560, 420)
        self.resize(600, 460)
        self._existing_chat_ref = (contact.chat_ref if contact else "") or ""
        self._original_invite = (contact.invite_link if contact else "") or ""
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(14)
        self.remark = QLineEdit(contact.remark if contact else "")
        self.remark.setMinimumHeight(32)
        self.user = QLineEdit(contact.watch_user if contact else "")
        self.user.setMinimumHeight(32)
        self.invite = QLineEdit(contact.invite_link if contact else "")
        self.invite.setPlaceholderText(tr("grp.chat_ph"))
        self.invite.setMinimumHeight(36)
        self.listen = QCheckBox(tr("grp.listen"))
        self.listen.setChecked(contact.listen_enabled if contact else True)
        self.owner = QComboBox()
        self.owner.setMinimumHeight(32)
        self.owner.addItems(owners)
        if contact and contact.owner_account_id in owners:
            self.owner.setCurrentText(contact.owner_account_id)
        form.addRow(tr("grp.remark"), self.remark)
        form.addRow(tr("grp.user"), self.user)
        form.addRow(tr("qt.tg.invite_link"), self.invite)
        form.addRow(tr("grp.owner_account"), self.owner)
        form.addRow("", self.listen)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        invite = self.invite.text().strip()
        # 邀请链接变更时清空已缓存群标识，强制按新链接解析
        chat_ref = (
            ""
            if invite != self._original_invite.strip()
            else self._existing_chat_ref
        )
        return {
            "remark": self.remark.text().strip(),
            "chat_ref": chat_ref,
            "watch_user": self.user.text().strip(),
            "invite_link": invite,
            "listen_enabled": self.listen.isChecked(),
            "owner_account_id": self.owner.currentText().strip(),
        }


class ContactsPage(QWidget):
    def __init__(self, presenter: WaPresenter, tr: Translator, parent=None) -> None:
        super().__init__(parent)
        self.presenter, self.tr = presenter, tr
        self.config = presenter.config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel(tr("grp.title"))
        title.setProperty("title", True)
        layout.addWidget(title)
        hint = QLabel(tr("grp.hint_toolbar"))
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
        self._btn_edit.clicked.connect(self._edit_selected)
        self._btn_delete = QPushButton(tr("common.delete"))
        style_button(self._btn_delete, "danger")
        self._btn_delete.clicked.connect(self._delete_selected)
        self._btn_up = QPushButton(tr("qt.tg.move_up"))
        style_button(self._btn_up, "ghost")
        self._btn_up.clicked.connect(lambda: self._move_selected(-1))
        self._btn_down = QPushButton(tr("qt.tg.move_down"))
        style_button(self._btn_down, "ghost")
        self._btn_down.clicked.connect(lambda: self._move_selected(1))
        toolbar.addWidget(self._btn_add)
        toolbar.addWidget(self._btn_edit)
        toolbar.addWidget(self._btn_delete)
        toolbar.addWidget(self._btn_up)
        toolbar.addWidget(self._btn_down)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # # / 备注 / 群(邀请或JID) / 用户 / 归属 / 监听 / 上次任务
        self.table = QTableWidget(0, 7)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setHorizontalHeaderLabels([
            "#",
            tr("grp.remark"),
            tr("grp.group"),
            tr("grp.user"),
            tr("grp.owner"),
            tr("grp.listen"),
            tr("sched.last_task_col"),
        ])
        bind_resizable_columns(
            self.table,
            "wa.contacts",
            [56, 234, 214, 125, 100, 64, 211],
        )
        layout.addWidget(self.table)
        presenter.config_changed.connect(self.set_config)
        presenter.audit_finished.connect(self._on_audit)

    def _on_audit(self, _result=None) -> None:
        self.set_config(self.presenter.config)

    def set_config(self, config: ConfigView) -> None:
        from PySide6.QtGui import QBrush, QColor

        from ....services.task_confirmations import (
            audit_contact_badge,
            audit_contact_colors,
        )

        selected = self._selected_entry_id()
        self.config = config
        self.table.setRowCount(len(config.contacts))
        for row, contact in enumerate(config.contacts):
            last = (contact.last_schedule_source_name or "").strip()
            last_text = (
                self.tr("sched.last_task", name=last)
                if last
                else self.tr("sched.last_task_empty")
            )
            flag = self.presenter.audit_flags.get(contact.entry_id, "")
            badge = audit_contact_badge(self.tr, flag)
            fg, bg = audit_contact_colors(flag)
            remark = contact.remark + (badge or "")
            # 群列优先显示邀请链接（更长时），否则 chat_ref
            group_text = (contact.invite_link or "").strip() or contact.chat_ref
            values = (
                str(row + 1),
                remark,
                group_text,
                contact.watch_user,
                contact.owner_account_id,
                self.tr("grp.listen_tag")
                if contact.listen_enabled
                else self.tr("grp.schedule_only"),
                last_text.replace(" · ", "").strip(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, contact.entry_id)
                if fg:
                    item.setForeground(QColor(fg))
                if bg:
                    item.setBackground(QBrush(QColor(bg)))
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 44)
        if selected:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == selected:
                    self.table.selectRow(row)
                    break

    def _owners(self) -> list[str]:
        return [account.account_id for account in self.config.accounts]

    def _selected_entry_id(self) -> str:
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def _selected_contact(self) -> ContactItem | None:
        entry_id = self._selected_entry_id()
        if not entry_id:
            return None
        return next(
            (c for c in self.config.contacts if c.entry_id == entry_id), None
        )

    def _add(self) -> None:
        dialog = ContactDialog(self.tr, self._owners(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.presenter.add_contact(
            values["remark"],
            values["chat_ref"],
            values["watch_user"],
            values["listen_enabled"],
            values["owner_account_id"],
            values["invite_link"],
        )

    def _edit_selected(self) -> None:
        contact = self._selected_contact()
        if contact is None:
            return
        dialog = ContactDialog(self.tr, self._owners(), contact, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.presenter.update_contact(contact.entry_id, **dialog.values())

    def _delete_selected(self) -> None:
        entry_id = self._selected_entry_id()
        if entry_id:
            self.presenter.delete_contact(entry_id)

    def _move_selected(self, delta: int) -> None:
        entry_id = self._selected_entry_id()
        if entry_id:
            self.presenter.move_contact(entry_id, delta)
