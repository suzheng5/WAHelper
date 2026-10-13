"""打包版 neonize：禁止向 _internal 下载/覆盖 DLL（会触发 Permission denied）。"""
from __future__ import annotations

import os
import sys


def apply_neonize_frozen_fix() -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        import neonize.download as nd
        import neonize._binder as nb
        from neonize.utils.platform import generated_name
    except Exception:
        return

    dll_path = os.path.join(os.path.dirname(nd.__file__), generated_name())

    def _safe_download() -> None:
        if os.path.isfile(dll_path):
            return
        nd.__download(  # type: ignore[attr-defined]
            f"{nd.__GIT_RELEASE_URL__}/releases/download/{nd.__GONEONIZE_VERSION__}/{generated_name()}",
            dll_path,
        )

    nd.download = _safe_download  # type: ignore[assignment]

    _orig_load = nb.load_goneonize

    def _load_goneonize():
        if os.path.isfile(dll_path):
            import ctypes

            gocode = ctypes.CDLL(dll_path)
            gocode.GetVersion.restype = ctypes.c_char_p
            return gocode
        return _orig_load()

    nb.load_goneonize = _load_goneonize  # type: ignore[assignment]
