"""Rules 页语言切换控件（下次启动生效）。"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QWidget

from i18n import get_lang, set_lang_for_next_launch
from i18n.ui_helpers import combo_label_for_lang, lang_combo_labels, lang_from_combo_label

Translator = Callable[..., str]


def add_language_controls(
    form: QFormLayout,
    *,
    tr: Translator,
    parent: QWidget,
    on_saved: Callable[[str], None] | None = None,
) -> QComboBox:
    combo = QComboBox(parent)
    labels = list(lang_combo_labels())
    combo.addItems(labels)
    combo.setCurrentText(combo_label_for_lang(get_lang()))
    hint = QLabel(tr("rules.lang_hint"), parent)
    hint.setWordWrap(True)
    hint.setProperty("muted", True)

    def _changed(_text: str = "") -> None:
        lang = lang_from_combo_label(combo.currentText())
        set_lang_for_next_launch(lang)  # type: ignore[arg-type]
        if on_saved is not None:
            on_saved(tr("rules.lang_saved", lang=tr(f"rules.lang_{lang}")))

    combo.currentTextChanged.connect(_changed)
    form.addRow(tr("rules.lang_label"), combo)
    form.addRow("", hint)
    return combo
