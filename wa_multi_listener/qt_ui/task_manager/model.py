"""事件驱动任务模型与筛选排序代理。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from .theme import bucket, sort_tier
from .types import TaskRecord


class TaskListModel(QAbstractListModel):
    RecordRole = int(Qt.ItemDataRole.UserRole) + 1
    IdRole = RecordRole + 1
    PlatformRole = RecordRole + 2
    BucketRole = RecordRole + 3
    SearchRole = RecordRole + 4
    SortTierRole = RecordRole + 5

    def __init__(self, records: Iterable[TaskRecord] = (), parent=None) -> None:
        super().__init__(parent)
        self._records = list(records)
        self._rows = {record.task_id: row for row, record in enumerate(self._records)}
        self.reset_count = 0
        self.patch_count = 0

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._records)

    def data(self, index: QModelIndex, role=int(Qt.ItemDataRole.DisplayRole)):
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return record.title
        if role == self.RecordRole:
            return record
        if role == self.IdRole:
            return record.task_id
        if role == self.PlatformRole:
            return record.platform.casefold()
        if role == self.BucketRole:
            return bucket(record)
        if role == self.SearchRole:
            return record.search_text
        if role == self.SortTierRole:
            return sort_tier(record)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.RecordRole: b"record",
            self.IdRole: b"taskId",
            self.PlatformRole: b"platform",
            self.BucketRole: b"bucket",
            self.SearchRole: b"searchText",
            self.SortTierRole: b"sortTier",
        }

    def record_at(self, row: int) -> TaskRecord | None:
        return self._records[row] if 0 <= row < len(self._records) else None

    def replace_records(self, records: Iterable[TaskRecord]) -> None:
        values = list(records)
        ids = [record.task_id for record in values]
        if len(ids) != len(set(ids)):
            raise ValueError("task_id must be unique")
        self.beginResetModel()
        self._records = values
        self._rows = {task_id: row for row, task_id in enumerate(ids)}
        self.reset_count += 1
        self.endResetModel()

    def patch_records(
        self,
        patches: Mapping[str, TaskRecord | Mapping[str, Any]],
    ) -> list[str]:
        """仅发送受影响行的 dataChanged；返回实际更新的 id。"""
        changed_rows: list[int] = []
        changed_ids: list[str] = []
        for task_id, patch in patches.items():
            row = self._rows.get(task_id)
            if row is None:
                continue
            old = self._records[row]
            new = patch if isinstance(patch, TaskRecord) else old.patched(patch)
            if new.task_id != task_id:
                raise ValueError("patch record id mismatch")
            if new == old:
                continue
            self._records[row] = new
            changed_rows.append(row)
            changed_ids.append(task_id)
        for row in changed_rows:
            index = self.index(row, 0)
            self.dataChanged.emit(
                index,
                index,
                [
                    self.RecordRole,
                    self.PlatformRole,
                    self.BucketRole,
                    self.SearchRole,
                    self.SortTierRole,
                ],
            )
        self.patch_count += len(changed_rows)
        return changed_ids


class TaskFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._platform = "all"
        self._status = "all"
        self._query = ""
        self._sort_mode = "semantic"
        self.setDynamicSortFilter(True)
        self.sort(0)

    def set_platform(self, platform: str) -> None:
        self._platform = (platform or "all").casefold()
        self.invalidateRowsFilter()

    def set_status(self, status: str) -> None:
        self._status = (status or "all").casefold()
        self.invalidateRowsFilter()

    def set_query(self, query: str) -> None:
        self._query = query.strip().casefold()
        self.invalidateRowsFilter()

    def set_sort_mode(self, mode: str) -> None:
        self._sort_mode = mode or "semantic"
        self.invalidate()
        self.sort(0)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        index = model.index(source_row, 0, source_parent)
        platform = str(model.data(index, TaskListModel.PlatformRole) or "")
        status = str(model.data(index, TaskListModel.BucketRole) or "")
        text = str(model.data(index, TaskListModel.SearchRole) or "")
        if self._platform != "all" and platform != self._platform:
            return False
        if self._status != "all":
            paused = {
                "listen_pause",
                "stage_listen_pause",
                "stopped_listen_pause",
                "other_pause",
            }
            if self._status == "paused" and status not in paused:
                return False
            if self._status != "paused" and status != self._status:
                return False
        return not self._query or self._query in text

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_record = left.data(TaskListModel.RecordRole)
        right_record = right.data(TaskListModel.RecordRole)
        if not isinstance(left_record, TaskRecord) or not isinstance(right_record, TaskRecord):
            return super().lessThan(left, right)
        if self._sort_mode == "title":
            left_key = (left_record.title.casefold(), left_record.source_order)
            right_key = (right_record.title.casefold(), right_record.source_order)
        elif self._sort_mode == "platform":
            left_key = (
                left_record.platform.casefold(),
                left_record.title.casefold(),
                left_record.source_order,
            )
            right_key = (
                right_record.platform.casefold(),
                right_record.title.casefold(),
                right_record.source_order,
            )
        else:
            left_key = (sort_tier(left_record), left_record.source_order)
            right_key = (sort_tier(right_record), right_record.source_order)
        return left_key < right_key
