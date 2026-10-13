"""可嵌入 WA/TG 的生产任务管理组件。"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from ..common.theme import COLORS, ButtonKind, style_button
from .delegate import TaskCardDelegate
from .model import TaskFilterProxy, TaskListModel
from .theme import bucket
from .types import TaskManagerActions, TaskRecord


class TaskListView(QListView):
    """显式路由卡片动作，避免不同平台样式吞掉 Delegate release 事件。"""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            delegate = self.itemDelegate()
            if index.isValid() and isinstance(delegate, TaskCardDelegate):
                option = QStyleOptionViewItem()
                self.initViewItemOption(option)
                option.rect = self.visualRect(index)
                if delegate.handle_click(index, option, event.position().toPoint()):
                    event.accept()
                    return
        super().mouseReleaseEvent(event)


class TaskManagerWidget(QWidget):
    """虚拟任务列表；宿主通过 replace/patch 推送事件，通过 actions 接收命令。"""

    def __init__(
        self,
        *,
        actions: TaskManagerActions,
        tr: Callable[..., str],
        parent=None,
        hidden_commands: Iterable[str] = (),
        refresh_provider: Callable[[], Iterable[TaskRecord]] | None = None,
        auto_refresh_ms: int = 2000,
    ) -> None:
        super().__init__(parent)
        self._actions = actions
        self._tr = tr
        self._hidden_commands = set(hidden_commands)
        self._refresh_provider = refresh_provider
        self.model = TaskListModel(parent=self)
        self.proxy = TaskFilterProxy(self)
        self.proxy.setSourceModel(self.model)
        self._buttons: dict[str, QPushButton] = {}
        self._build_ui()
        self._connect()
        self._update_summary()
        self._refresh_timer = QTimer(self)
        if refresh_provider is not None and auto_refresh_ms > 0:
            self._refresh_timer.setInterval(int(auto_refresh_ms))
            self._refresh_timer.timeout.connect(self._auto_refresh)
            self._refresh_timer.start()

    @property
    def view(self) -> QListView:
        return self._view

    @property
    def manual_next_day_mode(self) -> bool:
        return self.delegate.manual_next_day

    def command_button(self, command: str) -> QPushButton:
        return self._buttons[command]

    def replace_records(self, records: Iterable[TaskRecord]) -> None:
        self.model.replace_records(records)

    def patch_records(
        self,
        patches: Mapping[str, TaskRecord | Mapping[str, Any]],
    ) -> list[str]:
        return self.model.patch_records(patches)

    def _auto_refresh(self) -> None:
        if self._refresh_provider is None:
            return
        try:
            records = list(self._refresh_provider())
        except Exception:
            return
        self.replace_records(records)

    def _button(
        self,
        command: str,
        text_key: str,
        callback: Callable[[], None],
        parent: QWidget,
        *,
        checkable: bool = False,
        kind: ButtonKind = "accent",
    ) -> QPushButton:
        button = QPushButton(self._tr(text_key), parent)
        button.setObjectName(f"taskManager_{command}")
        button.setCheckable(checkable)
        style_button(button, kind)
        button.clicked.connect(callback)
        self._buttons[command] = button
        return button

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(10)

        commands = QFrame(self)
        commands.setObjectName("taskManagerCommands")
        commands.setProperty("card", True)
        commands_layout = QHBoxLayout(commands)
        commands_layout.setContentsMargins(10, 10, 10, 10)
        commands_layout.setSpacing(8)
        for command, key, callback, kind in (
            ("resume_all", "task_manager.command.resume_all", self._actions.resume_all, "primary"),
            ("next_day_all", "task_manager.command.next_day_all", self._actions.next_day_all, "accent"),
            ("delete_all", "task_manager.command.delete_all", self._actions.delete_all, "danger"),
            (
                "reload_wa_folders",
                "task_manager.command.reload_wa_folders",
                self._actions.reload_wa_folders,
                "default",
            ),
            ("send_images", "task_manager.command.send_images", self._actions.send_images, "accent"),
            (
                "send_images_sync",
                "task_manager.command.send_images_sync",
                self._actions.send_images_sync,
                "default",
            ),
        ):
            if command in self._hidden_commands:
                continue
            commands_layout.addWidget(
                self._button(command, key, callback, commands, kind=kind)
            )
        manual = self._button(
            "manual_next_day",
            "task_manager.command.manual_next_day",
            self._toggle_manual_next_day,
            commands,
            checkable=True,
            kind="ghost",
        )
        commands_layout.insertWidget(2, manual)
        commands_layout.addStretch(1)
        layout.addWidget(commands)

        filters = QFrame(self)
        filters.setObjectName("taskManagerFilters")
        filters.setProperty("card", True)
        filters_layout = QHBoxLayout(filters)
        filters_layout.setContentsMargins(10, 8, 10, 8)
        filters_layout.setSpacing(8)
        self._platform = QComboBox(filters)
        for key, value in (
            ("task_manager.option.all_platforms", "all"),
            ("task_manager.option.wa", "wa"),
            ("task_manager.option.tg", "tg"),
        ):
            self._platform.addItem(self._tr(key), value)
        self._status = QComboBox(filters)
        for key, value in (
            ("task_manager.option.all_statuses", "all"),
            ("task_manager.option.running", "running"),
            ("task_manager.option.paused", "paused"),
            ("task_manager.option.stopped", "stopped"),
        ):
            self._status.addItem(self._tr(key), value)
        self._sort = QComboBox(filters)
        for key, value in (
            ("task_manager.sort.semantic", "semantic"),
            ("task_manager.sort.title", "title"),
            ("task_manager.sort.platform", "platform"),
        ):
            self._sort.addItem(self._tr(key), value)
        self._search = QLineEdit(filters)
        self._search.setPlaceholderText(self._tr("task_manager.search.placeholder"))
        self._search.setClearButtonEnabled(True)
        self._summary = QLabel(filters)
        self._summary.setObjectName("taskManagerSummary")
        self._summary.setProperty("muted", True)
        self._summary.setMinimumWidth(160)
        filters_layout.addWidget(self._platform)
        filters_layout.addWidget(self._status)
        filters_layout.addWidget(self._sort)
        filters_layout.addWidget(self._search, 1)
        filters_layout.addWidget(self._summary)
        layout.addWidget(filters)

        self._view = TaskListView(self)
        self._view.setObjectName("taskManagerView")
        self._view.setModel(self.proxy)
        self.delegate = TaskCardDelegate(self._tr, self._actions, self._view)
        self._view.setItemDelegate(self.delegate)
        self._view.setViewMode(QListView.ViewMode.IconMode)
        self._view.setFlow(QListView.Flow.LeftToRight)
        self._view.setWrapping(True)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setMovement(QListView.Movement.Static)
        self._view.setUniformItemSizes(True)
        self._view.setSpacing(4)
        self._view.setLayoutMode(QListView.LayoutMode.Batched)
        self._view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setMouseTracking(True)
        layout.addWidget(self._view, 1)
        self._apply_style()
        self._view.viewport().installEventFilter(self)
        self._sync_grid_size()

    def _sync_grid_size(self) -> None:
        spacing = self._view.spacing()
        available = max(
            0, self._view.viewport().width() - spacing * (TaskCardDelegate.COLUMNS + 1)
        )
        width = max(180, available // TaskCardDelegate.COLUMNS)
        self._view.setGridSize(QSize(width, TaskCardDelegate.CARD_HEIGHT + spacing))
        self._view.doItemsLayout()

    def eventFilter(self, watched, event):  # noqa: N802
        from PySide6.QtCore import QEvent

        if watched is self._view.viewport() and event.type() == QEvent.Type.Resize:
            self._sync_grid_size()
        return super().eventFilter(watched, event)

    def _connect(self) -> None:
        self._platform.currentIndexChanged.connect(
            lambda: self.proxy.set_platform(str(self._platform.currentData() or "all"))
        )
        self._status.currentIndexChanged.connect(
            lambda: self.proxy.set_status(str(self._status.currentData() or "all"))
        )
        self._sort.currentIndexChanged.connect(
            lambda: self.proxy.set_sort_mode(str(self._sort.currentData() or "semantic"))
        )
        self._search.textChanged.connect(self.proxy.set_query)
        for signal in (
            self.proxy.modelReset,
            self.proxy.rowsInserted,
            self.proxy.rowsRemoved,
            self.proxy.layoutChanged,
            self.model.modelReset,
            self.model.dataChanged,
        ):
            signal.connect(self._update_summary)

    def _toggle_manual_next_day(self) -> None:
        enabled = self._buttons["manual_next_day"].isChecked()
        self.delegate.set_manual_next_day(enabled)
        self._actions.manual_next_day_mode_changed(enabled)

    def _update_summary(self, *_args) -> None:
        running = paused = stopped = 0
        for row in range(self.model.rowCount()):
            record = self.model.record_at(row)
            if record is None:
                continue
            kind = bucket(record)
            if kind == "running":
                running += 1
            elif kind == "stopped":
                stopped += 1
            else:
                paused += 1
        self._summary.setText(
            self._tr(
                "task_manager.summary_stats",
                running=running,
                paused=paused,
                stopped=stopped,
                visible=self.proxy.rowCount(),
                total=self.model.rowCount(),
            )
        )

    def _apply_style(self) -> None:
        c = COLORS
        self.setStyleSheet(
            f"""
            TaskManagerWidget {{ background: {c["bg"]}; color: {c["text"]}; }}
            QFrame#taskManagerCommands, QFrame#taskManagerFilters {{
                background: {c["card"]};
                border: 1px solid {c["border"]};
                border-radius: 12px;
            }}
            QListView {{ background: {c["bg"]}; border: 0; outline: 0; }}
            QListView::item {{ background: transparent; }}
            QLabel#taskManagerSummary {{ color: {c["muted"]}; font-weight: 600; }}
            """
        )
