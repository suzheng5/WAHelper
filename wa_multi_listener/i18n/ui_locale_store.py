"""界面语言配置（整合根目录 ui_locale.json）。"""
from __future__ import annotations

import json
import os
import threading
from typing import Literal

from platform_paths import combo_root

UiLanguage = Literal["zh", "en"]

_lock = threading.RLock()
_FILENAME = "ui_locale.json"
_KEY = "ui_language"


def _path() -> str:
    return os.path.join(combo_root(), _FILENAME)


def load_ui_language() -> UiLanguage:
    from i18n.system_locale import detect_system_language

    path = _path()
    with _lock:
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                lang = str(raw.get(_KEY, "")).strip().lower()
                if lang in ("zh", "en"):
                    return lang  # type: ignore[return-value]
            except (json.JSONDecodeError, OSError, TypeError):
                pass
        lang = detect_system_language()
        _write_unlocked(lang)
        return lang  # type: ignore[return-value]


def save_ui_language(lang: UiLanguage) -> None:
    with _lock:
        _write_unlocked(lang)


def _write_unlocked(lang: str) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path) or combo_root(), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({_KEY: lang}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
