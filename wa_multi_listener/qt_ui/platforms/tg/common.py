"""TG Qt 页面共享控件与 Presenter 调用保护。"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...common.dialogs import show_message

from ...common.theme import ButtonKind, style_button

Translator = Callable[..., str]


def shared_tr(key: str, **kwargs: Any) -> str:
    from i18n import t

    return t(key, **kwargs)


def button(
    key: str,
    tr: Translator,
    callback: Callable[[], None],
    *,
    kind: ButtonKind = "default",
    compact: bool = False,
) -> QPushButton:
    control = QPushButton(tr(key))
    style_button(control, kind, compact=compact)
    control.clicked.connect(callback)
    return control


def call_guarded(parent: QWidget, tr: Translator, fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:
        show_message(parent, tr, tr("common.unknown_error"), str(exc))
        return None


class DataTable(QTableWidget):
    def __init__(self, header_keys: list[str], tr: Translator) -> None:
        super().__init__(0, len(header_keys))
        self.setHorizontalHeaderLabels([tr(x) for x in header_keys])
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(42)
        self.setShowGrid(False)
        self.setWordWrap(False)

    def fill(self, rows: list[list[Any]], ids: Optional[list[str]] = None) -> None:
        self.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if ids and col_index == 0:
                    item.setData(Qt.UserRole, ids[row_index])
                self.setItem(row_index, col_index, item)
            self.setRowHeight(row_index, 42)

    def selected_id(self) -> str:
        row = self.currentRow()
        if row < 0 or self.item(row, 0) is None:
            return ""
        return str(self.item(row, 0).data(Qt.UserRole) or "")


def form_row(layout: QFormLayout, label_key: str, control: QWidget, tr: Translator) -> None:
    layout.addRow(tr(label_key), control)


def action_row(*controls: QWidget) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    for control in controls:
        layout.addWidget(control)
    layout.addStretch(1)
    return widget


def page_title(tr: Translator, key: str) -> QLabel:
    label = QLabel(tr(key))
    label.setObjectName("pageTitle")
    label.setProperty("title", True)
    return label
