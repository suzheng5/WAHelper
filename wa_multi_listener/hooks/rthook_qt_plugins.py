"""Ensure Qt plugins resolve under PyInstaller onedir."""
from __future__ import annotations

import os
import sys


def _configure_qt_plugins() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    candidates = [
        os.path.join(base, "PySide6", "plugins"),
        os.path.join(base, "qt6", "plugins"),
        os.path.join(base, "plugins"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            os.environ.setdefault("QT_PLUGIN_PATH", path)
            break


_configure_qt_plugins()
