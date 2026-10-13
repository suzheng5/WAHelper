"""TG 核心的延迟导入边界。

调用方必须先设置 TG_HELPER_DATA_ROOT，再构造 :class:`TgRuntime`。
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from types import ModuleType


class DataRootNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class TgModules:
    config: ModuleType
    coordinator: ModuleType
    auth: ModuleType
    listener: ModuleType
    scheduler: ModuleType
    images: ModuleType
    txt_import: ModuleType
    folder: ModuleType
    logger: ModuleType


def load_tg_modules() -> TgModules:
    """校验数据根后才导入任何会触及 TG config 的模块。"""
    if not os.environ.get("TG_HELPER_DATA_ROOT", "").strip():
        raise DataRootNotConfigured(
            "调用方必须在导入 TG config 前设置 TG_HELPER_DATA_ROOT"
        )
    # schedule_folder 位于 WA 包顶层；tg_multi_listener 位于仓库根
    from pathlib import Path
    import sys

    wa_root = Path(__file__).resolve().parents[3]
    repo_root = wa_root.parent
    for root in (str(wa_root), str(repo_root)):
        if root not in sys.path:
            sys.path.insert(0, root)
    names = {
        "config": "tg_multi_listener.config",
        "coordinator": "tg_multi_listener.telethon_coordinator",
        "auth": "tg_multi_listener.telethon_auth",
        "listener": "tg_multi_listener.listener",
        "scheduler": "tg_multi_listener.scheduler",
        "images": "tg_multi_listener.one_click_image",
        "txt_import": "tg_multi_listener.schedule_txt_import",
        "folder": "schedule_folder",
        "logger": "tg_multi_listener.logger_util",
    }
    loaded = {key: importlib.import_module(name) for key, name in names.items()}
    return TgModules(**loaded)
