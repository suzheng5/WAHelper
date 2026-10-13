"""检测系统界面语言。"""
from __future__ import annotations

import locale
import sys


def detect_system_language() -> str:
    """返回 zh 或 en。"""
    try:
        if sys.platform == "win32":
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
            primary = lang_id & 0x3FF
            if primary == 0x04:  # zh
                return "zh"
            return "en"
    except Exception:
        pass
    try:
        loc, _ = locale.getdefaultlocale()
        if loc and str(loc).lower().startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"
