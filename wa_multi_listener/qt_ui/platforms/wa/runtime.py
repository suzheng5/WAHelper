"""WA 旧业务模块的延迟导入边界。"""
from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class WaModules:
    config: ModuleType
    coordinator: ModuleType
    auth: ModuleType
    listener: ModuleType
    scheduler: ModuleType
    images: ModuleType
    txt_import: ModuleType
    folder: ModuleType
    schedule_account: ModuleType
    proxy: ModuleType
    logger: ModuleType
    stats: ModuleType


def ensure_legacy_import_root() -> Path:
    """旧模块使用 ``from config import ...``，故 WA 根目录须位于 sys.path。"""
    root = Path(__file__).resolve().parents[3]
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def load_wa_modules() -> WaModules:
    ensure_legacy_import_root()
    names = {
        "config": "config",
        "coordinator": "wa_coordinator",
        "auth": "wa_auth",
        "listener": "listener",
        "scheduler": "schedule2_runner",
        "images": "one_click_image",
        "txt_import": "schedule_txt_import",
        "folder": "schedule_folder",
        "schedule_account": "schedule_account",
        "proxy": "wa_proxy",
        "logger": "logger_util",
        "stats": "stats",
    }
    return WaModules(**{key: importlib.import_module(name) for key, name in names.items()})


def default_translator():
    ensure_legacy_import_root()
    return importlib.import_module("i18n").t
