"""模态弹窗：统一原生 tk 壳，底部按钮固定可见（不被正文挤出窗口）。"""
from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import Any, Callable, List, Optional, Sequence, Tuple

import customtkinter as ctk

from i18n import t
from wa_ui.file_picker_util import dialog_toplevel, release_modal_grabs
from wa_ui.theme import COLORS
from wa_ui.window_policy import (
    clear_topmost,
    close_window,
    present_once,
)

_BG = "#0f1115"
_CARD = "#1a1d24"
_TEXT = "#e6eaf2"
_MUTED = "#a0a6b0"
_BORDER = "#3a3f4b"
_ACCENT = "#3b82f6"
_MUTED_BTN = "#555a66"

# 统一默认尺寸（一键发图 / 开始 / 下一天 / 删除等共用）
DIALOG_WIDTH = 680
DIALOG_HEIGHT = 560
DIALOG_MIN_WIDTH = 620
DIALOG_MIN_HEIGHT = 480
BTN_BAR_HEIGHT = 70


def force_window_front(win: Any, *, keep_topmost: bool = False) -> None:
    """兼容旧调用：窗口只置前一次，不长期 topmost。"""
    present_once(win, focus=True)


def _clear_topmost(win: Any) -> None:
    clear_topmost(win)


def flash_root_front(widget: Any) -> Any:
    """打开系统对话框前准备主窗：只清 grab/topmost，绝不强制 topmost（会导致文件框空白）。"""
    from wa_ui.file_picker_util import prepare_native_dialog

    return prepare_native_dialog(widget)

def dialog_size_for_text(message: str) -> Tuple[int, int]:
    """按正文行数给出统一宽高。"""
    line_n = (message or "").count("\n") + 1
    if line_n > 14:
        return 740, 660
    if line_n > 6:
        return 700, 600
    return DIALOG_WIDTH, DIALOG_HEIGHT


