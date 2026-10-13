"""单 Delegate 绘制和命中所有卡片，不创建逐行 QWidget。"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .model import TaskListModel
from .theme import palette
from .types import TaskManagerActions, TaskRecord


class TaskCardDelegate(QStyledItemDelegate):
    CARD_HEIGHT = 196
    COLUMNS = 3
    BUTTON_HEIGHT = 28

    def __init__(
        self,
        tr: Callable[..., str],
        actions: TaskManagerActions,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr
        self._actions = actions
        self._manual_next_day = False

    @property
    def manual_next_day(self) -> bool:
        return self._manual_next_day

    def set_manual_next_day(self, enabled: bool) -> None:
        self._manual_next_day = bool(enabled)
        parent = self.parent()
        if parent is not None:
            parent.viewport().update()

    def _card_width(self, option) -> int:
        view = self.parent()
        if view is not None and hasattr(view, "viewport"):
            spacing = int(getattr(view, "spacing", lambda: 6)() or 6)
            available = max(0, view.viewport().width() - spacing * (self.COLUMNS + 1))
            return max(180, available // self.COLUMNS)
        return max(200, option.rect.width())

    def sizeHint(self, option, index) -> QSize:
        return QSize(self._card_width(option), self.CARD_HEIGHT)

    def action_rects(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> dict[str, QRect]:
        record = index.data(TaskListModel.RecordRole)
        if not isinstance(record, TaskRecord):
            return {}
        card = option.rect.adjusted(7, 5, -7, -5)
        right = card.right() - 12
        top = card.bottom() - self.BUTTON_HEIGHT - 10
        delete_width = 72
        result = {
            "delete": QRect(
                right - delete_width + 1,
                top,
                delete_width,
                self.BUTTON_HEIGHT,
            )
        }
        if self._manual_next_day and record.is_folder:
            next_width = 104
            result["next_day"] = QRect(
                result["delete"].left() - next_width - 8,
                top,
                next_width,
                self.BUTTON_HEIGHT,
            )
        return result

    @staticmethod
    def _font(option: QStyleOptionViewItem, size: int, bold: bool = False) -> QFont:
        font = QFont(option.font)
        font.setPointSize(size)
        if bold:
            font.setWeight(QFont.Weight.DemiBold)
        return font

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        color: QColor,
        font: QFont,
        alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        painter.setFont(font)
        painter.setPen(color)
        value = painter.fontMetrics().elidedText(
            text.replace("\r", " ").replace("\n", " "),
            Qt.TextElideMode.ElideRight,
            max(0, int(rect.width())),
        )
        painter.drawText(rect, alignment, value)

    def _draw_button(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        *,
        background: QColor,
        foreground: QColor,
        enabled: bool = True,
    ) -> None:
        bg = background if enabled else QColor("#4a5160")
        fg = foreground if enabled else QColor("#949bab")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(rect), 6, 6)
        self._draw_text(
            painter,
            QRectF(rect),
            text,
            fg,
            QFont("Microsoft YaHei UI", 8, QFont.Weight.DemiBold),
            Qt.AlignmentFlag.AlignCenter,
        )

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        record = index.data(TaskListModel.RecordRole)
        if not isinstance(record, TaskRecord):
            return super().paint(painter, option, index)
        colors = palette(record)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = QRectF(option.rect.adjusted(7, 5, -7, -5))
        border = QColor("#6da8e8") if option.state & QStyle.StateFlag.State_Selected else colors["border"]
        painter.setPen(QPen(border, 2))
        painter.setBrush(colors["fg"])
        painter.drawRoundedRect(card, 10, 10)

        left = card.left() + 14
        right = card.right() - 14
        title_font = self._font(option, 11, True)
        body_font = self._font(option, 9)
        small_font = self._font(option, 8)

        badge = QRectF(right - 42, card.top() + 10, 42, 23)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2877D4" if record.platform.casefold() == "tg" else "#178D67"))
        painter.drawRoundedRect(badge, 6, 6)
        self._draw_text(
            painter,
            badge,
            record.platform.upper(),
            QColor("#ffffff"),
            small_font,
            Qt.AlignmentFlag.AlignCenter,
        )

        action_hint = self._tr(
            "task_manager.card.next_day_hint"
            if self._manual_next_day and record.is_folder
            else "task_manager.card.pause_hint"
            if record.running
            else "task_manager.card.resume_hint"
        )
        self._draw_text(
            painter,
            QRectF(left, card.top() + 7, badge.left() - left - 8, 28),
            record.title,
            colors["title"],
            title_font,
        )
        self._draw_text(
            painter,
            QRectF(left, card.top() + 36, right - left, 21),
            self._tr(
                "task_manager.card.status",
                status=record.status,
                step=record.step,
            ),
            colors["status"],
            body_font,
        )
        self._draw_text(
            painter,
            QRectF(left, card.top() + 58, right - left, 20),
            self._tr(
                "task_manager.card.source_target",
                source=record.source_name,
                target=record.target,
            ),
            colors["file"],
            small_font,
        )
        folder = self._tr(
            "task_manager.card.folder_day",
            day=record.folder_day,
            total=record.folder_total,
        ) if record.is_folder else self._tr("task_manager.card.not_folder")
        self._draw_text(
            painter,
            QRectF(left, card.top() + 79, right - left, 20),
            self._tr(
                "task_manager.card.progress",
                cursor=record.cursor,
                total=record.total,
                folder=folder,
            ),
            colors["body"],
            small_font,
        )
        # 阶段提醒 / 发图备注（黄底，对齐旧版任务卡）
        rem = (record.reminder_note or "").strip()
        rem_text = (
            self._tr("taskmgr.note", text=rem)
            if rem
            else self._tr("taskmgr.note_none")
        )
        rem_rect = QRectF(left, card.top() + 100, right - left, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#ffd24a" if rem else "#5a4a18"))
        painter.drawRoundedRect(rem_rect, 4, 4)
        self._draw_text(
            painter,
            rem_rect.adjusted(6, 0, -6, 0),
            rem_text,
            QColor("#1f2328" if rem else "#c9b56a"),
            small_font,
        )
        detail_raw = record.last_error or record.pause_reason or action_hint
        if record.last_error:
            detail = detail_raw
            detail_key = "task_manager.card.error"
        elif record.pause_reason:
            from i18n.pause_reason import display_pause_reason

            detail = display_pause_reason(record.pause_reason)
            detail_key = "task_manager.card.pause"
        else:
            detail = detail_raw
            detail_key = "task_manager.card.action"
        button_left = min(
            (rect.left() for rect in self.action_rects(option, index).values()),
            default=int(right),
        )
        self._draw_text(
            painter,
            QRectF(left, card.top() + 126, max(60, button_left - int(left) - 10), 22),
            self._tr(detail_key, text=detail),
            QColor("#ffb3b3") if record.last_error else colors["hint"],
            small_font,
        )

        rects = self.action_rects(option, index)
        if "next_day" in rects:
            self._draw_button(
                painter,
                rects["next_day"],
                self._tr("task_manager.card.next_day"),
                background=QColor("#356878"),
                foreground=QColor("#ffffff"),
                enabled=record.can_advance_day,
            )
        self._draw_button(
            painter,
            rects["delete"],
            self._tr("task_manager.card.delete"),
            background=QColor("#a93f45"),
            foreground=QColor("#ffffff"),
        )
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if (
            event.type() != QEvent.Type.MouseButtonRelease
            or not isinstance(event, QMouseEvent)
            or event.button() != Qt.MouseButton.LeftButton
        ):
            return False
        return self.handle_click(index, option, event.position().toPoint())

    def handle_click(
        self,
        index: QModelIndex,
        option: QStyleOptionViewItem,
        point,
    ) -> bool:
        """供 QListView 和 editorEvent 共用的确定性命中入口。"""
        record = index.data(TaskListModel.RecordRole)
        if not isinstance(record, TaskRecord):
            return False
        rects = self.action_rects(option, index)
        if rects.get("delete", QRect()).contains(point):
            self._actions.delete_task(record.task_id)
            return True
        if rects.get("next_day", QRect()).contains(point):
            if record.can_advance_day:
                self._actions.next_day_task(record.task_id)
            return True
        if option.rect.contains(point):
            if self._manual_next_day and record.is_folder:
                if record.can_advance_day:
                    self._actions.next_day_task(record.task_id)
                return True
            self._actions.toggle_task(record.task_id)
            return True
        return False
