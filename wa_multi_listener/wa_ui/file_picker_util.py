"""文件选择对话框辅助。"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog
from typing import Any, List, Optional, Sequence, Tuple

from i18n import t
from logger_util import warning
from wa_ui.window_policy import (
    clear_topmost,
    close_window,
    present_once,
    release_grab,
)

# 记住上次选图目录，避免每次从奇怪位置开始且切目录异常
_last_image_dir: Optional[str] = None

# Windows/Tk：同一组扩展名用空格分隔，勿用分号（分号会导致筛选异常、目录难切）
IMAGE_FILETYPES: Sequence[Tuple[str, str]] = (
    ("Images", "*.jpg *.jpeg *.png *.webp *.gif *.bmp"),
    ("JPEG", "*.jpg *.jpeg"),
    ("PNG", "*.png"),
    ("All files", "*.*"),
)

_BG = "#0f1115"
_CARD = "#1a1d24"
_TEXT = "#e6eaf2"
_ACCENT = "#3b82f6"
_MUTED = "#555a66"


def dialog_toplevel(widget: Any) -> Any:
    """filedialog / messagebox 的 parent 必须是顶层窗口，不能用 CTkFrame。"""
    try:
        return widget.winfo_toplevel()
    except Exception:
        return widget


def release_modal_grabs(widget: Any) -> None:
    """
    释放当前活动 grab 与主窗 topmost，不改动其它独立弹窗。
    避免系统文件框空白，同时不让消息/阶段提醒互相影响。
    """
    root = dialog_toplevel(widget)
    try:
        current = root.grab_current()
    except Exception:
        current = None
    if current is not None:
        release_grab(current)
    release_grab(root)
    clear_topmost(root)
    try:
        root.update_idletasks()
    except Exception:
        pass


def prepare_native_dialog(widget: Any) -> Any:
    """打开系统对话框前：释放 grab、取消 topmost。"""
    root = dialog_toplevel(widget)
    release_modal_grabs(root)
    try:
        root.update_idletasks()
    except Exception:
        pass
    return root


def _default_pictures_dir() -> str:
    home = os.path.expanduser("~")
    for name in ("Pictures", "图片", "My Pictures"):
        p = os.path.join(home, name)
        if os.path.isdir(p):
            return p
    return home if os.path.isdir(home) else ""


def txt_open_initial_dir(current_path: str = "") -> Optional[str]:
    """定时任务选 TXT：优先打开输入框里上次所选文件的目录；无则返回 None。"""
    cur = (current_path or "").strip()
    if not cur:
        return None
    d = os.path.dirname(os.path.abspath(cur))
    if os.path.isdir(d):
        return d
    if os.path.isdir(cur):
        return os.path.abspath(cur)
    return None


def pick_single_file(
    parent: Any,
    *,
    title: str,
    initialdir: Optional[str] = None,
    filetypes: Sequence[Tuple[str, str]],
) -> str:
    """统一选择单个文件；Windows 原生失败时才回退 Tk。"""
    root = prepare_native_dialog(parent)
    start = (initialdir or "").strip()
    used_native = False
    path = ""
    if sys.platform == "win32":
        try:
            from wa_ui.win_file_dialog import (
                last_dialog_error,
                win_ask_open_filename,
            )

            path = win_ask_open_filename(
                title=title,
                initialdir=start,
                filetypes=filetypes,
                parent=root,
            )
            error_code = last_dialog_error()
            used_native = True
            if error_code:
                warning(f"Windows 文件对话框失败: 0x{error_code:08X}")
        except Exception as exc:
            warning(f"Windows 文件对话框异常，回退 Tk: {exc}")
    if not used_native:
        kwargs: dict = {
            "parent": root,
            "title": title,
            "filetypes": list(filetypes),
        }
        if start and os.path.isdir(start):
            kwargs["initialdir"] = start
        try:
            path = filedialog.askopenfilename(**kwargs) or ""
        except Exception:
            path = ""
    release_modal_grabs(root)
    return os.path.abspath(path) if path else ""


def pick_directory(
    parent: Any,
    *,
    title: str,
    initialdir: Optional[str] = None,
) -> str:
    """统一选择文件夹；Windows 原生失败时才回退 Tk。"""
    root = prepare_native_dialog(parent)
    start = (initialdir or "").strip()
    used_native = False
    path = ""
    if sys.platform == "win32":
        try:
            from wa_ui.win_file_dialog import (
                last_dialog_error,
                win_ask_directory,
            )

            path = win_ask_directory(
                title=title,
                initialdir=start,
                parent=root,
            )
            error_code = last_dialog_error()
            used_native = True
            if error_code:
                warning(f"Windows 文件夹对话框失败: 0x{error_code:08X}")
        except Exception as exc:
            warning(f"Windows 文件夹对话框异常，回退 Tk: {exc}")
    if not used_native:
        kwargs: dict = {"parent": root, "title": title}
        if start and os.path.isdir(start):
            kwargs["initialdir"] = start
        try:
            path = filedialog.askdirectory(**kwargs) or ""
        except Exception:
            path = ""
    release_modal_grabs(root)
    return os.path.abspath(path) if path else ""


def pick_image_files(
    parent: Any,
    *,
    title: str = "",
    initialdir: Optional[str] = None,
) -> List[str]:
    """
    多选图片。模态关闭后务必延时再调用。
    Windows 优先走原生 GetOpenFileName（绕过 CTk 下 Tk filedialog 不弹/空白）。
    返回绝对路径列表；取消则为空列表。
    """
    global _last_image_dir
    root = prepare_native_dialog(parent)
    start = (initialdir or "").strip() or (_last_image_dir or "") or _default_pictures_dir()
    if start and not os.path.isdir(start):
        start = _default_pictures_dir()

    dlg_title = title or t("img.pick_files")
    selected: List[str] = []
    used_native = False

    if sys.platform == "win32":
        try:
            from wa_ui.win_file_dialog import (
                last_dialog_error,
                win_ask_open_filenames,
            )

            selected = win_ask_open_filenames(
                title=dlg_title,
                initialdir=start,
                filetypes=list(IMAGE_FILETYPES),
                parent=root,
            )
            error_code = last_dialog_error()
            used_native = True
            if error_code:
                warning(f"Windows 选图对话框失败: 0x{error_code:08X}")
        except Exception as exc:
            warning(f"Windows 选图对话框异常，回退 Tk: {exc}")
            selected = []
            used_native = False

    if not used_native:
        kwargs: dict = {
            "parent": root,
            "title": dlg_title,
            "filetypes": list(IMAGE_FILETYPES),
        }
        if start:
            kwargs["initialdir"] = start
        try:
            paths = filedialog.askopenfilenames(**kwargs)
            selected = [os.path.abspath(p) for p in (paths or ()) if (p or "").strip()]
        except Exception:
            selected = []
    if selected:
        d = os.path.dirname(selected[0])
        if os.path.isdir(d):
            _last_image_dir = d
    release_modal_grabs(root)
    return selected


def _tk_btn(parent: tk.Misc, text: str, bg: str, command: Any, width: int = 16) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg="#ffffff",
        activebackground=bg,
        activeforeground="#ffffff",
        relief="flat",
        padx=12,
        pady=8,
        width=width,
        cursor="hand2",
        font=("Microsoft YaHei UI", 10),
    )


def _safe_destroy(dlg: Any) -> None:
    close_window(dlg)


def pick_txt_or_folder(parent, *, current_path: str = "") -> Optional[str]:
    """弹出选择：TXT 文件或文件夹。返回绝对路径，取消则 None。"""
    result: list[str] = []
    app_root = dialog_toplevel(parent)
    release_modal_grabs(app_root)
    initialdir = txt_open_initial_dir(current_path)

    dlg = tk.Toplevel(app_root)
    dlg.title(t("picker.title"))
    dlg.configure(bg=_BG)
    dlg.resizable(False, False)
    try:
        dlg.update_idletasks()
        dlg.geometry(f"480x220+{(dlg.winfo_screenwidth() - 480) // 2}+{(dlg.winfo_screenheight() - 220) // 2}")
    except Exception:
        dlg.geometry("480x220")

    outer = tk.Frame(dlg, bg=_CARD)
    outer.pack(fill="both", expand=True, padx=14, pady=14)
    tk.Label(
        outer,
        text=t("picker.prompt"),
        bg=_CARD,
        fg=_TEXT,
        font=("Microsoft YaHei UI", 11),
    ).pack(padx=12, pady=(12, 16))

    btn_row = tk.Frame(outer, bg=_CARD)
    btn_row.pack(pady=(0, 8))

    def _close() -> None:
        _safe_destroy(dlg)

    def _pick_file() -> None:
        release_modal_grabs(app_root)
        clear_topmost(dlg)
        release_grab(dlg)
        try:
            dlg.withdraw()
        except Exception:
            pass
        path = pick_single_file(
            app_root,
            title=t("picker.txt_dialog"),
            initialdir=initialdir,
            filetypes=[
                (t("picker.txt_filter"), "*.txt"),
                (t("picker.all_files"), "*.*"),
            ],
        )
        if path:
            result.append(os.path.abspath(path))
        _safe_destroy(dlg)
    def _pick_dir() -> None:
        release_modal_grabs(app_root)
        clear_topmost(dlg)
        release_grab(dlg)
        try:
            dlg.withdraw()
        except Exception:
            pass
        path = pick_directory(
            app_root,
            title=t("picker.folder_dialog"),
            initialdir=initialdir,
        )
        if path:
            result.append(os.path.abspath(path))
        _safe_destroy(dlg)

    _tk_btn(btn_row, t("picker.txt_file"), _ACCENT, _pick_file).pack(side="left", padx=(0, 8))
    _tk_btn(btn_row, t("picker.folder"), _ACCENT, _pick_dir).pack(side="left")
    _tk_btn(outer, t("common.cancel"), _MUTED, _close, width=12).pack(pady=(8, 12))

    dlg.protocol("WM_DELETE_WINDOW", _close)
    try:
        present_once(dlg, parent=app_root, focus=True)
        dlg.wait_window()
    finally:
        release_modal_grabs(parent)
    return result[0] if result else None
