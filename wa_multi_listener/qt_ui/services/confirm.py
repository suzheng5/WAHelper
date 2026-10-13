"""Confirmations that refuse destructive work without a UI parent."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from ..common.dialogs import ask_confirmation

Translator = Callable[..., str]


def confirm_or_abort(
    parent: QWidget | None,
    tr: Translator,
    title: str,
    message: str,
) -> bool:
    """无 parent 时拒绝执行，避免静默破坏数据。"""
    if parent is None:
        return False
    return ask_confirmation(parent, tr, title, message)
