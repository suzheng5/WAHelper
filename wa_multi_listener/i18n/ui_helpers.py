"""UI 辅助：messagebox、常用标签。"""
from __future__ import annotations

from typing import Any

from i18n import t


def msg_info(parent: Any, title_key: str, body_key: str, **kwargs: Any) -> None:
    from wa_ui.modal_util import dialog_size_for_text, show_message

    body = t(body_key, **kwargs)
    w, h = dialog_size_for_text(body)
    show_message(parent, t(title_key), body, width=w, height=h)


def msg_warning(parent: Any, title_key: str, body_key: str, **kwargs: Any) -> None:
    msg_info(parent, title_key, body_key, **kwargs)


def msg_error(parent: Any, title_key: str, body_key: str, **kwargs: Any) -> None:
    msg_info(parent, title_key, body_key, **kwargs)


def msg_askyesno(parent: Any, title_key: str, body_key: str, **kwargs: Any) -> bool:
    from wa_ui.modal_util import ask_yes_no, dialog_size_for_text

    body = t(body_key, **kwargs)
    w, h = dialog_size_for_text(body)
    return ask_yes_no(parent, t(title_key), body, width=w, height=h)


def lang_combo_labels() -> tuple[str, str]:
    return t("rules.lang_zh"), t("rules.lang_en")


def lang_from_combo_label(label: str) -> str:
    zh_lbl, en_lbl = lang_combo_labels()
    if label == en_lbl:
        return "en"
    return "zh"


def combo_label_for_lang(lang: str) -> str:
    zh_lbl, en_lbl = lang_combo_labels()
    return en_lbl if lang == "en" else zh_lbl
