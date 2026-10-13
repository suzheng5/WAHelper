"""任务数据模型与筛选代理；每条任务只占一个 Python 数据对象。"""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt

from .records import TaskRecord


class TaskListModel(QAbstractListModel):
    RecordRole = Qt.ItemDataRole.UserRole + 1
    PlatformRole = RecordRole + 1
    StatusRole = RecordRole + 2
    SearchRole = RecordRole + 3

    def __init__(self, records: list[TaskRecord] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._records = list(records or [])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return record.title
        if role == self.RecordRole:
            return record
        if role == self.PlatformRole:
            return record.platform
        if role == self.StatusRole:
            return record.status
        if role == self.SearchRole:
            return record.search_text
        return None

    def replace_records(self, records: list[TaskRecord]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()


class TaskFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._platform = "all"
        self._status = "all"
        self._query = ""
        self.setDynamicSortFilter(True)

    def set_platform(self, platform: str) -> None:
        self._platform = platform.casefold()
        self.invalidateRowsFilter()

    def set_status(self, status: str) -> None:
        self._status = status.casefold()
        self.invalidateRowsFilter()

    def set_query(self, query: str) -> None:
        self._query = query.strip().casefold()
        self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        platform = str(model.data(index, TaskListModel.PlatformRole) or "").casefold()
        status = str(model.data(index, TaskListModel.StatusRole) or "").casefold()
        search_text = str(model.data(index, TaskListModel.SearchRole) or "")
        if self._platform != "all" and platform != self._platform:
            return False
        if self._status != "all":
            if self._status == "paused":
                if status not in {"paused", "listen"}:
                    return False
            elif status != self._status:
                return False
        return not self._query or self._query in search_text
