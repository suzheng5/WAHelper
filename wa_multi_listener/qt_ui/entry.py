"""Qt 生产入口。"""
from __future__ import annotations

import sys

from .app import ensure_application, run_app
from .common.theme import apply_theme
from .composition import build_runtime_kwargs
from .license_dialog import ensure_activated_qt


def run_qt() -> int:
    from i18n import t
    from logger_util import error, info
    from neonize_frozen_fix import apply_neonize_frozen_fix
    from neonize_bootstrap import install_patched_neonize_dll_if_present
    from platform_paths import tg_data_root, wa_data_root

    apply_neonize_frozen_fix()

    app = ensure_application(sys.argv)
    apply_theme(app)
    if not ensure_activated_qt(t):
        return 0
    install_patched_neonize_dll_if_present()
    info(f"Qt 整合界面启动：WA={wa_data_root()}，TG={tg_data_root()}")

    kwargs = build_runtime_kwargs(t)
    kwargs["on_error"] = lambda exc: error(f"Qt 界面错误：{exc}")
    return run_app(**kwargs)
