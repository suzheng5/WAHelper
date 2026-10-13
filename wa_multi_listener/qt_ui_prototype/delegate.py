"""用单个 Delegate 绘制全部卡片，不为每条任务创建 QWidget。"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .model import TaskListModel
from .records import TaskRecord

STATUS_COLORS = {
    "running": QColor("#2EBD85"),
    "listen": QColor("#D19A37"),
    "paused": QColor("#D19A37"),
    "stopped": QColor("#788191"),
}


class TaskCardDelegate(QStyledItemDelegate):
    CARD_HEIGHT = 108

    def __init__(self, tr: Callable[..., str], parent=None) -> None:
        super().__init__(parent)
        self._tr = tr

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(320, option.rect.width()), self.CARD_HEIGHT)

    @staticmethod
    def _text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        *,
        color: QColor,
        font: QFont,
        alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        painter.setFont(font)
        painter.setPen(color)
        elided = painter.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, max(0, int(rect.width()))
        )
        painter.drawText(rect, alignment, elided)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        record = index.data(TaskListModel.RecordRole)
        if not isinstance(record, TaskRecord):
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = QRectF(option.rect.adjusted(6, 4, -6, -4))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        background = QColor("#243247" if selected else "#202936" if hovered else "#19212C")
        border = QColor("#3E75B6" if selected else "#303B49")
        painter.setPen(border)
        painter.setBrush(background)
        painter.drawRoundedRect(card, 9, 9)

        left = card.left() + 16
        right = card.right() - 16
        title_font = QFont(option.font)
        title_font.setPointSize(11)
        title_font.setWeight(QFont.Weight.DemiBold)
        normal_font = QFont(option.font)
        normal_font.setPointSize(9)
        small_font = QFont(option.font)
        small_font.setPointSize(8)

        platform_width = 34.0
        platform_rect = QRectF(right - platform_width, card.top() + 11, platform_width, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2877D4" if record.platform == "TG" else "#178D67"))
        painter.drawRoundedRect(platform_rect, 6, 6)
        self._text(
            painter,
            platform_rect,
            record.platform,
            color=QColor("#FFFFFF"),
            font=small_font,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        status_text = self._tr(f"status.{record.status}")
        status_width = max(58.0, float(painter.fontMetrics().horizontalAdvance(status_text) + 20))
        status_rect = QRectF(
            platform_rect.left() - status_width - 8, platform_rect.top(), status_width, 22
        )
        status_color = STATUS_COLORS.get(record.status, STATUS_COLORS["stopped"])
        painter.setBrush(QColor(status_color.red(), status_color.green(), status_color.blue(), 38))
        painter.setPen(status_color)
        painter.drawRoundedRect(status_rect, 6, 6)
        self._text(
            painter,
            status_rect,
            status_text,
            color=status_color,
            font=small_font,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        title_rect = QRectF(
            left, card.top() + 9, max(80.0, status_rect.left() - left - 10), 26
        )
        self._text(
            painter,
            title_rect,
            record.title,
            color=QColor("#F1F5FA"),
            font=title_font,
        )

        target = record.target or self._tr("target.none")
        detail = f"{target}  ·  {record.source_name}"
        self._text(
            painter,
            QRectF(left, card.top() + 39, right - left, 24),
            detail,
            color=QColor("#AAB5C3"),
            font=normal_font,
        )

        progress = self._tr("progress", cursor=record.cursor, total=record.total)
        note = record.note.replace("\r", " ").replace("\n", " ").strip()
        bottom = progress if not note else f"{progress}  ·  {note}"
        self._text(
            painter,
            QRectF(left, card.top() + 67, right - left, 25),
            bottom,
            color=QColor("#7F8C9D"),
            font=small_font,
        )
        painter.restore()
