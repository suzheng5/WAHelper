"""PySide6 Telegram 平台面板。

调用方必须先设置 ``TG_HELPER_DATA_ROOT``，再构造 ``TgPresenter``/``TgPanel``。
仅导入本包不会加载 ``tg_multi_listener.config``。
"""
from .panel import TgPanel
from .presenter import TgPresenter
from .runtime import DataRootNotConfigured, TgModules, load_tg_modules

__all__ = [
    "DataRootNotConfigured",
    "TgModules",
    "TgPanel",
    "TgPresenter",
    "load_tg_modules",
]
