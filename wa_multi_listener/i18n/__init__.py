"""界面国际化：启动时加载语言，运行期不切换。"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from i18n.ui_locale_store import UiLanguage, load_ui_language, save_ui_language

_LANG: UiLanguage = "zh"
_TABLE: Dict[str, str] = {}
_LOADED = False


def _locales_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")


def _load_table(lang: UiLanguage) -> Dict[str, str]:
    path = os.path.join(_locales_dir(), f"{lang}.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def init_i18n(lang: Optional[UiLanguage] = None) -> UiLanguage:
    """应用入口调用一次；未指定则从 ui_locale.json / 系统语言加载。"""
    global _LANG, _TABLE, _LOADED
    if lang is None:
        lang = load_ui_language()
    else:
        save_ui_language(lang)
    _LANG = lang
    _TABLE = _load_table(lang)
    _LOADED = True
    return _LANG


def get_lang() -> UiLanguage:
    return _LANG


def set_lang_for_next_launch(lang: UiLanguage) -> None:
    """写入配置，下次启动生效。"""
    save_ui_language(lang)


def t(key: str, **kwargs: Any) -> str:
    if not _LOADED:
        init_i18n()
    text = _TABLE.get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def translate_or_passthrough(key: str, fallback_zh: str, **kwargs: Any) -> str:
    """词典无条目时中文模式用 fallback。"""
    if not _LOADED:
        init_i18n()
    if key in _TABLE:
        return t(key, **kwargs)
    if _LANG == "zh":
        try:
            return fallback_zh.format(**kwargs)
        except (KeyError, ValueError):
            return fallback_zh
    return t(key, **kwargs)
