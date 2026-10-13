"""打包启动：强制 neonize 使用 _internal 磁盘上的补丁模块（避免 PYZ 内旧版 download 写 DLL）。"""
from __future__ import annotations

import importlib.util
import os
import sys

_NEONIZE_PATCHED = (
    "neonize.download",
    "neonize._binder",
)


def _patch_neonize_imports() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", "")
    if not base:
        return
    neonize_dir = os.path.join(base, "neonize")
    if not os.path.isdir(neonize_dir):
        return

    class _Finder:
        def find_spec(self, fullname, path, target=None):
            if fullname not in _NEONIZE_PATCHED:
                return None
            rel = fullname.split(".", 1)[1].replace(".", os.sep)
            candidate = os.path.join(neonize_dir, rel + ".py")
            if os.path.isfile(candidate):
                return importlib.util.spec_from_file_location(fullname, candidate)
            return None

    sys.meta_path.insert(0, _Finder())


_patch_neonize_imports()
