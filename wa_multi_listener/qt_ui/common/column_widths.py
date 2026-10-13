"""表格列宽：按固定默认值锁定，不可拖动。"""
from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import QHeaderView, QTableWidget

_MIN_WIDTH = 40


def apply_fixed_columns(
    table: QTableWidget,
    widths: Sequence[int],
) -> None:
    """全部列为 Fixed，使用代码内写死的宽度。"""
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionsMovable(False)
    for col in range(table.columnCount()):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        width = int(widths[col]) if col < len(widths) else _MIN_WIDTH
        table.setColumnWidth(col, max(_MIN_WIDTH, width))


# 兼容旧调用名
def bind_resizable_columns(
    table: QTableWidget,
    table_key: str,
    defaults: Sequence[int],
) -> None:
    del table_key  # 不再读写配置文件
    apply_fixed_columns(table, defaults)
