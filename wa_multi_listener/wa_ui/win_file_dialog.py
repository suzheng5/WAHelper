"""Windows 原生文件与文件夹对话框公共入口。"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence, Tuple

_last_error_code = 0


def last_dialog_error() -> int:
    """最近一次原生对话框错误码；0 表示成功或用户取消。"""
    return int(_last_error_code)


def _build_filter_text(
    filetypes: Optional[Sequence[Tuple[str, str]]],
) -> str:
    """保留给纯逻辑测试：Tk 筛选格式转 Windows 筛选格式。"""
    pairs = list(filetypes or [("All files", "*.*")])
    parts: list[str] = []
    for label, pattern in pairs:
        parts.append(str(label or "Files"))
        parts.append((pattern or "*.*").replace(" ", ";"))
    return "\0".join(parts) + "\0\0"


def _paths_from_chunks(chunks: Sequence[str]) -> List[str]:
    """保留给旧格式兼容测试。"""
    clean = [str(part) for part in chunks if part]
    if not clean:
        return []
    if len(clean) == 1:
        return [os.path.abspath(clean[0])]
    directory = clean[0]
    return [
        os.path.abspath(os.path.join(directory, name))
        for name in clean[1:]
    ]


def _hwnd_from_widget(widget: object) -> int:
    """从 Tk/CTk 控件取得 Windows 根所有者 HWND。"""
    if widget is None:
        return 0
    try:
        wid = int(widget.winfo_id())  # type: ignore[attr-defined]
    except Exception:
        return 0
    if sys.platform != "win32":
        return wid
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        hwnd = int(user32.GetAncestor(int(wid), 3) or 0)  # GA_ROOTOWNER
        return hwnd or int(wid)
    except Exception:
        return wid


def _pick_items(
    *,
    title: str,
    initialdir: str,
    filetypes: Optional[Sequence[Tuple[str, str]]],
    parent: object,
    multi: bool,
    folders: bool,
) -> List[str]:
    global _last_error_code
    _last_error_code = 0
    if sys.platform != "win32":
        return []
    from wa_ui.win_item_dialog import pick_items

    paths, error_code = pick_items(
        title=title,
        initialdir=initialdir,
        filetypes=filetypes,
        owner_hwnd=_hwnd_from_widget(parent),
        multi=multi,
        folders=folders,
    )
    _last_error_code = int(error_code)
    return paths


def win_ask_open_filenames(
    *,
    title: str = "",
    initialdir: str = "",
    filetypes: Optional[Sequence[Tuple[str, str]]] = None,
    parent: object = None,
    multi: bool = True,
) -> List[str]:
    return _pick_items(
        title=title,
        initialdir=initialdir,
        filetypes=filetypes,
        parent=parent,
        multi=multi,
        folders=False,
    )


def win_ask_open_filename(
    *,
    title: str = "",
    initialdir: str = "",
    filetypes: Optional[Sequence[Tuple[str, str]]] = None,
    parent: object = None,
) -> str:
    files = win_ask_open_filenames(
        title=title,
        initialdir=initialdir,
        filetypes=filetypes,
        parent=parent,
        multi=False,
    )
    return files[0] if files else ""


def win_ask_directory(
    *,
    title: str = "",
    initialdir: str = "",
    parent: object = None,
) -> str:
    files = _pick_items(
        title=title,
        initialdir=initialdir,
        filetypes=None,
        parent=parent,
        multi=False,
        folders=True,
    )
    return files[0] if files else ""
