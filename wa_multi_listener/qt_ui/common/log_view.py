"""Thread-safe incremental QPlainTextEdit log view."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from wa_ui.log_view_filter import is_visible_in_log_view


class _LogBridge(QObject):
    line_received = Signal(str)
    reset_received = Signal(object)


class IncrementalLogView(QPlainTextEdit):
    """Read-only capped log widget that avoids full-content refreshes."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        max_lines: int = 500,
        line_filter: Callable[[str], bool] | None = is_visible_in_log_view,
    ) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(max(1, int(max_lines)))
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._line_filter = line_filter
        self._bridge = _LogBridge(self)
        self._bridge.line_received.connect(self._append_line)
        self._bridge.reset_received.connect(self._replace_lines)

    def append_line(self, line: str) -> None:
        """Queue one line safely, including from worker threads."""
        text = str(line).rstrip("\r\n")
        if self._line_filter is not None and not self._line_filter(text):
            return
        self._bridge.line_received.emit(text)

    def append_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.append_line(line)

    def replace_lines(self, lines: Iterable[str]) -> None:
        values = [str(line).rstrip("\r\n") for line in list(lines)]
        if self._line_filter is not None:
            values = [line for line in values if self._line_filter(line)]
        self._bridge.reset_received.emit(values)

    @Slot(str)
    def _append_line(self, line: str) -> None:
        scrollbar = self.verticalScrollBar()
        follow = scrollbar.value() >= scrollbar.maximum() - 2
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.document().blockCount() > 1 or self.toPlainText():
            cursor.insertBlock()
        cursor.insertText(line)
        if follow:
            self.moveCursor(QTextCursor.MoveOperation.End)
            self.ensureCursorVisible()

    @Slot(object)
    def _replace_lines(self, lines: object) -> None:
        values = [str(line).rstrip("\r\n") for line in list(lines)]
        self.setPlainText("\n".join(values))
        self.moveCursor(QTextCursor.MoveOperation.End)
