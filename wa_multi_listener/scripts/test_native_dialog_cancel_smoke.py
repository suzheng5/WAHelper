"""Windows 原生文件/文件夹对话框取消路径冒烟。"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wa_ui.win_file_dialog import (
    last_dialog_error,
    win_ask_directory,
    win_ask_open_filename,
    win_ask_open_filenames,
)


def _close_window_by_title(title: str) -> None:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    for _ in range(100):
        found = False

        @callback_type
        def visit(hwnd, _param):
            nonlocal found
            size = user32.GetWindowTextLengthW(hwnd)
            if size <= 0:
                return True
            buf = ctypes.create_unicode_buffer(size + 1)
            user32.GetWindowTextW(hwnd, buf, len(buf))
            if buf.value == title:
                found = True
                cancel_button = user32.GetDlgItem(hwnd, 2)  # IDCANCEL
                if cancel_button:
                    user32.SendMessageW(cancel_button, 0x00F5, 0, 0)  # BM_CLICK
                else:
                    user32.SendMessageW(hwnd, 0x0111, 2, 0)
                return False
            return True

        user32.EnumWindows(visit, 0)
        if found:
            return
        time.sleep(0.05)
    raise RuntimeError(f"未找到测试对话框: {title}")


def _cancel_later(title: str) -> threading.Thread:
    thread = threading.Thread(
        target=_close_window_by_title,
        args=(title,),
        daemon=True,
    )
    thread.start()
    return thread


def main() -> None:
    if sys.platform != "win32":
        print("SKIP: Windows only")
        return
    root = tk.Tk()
    root.withdraw()
    try:
        file_title = "WAHelper native file dialog smoke"
        closer = _cancel_later(file_title)
        path = win_ask_open_filename(
            title=file_title,
            filetypes=[("Text", "*.txt")],
            parent=root,
        )
        closer.join(timeout=1)
        assert path == ""
        assert last_dialog_error() == 0

        image_title = "WAHelper native multi image dialog smoke"
        closer = _cancel_later(image_title)
        paths = win_ask_open_filenames(
            title=image_title,
            filetypes=[("Images", "*.jpg *.jpeg *.png")],
            parent=root,
            multi=True,
        )
        closer.join(timeout=1)
        assert paths == []
        assert last_dialog_error() == 0

        folder_title = "WAHelper native folder dialog smoke"
        closer = _cancel_later(folder_title)
        path = win_ask_directory(title=folder_title, parent=root)
        closer.join(timeout=1)
        assert path == ""
        assert last_dialog_error() == 0
    finally:
        root.destroy()
    print("ALL PASS")


if __name__ == "__main__":
    main()
