"""PySide6 Widgets 任务管理原型窗口。"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .delegate import TaskCardDelegate
from .localization import translator
from .model import TaskFilterProxy, TaskListModel
from .records import load_task_records, make_stress_records


def current_user_objects() -> int:
    if os.name != "nt":
        return 0
    try:
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetGuiResources.restype = ctypes.c_uint
        return int(user32.GetGuiResources(kernel32.GetCurrentProcess(), 1))
    except (AttributeError, OSError):
        return -1


class TaskManagerWindow(QMainWindow):
    def __init__(
        self,
        *,
        data_root: Path,
        stress_count: int = 0,
        language: str = "zh",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._data_root = Path(data_root)
        self._stress_count = max(0, int(stress_count))
        self._tr = translator(language)
        self._model = TaskListModel(parent=self)
        self._proxy = TaskFilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._build_ui()
        self._connect_signals()
        self.reload_records()

        self._resource_timer = QTimer(self)
        self._resource_timer.timeout.connect(self._update_footer)
        self._resource_timer.start(1000)

    @property
    def task_view(self) -> QListView:
        return self._task_view

    @property
    def source_model(self) -> TaskListModel:
        return self._model

    @property
    def proxy_model(self) -> TaskFilterProxy:
        return self._proxy

    def _build_ui(self) -> None:
        self.setWindowTitle(self._tr("window.title"))
        self.resize(1040, 720)
        self.setMinimumSize(720, 480)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        toolbar = QFrame(central)
        toolbar.setObjectName("toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 10, 12, 10)
        toolbar_layout.setSpacing(9)

        toolbar_layout.addWidget(QLabel(self._tr("toolbar.platform"), toolbar))
        self._platform = QComboBox(toolbar)
        self._platform.addItem(self._tr("option.all"), "all")
        self._platform.addItem("WhatsApp", "wa")
        self._platform.addItem("Telegram", "tg")
        toolbar_layout.addWidget(self._platform)

        toolbar_layout.addWidget(QLabel(self._tr("toolbar.status"), toolbar))
        self._status = QComboBox(toolbar)
        for key in ("all", "running", "paused", "stopped"):
            self._status.addItem(self._tr(f"option.{key}"), key)
        toolbar_layout.addWidget(self._status)

        self._search = QLineEdit(toolbar)
        self._search.setPlaceholderText(self._tr("toolbar.search"))
        self._search.setClearButtonEnabled(True)
        toolbar_layout.addWidget(self._search, 1)

        self._refresh = QPushButton(self._tr("toolbar.refresh"), toolbar)
        toolbar_layout.addWidget(self._refresh)
        layout.addWidget(toolbar)

        self._summary = QLabel(central)
        self._summary.setObjectName("summary")
        layout.addWidget(self._summary)

        self._task_view = QListView(central)
        self._task_view.setModel(self._proxy)
        self._task_view.setItemDelegate(TaskCardDelegate(self._tr, self._task_view))
        self._task_view.setUniformItemSizes(True)
        self._task_view.setLayoutMode(QListView.LayoutMode.Batched)
        self._task_view.setBatchSize(64)
        self._task_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._task_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._task_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._task_view.setMouseTracking(True)
        self._task_view.setSpacing(2)
        layout.addWidget(self._task_view, 1)

        self._footer = QLabel(central)
        self._footer.setObjectName("footer")
        layout.addWidget(self._footer)
        self.setCentralWidget(central)
        self._apply_style()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #10161F; color: #DCE4EE; }
            QFrame#toolbar {
                background: #19212C; border: 1px solid #303B49; border-radius: 9px;
            }
            QComboBox, QLineEdit {
                min-height: 32px; padding: 0 9px; background: #111923;
                border: 1px solid #354253; border-radius: 6px; color: #E7EDF5;
            }
            QComboBox:hover, QLineEdit:focus { border-color: #4389D9; }
            QComboBox QAbstractItemView {
                background: #19212C; color: #E7EDF5; selection-background-color: #2D5F98;
            }
            QPushButton {
                min-height: 32px; padding: 0 16px; background: #2877D4;
                border: none; border-radius: 6px; color: white; font-weight: 600;
            }
            QPushButton:hover { background: #3688E7; }
            QPushButton:pressed { background: #1D64B7; }
            QListView {
                background: #10161F; border: none; outline: none;
            }
            QListView::item { background: transparent; }
            QLabel#summary { color: #B7C3D1; font-size: 13px; font-weight: 600; }
            QLabel#footer { color: #758396; font-size: 12px; }
            QScrollBar:vertical { background: #10161F; width: 10px; margin: 2px; }
            QScrollBar::handle:vertical {
                background: #3A4655; border-radius: 4px; min-height: 32px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            """
        )

    def _connect_signals(self) -> None:
        self._platform.currentIndexChanged.connect(self._apply_filters)
        self._status.currentIndexChanged.connect(self._apply_filters)
        self._search.textChanged.connect(self._apply_filters)
        self._refresh.clicked.connect(self.reload_records)
        self._proxy.rowsInserted.connect(self._update_summary)
        self._proxy.rowsRemoved.connect(self._update_summary)
        self._proxy.modelReset.connect(self._update_summary)

    def reload_records(self) -> None:
        records = load_task_records(self._data_root)
        if self._stress_count:
            records = make_stress_records(records, self._stress_count)
        self._model.replace_records(records)
        self._update_summary()
        self._update_footer()

    def _apply_filters(self, *_args) -> None:
        self._proxy.set_platform(str(self._platform.currentData() or "all"))
        self._proxy.set_status(str(self._status.currentData() or "all"))
        self._proxy.set_query(self._search.text())
        self._update_summary()

    def _update_summary(self, *_args) -> None:
        self._summary.setText(
            self._tr(
                "summary",
                visible=self._proxy.rowCount(),
                total=self._model.rowCount(),
            )
        )

    def _update_footer(self) -> None:
        self._footer.setText(
            self._tr(
                "footer",
                total=self._model.rowCount(),
                user=current_user_objects(),
            )
        )
