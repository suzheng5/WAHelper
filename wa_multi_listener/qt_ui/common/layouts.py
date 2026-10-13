"""Reusable page layouts with fixed action areas."""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import ButtonKind, style_button


class ActionBar(QFrame):
    """A fixed-height bottom bar whose actions stay visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 10, 14, 10)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

    def add_button(
        self,
        text: str,
        callback,
        *,
        primary: bool = False,
        kind: ButtonKind | None = None,
    ) -> QPushButton:
        button = QPushButton(text, self)
        style_button(button, kind or ("primary" if primary else "default"))
        button.clicked.connect(callback)
        self._layout.addWidget(button)
        return button

    def set_buttons(self, specs: Iterable[tuple[str, object, bool]]) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        for text, callback, primary in specs:
            self.add_button(text, callback, primary=primary)


class ScrollPage(QWidget):
    """A page with a widget-resizable vertical scroll body."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QWidget(self.scroll_area)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(12, 12, 12, 12)
        self.content_layout.setSpacing(10)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.content)
        outer.addWidget(self.scroll_area)


class FixedActionPage(ScrollPage):
    """Scrollable content with an action bar outside the scroll area."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action_bar = ActionBar(self)
        self.layout().addWidget(self.action_bar)
