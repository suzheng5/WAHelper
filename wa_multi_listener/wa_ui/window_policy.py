"""统一窗口置前与关闭策略。"""
from __future__ import annotations

from typing import Any, Optional


def widget_exists(widget: Any) -> bool:
    try:
        return bool(widget is not None and widget.winfo_exists())
    except Exception:
        return False


def toplevel_of(widget: Any) -> Any:
    try:
        return widget.winfo_toplevel()
    except Exception:
        return widget


def clear_topmost(widget: Any) -> None:
    if not widget_exists(widget):
        return
    try:
        widget.attributes("-topmost", False)
    except Exception:
        pass


def present_once(
    window: Any,
    *,
    parent: Optional[Any] = None,
    bell: bool = False,
    clear_after_ms: int = 350,
    focus: bool = False,
) -> None:
    """
    新窗口只置前一次，随后取消 topmost。

    不设置 grab，不长期抢焦点，多个消息/阶段提醒可同时操作。
    """
    if not widget_exists(window):
        return
    owner = toplevel_of(parent) if parent is not None else None
    if owner is not None and owner is not window and widget_exists(owner):
        try:
            window.transient(owner)
        except Exception:
            pass
    for action in (
        lambda: window.deiconify(),
        lambda: window.attributes("-topmost", True),
        lambda: window.lift(),
    ):
        try:
            action()
        except Exception:
            pass
    if focus:
        try:
            window.focus_set()
        except Exception:
            pass
    if bell:
        try:
            window.bell()
        except Exception:
            pass
    try:
        window.after(
            max(1, int(clear_after_ms)),
            lambda current=window: clear_topmost(current),
        )
    except Exception:
        clear_topmost(window)


def release_grab(widget: Any) -> None:
    if not widget_exists(widget):
        return
    try:
        widget.grab_release()
    except Exception:
        pass


def close_window(widget: Any) -> None:
    """幂等关闭窗口，不改变其它窗口的 grab/topmost。"""
    if not widget_exists(widget):
        return
    clear_topmost(widget)
    release_grab(widget)
    try:
        widget.destroy()
    except Exception:
        pass
