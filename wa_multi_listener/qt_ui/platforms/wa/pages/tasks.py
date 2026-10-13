"""共享任务管理组件的 WA 宿主插槽。"""
from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..contracts import TaskManagerFactory, Translator
from ..presenter import WaPresenter


class TaskManagerPage(QWidget):
    """只做 factory 注入和数据转发，不实现第二套任务列表。"""

    def __init__(
        self,
        presenter: WaPresenter,
        tr: Translator,
        factory: TaskManagerFactory | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.presenter, self.factory = presenter, factory
        self.layout_box = QVBoxLayout(self)
        self.layout_box.addWidget(QLabel(tr("taskmgr.title")))
        self.host: Any = None
        self.placeholder = QLabel(tr("taskmgr.empty"))
        self.placeholder.setProperty("muted", True)
        self.layout_box.addWidget(self.placeholder)
        presenter.tasks_changed.connect(self.set_records)

    def set_records(self, records: Sequence[Any]) -> None:
        if self.factory is None:
            return
        if self.host is None:
            self.placeholder.hide()
            self.host = self.factory(self, records, self.presenter)
            if not isinstance(self.host, QWidget):
                raise TypeError("TaskManagerWidget factory must return QWidget")
            self.layout_box.addWidget(self.host)
            return
        setter = getattr(self.host, "replace_records", None)
        if not callable(setter):
            setter = getattr(self.host, "set_records", None)
        if not callable(setter):
            raise TypeError(
                "TaskManagerWidget must provide replace_records(records) "
                "or set_records(records)"
            )
        setter(records)
