"""定时任务导入页与可注入共享任务管理页。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Protocol

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...common.file_dialogs import pick_folder, pick_txt_file
from .common import Translator, button, call_guarded, page_title


class TaskManagerFactory(Protocol):
    def __call__(
        self, presenter: Any, tr: Translator, parent: Optional[QWidget] = None
    ) -> QWidget: ...


class SchedulePage(QWidget):
    def __init__(self, presenter: Any, tr: Translator) -> None:
        super().__init__()
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(page_title(tr, "nav.sched"))
        hint = QLabel(tr("sched.tg_hint"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)

        self.source = QLineEdit()
        self.source.setPlaceholderText(tr("sched.file_ph"))
        layout.addWidget(self.source)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(QLabel(tr("sched.interval_short")))
        self.interval_min, self.interval_max = QDoubleSpinBox(), QDoubleSpinBox()
        for control in (self.interval_min, self.interval_max):
            control.setRange(0, 10080)
            control.setValue(5)
            control.setMaximumWidth(90)
        action_row.addWidget(self.interval_min)
        action_row.addWidget(QLabel("-"))
        action_row.addWidget(self.interval_max)
        action_row.addWidget(
            button("picker.folder", tr, self._pick_folder, kind="primary"),
            1,
        )
        action_row.addWidget(
            button("picker.txt_file", tr, self._pick_txt, kind="ghost")
        )
        action_row.addWidget(
            button("sched.add_job", tr, self._add_job, kind="primary")
        )
        action_row.addWidget(
            button("sched.txt_format_tg", tr, self._open_doc, kind="ghost")
        )
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

        self.result = QLabel()
        self.result.setProperty("muted", True)
        layout.addWidget(self.result)
        status_hint = QLabel(tr("sched.status_hint"))
        status_hint.setWordWrap(True)
        status_hint.setProperty("muted", True)
        layout.addWidget(status_hint)

        presenter.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        checked = set(self.selected_ids())
        self.targets.clear()
        for index, row in enumerate(self.presenter.config.address_book, start=1):
            last = (getattr(row, "last_schedule_source_name", "") or "").strip()
            suffix = (
                self.tr("sched.last_task", name=last)
                if last
                else self.tr("sched.last_task_empty")
            )
            item = QListWidgetItem(
                f"{index}. {(row.remark or row.chat_ref)}{suffix}"
            )
            item.setData(Qt.ItemDataRole.UserRole, row.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if row.id in checked
                else Qt.CheckState.Unchecked
            )
            self.targets.addItem(item)

    def selected_ids(self) -> list[str]:
        return [
            str(self.targets.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.targets.count())
            if self.targets.item(index).checkState() == Qt.CheckState.Checked
        ]

    def _interval(self) -> tuple[float, float]:
        low, high = self.interval_min.value(), self.interval_max.value()
        return min(low, high), max(low, high)

    def _pick_txt(self) -> None:
        path = pick_txt_file(self, tr=self.tr)
        if path:
            self.source.setText(path)

    def _pick_folder(self) -> None:
        path = pick_folder(self, tr=self.tr)
        if path:
            self.source.setText(path)

    def _add_job(self) -> None:
        path = self.source.text().strip()
        if not path:
            return
        selected = self.selected_ids()
        target = Path(path)
        if target.is_dir():
            result = call_guarded(
                self,
                self.tr,
                lambda: self.presenter.import_folder(
                    path, selected, self._interval()
                ),
            )
            if result is not None:
                self.result.setText(
                    self.tr("qt.tg.folder_jobs_created", count=len(result))
                )
            return
        result = call_guarded(
            self,
            self.tr,
            lambda: self.presenter.import_txt(path, selected, self._interval()),
        )
        if result is not None:
            self.result.setText(self.tr("qt.tg.jobs_created", count=len(result)))

    def _open_doc(self) -> None:
        from ...services.task_confirmations import open_schedule_doc

        open_schedule_doc()


class TaskManagerPlaceholder(QWidget):
    """共享任务组件尚未注入时的稳定接口占位。"""

    action_requested = Signal(str, str)

    def __init__(
        self, presenter: Any, tr: Translator, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.addWidget(page_title(tr, "nav.taskmgr"))
        layout.addWidget(QLabel(tr("taskmgr.empty")))
        layout.addStretch(1)

    def replace_records(self, _records=None) -> None:
        return None
