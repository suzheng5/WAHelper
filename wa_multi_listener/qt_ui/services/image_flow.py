"""一键发图 / 同步客户：复刻原 CTk 确认与选图流程。"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from ..bridges.ui_call import call_on_ui
from ..common.dialogs import ask_confirmation, ask_text, choose_button_option, show_message
from ..common.file_dialogs import pick_images


def _resolve_notes_fn(
    jobs: Sequence[Any],
    notes_fn: Callable[[Sequence[Any]], str] | None,
) -> Callable[[Sequence[Any]], str] | None:
    """优先用调用方注入的 notes_fn；否则按任务结构选 WA/TG 实现。

    禁止 ``wa_notes or tg_notes``：合并包里两者都能 import，会误用 WA 版读 TG 的
    ``job.rows`` 直接抛 AttributeError，表现为一键发图点击无反应。
    """
    if notes_fn is not None:
        return notes_fn
    sample = next(iter(jobs), None)
    if sample is None:
        return None
    if hasattr(sample, "rows"):
        try:
            from one_click_image import notes_for_awaiting_jobs as wa_notes

            return wa_notes
        except Exception:
            return None
    if hasattr(sample, "items"):
        try:
            from tg_multi_listener.one_click_image import (
                notes_for_awaiting_jobs as tg_notes,
            )

            return tg_notes
        except Exception:
            return None
    return None


def _day_label(
    tr: Callable[..., str],
    group: Any,
    *,
    notes_fn: Callable[[Sequence[Any]], str] | None = None,
) -> str:
    notes = ""
    note = ""
    note_fn = _resolve_notes_fn(list(group.jobs), notes_fn)
    if note_fn is not None:
        try:
            note = note_fn(list(group.jobs)) or ""
        except Exception:
            note = ""
    if note:
        notes = tr("img.day_notes", text=note)
    day = int(getattr(group, "day_1based", 0) or 0)
    count = len(group.jobs)
    if day > 0:
        return tr("img.day_group", day=day, n=count, notes=notes)
    return tr("img.day_other", n=count, notes=notes)


def run_one_click_image_flow(
    parent: QWidget,
    *,
    tr: Callable[..., str],
    jobs: Sequence[Any],
    collect_fn: Callable[[Sequence[Any]], list[Any]],
    group_fn: Callable[[Sequence[Any]], list[Any]],
    request_send: Callable[..., bool],
    sync_to_customer: bool = False,
    notes_fn: Callable[[Sequence[Any]], str] | None = None,
    on_busy: Callable[[str], None] | None = None,
    on_done_refresh: Callable[[], None] | None = None,
) -> bool:
    awaiting = collect_fn(jobs)
    if not awaiting:
        show_message(parent, tr, tr("img.btn"), tr("img.none"))
        return False

    groups = group_fn(awaiting)
    if not groups:
        show_message(parent, tr, tr("img.btn"), tr("img.none"))
        return False

    labels = [_day_label(tr, group, notes_fn=notes_fn) for group in groups]
    selected = choose_button_option(
        parent, tr, tr("img.pick_day"), tr("img.pick_day"), labels
    )
    if selected is None:
        return False
    group = groups[selected]
    day = int(getattr(group, "day_1based", 0) or 0)
    count = len(group.jobs)
    if sync_to_customer:
        confirm = (
            tr("img.confirm_sync", day=day, n=count)
            if day > 0
            else tr("img.confirm_sync_other", n=count)
        )
    else:
        confirm = (
            tr("img.confirm", day=day, n=count)
            if day > 0
            else tr("img.confirm_other", n=count)
        )
    if not ask_confirmation(parent, tr, tr("img.btn"), confirm):
        return False

    extra = ""
    if sync_to_customer:
        value = ask_text(
            parent,
            tr,
            tr("img.extra_title"),
            tr("img.extra_hint"),
            multiline=True,
            allow_empty=True,
        )
        if value is None:
            return False
        extra = value

    def continue_pick() -> None:
        paths = pick_images(parent, tr=tr)
        if not paths:
            return
        if len(paths) > 3:
            show_message(parent, tr, tr("img.btn"), tr("img.too_many", max_n=3))
            return
        if on_busy is not None:
            if sync_to_customer:
                on_busy(tr("img.busy_sync"))
            elif len(paths) > 1:
                on_busy(tr("img.busy_multi", count=len(paths)))
            else:
                on_busy(tr("img.busy"))

        def progress(index: int, total: int, result: Any) -> None:
            target = getattr(result, "target", "") or getattr(result, "job_id", "")
            status = (
                "ok"
                if getattr(result, "ok", False)
                else getattr(result, "error", "fail")
            )
            if on_busy is None:
                return
            text = tr(
                "img.progress",
                i=index,
                total=total,
                target=target,
                status=status,
            )
            call_on_ui(parent, lambda t=text: on_busy(t))

        def done(ok: int, fail: int, resumed: int) -> None:
            def finish() -> None:
                show_message(
                    parent,
                    tr,
                    tr("img.btn"),
                    tr("img.done", ok=ok, fail=fail, resumed=resumed),
                )
                if on_done_refresh is not None:
                    on_done_refresh()

            call_on_ui(parent, finish)

        accepted = request_send(
            [job.id for job in group.jobs],
            paths,
            sync_to_customer=sync_to_customer,
            customer_extra_text=extra,
            on_progress=progress,
            on_done=done,
        )
        if not accepted:
            show_message(parent, tr, tr("img.btn"), tr("img.busy"))

    # 等确认弹窗完全关闭后再打开资源管理器，避免抢焦点失败。
    QTimer.singleShot(250, continue_pick)
    return True
