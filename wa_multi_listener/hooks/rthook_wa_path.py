# PyInstaller runtime hook: ensure exe directory is importable for side-by-side modules.
from __future__ import annotations

import os
import sys


def _ensure_app_dir_on_path() -> None:
    if not getattr(sys, "frozen", False):
        return
    root = os.path.dirname(os.path.abspath(sys.executable))
    if root and root not in sys.path:
        sys.path.insert(0, root)


_ensure_app_dir_on_path()
