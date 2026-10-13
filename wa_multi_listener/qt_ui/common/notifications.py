"""Independent message and stage reminder windows."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS, style_button

Translator: TypeAlias = Callable[..., str]


class ReminderWindow(QWidget):
    """Non-modal reminder that raises once and allows parallel windows."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        tr: Translator,
        title: str,
        heading: str,
        subtitle: str,
        body: str,
        close_key: str,
        accent: bool = False,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(title)
        self.setMinimumSize(420, 240)
        self.resize(500, 300)
        self._on_close = on_close
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        heading_label = QLabel(heading, self)
        heading_label.setWordWrap(True)
        if accent:
            heading_label.setStyleSheet(
                f"color: {COLORS['accent']}; font-weight: 700; font-size: 15px;"
            )
        else:
            heading_label.setStyleSheet("font-weight: 700; font-size: 15px;")
        layout.addWidget(heading_label)
        if subtitle:
            subtitle_label = QLabel(subtitle, self)
            subtitle_label.setProperty("muted", True)
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)
        body_view = QPlainTextEdit(self)
        body_view.setPlainText(body)
        body_view.setReadOnly(True)
        layout.addWidget(body_view, 1)
        close_button = QPushButton(str(tr(close_key)), self)
        style_button(close_button, "primary")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignLeft)

    def present(self) -> "ReminderWindow":
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            margin = 12
            self.move(geo.left() + margin, geo.top() + margin)
        self.show()
        self.raise_()
        self.activateWindow()
        return self

    def closeEvent(self, event) -> None:
        try:
            if self._on_close:
                self._on_close()
        finally:
            super().closeEvent(event)


def show_alert(
    parent: QWidget | None,
    *,
    tr: Translator,
    title: str,
    chat_title: str,
    sender_name: str,
    message_text: str,
    remark: str = "",
    on_close: Callable[[], None] | None = None,
) -> ReminderWindow:
    remark_text = (remark or "").strip()
    chat = (chat_title or "").strip()
    sender = (sender_name or "").strip()
    if remark_text:
        heading = f"{remark_text} · {chat}" if chat else remark_text
        subtitle = " · ".join(part for part in (chat, sender) if part)
    else:
        heading = chat
        subtitle = sender
    return ReminderWindow(
        parent,
        tr=tr,
        title=title,
        heading=heading,
        subtitle=subtitle,
        body=message_text,
        close_key="alert.close",
        on_close=on_close,
    ).present()


def show_stage_reminder(
    parent: QWidget | None,
    *,
    tr: Translator,
    title: str,
    subtitle: str,
    body: str,
) -> ReminderWindow:
    return ReminderWindow(
        parent,
        tr=tr,
        title=title,
        heading=title,
        subtitle=subtitle,
        body=body,
        close_key="stage.got_it",
        accent=True,
    ).present()
