"""TXT / 文件夹定时任务导入 View。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ....common.file_dialogs import pick_folder, pick_txt_file
from ....common.theme import style_button
from ..contracts import ConfigView, Translator
from ..presenter import WaPresenter


class SchedulePage(QWidget):
    def __init__(self, presenter: WaPresenter, tr: Translator, parent=None) -> None:
        super().__init__(parent)
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel(tr("sched.title"))
        title.setProperty("title", True)
        layout.addWidget(title)
        hint = QLabel(tr("sched.wa_hint"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        self.source = QLineEdit()
        self.source.setPlaceholderText(tr("sched.file_ph"))
        layout.addWidget(self.source)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        interval_label = QLabel(tr("sched.interval_short"))
        self.interval = QLineEdit("5-10")
        self.interval.setPlaceholderText(tr("sched.interval_hint_short"))
        self.interval.setMaximumWidth(120)
        self.interval.setFixedWidth(110)
        pick_folder_btn = QPushButton(tr("picker.folder"))
        style_button(pick_folder_btn, "primary")
        pick_folder_btn.clicked.connect(self._pick_folder)
        pick_file = QPushButton(tr("picker.txt_file"))
        style_button(pick_file, "ghost")
        pick_file.clicked.connect(self._pick_file)
        add = QPushButton(tr("sched.add_job"))
        style_button(add, "primary")
        add.clicked.connect(self._import)
        doc = QPushButton(tr("sched.txt_format"))
        style_button(doc, "ghost")
        doc.clicked.connect(self._open_doc)
        action_row.addWidget(interval_label)
        action_row.addWidget(self.interval)
        action_row.addWidget(pick_folder_btn, 1)
        action_row.addWidget(pick_file)
        action_row.addWidget(add)
        action_row.addWidget(doc)
        layout.addLayout(action_row)

        layout.addWidget(QLabel(tr("sched.targets")))
        self.targets = QListWidget()
        self.targets.setAlternatingRowColors(True)
        self.targets.setSelectionMode(QListWidget.NoSelection)
        self.targets.setStyleSheet(
            "QListWidget { alternate-background-color: #1e2a36; background: #151c24; }"
            "QListWidget::item { padding: 6px 4px; }"
            "QListWidget::indicator { width: 16px; height: 16px; }"
        )
        layout.addWidget(self.targets, 1)
        status_hint = QLabel(tr("sched.status_hint"))
        status_hint.setWordWrap(True)
        status_hint.setProperty("muted", True)
        layout.addWidget(status_hint)

        presenter.config_changed.connect(self.set_config)

    def set_config(self, config: ConfigView) -> None:
        checked = {
            self.targets.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.targets.count())
            if self.targets.item(index).checkState() == Qt.CheckState.Checked
        }
        self.targets.clear()
        for index, contact in enumerate(config.contacts, start=1):
            last = (contact.last_schedule_source_name or "").strip()
            suffix = (
                self.tr("sched.last_task", name=last)
                if last
                else self.tr("sched.last_task_empty")
            )
            item = QListWidgetItem(
                f"{index}. {contact.remark} · {contact.chat_ref}{suffix}"
            )
            item.setData(Qt.ItemDataRole.UserRole, contact.entry_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if contact.entry_id in checked
                else Qt.CheckState.Unchecked
            )
            self.targets.addItem(item)

    def _pick_file(self) -> None:
        path = pick_txt_file(self, tr=self.tr)
        if path:
            self.source.setText(path)

    def _pick_folder(self) -> None:
        path = pick_folder(self, tr=self.tr)
        if path:
            self.source.setText(path)

    def _import(self) -> None:
        selected = [
            self.targets.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.targets.count())
            if self.targets.item(index).checkState() == Qt.CheckState.Checked
        ]
        self.presenter.import_schedule(
            self.source.text(), selected, self.interval.text()
        )

    def _open_doc(self) -> None:
        from ....services.task_confirmations import open_schedule_doc

        open_schedule_doc()