def _center_on_screen(dlg: Any, width: int, height: int) -> None:
    try:
        dlg.update_idletasks()
        sw = int(dlg.winfo_screenwidth())
        sh = int(dlg.winfo_screenheight())
        usable_h = max(400, sh - 80)
        h = min(int(height), usable_h)
        w = min(int(width), max(480, sw - 40))
        x = max(0, (sw - w) // 2)
        y = max(20, (usable_h - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        try:
            dlg.geometry(f"{width}x{height}")
        except Exception:
            pass


def create_modal_toplevel(
    parent: Any,
    *,
    title: str,
    grab: bool = True,
) -> ctk.CTkToplevel:
    """创建 CTk 模态窗（兼容旧调用）。优先改用本模块原生 tk 弹窗。"""
    root = dialog_toplevel(parent)
    try:
        root.update_idletasks()
    except Exception:
        pass

    prev = bool(getattr(ctk.CTkToplevel, "_deactivate_windows_window_header_manipulation", False))
    ctk.CTkToplevel._deactivate_windows_window_header_manipulation = True
    try:
        dlg = ctk.CTkToplevel(root)
    finally:
        ctk.CTkToplevel._deactivate_windows_window_header_manipulation = prev

    dlg.title(title)
    try:
        dlg.configure(fg_color=COLORS.get("bg", dlg.cget("fg_color")))
    except Exception:
        pass
    dlg.resizable(False, False)
    dlg._modal_want_grab = bool(grab)  # noqa: SLF001
    try:
        dlg.after(1, lambda: force_window_front(dlg))
    except Exception:
        force_window_front(dlg)
    return dlg


def finalize_modal(dlg: Any) -> None:
    """内容布局完成后置前一次；不抓取其它窗口的输入。"""
    if dlg is None:
        return
    try:
        dlg.update_idletasks()
    except Exception:
        pass
    try:
        dlg.deiconify()
    except Exception:
        pass
    try:
        dlg.update()
    except Exception:
        pass
    force_window_front(dlg)


def close_modal(dlg: Any) -> None:
    """关闭当前模态窗，不改变其它弹窗状态。"""
    close_window(dlg)


def _tk_button(
    parent: tk.Misc,
    text: str,
    bg: str,
    command: Callable[[], None],
    *,
    width: int = 12,
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg="#ffffff",
        activebackground=bg,
        activeforeground="#ffffff",
        relief="flat",
        padx=16,
        pady=9,
        width=width,
        cursor="hand2",
        font=("Microsoft YaHei UI", 11),
    )


def _new_dialog_shell(
    parent: Any,
    title: str,
    *,
    width: int,
    height: int,
) -> Tuple[tk.Toplevel, tk.Frame, tk.Frame, tk.Frame]:
    """
    统一弹窗骨架：
    - 中部 content（可扩展滚动）
    - 底部 btn_bar 固定高度，永远可见
    返回 (dlg, outer, content, btn_bar)
    """
    root = dialog_toplevel(parent)
    w = max(DIALOG_MIN_WIDTH, int(width))
    h = max(DIALOG_MIN_HEIGHT, int(height))

    dlg = tk.Toplevel(root)
    dlg.title(title or "")
    dlg.configure(bg=_BG)
    dlg.resizable(True, True)
    dlg.minsize(DIALOG_MIN_WIDTH, DIALOG_MIN_HEIGHT)
    try:
        dlg.transient(root)
    except Exception:
        pass

    outer = tk.Frame(dlg, bg=_CARD, highlightbackground=_BORDER, highlightthickness=1)
    outer.pack(fill="both", expand=True, padx=12, pady=12)
    outer.grid_columnconfigure(0, weight=1)
    outer.grid_rowconfigure(0, weight=1)
    outer.grid_rowconfigure(1, weight=0)

    content = tk.Frame(outer, bg=_CARD)
    content.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 6))
    content.grid_columnconfigure(0, weight=1)

    btn_bar = tk.Frame(outer, bg=_CARD, height=BTN_BAR_HEIGHT)
    btn_bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
    btn_bar.grid_propagate(False)
    btn_bar.pack_propagate(False)

    _center_on_screen(dlg, w, h)
    return dlg, outer, content, btn_bar


def _place_btn_row(
    btn_bar: tk.Frame,
    specs: Sequence[Tuple[str, str, Callable[[], None]]],
) -> None:
    """
    在固定底栏右侧放置按钮。
    specs 从左到右；最后一项最靠右（一般为确认）。
    每项 (text, bg, command)。
    """
    inner = tk.Frame(btn_bar, bg=_CARD)
    inner.pack(side="right", padx=8, pady=12)
    for text, bg, command in reversed(list(specs)):
        width = 18 if len(text or "") > 6 else 12
        _tk_button(inner, text, bg, command, width=width).pack(side="right", padx=(10, 0))


def _show_tk_modal(dlg: tk.Toplevel, parent: Any) -> None:
    root = dialog_toplevel(parent)
    try:
        dlg.update_idletasks()
        try:
            geo = dlg.geometry().split("+")[0]
            wh = geo.split("x")
            if len(wh) == 2:
                _center_on_screen(dlg, int(wh[0]), int(wh[1]))
        except Exception:
            pass
        present_once(dlg, parent=root, focus=True)
        dlg.wait_window()
    finally:
        _clear_topmost(dlg)


def _add_scroll_text(parent: tk.Frame, message: str) -> scrolledtext.ScrolledText:
    body = scrolledtext.ScrolledText(
        parent,
        wrap="word",
        bg=_BG,
        fg=_TEXT,
        insertbackground=_TEXT,
        relief="flat",
        borderwidth=0,
        font=("Microsoft YaHei UI", 11),
        height=12,
    )
    body.grid(row=0, column=0, sticky="nsew")
    body.insert("1.0", message or "")
    body.configure(state="disabled")
    return body


def show_message(
    parent: Any,
    title: str,
    message: str,
    *,
    width: int = DIALOG_WIDTH,
    height: int = DIALOG_HEIGHT,
) -> None:
    """统一提示框。"""
    w, h = width, height
    if width == DIALOG_WIDTH and height == DIALOG_HEIGHT:
        w, h = dialog_size_for_text(message)
    dlg, _outer, content, btn_bar = _new_dialog_shell(parent, title, width=w, height=h)
    content.grid_rowconfigure(0, weight=1)
    _add_scroll_text(content, message)

    def _ok() -> None:
        close_modal(dlg)

    _place_btn_row(btn_bar, [(t("common.confirm"), _ACCENT, _ok)])
    dlg.protocol("WM_DELETE_WINDOW", _ok)
    _show_tk_modal(dlg, parent)


def ask_yes_no(
    parent: Any,
    title: str,
    message: str,
    *,
    yes_text: str = "",
    no_text: str = "",
    width: int = DIALOG_WIDTH,
    height: int = DIALOG_HEIGHT,
) -> bool:
    """统一确认框：正文可滚，确认/取消固定底栏。"""
    result = {"ok": False}
    w, h = width, height
    if width == DIALOG_WIDTH and height == DIALOG_HEIGHT:
        w, h = dialog_size_for_text(message)
    dlg, _outer, content, btn_bar = _new_dialog_shell(parent, title, width=w, height=h)
    content.grid_rowconfigure(0, weight=1)
    _add_scroll_text(content, message)

    def _yes() -> None:
        result["ok"] = True
        close_modal(dlg)

    def _no() -> None:
        result["ok"] = False
        close_modal(dlg)

    _place_btn_row(
        btn_bar,
        [
            (no_text or t("common.cancel"), _MUTED_BTN, _no),
            (yes_text or t("common.confirm"), _ACCENT, _yes),
        ],
    )
    dlg.protocol("WM_DELETE_WINDOW", _no)
    _show_tk_modal(dlg, parent)
    return bool(result["ok"])


def run_after_modal_closed(
    widget: Any,
    delay_ms: int,
    callback: Callable[[], None],
) -> None:
    """模态关闭后延时执行：先清 grab/topmost，再回调（选文件前建议 ≥250ms）。"""

    def _run() -> None:
        release_modal_grabs(widget)
        try:
            callback()
        finally:
            release_modal_grabs(widget)

    try:
        root = dialog_toplevel(widget)
        root.after(max(0, int(delay_ms)), _run)
    except Exception:
        _run()


def prompt_text_with_skip(
    parent: Any,
    title: str,
    hint: str,
    *,
    ok_text: str = "",
    skip_text: str = "",
    cancel_text: str = "",
    width: int = DIALOG_WIDTH,
    height: int = DIALOG_HEIGHT,
) -> Optional[str]:
    """
    多行文字输入（一键发图同步客户附加文字）。
    返回：None=取消；""=不附加文字继续；其它=输入内容。
    """
    result: dict[str, Optional[str]] = {"value": None}
    dlg, _outer, content, btn_bar = _new_dialog_shell(
        parent, title, width=max(DIALOG_WIDTH, int(width)), height=max(DIALOG_HEIGHT, int(height))
    )
    content.grid_rowconfigure(2, weight=1)

    tk.Label(
        content,
        text=title or "",
        bg=_CARD,
        fg=_TEXT,
        font=("Microsoft YaHei UI", 12, "bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", pady=(4, 6))
    tk.Label(
        content,
        text=hint or "",
        bg=_CARD,
        fg=_MUTED,
        font=("Microsoft YaHei UI", 10),
        wraplength=max(520, int(width) - 80),
        justify="left",
        anchor="w",
    ).grid(row=1, column=0, sticky="ew", pady=(0, 8))

    box = tk.Text(
        content,
        wrap="word",
        bg=_BG,
        fg=_TEXT,
        insertbackground=_TEXT,
        relief="flat",
        borderwidth=0,
        font=("Microsoft YaHei UI", 11),
        height=10,
    )
    box.grid(row=2, column=0, sticky="nsew")

    def _ok() -> None:
        result["value"] = (box.get("1.0", "end") or "").strip()
        close_modal(dlg)

    def _skip() -> None:
        result["value"] = ""
        close_modal(dlg)

    def _cancel() -> None:
        result["value"] = None
        close_modal(dlg)

    _place_btn_row(
        btn_bar,
        [
            (cancel_text or t("common.cancel"), _MUTED_BTN, _cancel),
            (skip_text or t("img.extra_skip"), _MUTED_BTN, _skip),
            (ok_text or t("img.extra_ok"), _ACCENT, _ok),
        ],
    )
    dlg.protocol("WM_DELETE_WINDOW", _cancel)
    _show_tk_modal(dlg, parent)
    return result["value"]


def pick_button_option(
    parent: Any,
    title: str,
    options: List[str],
    *,
    cancel_text: str = "",
    width: int = DIALOG_WIDTH,
    height: int = DIALOG_HEIGHT,
) -> Optional[int]:
    """列表按钮选择（一键发图选天）。返回选项下标，取消则 None。"""
    result: dict[str, Optional[int]] = {"idx": None}
    w = max(DIALOG_WIDTH, int(width))
    h = max(DIALOG_HEIGHT, int(height))
    dlg, _outer, content, btn_bar = _new_dialog_shell(parent, title, width=w, height=h)
    content.grid_rowconfigure(1, weight=1)

    tk.Label(
        content,
        text=title or "",
        bg=_CARD,
        fg=_TEXT,
        font=("Microsoft YaHei UI", 12, "bold"),
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", pady=(4, 8))

    list_wrap = tk.Frame(content, bg=_CARD)
    list_wrap.grid(row=1, column=0, sticky="nsew")
    list_wrap.grid_columnconfigure(0, weight=1)
    list_wrap.grid_rowconfigure(0, weight=1)

    canvas = tk.Canvas(list_wrap, bg=_BG, highlightthickness=0, borderwidth=0)
    scroll = tk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=_BG)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")

    def _on_canvas_configure(event: Any) -> None:
        try:
            canvas.itemconfigure(win_id, width=event.width)
        except Exception:
            pass

    canvas.bind("<Configure>", _on_canvas_configure)

    def _pick(i: int) -> None:
        result["idx"] = i
        close_modal(dlg)

    def _cancel() -> None:
        result["idx"] = None
        close_modal(dlg)

    for i, label in enumerate(options):
        tk.Button(
            inner,
            text=label,
            command=lambda idx=i: _pick(idx),
            bg=_ACCENT,
            fg="#ffffff",
            activebackground=_ACCENT,
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=10,
            anchor="w",
            cursor="hand2",
            font=("Microsoft YaHei UI", 11),
            wraplength=max(500, w - 100),
            justify="left",
        ).pack(fill="x", padx=8, pady=4)

    _place_btn_row(btn_bar, [(cancel_text or t("common.cancel"), _MUTED_BTN, _cancel)])
    dlg.protocol("WM_DELETE_WINDOW", _cancel)
    _show_tk_modal(dlg, parent)
    return result["idx"]
