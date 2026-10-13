"""Unified modal dialogs with fixed action bars."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeAlias

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import ButtonKind, style_button

Translator: TypeAlias = Callable[..., str]


def _text(tr: Translator, key: str, **kwargs: object) -> str:
    return str(tr(key, **kwargs))


class BaseDialog(QDialog):
    """Dialog shell keeping its button row outside expanding content."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        width: int = 680,
        height: int = 520,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(width, height)
        self.setMinimumSize(min(width, 520), min(height, 360))
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(18, 18, 18, 16)
        self.root_layout.setSpacing(12)
        self.content_layout = QVBoxLayout()
        self.content_layout.setSpacing(10)
        self.root_layout.addLayout(self.content_layout, 1)
        self.action_layout = QHBoxLayout()
        self.action_layout.setSpacing(8)
        self.action_layout.addStretch(1)
        self.root_layout.addLayout(self.action_layout)

    def add_action(
        self,
        text: str,
        callback,
        *,
        primary: bool = False,
        kind: ButtonKind | None = None,
    ) -> QPushButton:
        button = QPushButton(text, self)
        style_button(button, kind or ("primary" if primary else "ghost"))
        button.clicked.connect(callback)
        self.action_layout.addWidget(button)
        return button


class MessageDialog(BaseDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        tr: Translator,
        title: str,
        message: str,
        long_text: bool = False,
    ) -> None:
        super().__init__(parent, title=title)
        body = QPlainTextEdit(self)
        body.setPlainText(message)
        body.setReadOnly(True)
        if not long_text:
            body.setMaximumHeight(260)
        self.content_layout.addWidget(body)
        self.add_action(_text(tr, "common.confirm"), self.accept, primary=True)


class ConfirmDialog(BaseDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        tr: Translator,
        title: str,
        message: str,
        confirm_text: str | None = None,
        cancel_text: str | None = None,
    ) -> None:
        super().__init__(parent, title=title)
        body = QPlainTextEdit(self)
        body.setPlainText(message)
        body.setReadOnly(True)
        self.content_layout.addWidget(body)
        self.add_action(cancel_text or _text(tr, "common.cancel"), self.reject)
        self.add_action(confirm_text or _text(tr, "common.confirm"), self.accept, primary=True)


class TextInputDialog(BaseDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        tr: Translator,
        title: str,
        prompt: str,
        initial: str = "",
        multiline: bool = False,
        allow_empty: bool = True,
    ) -> None:
        super().__init__(parent, title=title)
        label = QLabel(prompt, self)
        label.setWordWrap(True)
        self.content_layout.addWidget(label)
        self.editor: QLineEdit | QPlainTextEdit
        if multiline:
            editor = QPlainTextEdit(self)
            editor.setPlainText(initial)
            self.editor = editor
        else:
            editor = QLineEdit(initial, self)
            self.editor = editor
        self.content_layout.addWidget(editor, 1)
        self.ok_button = self.add_action(
            _text(tr, "common.confirm"), self._accept_if_valid, primary=True
        )
        self.add_action(_text(tr, "common.cancel"), self.reject)
        self._allow_empty = allow_empty
        if not allow_empty:
            editor.textChanged.connect(self._update_validity)
            self._update_validity()

    def value(self) -> str:
        if isinstance(self.editor, QPlainTextEdit):
            return self.editor.toPlainText().strip()
        return self.editor.text().strip()

    def _update_validity(self) -> None:
        self.ok_button.setEnabled(self._allow_empty or bool(self.value()))

    def _accept_if_valid(self) -> None:
        if self._allow_empty or self.value():
            self.accept()


class ButtonOptionDialog(BaseDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        tr: Translator,
        title: str,
        prompt: str,
        options: Sequence[str],
    ) -> None:
        super().__init__(parent, title=title)
        self.selected_index: int | None = None
        prompt_label = QLabel(prompt, self)
        prompt_label.setWordWrap(True)
        self.content_layout.addWidget(prompt_label)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        options_widget = QWidget(scroll)
        options_layout = QVBoxLayout(options_widget)
        for index, option in enumerate(options):
            button = QPushButton(option, options_widget)
            style_button(button, "primary")
            button.clicked.connect(
                lambda _checked=False, selected=index: self._accept_index(selected)
            )
            options_layout.addWidget(button)
        options_layout.addStretch(1)
        scroll.setWidget(options_widget)
        self.content_layout.addWidget(scroll, 1)
        self.add_action(_text(tr, "common.cancel"), self.reject)

    def _accept_index(self, index: int) -> None:
        self.selected_index = index
        self.accept()


def show_message(
    parent: QWidget | None, tr: Translator, title: str, message: str
) -> None:
    MessageDialog(parent, tr=tr, title=title, message=message).exec()


def show_long_text(
    parent: QWidget | None, tr: Translator, title: str, text: str
) -> None:
    MessageDialog(parent, tr=tr, title=title, message=text, long_text=True).exec()


def ask_confirmation(
    parent: QWidget | None,
    tr: Translator,
    title: str,
    message: str,
    *,
    confirm_text: str | None = None,
    cancel_text: str | None = None,
) -> bool:
    dialog = ConfirmDialog(
        parent,
        tr=tr,
        title=title,
        message=message,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


def ask_text(
    parent: QWidget | None,
    tr: Translator,
    title: str,
    prompt: str,
    *,
    initial: str = "",
    multiline: bool = False,
    allow_empty: bool = True,
) -> str | None:
    dialog = TextInputDialog(
        parent,
        tr=tr,
        title=title,
        prompt=prompt,
        initial=initial,
        multiline=multiline,
        allow_empty=allow_empty,
    )
    return dialog.value() if dialog.exec() == QDialog.DialogCode.Accepted else None


def choose_button_option(
    parent: QWidget | None,
    tr: Translator,
    title: str,
    prompt: str,
    options: Sequence[str],
) -> int | None:
    dialog = ButtonOptionDialog(parent, tr=tr, title=title, prompt=prompt, options=options)
    dialog.exec()
    return dialog.selected_index
