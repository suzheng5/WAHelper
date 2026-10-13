"""主窗口：侧边栏 + 多页面（暗色主题）。"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 `python .../tg_multi_listener/ui/app.py`：此时 sys.path[0] 为 ui/，需先加入项目根。
_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))
_wa_pkg = _pkg_root.parent / "wa_multi_listener"
if _wa_pkg.is_dir() and str(_wa_pkg) not in sys.path:
    sys.path.insert(0, str(_wa_pkg))
from wa_ui.card_grid import TASKMGR_COLS, TG_ACCT_COLS, configure_equal_columns, grid_place, reorder_taskmgr_grid
from wa_ui.taskmgr_tile_theme import (
    format_taskmgr_count_summary,
    taskmgr_card_status_text,
    taskmgr_count_jobs,
    taskmgr_fonts,
    taskmgr_sort_jobs_for_display,
    taskmgr_tile_palette,
)
from i18n.job_card import format_job_status_label, operator_note_for_items
from i18n.pause_reason import CODE_MANUAL, display_pause_reason, is_await_image_send
from ..one_click_image import (
    MAX_BULK_IMAGES,
    collect_awaiting_image_jobs,
    group_awaiting_by_day,
    notes_for_awaiting_jobs,
)
from i18n import get_lang, set_lang_for_next_launch, t
from i18n.ui_helpers import (
    combo_label_for_lang,
    lang_combo_labels,
    lang_from_combo_label,
    msg_askyesno,
    msg_info,
)
from schedule_folder import (
    FOLDER_BULK_ADVANCE_BATCH_PAUSE_SEC,
    FOLDER_BULK_ADVANCE_BATCH_SIZE,
    bulk_delete_job_summary,
    can_advance_folder_day,
    entry_schedule_kind_hint,
    format_bulk_delete_confirm_message,
    format_folder_advance_line,
    format_folder_last_day_delete_line,
    folder_txt_abs_path,
    is_folder_job,
    schedule_kind_badge,
    scan_schedule_folder,
    split_folder_jobs_for_bulk_advance,
    taskmgr_job_file_label,
)
from wa_ui.log_textbox_util import (
    LOG_PUMP_IDLE_MS,
    LOG_PUMP_MS,
    LOG_TEXTBOX_MAX_LINES,
    append_log_line_capped,
    bind_log_textbox_wheel,
    reload_log_textbox_from_memory,
)
from wa_ui.file_picker_util import (
    pick_image_files,
    pick_txt_or_folder,
    release_modal_grabs,
    txt_open_initial_dir,
)
from wa_ui.modal_util import (
    ask_yes_no,
    pick_button_option,
    prompt_text_with_skip,
    run_after_modal_closed,
    show_message,
)
from wa_ui.scroll_util import (
    bind_scroll_tree_once,
    mount_page_scroll,
    scroll_wheel,
)

import os
import queue
import random
import re
import threading
import time
import uuid
import webbrowser
from collections import Counter
import tkinter as tk
from tkinter import TclError
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, TYPE_CHECKING

import customtkinter as ctk

from ..compat_config import (
    Account,
    AddressEntry,
    apply_last_schedule_for_jobs,
    apply_last_schedule_from_current_jobs,
    chat_ref_to_optional_int,
    format_job_targets_label,
    format_listener_chat_label,
    load_config,
    parse_chat_ref_input,
    parse_watch_user_input,
    save_config,
    sync_last_schedule_from_disk,
)
from ..listener import ListenerController
from ..paths import app_root, resource_path
from ..ui.log_view_filter import filter_lines_for_log_view, is_visible_in_log_view
from ..logger_util import add_memory_listener, error, error_i18n, get_recent_lines, info, info_i18n, remove_memory_listener, warning_i18n
from ..notifier import AlertPopup
from ..scheduler import (
    LISTEN_HIT_PAUSE_REASON,
    DocMessage,
    ScheduledJob,
    ScheduleRunner,
    advance_scheduled_folder_day,
    bulk_resume_job_counts,
    load_jobs,
    save_jobs,
    save_jobs_patch,
)
from ..group_owner import (
    apply_main_account_mapping,
    clone_doc_items,
    doc_has_main_account_placeholder,
    is_main_account_placeholder,
)
from ..schedule_txt_import import import_doc_items, items_have_any_txt_interval, items_use_txt_intervals
from ..session_check import is_session_authorized_sync
from ..stats import record_alert, today_alert_count
from ..telethon_auth import run_login_in_thread
from ..telethon_coordinator import DEFAULT_JOIN_TIMEOUT, TelethonCoordinator
from ..watch_membership_audit import WatchAuditRow, WatchAuditStatus
from .address_edit_dialog import AddressEditDialog
from .theme import COLORS, SIDEBAR_WIDTH

# 固定窗口比例 16:10：禁止拖拽边缘改尺寸；略增高以减少纵向遮挡。
MAIN_WINDOW_W = 1152
MAIN_WINDOW_H = 720
MAIN_WINDOW_GEOMETRY = f"{MAIN_WINDOW_W}x{MAIN_WINDOW_H}"

NavId = str


class MainWindow(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk | ctk.CTkFrame,
        listener: ListenerController,
        scheduler: ScheduleRunner,
        *,
        embedded: bool = False,
    ) -> None:
        super().__init__(master)
        self._embedded = embedded
        self._listener = listener
        self._scheduler = scheduler
        self._coord: Optional[TelethonCoordinator] = None
        self._service_reload_busy = False
        self._scheduler.set_reminder_callback(self._doc_schedule_reminder)
        self._cfg = load_config()
        sync_last_schedule_from_disk(self._cfg)
        self._nav: Dict[NavId, ctk.CTkFrame] = {}
        self._content: Optional[ctk.CTkFrame] = None
        self._login_status: Dict[str, Optional[bool]] = {}
        self._login_probe_gen = 0
        self._pages_ready = False
        self._sched_edit_job_id: Optional[str] = None
        self._sched_job_label_to_id: Dict[str, str] = {}
        self._sched_job_row_widgets: Dict[str, Dict[str, Any]] = {}
        self._sched_listed_job_ids: List[str] = []
        self._sched_job_fingerprints: Dict[str, tuple] = {}
        self._taskmgr_widgets: Dict[str, Dict[str, Any]] = {}
        self._taskmgr_listed_ids: List[str] = []
        self._taskmgr_display_ids: List[str] = []
        self._taskmgr_fp_cache: Dict[str, tuple] = {}
        self._taskmgr_toggle_busy = False
        self._manual_folder_advance_mode = False
        self._sched_target_rows: List[Tuple[AddressEntry, ctk.BooleanVar]] = []
        self._grp_row_widgets: Dict[str, Dict[str, Any]] = {}
        self._grp_row_ids: List[str] = []
        self._grp_row_fp_cache: Dict[str, tuple] = {}
        self._grp_scroll_bound = False
        self._sched_targets_dirty = False
        self._address_edit_dlg: Optional[AddressEditDialog] = None
        self._grp_title_font: Optional[ctk.CTkFont] = None
        self._grp_summary_font: Optional[ctk.CTkFont] = None
        self._acc_widgets: Dict[str, Dict[str, Any]] = {}
        self._acc_listed_ids: List[str] = []
        self._log_ui_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._log_ui_pump_on = True
        self._current_nav: NavId = "dash"
        self._watch_audit_flags: Dict[str, str] = {}

        if not embedded:
            root = master if isinstance(master, ctk.CTk) else master.winfo_toplevel()
            try:
                root.title(t("app.brand"))
                root.geometry(MAIN_WINDOW_GEOMETRY)
                root.resizable(False, False)
            except Exception:
                pass
        self.configure(fg_color=COLORS["bg"])

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        # 先只铺侧栏 +「加载中」，避免主线程在 mainloop 前一次性创建全部页面导致长时间白屏/无响应
        self._content = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        self._content.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._content,
            text=t("common.loading_ui"),
            font=ctk.CTkFont(size=16),
            text_color=COLORS["muted"],
        ).grid(row=0, column=0)
        self.after(1, self._deferred_bootstrap_ui)
        self.after(LOG_PUMP_MS, self._pump_log_ui_queue)
        self._log_listener: Optional[Callable[[str], None]] = self._on_log_line
        add_memory_listener(self._on_log_line)
        if not embedded:
            root = master if isinstance(master, ctk.CTk) else master.winfo_toplevel()
            try:
                root.protocol("WM_DELETE_WINDOW", self._on_exit)
            except Exception:
                pass

    def _deferred_bootstrap_ui(self) -> None:
        """首帧后再创建各功能页；分多帧构建，避免单帧内创建全部页面导致长时间未响应。"""
        if self._pages_ready:
            return
        try:
            if self._content is not None:
                self._content.destroy()
            self._content = ctk.CTkFrame(self, fg_color=COLORS["bg"])
            self._content.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
            self._content.grid_rowconfigure(0, weight=1)
            self._content.grid_columnconfigure(0, weight=1)
            self._nav.clear()
            self._page_build_queue: List[NavId] = ["dash", "acct", "grp", "rules", "sched", "taskmgr", "logs"]
            self._page_build_tick()
        except Exception as exc:
            error_i18n("log.ui_load_fail", err=exc)

    def _page_build_tick(self) -> None:
        if self._pages_ready:
            return
        try:
            if not self._page_build_queue:
                for f in self._nav.values():
                    f.grid(row=0, column=0, sticky="nsew")
                self._pages_ready = True
                self._show_nav("dash")
                self.after(80, self._raise_main_window)
                info_i18n("log.ui_ready")
                return
            nav_id = self._page_build_queue.pop(0)
            builders = {
                "dash": self._page_dashboard,
                "acct": self._page_accounts,
                "grp": self._page_groups,
                "rules": self._page_rules,
                "sched": self._page_schedule,
                "taskmgr": self._page_task_manager,
                "logs": self._page_logs,
            }
            try:
                self._nav[nav_id] = builders[nav_id]()
            except Exception as exc:
                error_i18n("log.ui_page_fail", nav_id=nav_id, err=exc)
                fail = ctk.CTkFrame(self._content, fg_color="transparent")
                ctk.CTkLabel(
                    fail,
                    text=t("log.ui_page_load_fail", nav_id=nav_id, err=exc),
                    text_color=COLORS["danger"],
                    wraplength=480,
                    justify="left",
                ).pack(anchor="w", padx=16, pady=16)
                self._nav[nav_id] = fail
            try:
                self.update_idletasks()
            except Exception:
                pass
            self.after(1, self._page_build_tick)
        except Exception as exc:
            error_i18n("log.ui_load_fail", err=exc)
            self._show_ui_bootstrap_error(str(exc))

    def shutdown_ui(self) -> None:
        self._log_ui_pump_on = False
        if self._log_listener is not None:
            try:
                remove_memory_listener(self._log_listener)
            except Exception:
                pass
            self._log_listener = None

    def _raise_main_window(self) -> None:
        if self._embedded:
            return
        try:
            self.deiconify()
        except TclError:
            pass

    def _tg_session_running(self) -> bool:
        return self._coord is not None and self._coord.is_running()

    def _warn_if_tg_session_down(self) -> None:
        if self._coord is not None and not self._coord.is_running():
            warning_i18n("log.coord_not_running")

    def _show_ui_bootstrap_error(self, msg: str) -> None:
        """界面分步构建失败时，在右侧显示错误而不是留黑屏。"""
        try:
            for ch in self._content.winfo_children():
                ch.destroy()
            ctk.CTkLabel(
                self._content,
                text=t("log.ui_bootstrap_body", msg=msg),
                font=ctk.CTkFont(size=14),
                text_color=COLORS["danger"],
                wraplength=520,
                justify="left",
            ).grid(row=0, column=0, padx=20, pady=20, sticky="nw")
        except Exception:
            pass

    def _account_id_values(self) -> List[str]:
        ids = [a.id for a in self._cfg.accounts]
        return ids if ids else ["default"]

    def _owner_account_values(self) -> List[str]:
        """通讯录归属账号：列出账号管理中全部账号（不限于勾选启用）。"""
        return [a.id for a in self._cfg.accounts]

    def _refresh_owner_account_combos(self) -> None:
        vals = self._owner_account_values()
        if getattr(self, "_addr_owner", None) is None:
            return
        cur = self._addr_owner.get().strip()
        if vals:
            self._addr_owner.configure(values=vals)
            self._addr_owner.set(cur if cur in vals else vals[0])
        else:
            self._addr_owner.configure(values=["—"])
            self._addr_owner.set("—")

    def _after_address_book_order_changed(self) -> None:
        self._patch_group_rows()
        self._mark_schedule_targets_dirty()

    def _move_address_book_entry(self, entry_id: str, delta: int) -> None:
        book = self._cfg.address_book
        idx = next((i for i, e in enumerate(book) if e.id == entry_id), -1)
        if idx < 0:
            return
        j = idx + delta
        if j < 0 or j >= len(book):
            return
        book[idx], book[j] = book[j], book[idx]
        self._optional_merge_global_api_from_ui()
        save_config(self._cfg)
        self._after_address_book_order_changed()

    def _mark_schedule_targets_dirty(self) -> None:
        self._sched_targets_dirty = True

    def _refresh_schedule_targets_if_dirty(self) -> None:
        if not getattr(self, "_sched_targets_dirty", False):
            return
        self._sched_targets_dirty = False
        self._refresh_schedule_target_checks()

    def _grp_list_fonts(self) -> tuple[ctk.CTkFont, ctk.CTkFont]:
        if self._grp_title_font is None:
            family = "Microsoft YaHei UI"
            self._grp_title_font = ctk.CTkFont(family=family, size=14, weight="bold")
            self._grp_summary_font = ctk.CTkFont(family=family, size=12)
        return self._grp_title_font, self._grp_summary_font

    def _mount_main_scroll(
        self, page: ctk.CTkFrame, footer: Optional[ctk.CTkFrame] = None
    ) -> tuple[ctk.CTkFrame, Callable[[], None]]:
        """主内容区：Canvas 滚动 + 全页滚轮绑定。返回 (inner, finish_scroll_bind)。"""
        inner, canvas, finish = mount_page_scroll(page, footer=footer, bg=COLORS["bg"])
        self._scroll_wheel_handler = lambda e, c=canvas: scroll_wheel(c, e)
        return inner, finish

    def _elastic_wraplabels(self, scroll_widget: ctk.CTkFrame, labels: List[ctk.CTkLabel], inset: int = 56) -> None:
        """说明文字随滚动区宽度自动折行，避免固定 wraplength 在窄窗口下溢出。"""
        if not labels:
            return

        def sync(_event: Any = None) -> None:
            try:
                w = int(scroll_widget.winfo_width())
                if w <= inset + 80:
                    return
                wl = max(260, w - inset)
                for lb in labels:
                    lb.configure(wraplength=wl)
            except Exception:
                pass

        scroll_widget.bind("<Configure>", sync)
        self.after_idle(sync)

    def _bind_label_wrap_to_card_width(self, card: ctk.CTkFrame, label: ctk.CTkLabel, inset: int = 28) -> None:
        """卡片变窄时自动收紧 Label 折行宽度，避免横向溢出。"""
        def sync(_e: Any = None) -> None:
            try:
                w = int(card.winfo_width())
                if w > inset + 80:
                    label.configure(wraplength=max(200, w - inset))
            except Exception:
                pass

        card.bind("<Configure>", sync)
        self.after_idle(sync)

    def bind_coordinator(self, coord: TelethonCoordinator) -> None:
        self._coord = coord
        bind_warning = getattr(coord, "set_address_warning_callback", None)
        if callable(bind_warning):
            bind_warning(self._show_address_group_warning)

    def _show_address_group_warning(self, label: str, kind: str, peer_id: int) -> None:
        def run() -> None:
            from i18n.ui_helpers import msg_warning

            type_key = (
                "grp.type_basic_group"
                if kind == "basic_group"
                else "grp.type_channel"
            )
            msg_warning(
                self,
                "grp.upgrade_supergroup_title",
                "grp.upgrade_supergroup_body",
                name=label,
                type=t(type_key),
                peer_id=peer_id,
            )

        self.after(0, run)

    def _doc_schedule_reminder(
        self,
        job: ScheduledJob,
        item: DocMessage,
        step_one_based: int,
        paused_count: int = 0,
        affected_job_ids: Optional[List[str]] = None,
    ) -> None:
        """阶段提醒：runner 已暂停，patch 任务卡片；可选置顶弹窗。"""
        ids = list(dict.fromkeys(affected_job_ids or []))
        overrides: Dict[str, ScheduledJob] = {job.id: job}
        if job.id not in ids:
            ids.append(job.id)
        note = (getattr(item, "reminder_note", "") or "").strip()

        def run() -> None:
            if ids:
                self._patch_taskmgr_cards(ids, reorder=True, job_overrides=overrides)
            if not getattr(self._cfg, "stage_reminder_popup_enabled", True):
                return
            try:
                from tg_multi_listener.notifier import show_stage_reminder
                from i18n.pause_reason import CODE_JOIN_GROUP_FAILED, pause_reason_is

                cfg = load_config()
                grp = format_job_targets_label(cfg, job)
                is_join = pause_reason_is(job.pause_reason or "", CODE_JOIN_GROUP_FAILED)
                if is_join:
                    acc = (getattr(item, "original_account_id", None) or getattr(item, "account_id", None) or "").strip()
                    subtitle = t("join.subtitle", name=job.source_name, account=acc or "—")
                    if grp:
                        subtitle += t("join.subtitle_group", grp=grp)
                    title = t("join.title_tg")
                else:
                    subtitle = t("stage.subtitle", step=step_one_based, name=job.source_name)
                    if grp:
                        subtitle += t("stage.subtitle_group", grp=grp)
                    title = t("stage.title_tg")
                body = note or t("stage.no_note")
                if paused_count > 0:
                    body += t("stage.paused_related", n=paused_count)
                show_stage_reminder(
                    self,
                    title=title,
                    subtitle=subtitle,
                    body=body,
                )
            except Exception as exc:
                error_i18n("log.stage_popup_fail", err=exc)

        self.after(0, run)

    def alert_callback(self, payload: Dict) -> None:
        """由 Telethon 后台线程调用：暂停须立即落盘，UI 刷新仍走主线程。"""
        p = dict(payload)
        touched_ids: List[str] = []
        try:
            chat_id = int(p.get("chat_id"))
            raw = p.get("chat_id_raw")
            raw_i = int(raw) if raw is not None else None
            ev_u = str(p.get("chat_username") or "").strip() or None
            ev_t = str(p.get("chat_title") or "").strip() or None
            touched_ids.extend(
                self._scheduler.pause_jobs_by_chat(
                    chat_id,
                    LISTEN_HIT_PAUSE_REASON,
                    raw_chat_id=raw_i,
                    event_username=ev_u,
                    event_title=ev_t,
                )
            )
            if raw_i is not None and raw_i != chat_id:
                touched_ids.extend(
                    self._scheduler.pause_jobs_by_chat(
                        raw_i,
                        LISTEN_HIT_PAUSE_REASON,
                        raw_chat_id=chat_id,
                        event_username=ev_u,
                        event_title=ev_t,
                    )
                )
            touched_ids = list(dict.fromkeys(touched_ids))
        except Exception as exc:
            error_i18n("log.listen_hit_pause_fail", err=exc)

        def run_on_main() -> None:
            try:
                record_alert()
                chat_disp = ""
                try:
                    chat_id = int(p.get("chat_id"))
                    raw = p.get("chat_id_raw")
                    raw_i = int(raw) if raw is not None else None
                    ev_u = str(p.get("chat_username") or "").strip() or None
                    ev_t = str(p.get("chat_title") or "").strip() or None
                    chat_disp = format_listener_chat_label(
                        load_config(),
                        peer_id=chat_id,
                        chat_title=ev_t or "",
                        chat_id_raw=raw_i,
                        chat_username=ev_u,
                    )
                except Exception:
                    chat_disp = str(p.get("chat_title", ""))
                if touched_ids:
                    info_i18n("log.listen_hit_chat", chat=chat_disp, n=len(touched_ids))
                    self._patch_taskmgr_cards(touched_ids, reorder=True)
            except Exception as exc:
                error_i18n("log.listen_hit_ui_fail", err=exc)
            try:
                AlertPopup(
                    self,
                    chat_title=str(p.get("chat_title", "")),
                    chat_meta=chat_disp if chat_disp else str(p.get("chat_title", "")),
                    sender_name=str(p.get("sender_name", "")),
                    message_text=str(p.get("message_text", "")),
                    chat_username=p.get("chat_username"),
                )
            except Exception as exc:
                error_i18n("log.listen_hit_popup_fail", err=exc)

        try:
            self.after(0, run_on_main)
        except Exception as exc:
            error_i18n("log.listen_hit_dispatch_fail", err=exc)

    def _on_exit(self) -> None:
        # 不在此线程 join Telethon（会卡窗体数秒）；释放 UI 后由 main() 的 finally 统一 stop。
        self._log_ui_pump_on = False
        if self._log_listener:
            remove_memory_listener(self._log_listener)
        self.destroy()

    def _on_log_line(self, line: str) -> None:
        if not is_visible_in_log_view(line):
            return
        try:
            self._log_ui_queue.put_nowait(line)
        except Exception:
            pass

    def _tg_log_lines(self, limit: int) -> List[str]:
        return filter_lines_for_log_view(get_recent_lines(limit))

    def _drain_log_queue_to_textbox(self) -> None:
        lb = getattr(self, "_log_box", None)
        if lb is None:
            return
        for _ in range(500):
            try:
                line = self._log_ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                append_log_line_capped(lb, line, max_lines=LOG_TEXTBOX_MAX_LINES)
            except Exception:
                break

    def _pump_log_ui_queue(self) -> None:
        """主线程消费日志队列；仅「日志中心」页刷新 Textbox，其它页降低泵频率。"""
        if not getattr(self, "_log_ui_pump_on", True):
            return
        on_logs = getattr(self, "_current_nav", "") == "logs"
        if on_logs:
            self._drain_log_queue_to_textbox()
        if self._log_ui_pump_on:
            try:
                if self.winfo_exists():
                    delay = LOG_PUMP_MS if on_logs else LOG_PUMP_IDLE_MS
                    self.after(delay, self._pump_log_ui_queue)
            except Exception:
                pass

    def _restart_services(self) -> bool:
        """停止并重新启动监听/定时后台线程。可能阻塞数十秒（内部 join），勿在主 UI 线程直接调用。"""
        if self._coord is not None:
            if not self._coord.stop(join_timeout=DEFAULT_JOIN_TIMEOUT):
                error_i18n("log.reload_abort")
                return False
        else:
            self._listener.stop()
            self._scheduler.stop()
        self._cfg = load_config()
        self._listener.start(self._cfg, self.alert_callback)
        self._scheduler.start(self._cfg)
        if self._coord is not None:
            if not self._coord.start(self._cfg):
                return False
        return True

    def _invoke_restart_in_background(self, on_main_thread: Optional[Callable[[], None]] = None) -> None:
        """在后台线程执行重载，避免主界面在 join Telethon 线程时卡死。"""
        if self._service_reload_busy:
            info_i18n("log.reload_busy")
            return
        self._service_reload_busy = True

        def worker() -> None:
            ok = False
            try:
                ok = self._restart_services()
            except Exception as exc:
                error_i18n("log.reload_fail", err=exc)
            finally:
                def done() -> None:
                    self._service_reload_busy = False
                    if not ok:
                        info_i18n("log.reload_incomplete")
                    if on_main_thread is not None and ok:
                        try:
                            on_main_thread()
                        except Exception:
                            pass

                self.after(0, done)

        threading.Thread(target=worker, daemon=True, name="tg-restart-services").start()

    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, fg_color=COLORS["sidebar"], corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")

        logo = ctk.CTkLabel(
            side,
            text=t("tg.brand"),
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text"],
        )
        logo.pack(anchor="w", padx=18, pady=(24, 8))

        sub = ctk.CTkLabel(side, text=t("tg.subtitle"), font=ctk.CTkFont(size=12), text_color=COLORS["muted"])
        sub.pack(anchor="w", padx=18, pady=(0, 20))

        for nav_id, label in (
            ("dash", t("nav.dash")),
            ("acct", t("nav.acct")),
            ("grp", t("nav.grp")),
            ("rules", t("nav.rules")),
            ("sched", t("nav.sched")),
            ("taskmgr", t("nav.taskmgr")),
            ("logs", t("nav.logs_tg")),
        ):
            b = ctk.CTkButton(
                side,
                text=label,
                anchor="w",
                height=36,
                fg_color="transparent",
                text_color=COLORS["muted"],
                hover_color=COLORS["card"],
                command=lambda n=nav_id: self._show_nav(n),
            )
            b.pack(fill="x", padx=10, pady=4)

        save_btn = ctk.CTkButton(
            side,
            text=t("common.save_reload_service"),
            fg_color=COLORS["accent"],
            hover_color="#3d7ae6",
            command=self._save_all_and_restart,
        )
        save_btn.pack(side="bottom", fill="x", padx=14, pady=(8, 16))

    def _wrap_page(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        wrap, finish = self._mount_main_scroll(parent)
        wrap.grid_columnconfigure(0, weight=1)
        t = ctk.CTkLabel(
            wrap,
            text=title,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text"],
        )
        t.grid(row=0, column=0, sticky="w", padx=4, pady=(8, 16))
        finish()
        return wrap

    def _format_send_progress(self, total: int, done: int, remain: int, *, step_total: int = 0) -> str:
        if total <= 0:
            return t("send_progress.none")
        if remain <= 0:
            base = t("send_progress.all_done", done=done)
        else:
            base = t("send_progress.remain", done=done, remain=remain)
        if step_total > total:
            return t("send_progress.with_reminders", base=base, steps=step_total, reminders=step_total - total)
        return base

    def _show_nav(self, nav_id: NavId) -> None:
        if not self._pages_ready or not self._nav:
            return
        try:
            release_modal_grabs(self)
        except Exception:
            pass
        self._current_nav = nav_id
        for k, fr in self._nav.items():
            if k == nav_id:
                fr.grid()
            else:
                fr.grid_remove()
        if nav_id == "dash":
            self._refresh_dashboard()
            self._schedule_login_probe()
        elif nav_id == "acct":
            self._schedule_login_probe()
            self._render_account_rows()
        elif nav_id == "grp":
            self._refresh_owner_account_combos()
            self._patch_group_rows()
            foot = getattr(self, "_grp_foot", None)
            if foot is not None:
                try:
                    foot.lift()
                    foot.grid(row=2, column=0, sticky="ew")
                except Exception:
                    pass
        elif nav_id == "sched":
            self._refresh_schedule_targets_if_dirty()
        elif nav_id == "taskmgr":
            self._sync_taskmgr_page()
        elif nav_id == "logs":
            self._flush_logs_ui()

    def _schedule_login_probe(self) -> None:
        """后台检测各账号 session 是否已授权；结果用于账号行样式与仪表盘。"""
        self._login_probe_gen += 1
        gen = self._login_probe_gen

        def worker() -> None:
            # 必须等 Telegram 统一会话线程把 listener._running 置为 True 后再碰 .session，
            # 否则与 TelethonCoordinator 同时 asyncio.run 连同一库会导致长时间锁死，表现为「有进程无界面」。
            deadline = time.time() + 12.0
            while not self._listener.is_running() and time.time() < deadline:
                time.sleep(0.05)
            if not self._listener.is_running():
                info_i18n("log.session_probe_skip")

                def apply_skip() -> None:
                    if gen != self._login_probe_gen:
                        return
                    if getattr(self, "_pages_ready", False):
                        self._refresh_dashboard()

                self.after(0, apply_skip)
                return
            cfg = load_config()
            status: Dict[str, Optional[bool]] = {}
            for a in cfg.accounts:
                try:
                    # 监听已在跑时，不再并发探测同一 session，避免偶发锁冲突导致误判未登录。
                    if a.enabled and self._listener.is_running():
                        status[a.id] = True
                    else:
                        status[a.id] = bool(is_session_authorized_sync(a, cfg))
                except Exception:
                    status[a.id] = False

            def apply() -> None:
                if gen != self._login_probe_gen:
                    return
                self._login_status = status
                if not getattr(self, "_pages_ready", False):
                    return
                if self._nav.get("acct") and self._nav["acct"].winfo_ismapped():
                    self._patch_account_rows()
                self._refresh_dashboard()

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _card(self, parent: Any, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        card.grid(row=row, column=0, sticky="ew", pady=8)
        card.grid_columnconfigure(0, weight=1)
        return card

    def _page_dashboard(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        wrap = self._wrap_page(page, t("nav.dash"))

        c1 = self._card(wrap, 1)
        c1.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(c1, text=t("dash.today_alerts"), font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"]).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 4)
        )
        self._dash_today = ctk.CTkLabel(c1, text="", font=ctk.CTkFont(size=14), text_color=COLORS["text"])
        self._dash_today.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 12))

        c2 = self._card(wrap, 2)
        ctk.CTkLabel(c2, text=t("dash.listen_status"), font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"]).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 4)
        )
        self._dash_listen = ctk.CTkLabel(c2, text="", font=ctk.CTkFont(size=14), text_color=COLORS["muted"], justify="left")
        self._dash_listen.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        c3 = self._card(wrap, 3)
        ctk.CTkLabel(c3, text=t("dash.account_summary"), font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"]).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 4)
        )
        self._dash_acct = ctk.CTkLabel(
            c3,
            text="",
            font=ctk.CTkFont(size=14),
            text_color=COLORS["muted"],
            justify="left",
            anchor="w",
            wraplength=840,
        )
        self._dash_acct.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        self._elastic_wraplabels(wrap, [self._dash_listen, self._dash_acct])
        return page

    def _refresh_dashboard(self) -> None:
        n = today_alert_count()
        self._dash_today.configure(text=t("dash.today_count", n=n))
        listen_on = bool(self._cfg.listening_enabled)
        conn = self._listener.is_running()
        parts = [
            t("dash.listen_on") if listen_on else t("dash.listen_off"),
            t("dash.tg_connected") if conn else t("dash.tg_disconnected"),
        ]
        if listen_on and conn:
            parts.append(t("dash.listening_active"))
        elif listen_on and not conn:
            parts.append(t("dash.listen_on_disconnected_tg"))
        self._dash_listen.configure(text="  ·  ".join(parts))
        lines = []
        for a in self._cfg.accounts:
            st = self._login_status.get(a.id)
            if st is True:
                st_txt = t("dash.tg_logged_in")
            elif st is False:
                st_txt = t("dash.tg_not_logged_in")
            else:
                st_txt = t("dash.tg_checking")
            extra = t("dash.tg_session_file", name=a.session_name) if a.session_name != a.id else ""
            lines.append(t("dash.account_line", id=a.id, status=st_txt, enabled=t("dash.enabled") if a.enabled else t("dash.disabled")) + extra)
        self._dash_acct.configure(text="\n".join(lines) if lines else t("dash.no_accounts_configured"))

    # --- accounts ---
    def _page_accounts(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")

        acct_foot = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        af = ctk.CTkFrame(acct_foot, fg_color="transparent")
        af.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(
            af,
            text=t("acct.tg.open_api_site"),
            fg_color=COLORS["border"],
            command=lambda: webbrowser.open("https://my.telegram.org/apps"),
        ).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(af, text=t("acct.tg.save_list_only"), fg_color=COLORS["border"], command=self._add_account_row_ui).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(af, text=t("acct.tg.login_this"), fg_color=COLORS["accent"], hover_color="#3d7ae6", command=self._login_from_form).pack(fill="x")

        wrap, finish_scroll = self._mount_main_scroll(page, footer=acct_foot)

        ctk.CTkLabel(wrap, text=t("acct.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=(8, 4))
        intro_acct = ctk.CTkLabel(
            wrap,
            text=t("acct.tg.intro"),
            text_color=COLORS["muted"],
            wraplength=520,
            justify="left",
        )
        intro_acct.pack(anchor="w", pady=(0, 14))

        api_card = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        api_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(api_card, text=t("acct.tg.api_global_title"), font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", padx=14, pady=(12, 6)
        )
        api_hint = ctk.CTkLabel(
            api_card,
            text=t("acct.tg.api_global_hint"),
            text_color=COLORS["muted"],
            wraplength=520,
            justify="left",
        )
        api_hint.pack(anchor="w", padx=14, pady=(0, 10))

        api_form = ctk.CTkFrame(api_card, fg_color="transparent")
        api_form.pack(fill="x", padx=14, pady=(0, 12))
        api_form.grid_columnconfigure(0, weight=1)
        self._glob_api_id = ctk.CTkEntry(api_form, placeholder_text=t("acct.tg.api_id_ph"))
        self._glob_api_hash = ctk.CTkEntry(api_form, placeholder_text=t("acct.tg.api_hash_ph"))
        self._glob_api_id.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self._glob_api_hash.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        if self._cfg.api_id:
            self._glob_api_id.insert(0, str(self._cfg.api_id))
        if self._cfg.api_hash:
            self._glob_api_hash.insert(0, self._cfg.api_hash)

        login_card = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        login_card.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(login_card, text=t("acct.tg.login_flow_title"), font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", padx=14, pady=(12, 6)
        )
        login_intro = ctk.CTkLabel(
            login_card,
            text=t("acct.tg.login_flow_hint"),
            text_color=COLORS["muted"],
            wraplength=520,
            justify="left",
        )
        login_intro.pack(anchor="w", padx=14, pady=(0, 10))

        form = ctk.CTkFrame(login_card, fg_color="transparent")
        form.pack(fill="x", padx=14, pady=(0, 14))
        form.grid_columnconfigure(0, weight=1)
        self._acc_id = ctk.CTkEntry(form, placeholder_text=t("acct.id_ph"))
        self._acc_phone = ctk.CTkEntry(form, placeholder_text=t("acct.phone_ph"))

        rows = (
            ("acct.tg.id_label", self._acc_id, t("acct.tg.id_hint")),
            ("acct.tg.remark_label", self._acc_phone, t("acct.tg.remark_hint")),
        )
        r = 0
        form_hints: List[ctk.CTkLabel] = []
        for lab, widget, hint in rows:
            ctk.CTkLabel(form, text=lab, text_color=COLORS["text"]).grid(row=r, column=0, padx=0, pady=(8, 4), sticky="w")
            widget.grid(row=r + 1, column=0, sticky="ew", pady=(0, 4))
            hl = ctk.CTkLabel(form, text=hint, text_color=COLORS["muted"], font=ctk.CTkFont(size=11), wraplength=360, justify="left")
            hl.grid(row=r + 2, column=0, sticky="w", pady=(0, 8))
            form_hints.append(hl)
            r += 3

        self._elastic_wraplabels(wrap, [intro_acct, api_hint, login_intro, *form_hints])

        self._acc_rows_title = ctk.CTkLabel(wrap, text=t("acct.tg.saved_rows_title"), font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text"])
        self._acc_rows_title.pack(anchor="w", pady=(10, 8))
        self._acc_rows = ctk.CTkFrame(wrap, fg_color="transparent")
        self._acc_rows.pack(fill="both", expand=True)

        self._render_account_rows(force=True)
        finish_scroll()
        return page

    def _account_login_style(self, account_id: str) -> tuple:
        st = self._login_status.get(account_id)
        if st is True:
            return COLORS["success"], 2, t("acct.tg.logged_in"), COLORS["success"]
        if st is False:
            return COLORS["danger"], 2, t("acct.not_logged_in"), COLORS["danger"]
        return COLORS["border"], 1, t("acct.tg.checking"), COLORS["muted"]

    def _apply_account_tile(self, w: Dict[str, Any], a: Account) -> None:
        bcol, bw, badge, bfg = self._account_login_style(a.id)
        w["card"].configure(border_width=bw, border_color=bcol)
        w["badge"].configure(text=badge, text_color=bfg)

    def _build_account_tile(self, a: Account, index: int, acc_index: int) -> Dict[str, Any]:
        bcol, bw, badge, bfg = self._account_login_style(a.id)
        card = ctk.CTkFrame(
            self._acc_rows,
            fg_color=COLORS["card"],
            corner_radius=10,
            border_width=bw,
            border_color=bcol,
            height=150,
        )
        grid_place(card, index, TG_ACCT_COLS, padx=6, pady=6)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        v = ctk.BooleanVar(value=a.enabled)

        def make_toggle(idx: int, var: ctk.BooleanVar):
            def on_change(*_a: object) -> None:
                self._cfg.accounts[idx].enabled = bool(var.get())
                save_config(self._cfg)
                self._refresh_owner_account_combos()

            return on_change

        disp = a.id
        if a.session_name != a.id:
            disp = f"{a.id}\n({a.session_name})"
        cb = ctk.CTkCheckBox(
            inner,
            text=disp,
            variable=v,
            command=make_toggle(acc_index, v),
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        cb.pack(anchor="w", pady=(0, 6))
        badge_lbl = ctk.CTkLabel(inner, text=badge, font=ctk.CTkFont(size=12, weight="bold"), text_color=bfg, anchor="w")
        badge_lbl.pack(anchor="w", pady=(0, 8))
        ctk.CTkButton(
            inner,
            text=t("acct.login"),
            height=28,
            fg_color=COLORS["accent"],
            hover_color="#3d7ae6",
            command=lambda idx=acc_index: self._login_account_idx(idx),
        ).pack(fill="x", pady=(0, 4))
        ctk.CTkButton(
            inner,
            text=t("common.delete"),
            height=26,
            fg_color=COLORS["border"],
            command=lambda idx=acc_index: self._del_account(idx),
        ).pack(fill="x")
        return {"card": card, "badge": badge_lbl, "var": v, "cb": cb}

    def _full_rebuild_account_grid(self) -> None:
        for ch in self._acc_rows.winfo_children():
            ch.destroy()
        self._acc_widgets.clear()
        self._acc_vars = []
        configure_equal_columns(self._acc_rows, TG_ACCT_COLS, uniform="tg_acct")
        for i, a in enumerate(self._cfg.accounts):
            self._acc_widgets[a.id] = self._build_account_tile(a, i, i)
            self._acc_vars.append(self._acc_widgets[a.id]["var"])
        self._acc_listed_ids = [a.id for a in self._cfg.accounts]

    def _patch_account_rows(self) -> None:
        if not getattr(self, "_acc_widgets", None):
            self._render_account_rows(force=True)
            return
        ids = [a.id for a in self._cfg.accounts]
        if ids != self._acc_listed_ids:
            self._render_account_rows(force=True)
            return
        for a in self._cfg.accounts:
            w = self._acc_widgets.get(a.id)
            if w:
                self._apply_account_tile(w, a)

    def _render_account_rows(self, *, force: bool = False) -> None:
        if getattr(self, "_acc_rows", None) is None:
            return
        ids = [a.id for a in self._cfg.accounts]
        if not force and ids == self._acc_listed_ids and self._acc_widgets:
            self._patch_account_rows()
            self._refresh_schedule_combo()
            return
        self._full_rebuild_account_grid()
        self._refresh_schedule_combo()
        handler = getattr(self, "_scroll_wheel_handler", None)
        if handler:
            bind_scroll_tree_once(self._acc_rows, handler)

    def _merge_global_api_from_ui_into_cfg(self) -> bool:
        """将顶部共用 API 写入内存配置；失败返回 False。"""
        if getattr(self, "_glob_api_id", None) is None:
            return bool(self._cfg.api_id and str(self._cfg.api_hash).strip())
        try:
            aid = int(self._glob_api_id.get().strip())
        except ValueError:
            return False
        h = self._glob_api_hash.get().strip()
        if aid <= 0 or not h:
            return False
        self._cfg.api_id = aid
        self._cfg.api_hash = h
        return True

    def _optional_merge_global_api_from_ui(self) -> None:
        """保存配置时尽量带上顶部 API；格式不对则保留原配置。"""
        if getattr(self, "_glob_api_id", None) is None:
            return
        try:
            aid = int(self._glob_api_id.get().strip())
            h = self._glob_api_hash.get().strip()
            if aid > 0 and h:
                self._cfg.api_id = aid
                self._cfg.api_hash = h
        except ValueError:
            pass

    def _parse_account_form(self) -> Optional[Account]:
        if not self._merge_global_api_from_ui_into_cfg():
            info_i18n("log.tg_api_required")
            return None
        aid = self._acc_id.get().strip() or "default"
        phone = self._acc_phone.get().strip()
        return Account(id=aid, session_name=aid, enabled=True, phone=phone)

    def _login_account_idx(self, idx: int) -> None:
        try:
            acc = self._cfg.accounts[idx]
        except IndexError:
            return
        if not self._merge_global_api_from_ui_into_cfg():
            info_i18n("log.tg_api_required_short")
            return
        save_config(self._cfg)
        self._begin_login(acc)

    def _login_from_form(self) -> None:
        acc = self._parse_account_form()
        if acc is None:
            return
        replaced = False
        for i, x in enumerate(self._cfg.accounts):
            if x.id == acc.id:
                self._cfg.accounts[i] = acc
                replaced = True
                break
        if not replaced:
            self._cfg.accounts.append(acc)
        save_config(self._cfg)
        self._render_account_rows()
        self._begin_login(acc)

    def _stop_backend_for_exclusive_login(self) -> None:
        """在登录专用线程内调用：必须等统一会话彻底释放 .session，否则会 sqlite/database locked 卡死。"""
        info_i18n("log.tg_login_prepare")
        if self._coord is not None:
            if not self._coord.stop(join_timeout=DEFAULT_JOIN_TIMEOUT):
                raise RuntimeError(
                    "Telegram 会话线程未在时限内退出，请暂停定时任务后稍候再试，或完全退出程序后重开。"
                )
        else:
            self._listener.stop()
            self._scheduler.stop()

    def _begin_login(self, acc: Account) -> None:
        if not self._merge_global_api_from_ui_into_cfg():
            info_i18n("log.tg_api_required_short")
            return
        save_config(self._cfg)
        info_i18n("log.tg_login_start", id=acc.id)

        login_id = acc.id

        def on_done(ok: bool, msg: str) -> None:
            info(msg)
            self._cfg = load_config()
            self._sync_global_api_inputs_after_cfg_reload()
            self._login_status[login_id] = ok

            def after_restart() -> None:
                self._render_account_rows()
                self._refresh_owner_account_combos()
                self._refresh_schedule_combo()
                self._refresh_schedule_target_checks()
                self._sync_taskmgr_page()
                self._sync_sched_job_pick_combo()
                self._refresh_dashboard()
                self._schedule_login_probe()
                info_i18n("log.tg_services_restarted")

            self._invoke_restart_in_background(after_restart)

        run_login_in_thread(self, acc, self._cfg, on_done, pre_login=self._stop_backend_for_exclusive_login)

    def _sync_global_api_inputs_after_cfg_reload(self) -> None:
        if getattr(self, "_glob_api_id", None) is None:
            return
        self._glob_api_id.delete(0, "end")
        self._glob_api_hash.delete(0, "end")
        if self._cfg.api_id:
            self._glob_api_id.insert(0, str(self._cfg.api_id))
        if self._cfg.api_hash:
            self._glob_api_hash.insert(0, self._cfg.api_hash)

    def _add_account_row_ui(self) -> None:
        self._optional_merge_global_api_from_ui()
        acc = self._parse_account_form()
        if acc is None:
            return
        self._cfg.accounts.append(acc)
        save_config(self._cfg)
        self._acc_id.delete(0, "end")
        self._acc_phone.delete(0, "end")
        self._render_account_rows()
        self._refresh_owner_account_combos()
        if self._coord is not None and self._coord.has_connected_clients():
            self._coord.apply_config_hot(self._cfg)
        else:
            self._scheduler.start(self._cfg)
        info_i18n("log.tg_account_saved", id=acc.id)

    def _refresh_schedule_combo(self) -> None:
        if getattr(self, "_jacc", None) is None:
            return
        ids = [a.id for a in self._cfg.accounts] or ["default"]
        self._jacc.configure(values=ids)

    def _del_account(self, idx: int) -> None:
        try:
            dead = self._cfg.accounts.pop(idx)
        except IndexError:
            return
        self._login_status.pop(dead.id, None)
        for ent in self._cfg.address_book:
            if ent.owner_account_id == dead.id:
                ent.owner_account_id = ""
        self._optional_merge_global_api_from_ui()
        save_config(self._cfg)
        self._render_account_rows()
        self._refresh_owner_account_combos()
        self._refresh_schedule_combo()
        info_i18n("log.tg_account_deleted", dead=dead.id)
        if self._coord is not None and self._coord.has_connected_clients():
            def after_reload() -> None:
                self._render_account_rows()
                self._refresh_owner_account_combos()
                self._refresh_dashboard()
                self._schedule_login_probe()

            self._invoke_restart_in_background(after_reload)

    # --- 通讯录（群 + 用户，一处保存后监听/定时任务里选用） ---
    def _page_groups(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        page.grid_rowconfigure(2, weight=0)

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text=t("grp.header"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", pady=(8, 4)
        )
        ctk.CTkLabel(
            header,
            text=t("grp.tg_hint"),
            text_color=COLORS["muted"],
            wraplength=680,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        list_host = ctk.CTkFrame(page, fg_color="transparent")
        list_host.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        list_card = ctk.CTkFrame(list_host, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        list_card.pack(fill="both", expand=True)
        ctk.CTkLabel(list_card, text=t("grp.list_title"), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=(10, 4))
        # 不用固定高度：小窗口下会把底栏顶出可视区
        list_inner, list_canvas, finish_list = mount_page_scroll(list_card, bg=COLORS["bg"])
        self._grp_list_scroll_handler = lambda e, c=list_canvas: scroll_wheel(c, e)
        self._grp_rows = ctk.CTkFrame(list_inner, fg_color="transparent")
        self._grp_rows.pack(fill="x")
        self._grp_scroll_bound = False
        self._render_group_rows()
        finish_list()

        grp_foot = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        grp_foot.grid(row=2, column=0, sticky="ew")
        self._grp_foot = grp_foot
        form = ctk.CTkFrame(grp_foot, fg_color="transparent")
        form.pack(fill="x", padx=10, pady=8)

        def _addr_field_row(label: str, placeholder: str) -> ctk.CTkEntry:
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, text_color=COLORS["muted"], width=52, anchor="w").pack(side="left", padx=(0, 6))
            ent = ctk.CTkEntry(row, placeholder_text=placeholder, height=28)
            ent.pack(side="left", fill="x", expand=True)
            return ent

        self._addr_remark = _addr_field_row(t("grp.remark"), t("grp.display_name_ph"))
        self._addr_chat = _addr_field_row(t("grp.group"), t("grp.tg_chat_ph"))
        self._addr_user = _addr_field_row(t("grp.user"), t("grp.tg_user_ph"))

        action = ctk.CTkFrame(form, fg_color="transparent")
        action.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(action, text=t("grp.owner"), text_color=COLORS["muted"], width=52, anchor="w").pack(side="left", padx=(0, 6))
        acc_own = self._owner_account_values()
        self._addr_owner = ctk.CTkComboBox(action, width=88, height=28, values=acc_own or ["—"])
        self._addr_owner.pack(side="left", padx=(0, 8))
        if acc_own:
            self._addr_owner.set(acc_own[0])
        elif not acc_own:
            self._addr_owner.set("—")
        self._addr_listen = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            action,
            text=t("grp.listen"),
            variable=self._addr_listen,
            text_color=COLORS["text"],
            width=56,
            checkbox_height=18,
            checkbox_width=18,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            action,
            text=t("common.add"),
            width=64,
            height=28,
            fg_color=COLORS["accent"],
            command=self._add_address_entry,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            action,
            text=t("grp.save"),
            width=64,
            height=28,
            fg_color=COLORS["border"],
            command=self._save_address_book,
        ).pack(side="left")
        return page

    def _commit_address_book(self, *, resolve_online: bool = True) -> None:
        """保存通讯录；在线时解析群/用户并刷新监听，无需整程序重启。"""
        self._optional_merge_global_api_from_ui()
        save_config(self._cfg)
        self._render_group_rows()
        self._mark_schedule_targets_dirty()
        if not resolve_online:
            info_i18n("log.address_saved_file")
            return
        if self._coord is not None and self._coord.has_connected_clients():
            self._coord.apply_config_hot(self._cfg)
        else:
            info_i18n("log.address_saved_offline")

    def _save_address_book(self) -> None:
        self._commit_address_book(resolve_online=True)

    def _group_row_summary(self, ent: AddressEntry) -> str:
        listen_txt = t("grp.listen_ok") if ent.listen_enabled else t("grp.schedule_only")
        user_txt = ent.watch_user.strip() or "—"
        owner_txt = (ent.owner_account_id or "").strip() or t("grp.not_selected")
        base = t("grp.row_summary", chat=ent.chat_ref, user=user_txt, owner=owner_txt, tag=listen_txt)
        extra, _ = self._watch_audit_display(ent)
        return base + extra

    def _watch_audit_display(self, ent: AddressEntry) -> Tuple[str, str]:
        st = self._watch_audit_flags.get(ent.id, "")
        if st == WatchAuditStatus.ABSENT.value:
            return (
                t("audit.not_in_group_short"),
                COLORS["danger"],
            )
        if st == WatchAuditStatus.ERROR.value:
            return (t("audit.check_fail_short"), COLORS["border"])
        if st == WatchAuditStatus.OFFLINE.value:
            return (t("audit.offline_short"), COLORS["border"])
        return "", COLORS["border"]

    def _address_book_ids(self) -> List[str]:
        return [e.id for e in self._cfg.address_book]

    def _group_row_fingerprint(self, i: int, ent: AddressEntry, n_book: int) -> tuple:
        return (
            i,
            ent.remark,
            ent.chat_ref,
            ent.watch_user,
            ent.listen_enabled,
            ent.owner_account_id,
            self._watch_audit_flags.get(ent.id, ""),
            i > 0,
            i < n_book - 1,
        )

    def _patch_group_row_widget(self, i: int, ent: AddressEntry, w: Dict[str, Any], n_book: int) -> None:
        title_txt = f"{i + 1}. {ent.remark.strip() or ent.id}"
        extra, border = self._watch_audit_display(ent)
        if self._watch_audit_flags.get(ent.id) == WatchAuditStatus.ABSENT.value:
            title_txt += t("grp.not_in_group_badge")
        w["title"].configure(
            text=title_txt,
            text_color=COLORS["danger"] if extra else COLORS["text"],
        )
        w["summary"].configure(
            text=self._group_row_summary(ent),
            text_color=COLORS["danger"] if extra else COLORS["muted"],
        )
        w["row"].configure(border_color=border)
        w["up_btn"].configure(state="normal" if i > 0 else "disabled")
        w["down_btn"].configure(state="normal" if i < n_book - 1 else "disabled")

    def _patch_group_rows(self) -> None:
        if not getattr(self, "_grp_rows", None):
            return
        ids = self._address_book_ids()
        if ids != self._grp_row_ids or len(ids) != len(self._grp_row_widgets):
            self._render_group_rows(force=True)
            return
        n = len(ids)
        for i, ent in enumerate(self._cfg.address_book):
            fp = self._group_row_fingerprint(i, ent, n)
            if self._grp_row_fp_cache.get(ent.id) == fp:
                continue
            self._grp_row_fp_cache[ent.id] = fp
            w = self._grp_row_widgets.get(ent.id)
            if w:
                self._patch_group_row_widget(i, ent, w, n)

    def _render_group_rows(self, *, force: bool = False) -> None:
        if not getattr(self, "_grp_rows", None):
            return
        ids = self._address_book_ids()
        if not ids:
            if self._grp_row_ids:
                for ch in self._grp_rows.winfo_children():
                    ch.destroy()
                self._grp_row_widgets.clear()
                self._grp_row_fp_cache.clear()
                self._grp_row_ids = []
            if not self._grp_rows.winfo_children():
                ctk.CTkLabel(
                    self._grp_rows,
                    text=t("grp.empty"),
                    text_color=COLORS["muted"],
                ).pack(anchor="w", padx=4, pady=8)
            return
        if not force and ids == self._grp_row_ids and len(self._grp_row_widgets) == len(ids):
            self._patch_group_rows()
            return
        for ch in self._grp_rows.winfo_children():
            ch.destroy()
        self._grp_row_widgets.clear()
        self._grp_row_fp_cache.clear()
        self._grp_row_ids = list(ids)
        title_font, summary_font = self._grp_list_fonts()
        n_book = len(self._cfg.address_book)
        for i, ent in enumerate(self._cfg.address_book):
            extra, border_color = self._watch_audit_display(ent)
            row = ctk.CTkFrame(
                self._grp_rows,
                fg_color=COLORS["card"],
                corner_radius=10,
                border_width=1,
                border_color=border_color,
            )
            row.pack(fill="x", pady=3)
            head = ctk.CTkFrame(row, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(8, 0))
            title_txt = f"{i + 1}. {ent.remark.strip() or ent.id}"
            if self._watch_audit_flags.get(ent.id) == WatchAuditStatus.ABSENT.value:
                title_txt += t("grp.not_in_group_badge")
            title_lb = ctk.CTkLabel(
                head,
                text=title_txt,
                font=title_font,
                text_color=COLORS["danger"] if extra else COLORS["text"],
                anchor="w",
            )
            title_lb.pack(side="left", fill="x", expand=True)
            order_btns = ctk.CTkFrame(head, fg_color="transparent")
            order_btns.pack(side="right")
            eid = ent.id
            up_btn = ctk.CTkButton(
                order_btns,
                text="↑",
                width=32,
                height=26,
                fg_color=COLORS["border"],
                state="normal" if i > 0 else "disabled",
                command=lambda e=eid: self._move_address_book_entry(e, -1),
            )
            up_btn.pack(side="left", padx=(0, 4))
            down_btn = ctk.CTkButton(
                order_btns,
                text="↓",
                width=32,
                height=26,
                fg_color=COLORS["border"],
                state="normal" if i < n_book - 1 else "disabled",
                command=lambda e=eid: self._move_address_book_entry(e, 1),
            )
            down_btn.pack(side="left", padx=(0, 4))
            ctk.CTkButton(
                order_btns,
                text=t("grp.edit_btn"),
                width=52,
                height=26,
                fg_color=COLORS["accent"],
                hover_color="#3d7ae6",
                command=lambda e=eid: self._open_address_edit_dialog(e),
            ).pack(side="left")
            summary_lb = ctk.CTkLabel(
                row,
                text=self._group_row_summary(ent),
                font=summary_font,
                text_color=COLORS["danger"] if extra else COLORS["muted"],
                justify="left",
                anchor="w",
                wraplength=640,
            )
            summary_lb.pack(anchor="w", padx=12, pady=(6, 10))
            self._grp_row_widgets[ent.id] = {
                "row": row,
                "title": title_lb,
                "summary": summary_lb,
                "up_btn": up_btn,
                "down_btn": down_btn,
            }
            self._grp_row_fp_cache[ent.id] = self._group_row_fingerprint(i, ent, n_book)
        if not self._grp_scroll_bound:
            self._grp_scroll_bound = True
            handler = getattr(self, "_grp_list_scroll_handler", None)
            if handler:
                bind_scroll_tree_once(self._grp_rows, handler)

    def _apply_address_entry_update(self, updated: AddressEntry) -> None:
        for i, ent in enumerate(self._cfg.address_book):
            if ent.id == updated.id:
                self._cfg.address_book[i] = updated
                break
        else:
            return
        self._optional_merge_global_api_from_ui()
        save_config(self._cfg)
        self._patch_group_rows()
        self._mark_schedule_targets_dirty()
        info_i18n("log.address_updated_remark", remark=updated.remark)
        if self._coord is not None and self._coord.has_connected_clients():
            self._coord.apply_config_hot(self._cfg)

    def _open_address_edit_dialog(self, entry_id: str) -> None:
        ent = next((e for e in self._cfg.address_book if e.id == entry_id), None)
        if ent is None:
            return
        try:
            if self._address_edit_dlg is not None and self._address_edit_dlg.winfo_exists():
                self._address_edit_dlg.focus()
                return
        except Exception:
            pass
        self._address_edit_dlg = AddressEditDialog(
            self.winfo_toplevel(),
            entry=ent,
            owner_values=self._owner_account_values(),
            on_save=self._apply_address_entry_update,
            on_delete=lambda eid=entry_id: self._del_address_entry(eid),
        )

    def _add_address_entry(self) -> None:
        remark = self._addr_remark.get().strip()
        g = self._addr_chat.get().strip()
        u = self._addr_user.get().strip()
        listen_on = bool(self._addr_listen.get())
        if not remark or not g:
            info_i18n("addr_edit.save_required")
            return
        try:
            parse_chat_ref_input(g)
        except ValueError as exc:
            info_i18n("addr_edit.chat_invalid")
            return
        if listen_on:
            if not u:
                info_i18n("log.watch_user_required")
                return
            try:
                parse_watch_user_input(u)
            except ValueError:
                info_i18n("log.watch_user_invalid_tg")
                return
        elif u:
            try:
                parse_watch_user_input(u)
            except ValueError:
                info_i18n("addr_edit.user_invalid")
                return
        acc_vals = self._owner_account_values()
        if not acc_vals:
            info_i18n("log.need_account_first")
            return
        owner = ""
        if getattr(self, "_addr_owner", None) is not None:
            owner = self._addr_owner.get().strip()
        if owner in ("", "—", t("grp.please_select")):
            owner = acc_vals[0]
        if owner not in acc_vals:
            info_i18n("log.need_owner_account")
            return
        ent = AddressEntry(
            id=uuid.uuid4().hex[:12],
            remark=remark,
            chat_ref=g.strip(),
            watch_user=u.strip() if u else "",
            listen_enabled=listen_on,
            owner_account_id=owner,
        )
        self._cfg.address_book.append(ent)
        self._addr_remark.delete(0, "end")
        self._addr_chat.delete(0, "end")
        self._addr_user.delete(0, "end")
        self._addr_listen.set(True)
        if acc_vals:
            self._addr_owner.set(acc_vals[0])
        try:
            self._commit_address_book()
            info_i18n("log.address_added_owner", remark=remark, owner=owner)
        except Exception as exc:
            error_i18n("log.address_add_fail", err=exc)
            self._cfg.address_book = [e for e in self._cfg.address_book if e.id != ent.id]

    def _del_address_entry(self, entry_id: str) -> None:
        removed = next((e for e in self._cfg.address_book if e.id == entry_id), None)
        self._cfg.address_book = [e for e in self._cfg.address_book if e.id != entry_id]
        self._sync_jobs_after_address_entry_removed(entry_id)
        self._commit_address_book()
        if removed is not None:
            info_i18n("log.address_removed", name=removed.remark or removed.id)
        else:
            info_i18n("log.address_removed_simple")

    def _sync_jobs_after_address_entry_removed(self, entry_id: str) -> None:
        """通讯录删群后，同步清理任务目标并移除空目标任务。"""
        eid = (entry_id or "").strip()
        if not eid:
            return
        jobs = load_jobs()
        if not jobs:
            return
        kept: List[ScheduledJob] = []
        changed = 0
        removed = 0
        for j in jobs:
            before = [str(x) for x in (j.chat_entry_ids or []) if str(x).strip()]
            after = [x for x in before if x != eid]
            if len(after) != len(before):
                j.chat_entry_ids = after
                changed += 1
            # 仅按通讯录目标发送的任务，如果条目被删后无目标，则删除该任务
            if not j.chat_entry_ids and not j.chat_ids:
                removed += 1
                continue
            kept.append(j)
        if changed == 0 and removed == 0:
            return
        save_jobs(kept)
        if removed > 0:
            info_i18n("log.address_sync_both", changed=changed, removed=removed)
        else:
            info_i18n("log.address_sync_updated", changed=changed)
        if self._sched_edit_job_id and all(j.id != self._sched_edit_job_id for j in kept):
            self._sched_edit_job_id = None
        self._render_jobs(full=True)
        self._render_taskmgr_cards(force=True)

    def _clear_sched_target_selection(self) -> None:
        for _ent, var in getattr(self, "_sched_target_rows", []):
            var.set(False)
        for v in getattr(self, "_sched_target_vars", []):
            v.set(False)

    def _refresh_schedule_target_checks(self) -> None:
        """定时任务页：按通讯录生成群发目标勾选框。"""
        if getattr(self, "_sched_targets", None) is None:
            return
        sync_last_schedule_from_disk(self._cfg)
        jobs = load_jobs()
        for ch in self._sched_targets.winfo_children():
            ch.destroy()
        self._sched_target_vars = []
        self._sched_target_rows = []
        if not self._cfg.address_book:
            ctk.CTkLabel(self._sched_targets, text=t("grp.no_groups_hint"), text_color=COLORS["muted"]).pack(anchor="w", padx=4, pady=6)
            return
        for ent in self._cfg.address_book:
            v = ctk.BooleanVar(value=False)
            self._sched_target_vars.append(v)
            self._sched_target_rows.append((ent, v))
            owner = (ent.owner_account_id or "").strip()
            own_hint = t("grp.owner_hint", owner=owner) if owner else ""
            kind_hint = entry_schedule_kind_hint(jobs, ent.id)
            last_fn = (getattr(ent, "last_schedule_source_name", "") or "").strip()
            last_hint = t("grp.last_task", name=last_fn) if last_fn else t("grp.last_task_empty")
            disp = f"{ent.remark.strip() or ent.id}{own_hint}{kind_hint}   （{ent.chat_ref}{last_hint}）"
            ctk.CTkCheckBox(
                self._sched_targets,
                text=disp,
                variable=v,
                text_color=COLORS["text"],
            ).pack(anchor="w", padx=4, pady=4)

    # --- rules ---
    def _page_rules(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        wrap, finish_scroll = self._mount_main_scroll(page)
        ctk.CTkLabel(wrap, text=t("rules.title_tg"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=(8, 16))

        box = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        box.pack(fill="x")
        lang_row = ctk.CTkFrame(box, fg_color="transparent")
        lang_row.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(lang_row, text=t("rules.lang_label"), text_color=COLORS["muted"]).pack(side="left")
        self._lang_combo = ctk.CTkComboBox(
            lang_row,
            width=140,
            values=list(lang_combo_labels()),
            command=self._on_lang_combo_changed,
        )
        self._lang_combo.pack(side="left", padx=(8, 0))
        self._lang_combo.set(combo_label_for_lang(get_lang()))
        ctk.CTkLabel(
            box,
            text=t("rules.lang_hint"),
            text_color=COLORS["muted"],
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=14, pady=(0, 8))
        self._listen_var = ctk.BooleanVar(value=self._cfg.listening_enabled)
        ctk.CTkCheckBox(
            box,
            text=t("rules.enable_listen_tg"),
            variable=self._listen_var,
            command=lambda: setattr(self._cfg, "listening_enabled", bool(self._listen_var.get())),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=14, pady=(12, 4))
        self._stage_popup_var = ctk.BooleanVar(value=getattr(self._cfg, "stage_reminder_popup_enabled", True))
        ctk.CTkCheckBox(
            box,
            text=t("rules.stage_popup"),
            variable=self._stage_popup_var,
            command=lambda: setattr(
                self._cfg, "stage_reminder_popup_enabled", bool(self._stage_popup_var.get())
            ),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=14, pady=(0, 12))

        ctk.CTkLabel(box, text=t("rules.rate_limit"), text_color=COLORS["muted"]).pack(anchor="w", padx=14, pady=(4, 6))
        self._rate_entry = ctk.CTkEntry(box, placeholder_text=t("rules.rate_limit_ph"))
        self._rate_entry.insert(0, str(self._cfg.rate_limit_seconds))
        self._rate_entry.pack(fill="x", padx=14, pady=(0, 14))

        def save_rate(*_a: object) -> None:
            try:
                self._cfg.rate_limit_seconds = float(self._rate_entry.get().strip())
            except ValueError:
                pass

        self._rate_entry.bind("<FocusOut>", save_rate)

        sync_box = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        sync_box.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(
            sync_box,
            text=t("rules.sync_hint"),
            text_color=COLORS["muted"],
            wraplength=640,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 8))
        ctk.CTkButton(
            sync_box,
            text=t("rules.sync_btn"),
            fg_color=COLORS["accent"],
            hover_color="#3d7ae6",
            command=self._sync_last_schedule_from_jobs,
        ).pack(fill="x", padx=14, pady=(0, 14))

        audit_box = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        audit_box.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(
            audit_box,
            text=t("rules.audit_hint"),
            text_color=COLORS["muted"],
            wraplength=640,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 8))
        ctk.CTkButton(
            audit_box,
            text=t("rules.audit_btn"),
            fg_color=COLORS["accent"],
            hover_color="#3d7ae6",
            command=self._check_watch_memberships,
        ).pack(fill="x", padx=14, pady=(0, 14))
        finish_scroll()
        return page

    def _on_lang_combo_changed(self, choice: str) -> None:
        lang = lang_from_combo_label(choice)
        set_lang_for_next_launch(lang)
        info_i18n("rules.lang_saved", lang=combo_label_for_lang(lang))

    def _check_watch_memberships(self) -> None:
        if not self._coord or not self._coord.has_connected_clients():
            info_i18n("log.audit_need_login_tg")
            return
        info_i18n("log.audit_start")

        def on_done(result: Dict[str, WatchAuditRow]) -> None:
            self.after(0, lambda: self._apply_watch_membership_audit(result))

        if not self._coord.request_watch_membership_audit(self._cfg, on_done):
            info_i18n("log.audit_no_online")

    def _apply_watch_membership_audit(self, result: Dict[str, WatchAuditRow]) -> None:
        self._watch_audit_flags = {eid: row.status.value for eid, row in result.items()}
        ok = sum(1 for r in result.values() if r.status == WatchAuditStatus.OK)
        absent = sum(1 for r in result.values() if r.status == WatchAuditStatus.ABSENT)
        err = sum(1 for r in result.values() if r.status == WatchAuditStatus.ERROR)
        offline = sum(1 for r in result.values() if r.status == WatchAuditStatus.OFFLINE)
        self._render_group_rows(force=True)
        if not result:
            info_i18n("log.audit_incomplete")
            return
        parts = [t("log.audit_checked", n=ok + absent)]
        if absent:
            parts.append(t("log.audit_absent", n=absent))
        if err:
            parts.append(t("log.audit_failed", n=err))
        if offline:
            parts.append(t("log.audit_offline", n=offline))
        info(t("log.audit_summary", summary="；".join(parts)))

    def _sync_last_schedule_from_jobs(self) -> None:
        before = {e.id: (e.last_schedule_source_name or "").strip() for e in self._cfg.address_book}
        n_jobs = len(load_jobs())
        apply_last_schedule_from_current_jobs(self._cfg)
        n_changed = sum(
            1
            for e in self._cfg.address_book
            if before.get(e.id, "") != (e.last_schedule_source_name or "").strip()
        )
        n_filled = sum(1 for e in self._cfg.address_book if (e.last_schedule_source_name or "").strip())
        self._sched_targets_dirty = False
        self._refresh_schedule_target_checks()
        if n_changed:
            info_i18n(
                "log.sync_last_changed",
                n_jobs=n_jobs,
                n_changed=n_changed,
                n_filled=n_filled,
                n_empty=len(self._cfg.address_book) - n_filled,
            )
        else:
            info_i18n("log.sync_last_unchanged", n_jobs=n_jobs, n_filled=n_filled)

    # --- schedule ---
    def _schedule_doc_path(self) -> str:
        p = resource_path("docs", "定时任务导入说明与示例.txt")
        if os.path.isfile(p):
            return p
        alt = os.path.join(app_root(), "docs", "定时任务导入说明与示例.txt")
        return alt if os.path.isfile(alt) else p

    def _open_schedule_import_doc(self) -> None:
        path = self._schedule_doc_path()
        if os.path.isfile(path):
            webbrowser.open(Path(path).as_uri())
        else:
            info_i18n("log.doc_sample_not_found", path=path)

    def _page_schedule(self) -> ctk.CTkFrame:
        """群勾选在滚动区；间隔/TXT/添加固定在页底，勾群时无需来回滚动。"""
        page = ctk.CTkFrame(self._content, fg_color="transparent")

        sched_foot = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        sf = ctk.CTkFrame(sched_foot, fg_color="transparent")
        sf.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(
            sf,
            text=t("sched.fixed_interval"),
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(0, 4))
        self._sched_interval = ctk.CTkEntry(sf, placeholder_text="5-10")
        self._sched_interval.insert(0, "5-10")
        self._sched_interval.pack(fill="x", pady=(0, 6))
        self._jfile = ctk.CTkEntry(sf, placeholder_text=t("sched.file_ph"))
        self._jfile.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(sf, text=t("sched.pick_source"), fg_color=COLORS["border"], command=self._pick_schedule_source).pack(fill="x", pady=(0, 6))
        ctk.CTkButton(sf, text=t("sched.add_job"), fg_color=COLORS["accent"], command=self._add_job).pack(fill="x")

        wrap, finish_scroll = self._mount_main_scroll(page, footer=sched_foot)
        ctk.CTkLabel(wrap, text=t("sched.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=8)
        sched_intro = ctk.CTkLabel(
            wrap,
            text=t("sched.tg_hint"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        )
        sched_intro.pack(anchor="w", pady=(0, 8))
        ctk.CTkButton(
            wrap,
            text=t("sched.txt_format_tg"),
            fg_color=COLORS["border"],
            command=lambda: webbrowser.open(Path(self._schedule_doc_path()).as_uri()) if os.path.isfile(self._schedule_doc_path()) else info_i18n("log.doc_sample_not_found", path=self._schedule_doc_path()),
        ).pack(anchor="w", pady=4)

        form = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        form.pack(fill="x", pady=8)
        ctk.CTkLabel(form, text=t("sched.targets"), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=(10, 4))
        self._sched_targets = ctk.CTkFrame(form, fg_color="transparent")
        self._sched_targets.pack(fill="x", padx=10, pady=(4, 12))

        edit_card = ctk.CTkFrame(wrap, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        edit_card.pack(fill="x", pady=8)
        ctk.CTkLabel(
            edit_card,
            text=t("sched.bulk_title"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=12, pady=(12, 8))
        pick_row = ctk.CTkFrame(edit_card, fg_color="transparent")
        pick_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(pick_row, text=t("sched.pick_job"), text_color=COLORS["muted"]).pack(side="left", padx=(0, 8))
        self._sched_job_pick = ctk.CTkComboBox(pick_row, width=280, values=["—"], command=self._on_sched_job_pick_changed)
        self._sched_job_pick.pack(side="left", fill="x", expand=True)
        bulk_row = ctk.CTkFrame(edit_card, fg_color="transparent")
        bulk_row.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkLabel(bulk_row, text=t("sched.from_account"), text_color=COLORS["muted"]).grid(row=0, column=0, padx=(0, 8), pady=4, sticky="w")
        self._sched_bulk_from_combo = ctk.CTkComboBox(bulk_row, width=160, values=["—"])
        self._sched_bulk_from_combo.grid(row=0, column=1, pady=4, sticky="w")
        ctk.CTkLabel(bulk_row, text=t("sched.to_account_tg"), text_color=COLORS["muted"]).grid(row=1, column=0, padx=(0, 8), pady=4, sticky="w")
        acc0 = self._account_id_values()
        self._sched_bulk_to_combo = ctk.CTkComboBox(bulk_row, width=160, values=acc0)
        self._sched_bulk_to_combo.grid(row=1, column=1, pady=4, sticky="w")
        ctk.CTkButton(bulk_row, text=t("sched.bulk_replace"), fg_color=COLORS["border"], command=self._schedule_bulk_replace_by_original).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=8
        )

        self._sched_target_vars = []
        self._refresh_schedule_target_checks()

        sched_note = ctk.CTkLabel(
            wrap,
            text=t("sched.status_hint"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        )
        sched_note.pack(anchor="w", pady=(8, 4))
        self._elastic_wraplabels(wrap, [sched_intro, sched_note])
        finish_scroll()
        return page

    def _page_task_manager(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        wrap, finish_scroll = self._mount_main_scroll(page)
        ctk.CTkLabel(wrap, text=t("taskmgr.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", pady=(8, 4)
        )
        ctk.CTkLabel(
            wrap,
            text=t("taskmgr.legend"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        self._taskmgr_count_lbl = ctk.CTkLabel(
            wrap,
            text=t("taskmgr.count.total", total=0),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        self._taskmgr_count_lbl.pack(anchor="w", pady=(0, 10))
        ctk.CTkButton(
            wrap,
            text=t("taskmgr.resume_all"),
            fg_color=COLORS["accent"],
            hover_color="#3d7ae6",
            height=40,
            command=self._resume_all_doc_jobs,
        ).pack(fill="x", pady=(0, 10))
        ctk.CTkButton(
            wrap,
            text=t("taskmgr.next_day"),
            fg_color="#5a4a12",
            hover_color="#6d5a18",
            height=38,
            command=lambda: self.after(10, self._start_next_folder_day),
        ).pack(fill="x", pady=(0, 10))
        self._btn_manual_folder_day = ctk.CTkButton(
            wrap,
            text=t("taskmgr.manual_day"),
            fg_color="#2a4a5a",
            hover_color="#356878",
            height=38,
            command=self._toggle_manual_folder_advance_mode,
        )
        self._btn_manual_folder_day.pack(fill="x", pady=(0, 10))
        img_row = ctk.CTkFrame(wrap, fg_color="transparent")
        img_row.pack(fill="x", pady=(0, 10))
        img_row.grid_columnconfigure(0, weight=1)
        img_row.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            img_row,
            text=t("img.btn"),
            fg_color="#4a3060",
            hover_color="#5c3c78",
            height=38,
            command=lambda: self.after(10, self._one_click_send_images),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            img_row,
            text=t("img.btn_sync"),
            fg_color="#3a4060",
            hover_color="#4a5078",
            height=38,
            command=lambda: self.after(10, self._one_click_send_images_sync),
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ctk.CTkButton(
            wrap,
            text=t("taskmgr.delete_all"),
            fg_color=COLORS["danger"],
            hover_color="#b63a3a",
            height=38,
            command=self._delete_all_jobs,
        ).pack(fill="x", pady=(0, 10))
        self._taskmgr_cards = ctk.CTkFrame(wrap, fg_color="transparent")
        self._taskmgr_cards.pack(fill="both", expand=True, pady=4)
        self._render_taskmgr_cards(force=True)
        finish_scroll()
        return page

    def _doc_job_is_running(self, j: ScheduledJob) -> bool:
        return bool(j.enabled) and j.state == "running"

    def _doc_job_status_label(self, j: ScheduledJob) -> str:
        return format_job_status_label(
            enabled=bool(j.enabled),
            state=j.state,
            pause_reason=j.pause_reason or "",
        )

    def _doc_job_step_label(self, j: ScheduledJob) -> str:
        total = j.item_count()
        if total <= 0:
            return t("job_step.none")
        if is_await_image_send(j.pause_reason or ""):
            step_no = max(1, int(j.cursor or 0))
            return t("job_step.image", cur=min(step_no, total), total=total)
        if j.cursor >= total:
            return t("job_step.done", cur=total, total=total)
        step_no = j.cursor + 1
        item = j.current_item()
        if item is None:
            return t("job_step.item", cur=step_no, total=total, preview="")
        if item.is_reminder:
            return t("job_step.reminder", cur=step_no, total=total)
        if getattr(item, "is_image_send", False):
            return t("job_step.image", cur=step_no, total=total)
        preview = (item.content or "").replace("\n", " ").strip()[:28]
        return t("job_step.item", cur=step_no, total=total, preview=preview or t("job_step.ellipsis"))

    def _bind_taskmgr_card_click(self, widget: ctk.CTkBaseClass, job_id: str) -> None:
        if isinstance(widget, ctk.CTkButton):
            return

        def on_click(_event: Any = None) -> None:
            if self._manual_folder_advance_mode:
                self._manual_advance_folder_day_by_id(job_id)
            else:
                self._toggle_job_run_by_id(job_id)

        widget.bind("<Button-1>", on_click)
        for child in widget.winfo_children():
            self._bind_taskmgr_card_click(child, job_id)

    def _taskmgr_fingerprint(self, j: ScheduledJob) -> tuple:
        return (
            self._doc_job_is_running(j),
            j.enabled,
            j.state,
            (j.pause_reason or "")[:40],
            j.cursor,
            j.source_name,
            getattr(j, "folder_day_index", 0),
            is_folder_job(j),
            self._doc_job_step_label(j),
            self._job_target_short(j),
            self._task_reminder_summary(j),
        )

    def _task_reminder_summary(self, j: ScheduledJob) -> str:
        return operator_note_for_items(j.items, cursor=int(j.cursor or 0), max_len=56)

    def _apply_taskmgr_tile(self, w: Dict[str, Any], j: ScheduledJob) -> None:
        running = self._doc_job_is_running(j)
        pal = taskmgr_tile_palette(running=running, enabled=bool(j.enabled), pause_reason=j.pause_reason or "")
        w["card"].configure(fg_color=pal["fg"], border_color=pal["border"])
        w["title"].configure(text=self._job_target_short(j), text_color=pal["title"])
        w["status"].configure(
            text=taskmgr_card_status_text(
                self._doc_job_status_label(j),
                self._doc_job_step_label(j),
            ),
            text_color=pal["status"],
        )
        w["file"].configure(
            text=taskmgr_job_file_label(j),
            text_color=pal["file"],
        )
        rem = self._task_reminder_summary(j)
        rem_c = "#1f2328"
        rem_bg = "#ffd24a"
        w["reminder_box"].configure(fg_color=rem_bg)
        w["reminder"].configure(
            text=(t("taskmgr.note", text=rem) if rem else t("taskmgr.note_none")),
            text_color=rem_c if rem else "#5c4a00",
        )
        hint = t("taskmgr.hint_pause") if running else (t("taskmgr.hint_resume") if j.enabled else t("taskmgr.hint_restart"))
        if self._manual_folder_advance_mode and is_folder_job(j):
            hint = (
                t("taskmgr.hint_next_day")
                if can_advance_folder_day(j)
                else t("taskmgr.hint_last_day")
            )
        w["hint"].configure(text=hint, text_color=pal["hint"])

    def _build_taskmgr_tile(self, j: ScheduledJob, index: int) -> Dict[str, Any]:
        running = self._doc_job_is_running(j)
        pal = taskmgr_tile_palette(running=running, enabled=bool(j.enabled), pause_reason=j.pause_reason or "")
        fonts = taskmgr_fonts()
        card = ctk.CTkFrame(
            self._taskmgr_cards,
            fg_color=pal["fg"],
            corner_radius=10,
            border_width=2,
            border_color=pal["border"],
            height=168,
        )
        grid_place(card, index, TASKMGR_COLS, padx=6, pady=6)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=10, pady=10)
        head = ctk.CTkFrame(inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 4))
        title = ctk.CTkLabel(
            head,
            text=self._job_target_short(j),
            font=fonts["title"],
            text_color=pal["title"],
            anchor="w",
            wraplength=160,
            justify="left",
        )
        title.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            head,
            text=t("common.delete"),
            width=52,
            height=24,
            font=fonts["btn"],
            fg_color="#8b2e2e",
            hover_color="#a83232",
            command=lambda jid=j.id: self._del_job_by_id(jid),
        ).pack(side="right", padx=(4, 0))
        body = ctk.CTkFrame(inner, fg_color="transparent")
        body.pack(fill="both", expand=True)
        status = ctk.CTkLabel(
            body,
            text="",
            font=fonts["status"],
            anchor="w",
            wraplength=200,
            justify="left",
        )
        status.pack(fill="x", pady=(0, 4))
        file_lbl = ctk.CTkLabel(
            body,
            text="",
            font=fonts["body"],
            anchor="w",
            wraplength=200,
            justify="left",
        )
        file_lbl.pack(fill="x", pady=(0, 2))
        reminder_box = ctk.CTkFrame(body, corner_radius=6, fg_color="#ffd24a")
        reminder_box.pack(fill="x", pady=(2, 3))
        reminder_lbl = ctk.CTkLabel(
            reminder_box,
            text="",
            font=fonts["reminder"],
            anchor="w",
            wraplength=188,
            justify="left",
        )
        reminder_lbl.pack(fill="x", padx=6, pady=4)
        hint = ctk.CTkLabel(
            body,
            text="",
            font=fonts["hint"],
            text_color="#e9e9e9",
            anchor="w",
        )
        hint.pack(fill="x")
        widgets = {
            "card": card,
            "title": title,
            "status": status,
            "file": file_lbl,
            "reminder_box": reminder_box,
            "reminder": reminder_lbl,
            "hint": hint,
        }
        self._apply_taskmgr_tile(widgets, j)
        self._bind_taskmgr_card_click(card, j.id)
        return widgets

    def _full_rebuild_taskmgr_grid(self, jobs: List[ScheduledJob]) -> None:
        for w in self._taskmgr_cards.winfo_children():
            w.destroy()
        self._taskmgr_widgets.clear()
        self._taskmgr_fp_cache.clear()
        configure_equal_columns(self._taskmgr_cards, TASKMGR_COLS, uniform="tg_task")
        for i, j in enumerate(jobs):
            self._taskmgr_widgets[j.id] = self._build_taskmgr_tile(j, i)
            self._taskmgr_fp_cache[j.id] = self._taskmgr_fingerprint(j)

    def _patch_taskmgr_cards(
        self,
        job_ids: Iterable[str],
        *,
        reorder: bool = True,
        job_overrides: Optional[Dict[str, ScheduledJob]] = None,
    ) -> None:
        """只更新指定卡片的文案/颜色；可选重排一次（保留置顶规则）。"""
        if getattr(self, "_taskmgr_cards", None) is None:
            return
        unique_ids = list(dict.fromkeys(job_ids))
        if not unique_ids:
            return
        overrides = dict(job_overrides or {})
        jobs = load_jobs()
        job_map = {j.id: j for j in jobs}
        job_map.update(overrides)
        merged_jobs: List[ScheduledJob] = []
        seen: Set[str] = set()
        for j in jobs:
            merged_jobs.append(job_map[j.id])
            seen.add(j.id)
        for jid, oj in overrides.items():
            if jid not in seen:
                merged_jobs.append(oj)
        for jid in unique_ids:
            j = job_map.get(jid)
            if j is None:
                continue
            w = self._taskmgr_widgets.get(jid)
            if w is None:
                continue
            self._taskmgr_fp_cache[jid] = self._taskmgr_fingerprint(j)
            self._apply_taskmgr_tile(w, j)
        self._update_taskmgr_count_label(merged_jobs)
        if reorder:
            self._sync_taskmgr_display_order(merged_jobs)

    def _refresh_taskmgr_card(self, job_id: str) -> None:
        """单卡暂停/继续：只 patch 该卡并重排。"""
        if getattr(self, "_taskmgr_cards", None) is None:
            return
        jobs = load_jobs()
        if next((x for x in jobs if x.id == job_id), None) is None:
            self._render_taskmgr_cards(force=True)
            return
        if self._taskmgr_widgets.get(job_id) is None:
            self._sync_taskmgr_page()
            return
        self._patch_taskmgr_cards([job_id], reorder=True)

    def _sync_taskmgr_page(self) -> None:
        """进入任务管理页时手动同步（非定时刷新）。"""
        if getattr(self, "_taskmgr_cards", None) is None:
            return
        jobs = load_jobs()
        if not jobs:
            self._render_taskmgr_cards(force=False)
            return
        ids = [j.id for j in jobs]
        if ids != self._taskmgr_listed_ids:
            self._render_taskmgr_cards(force=True)
            return
        self._patch_taskmgr_cards([j.id for j in jobs], reorder=True)

    def _sync_taskmgr_display_order(self, jobs: List[ScheduledJob]) -> None:
        display_jobs = taskmgr_sort_jobs_for_display(jobs, is_running=self._doc_job_is_running)
        display_ids = [j.id for j in display_jobs]
        if display_ids == self._taskmgr_display_ids:
            return
        reorder_taskmgr_grid(self._taskmgr_widgets, display_jobs, cols=TASKMGR_COLS, padx=6, pady=6)
        self._taskmgr_display_ids = display_ids

    def _update_taskmgr_count_label(self, jobs: List[ScheduledJob]) -> None:
        lbl = getattr(self, "_taskmgr_count_lbl", None)
        if lbl is None:
            return
        counts = taskmgr_count_jobs(jobs, is_running=self._doc_job_is_running)
        lbl.configure(text=format_taskmgr_count_summary(counts))

    def _refresh_job_run_ui(self, job_id: str) -> None:
        """任务卡片 + 定时任务页控件同步刷新（暂停/继续后）。"""
        self._refresh_taskmgr_card(job_id)
        j = next((x for x in load_jobs() if x.id == job_id), None)
        if j is None:
            return
        w = self._sched_job_row_widgets.get(job_id)
        if not w:
            return
        self._sched_job_fingerprints[job_id] = self._sched_job_fingerprint(j)
        w["detail"].configure(text=self._job_detail_text(j))
        w["btn_run"].configure(text=(t("taskmgr.hint_resume") if j.state == "paused" else t("taskmgr.hint_pause")))
        w["btn_en"].configure(text=(t("dash.disabled") if j.enabled else t("dash.enabled")))

    def _render_taskmgr_cards(self, *, force: bool = False) -> None:
        """增删任务或结构变化时重建网格；不做定时刷新，也不联动定时任务页控件。"""
        if getattr(self, "_taskmgr_cards", None) is None:
            return
        jobs = load_jobs()
        ids = [j.id for j in jobs]
        if not jobs:
            if self._taskmgr_listed_ids:
                for w in self._taskmgr_cards.winfo_children():
                    w.destroy()
                self._taskmgr_widgets.clear()
                self._taskmgr_fp_cache.clear()
                self._taskmgr_listed_ids = []
                self._taskmgr_display_ids = []
            if not self._taskmgr_cards.winfo_children():
                ctk.CTkLabel(
                    self._taskmgr_cards,
                    text=t("taskmgr.empty_doc"),
                    text_color=COLORS["muted"],
                ).grid(row=0, column=0, columnspan=TASKMGR_COLS, sticky="w", padx=8, pady=12)
            self._update_taskmgr_count_label(jobs)
            return
        display_jobs = taskmgr_sort_jobs_for_display(jobs, is_running=self._doc_job_is_running)
        display_ids = [j.id for j in display_jobs]
        if force or ids != self._taskmgr_listed_ids:
            self._taskmgr_listed_ids = ids
            self._full_rebuild_taskmgr_grid(display_jobs)
            self._taskmgr_display_ids = display_ids
        self._update_taskmgr_count_label(jobs)
        handler = getattr(self, "_scroll_wheel_handler", None)
        if handler:
            bind_scroll_tree_once(self._taskmgr_cards, handler)

    def _one_click_send_images(self) -> None:
        self._one_click_send_images_flow(sync_to_customer=False, customer_extra_text="")

    def _one_click_send_images_sync(self) -> None:
        if getattr(self, "_bulk_image_busy", False):
            info_i18n("img.busy")
            return
        extra = self._prompt_customer_extra_text()
        if extra is None:
            return
        self._one_click_send_images_flow(sync_to_customer=True, customer_extra_text=extra)

    def _prompt_customer_extra_text(self) -> Optional[str]:
        """同步客户附加文字输入框。返回 None=取消；空字符串=不附加文字。"""
        return prompt_text_with_skip(
            self,
            t("img.extra_title"),
            t("img.extra_hint"),
            ok_text=t("img.extra_ok"),
            skip_text=t("img.extra_skip"),
            cancel_text=t("img.cancel"),
        )

    def _one_click_send_images_flow(
        self, *, sync_to_customer: bool, customer_extra_text: str
    ) -> None:
        if getattr(self, "_bulk_image_busy", False):
            info_i18n("img.busy")
            return
        jobs = collect_awaiting_image_jobs(load_jobs())
        if not jobs:
            title = "img.btn_sync" if sync_to_customer else "img.btn"
            msg_info(self, title, "img.none")
            return
        groups = group_awaiting_by_day(jobs)
        labels: List[str] = []
        for g in groups:
            n = len(g.jobs)
            notes = notes_for_awaiting_jobs(g.jobs)
            notes_part = t("img.day_notes", text=notes) if notes else ""
            labels.append(
                t("img.day_group", day=g.day_1based, n=n, notes=notes_part)
                if g.day_1based > 0
                else t("img.day_other", n=n, notes=notes_part)
            )
        idx = pick_button_option(
            self,
            t("img.pick_day"),
            labels,
            cancel_text=t("img.cancel"),
        )
        if idx is None or idx < 0 or idx >= len(groups):
            return
        g = groups[idx]
        run_after_modal_closed(
            self,
            280,
            lambda: self._start_bulk_image_for_group(
                g.day_1based,
                list(g.jobs),
                sync_to_customer=sync_to_customer,
                customer_extra_text=customer_extra_text,
            ),
        )

    def _start_bulk_image_for_group(
        self,
        day: int,
        group_jobs: List[ScheduledJob],
        *,
        sync_to_customer: bool = False,
        customer_extra_text: str = "",
    ) -> None:
        n = len(group_jobs)
        if n <= 0:
            return
        title_key = "img.btn_sync" if sync_to_customer else "img.btn"
        if sync_to_customer:
            body_key = "img.confirm_sync" if day > 0 else "img.confirm_sync_other"
        else:
            body_key = "img.confirm" if day > 0 else "img.confirm_other"
        kwargs = {"n": n, "day": day} if day > 0 else {"n": n}
        release_modal_grabs(self)
        if not msg_askyesno(self, title_key, body_key, **kwargs):
            return
        run_after_modal_closed(
            self,
            300,
            lambda: self._bulk_image_after_pick(
                day,
                group_jobs,
                sync_to_customer=sync_to_customer,
                customer_extra_text=customer_extra_text,
                title_key=title_key,
            ),
        )

    def _bulk_image_after_pick(
        self,
        day: int,
        group_jobs: List[ScheduledJob],
        *,
        sync_to_customer: bool,
        customer_extra_text: str,
        title_key: str,
    ) -> None:
        selected = pick_image_files(self, title=t("img.pick_files"))
        if not selected:
            return
        if len(selected) > MAX_BULK_IMAGES:
            msg_info(self, title_key, "img.too_many", max_n=MAX_BULK_IMAGES)
            return
        coord = self._coord
        if coord is None or not getattr(coord, "request_bulk_image_send", None):
            info_i18n("log.coord_not_running")
            return
        self._bulk_image_busy = True
        if sync_to_customer:
            info_i18n("img.busy_sync")
        else:
            info_i18n("img.busy_multi", count=len(selected))
        job_ids = [j.id for j in group_jobs]
        target_map = {j.id: self._job_target_short(j) for j in group_jobs}

        def on_progress(i: int, total: int, res: Any) -> None:
            status = "ok" if getattr(res, "ok", False) else f"fail:{getattr(res, 'error', '')}"
            tgt = target_map.get(getattr(res, "job_id", ""), getattr(res, "job_id", ""))

            def ui() -> None:
                info(t("img.progress", i=i, total=total, target=tgt, status=status))

            try:
                self.after(0, ui)
            except Exception:
                pass

        def on_done(ok: int, fail: int, resumed: int) -> None:
            def ui() -> None:
                self._bulk_image_busy = False
                info(t("img.done", ok=ok, fail=fail, resumed=resumed))
                self._render_taskmgr_cards(force=True)

            try:
                self.after(0, ui)
            except Exception:
                self._bulk_image_busy = False

        if not coord.request_bulk_image_send(
            job_ids,
            image_paths=selected,
            on_progress=on_progress,
            on_done=on_done,
            sync_to_customer=sync_to_customer,
            customer_extra_text=customer_extra_text,
        ):
            self._bulk_image_busy = False
            info_i18n("log.coord_not_running")

    def _resume_all_doc_jobs(self) -> None:
        jobs = load_jobs()
        resumable, skipped = bulk_resume_job_counts(jobs)
        if resumable <= 0:
            running = sum(1 for j in jobs if self._doc_job_is_running(j))
            if running > 0:
                info_i18n("log.resume_all_connected", running=running)
            elif skipped > 0:
                info_i18n("log.resume_all_none_skipped", skipped=skipped)
            else:
                info_i18n("log.resume_all_none")
            return
        skipped_line = t("msgbox.resume_all.skipped", skipped=skipped) if skipped > 0 else ""
        body_kwargs = {"resumable": resumable, "skipped_line": skipped_line}
        if not msg_askyesno(self, "msgbox.resume_all.title", "msgbox.resume_all.body_doc", **body_kwargs):
            return
        n = self._scheduler.resume_all_jobs()
        self._cfg = load_config()
        self._refresh_schedule_target_checks()
        jobs = load_jobs()
        if jobs and self._taskmgr_listed_ids == [j.id for j in jobs]:
            self._patch_taskmgr_cards([j.id for j in jobs], reorder=True)
        else:
            self._render_taskmgr_cards(force=True)
        self._render_jobs()
        if n > 0:
            self._warn_if_tg_session_down()
            if skipped > 0:
                info_i18n("log.resume_all_doc_done_skipped", n=n, skipped=skipped)
            else:
                info_i18n("log.resume_all_doc_done", n=n)
            return
        info_i18n("log.resume_all_none")

    def _pick_schedule_source(self) -> None:
        cur = self._jfile.get() if getattr(self, "_jfile", None) else ""
        path = pick_txt_or_folder(self, current_path=cur)
        if path:
            self._jfile.delete(0, "end")
            self._jfile.insert(0, path)

    def _parse_interval_minutes(self, s: str) -> Optional[tuple[float, float]]:
        raw = (s or "").strip()
        if not raw:
            return None
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$", raw)
        if m:
            a = float(m.group(1))
            b = float(m.group(2))
            if a <= 0 or b <= 0:
                return None
            if b < a:
                a, b = b, a
            return (a, b)
        if re.match(r"^\d+(?:\.\d+)?$", raw):
            x = float(raw)
            if x <= 0:
                return None
            return (x, x)
        return None

    def _sched_add_fail(self, key: str, **kwargs: object) -> None:
        if "." in key and not key.startswith("\n"):
            info_i18n(key, **kwargs)
            try:
                msg_info(self, "msgbox.cannot_add_doc.title", key, **kwargs)
            except Exception:
                pass
        else:
            info(key)
            try:
                show_message(self, t("msgbox.cannot_add_doc.title"), key)
            except Exception:
                pass

    def _add_job(self) -> None:
        selected_ids: List[str] = []
        rows = getattr(self, "_sched_target_rows", None) or []
        if rows:
            for ent, var in rows:
                if var.get():
                    selected_ids.append(ent.id)
        else:
            vars_list = getattr(self, "_sched_target_vars", []) or []
            for i, ent in enumerate(self._cfg.address_book):
                if i < len(vars_list) and vars_list[i].get():
                    selected_ids.append(ent.id)
        if not selected_ids:
            self._sched_add_fail("log.need_select_group")
            return
        path = self._jfile.get().strip()
        if not path:
            self._sched_add_fail("log.need_txt_or_folder")
            return
        if os.path.isdir(path):
            self._add_folder_jobs(path, selected_ids)
            return
        if not os.path.isfile(path):
            self._sched_add_fail("log.path_invalid")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            self._sched_add_fail("folder.read_decode_fail")
            return
        except OSError as exc:
            self._sched_add_fail("folder.read_fail", err=exc)
            return
        valid = {a.id for a in self._cfg.accounts}
        if not valid:
            self._sched_add_fail("log.need_account_first")
            return
        items, errors = import_doc_items(text, valid_accounts=valid, require_per_item_interval=False)
        sends = [it for it in items if not it.is_non_send_step()]
        if not sends:
            self._sched_add_fail("log.txt_no_items")
            return
        if errors:
            for e in errors[:10]:
                info(e)
        all_txt = items_use_txt_intervals(items)
        any_txt = items_have_any_txt_interval(items)
        min_m = 0.0
        max_m = 0.0
        if all_txt:
            mode = "txt"
            interval_note = t("sched.interval.txt_only")
        else:
            interval = self._parse_interval_minutes(
                self._sched_interval.get().strip() if getattr(self, "_sched_interval", None) else ""
            )
            if interval is None:
                if any_txt:
                    self._sched_add_fail("log.interval_invalid")
                else:
                    self._sched_add_fail("log.interval_invalid")
                return
            min_m, max_m = interval
            mode = "mixed" if any_txt else "fixed"
            interval_note = (
                t("sched.interval.txt_plus_fixed", min_m=min_m, max_m=max_m)
                if any_txt
                else t("sched.interval.fixed", min_m=min_m, max_m=max_m)
            )
        has_main = doc_has_main_account_placeholder(items)
        by_eid = {e.id: e for e in self._cfg.address_book}
        jobs = load_jobs()
        created: List[ScheduledJob] = []
        skipped: List[str] = []

        def _owner_for_entry(ent: AddressEntry) -> str:
            return (ent.owner_account_id or "").strip()

        targets: List[AddressEntry] = []
        for eid in selected_ids:
            ent = by_eid.get(eid)
            if ent:
                targets.append(ent)

        # 与 WA 一致：每勾选一个群 = 一个独立任务，可分别开始/暂停
        for ent in targets:
            if has_main:
                owner = _owner_for_entry(ent)
                if not owner:
                    skipped.append(ent.remark.strip() or ent.id)
                    continue
                if owner not in valid:
                    self._sched_add_fail("log.need_group_owner", group=ent.remark)
                    return
                job_items = clone_doc_items(items)
                mapped = apply_main_account_mapping(job_items, owner)
                if mapped == 0:
                    self._sched_add_fail("log.job_create_failed")
                    return
            else:
                job_items = clone_doc_items(items)

            chat_nums: List[int] = []
            n = chat_ref_to_optional_int(ent.chat_ref)
            if n is not None:
                chat_nums.append(n)
            job = ScheduledJob.new(
                chat_ids=chat_nums,
                source_path=path,
                items=job_items,
                chat_entry_ids=[ent.id],
                interval_min_minutes=min_m,
                interval_max_minutes=max_m,
                interval_mode=mode,
                start_paused=True,
            )
            jobs.append(job)
            created.append(job)

        if skipped:
            info_i18n("log.skipped_no_owner", names="、".join(skipped))
        if not created:
            if has_main:
                self._sched_add_fail("log.job_create_failed")
            else:
                self._sched_add_fail("log.job_create_failed")
            return

        save_jobs(jobs)
        apply_last_schedule_for_jobs(self._cfg, created)
        self._sched_edit_job_id = created[-1].id
        self._render_taskmgr_cards(force=True)
        self._sync_sched_job_pick_combo()
        steps_lbl = t("sched.job_steps", n=len(items))
        if len(created) > 1:
            info_i18n("log.job_added_multi", n=len(created), name=j0.source_name, steps=steps_lbl)
        else:
            info_i18n("log.job_added_single", name=j0.source_name, steps=steps_lbl)
        self._clear_sched_target_selection()
        self._refresh_schedule_target_checks()

    def _add_folder_jobs(self, folder_path: str, selected_ids: List[str]) -> None:
        rel_files, scan_errs = scan_schedule_folder(folder_path)
        if scan_errs:
            for err in scan_errs[:8]:
                info(err)
            self._sched_add_fail("log.path_invalid")
            return
        folder_abs = os.path.abspath(folder_path)
        first_rel = rel_files[0]
        first_path = folder_txt_abs_path(folder_abs, first_rel)
        try:
            with open(first_path, "r", encoding="utf-8") as f:
                text = f.read()
        except UnicodeDecodeError:
            self._sched_add_fail("folder.read_decode_fail")
            return
        except OSError as exc:
            self._sched_add_fail("folder.read_fail", err=exc)
            return
        valid = {a.id for a in self._cfg.accounts}
        if not valid:
            self._sched_add_fail("log.need_account_first")
            return
        items, errors = import_doc_items(text, valid_accounts=valid, require_per_item_interval=False)
        sends = [it for it in items if not it.is_non_send_step()]
        if not sends:
            self._sched_add_fail("log.folder_first_no_items")
            return
        if errors:
            for e in errors[:10]:
                info(e)
        all_txt = items_use_txt_intervals(items)
        any_txt = items_have_any_txt_interval(items)
        ui_interval = self._parse_interval_minutes(
            self._sched_interval.get().strip() if getattr(self, "_sched_interval", None) else ""
        )
        min_m = 0.0
        max_m = 0.0
        if all_txt:
            mode = "txt"
            if not ui_interval:
                self._sched_add_fail("sched.folder_interval_hint")
                return
            min_m, max_m = ui_interval
            interval_note = t("sched.interval.txt_mixed_fixed", min_m=min_m, max_m=max_m)
        else:
            interval = ui_interval
            if interval is None:
                if any_txt:
                    self._sched_add_fail("log.interval_invalid")
                else:
                    self._sched_add_fail("log.interval_invalid")
                return
            min_m, max_m = interval
            mode = "mixed" if any_txt else "fixed"
            interval_note = (
                t("sched.interval.txt_plus_fixed", min_m=min_m, max_m=max_m)
                if any_txt
                else t("sched.interval.fixed", min_m=min_m, max_m=max_m)
            )
        has_main = doc_has_main_account_placeholder(items)
        by_eid = {e.id: e for e in self._cfg.address_book}
        jobs = load_jobs()
        created: List[ScheduledJob] = []
        skipped: List[str] = []

        def _owner_for_entry(ent: AddressEntry) -> str:
            return (ent.owner_account_id or "").strip()

        targets: List[AddressEntry] = []
        for eid in selected_ids:
            ent = by_eid.get(eid)
            if ent:
                targets.append(ent)

        for ent in targets:
            if has_main:
                owner = _owner_for_entry(ent)
                if not owner:
                    skipped.append(ent.remark.strip() or ent.id)
                    continue
                if owner not in valid:
                    self._sched_add_fail("log.need_group_owner", group=ent.remark)
                    return
                job_items = clone_doc_items(items)
                mapped = apply_main_account_mapping(job_items, owner)
                if mapped == 0:
                    self._sched_add_fail("log.job_create_failed")
                    return
            else:
                job_items = clone_doc_items(items)

            chat_nums: List[int] = []
            n = chat_ref_to_optional_int(ent.chat_ref)
            if n is not None:
                chat_nums.append(n)
            job = ScheduledJob.new(
                chat_ids=chat_nums,
                source_path=first_path,
                items=job_items,
                chat_entry_ids=[ent.id],
                interval_min_minutes=min_m,
                interval_max_minutes=max_m,
                interval_mode=mode,
                start_paused=True,
            )
            job.source_kind = "folder"
            job.folder_path = folder_abs
            job.folder_files = list(rel_files)
            job.folder_day_index = 0
            jobs.append(job)
            created.append(job)

        if skipped:
            info_i18n("log.skipped_no_owner", names="、".join(skipped))
        if not created:
            if has_main:
                self._sched_add_fail("log.job_create_failed")
            else:
                self._sched_add_fail("log.job_create_failed")
            return

        save_jobs(jobs)
        apply_last_schedule_for_jobs(self._cfg, created)
        self._sched_edit_job_id = created[-1].id
        self._render_taskmgr_cards(force=True)
        self._sync_sched_job_pick_combo()
        if len(created) > 1:
            info_i18n("log.folder_job_added_multi", n=len(created), days=len(rel_files))
        else:
            info_i18n(
                "log.folder_job_added_single",
                days=len(rel_files),
                name=j0.source_name,
                steps=t("sched.job_steps", n=len(items)),
            )
        self._clear_sched_target_selection()
        self._refresh_schedule_target_checks()

    def _sync_manual_folder_advance_btn(self) -> None:
        btn = getattr(self, "_btn_manual_folder_day", None)
        if btn is None:
            return
        if self._manual_folder_advance_mode:
            btn.configure(text=t("taskmgr.manual_day_cancel"), fg_color="#6a3a12", hover_color="#7d4518")
        else:
            btn.configure(text=t("taskmgr.manual_day"), fg_color="#2a4a5a", hover_color="#356878")

    def _toggle_manual_folder_advance_mode(self) -> None:
        self._manual_folder_advance_mode = not self._manual_folder_advance_mode
        self._sync_manual_folder_advance_btn()
        jobs = load_jobs()
        if jobs:
            self._patch_taskmgr_cards([j.id for j in jobs], reorder=False)
        if self._manual_folder_advance_mode:
            info_i18n("log.manual_day_mode_on")
        else:
            info_i18n("log.manual_day_mode_off")

    def _manual_advance_folder_day_by_id(self, job_id: str) -> None:
        if self._taskmgr_toggle_busy:
            return
        j = next((x for x in load_jobs() if x.id == job_id), None)
        if j is None:
            return
        if not is_folder_job(j):
            msg_info(self, "msgbox.manual_day.title", "msgbox.manual_day.folder_only")
            return
        if not can_advance_folder_day(j):
            msg_info(self, "msgbox.manual_day.title", "msgbox.manual_day.last_day")
            return
        nxt = j.folder_day_index + 1
        unnamed = t("grp.unnamed")
        if not msg_askyesno(
            self,
            "msgbox.manual_day.title",
            "msgbox.manual_day.confirm",
            target=self._job_target_short(j),
            current=j.source_name or unnamed,
            next_file=j.folder_files[nxt],
            day=nxt + 1,
            total=len(j.folder_files),
        ):
            return
        self._cfg = load_config()
        ok, err = advance_scheduled_folder_day(j, self._cfg)
        if not ok:
            info_i18n("log.folder_advance_fail", err=err)
            return
        save_jobs_patch([j])
        apply_last_schedule_for_jobs(self._cfg, [j])
        self._refresh_taskmgr_card(j.id)
        info_i18n(
            "log.folder_advance_ok",
            target=self._job_target_short(j),
            day=j.folder_day_index + 1,
        )

    def _start_next_folder_day(self) -> None:
        jobs = load_jobs()
        candidates, stale = split_folder_jobs_for_bulk_advance(jobs)
        if not candidates and not stale:
            try:
                msg_info(self, "msgbox.next_day.title", "msgbox.next_day.no_folder")
            except Exception:
                info_i18n("log.next_day_no_folder")
            return

        lines: List[str] = []
        running_n = 0
        unnamed = t("grp.unnamed")
        for j in candidates:
            nxt = j.folder_day_index + 1
            lines.append(
                format_folder_advance_line(
                    target_label=self._job_target_short(j),
                    current_name=j.source_name or unnamed,
                    next_name=j.folder_files[nxt],
                    next_day_one_based=nxt + 1,
                    total_days=len(j.folder_files),
                )
            )
            if self._doc_job_is_running(j):
                running_n += 1

        del_lines: List[str] = []
        for j in stale:
            idx = max(0, int(j.folder_day_index))
            del_lines.append(
                format_folder_last_day_delete_line(
                    target_label=self._job_target_short(j),
                    current_name=j.source_name or unnamed,
                    day_one_based=idx + 1,
                    total_days=len(j.folder_files),
                )
            )

        body_kwargs: Dict[str, Any] = {"advance_block": "", "delete_block": ""}
        if candidates:
            advance_intro = t("msgbox.next_day.interrupt")
            if running_n:
                advance_intro += "\n\n" + t("msgbox.next_day.running", n=running_n)
            advance_intro += "\n\n" + t("msgbox.next_day.advance_list") + "\n" + "\n".join(lines)
            body_kwargs["advance_block"] = advance_intro
        if stale:
            delete_block = t("msgbox.next_day.delete_list") + "\n" + "\n".join(del_lines)
            if body_kwargs["advance_block"]:
                body_kwargs["delete_block"] = "\n\n" + delete_block
            else:
                body_kwargs["delete_block"] = delete_block
        try:
            if not msg_askyesno(self, "msgbox.next_day.title", "msgbox.next_day.body", **body_kwargs):
                return
        except Exception as exc:
            error(f"一键开始下一天确认框失败: {exc}")
            return

        self._cfg = load_config()
        self._bulk_folder_advance_ids = [j.id for j in candidates]
        self._bulk_folder_advance_stale_ids = {j.id for j in stale}
        self._bulk_folder_advance_done = 0
        self._bulk_folder_advance_failed = 0
        total = len(self._bulk_folder_advance_ids)
        if total:
            info_i18n("log.next_day_batch", total=total, batch=FOLDER_BULK_ADVANCE_BATCH_SIZE)
        self._run_bulk_folder_advance_batch()

    def _run_bulk_folder_advance_batch(self) -> None:
        ids = getattr(self, "_bulk_folder_advance_ids", None) or []
        if not ids:
            self._finish_bulk_folder_advance()
            return

        batch_ids = ids[:FOLDER_BULK_ADVANCE_BATCH_SIZE]
        self._bulk_folder_advance_ids = ids[FOLDER_BULK_ADVANCE_BATCH_SIZE:]
        batch_updated: List[ScheduledJob] = []

        for job_id in batch_ids:
            live = next((x for x in load_jobs() if x.id == job_id), None)
            if live is None or not can_advance_folder_day(live):
                continue
            ok, err = advance_scheduled_folder_day(live, self._cfg)
            if ok:
                save_jobs_patch([live])
                batch_updated.append(live)
                self._bulk_folder_advance_done += 1
            else:
                self._bulk_folder_advance_failed += 1
                info_i18n("log.folder_advance_job_fail", target=self._job_target_short(live), err=err)

        if batch_updated:
            apply_last_schedule_for_jobs(self._cfg, batch_updated)
            self._render_taskmgr_cards(force=True)

        remaining = len(self._bulk_folder_advance_ids)
        if remaining:
            info_i18n(
                "log.bulk_advance_batch",
                batch=len(batch_updated),
                done=self._bulk_folder_advance_done,
                remaining=remaining,
            )
            self.after(
                int(FOLDER_BULK_ADVANCE_BATCH_PAUSE_SEC * 1000),
                self._run_bulk_folder_advance_batch,
            )
            return
        self._finish_bulk_folder_advance()

    def _finish_bulk_folder_advance(self) -> None:
        stale_ids = getattr(self, "_bulk_folder_advance_stale_ids", None) or set()
        done = int(getattr(self, "_bulk_folder_advance_done", 0) or 0)
        failed = int(getattr(self, "_bulk_folder_advance_failed", 0) or 0)

        if stale_ids:
            kept = [x for x in load_jobs() if x.id not in stale_ids]
            save_jobs(kept)
            if self._sched_edit_job_id in stale_ids:
                self._sched_edit_job_id = None

        self._bulk_folder_advance_ids = []
        self._bulk_folder_advance_stale_ids = set()

        if done == 0 and failed == 0 and not stale_ids:
            info_i18n("log.next_day_nothing")
            return

        self._render_taskmgr_cards(force=True)
        parts: List[str] = []
        if done:
            parts.append(t("log.next_day_advanced", n=done))
        if failed:
            parts.append(t("log.next_day_failed", n=failed))
        if stale_ids:
            parts.append(t("log.next_day_deleted", n=len(stale_ids)))
        if parts:
            info(t("log.next_day_summary", summary="；".join(parts)))

    def _sched_job_fingerprint(self, j: ScheduledJob) -> tuple:
        stotal, sdone, sremain = j.send_progress()
        return (
            j.state,
            j.enabled,
            j.pause_reason or "",
            sdone,
            sremain,
            stotal,
            j.item_count(),
            j.interval_mode,
            j.interval_min_minutes,
            j.interval_max_minutes,
        )

    def _sched_jobs_structure_changed(self, jobs: List[ScheduledJob]) -> bool:
        ids = [j.id for j in jobs]
        return ids != getattr(self, "_sched_listed_job_ids", [])

    def _job_detail_text(self, j: ScheduledJob) -> str:
        if not j.enabled:
            status = t("dash.disabled")
        elif j.state == "paused":
            reason = display_pause_reason(j.pause_reason or CODE_MANUAL)
            status = t("job_card.paused_paren", reason=reason)
        else:
            status = t("job_card.running")
        emap = {e.id: e for e in self._cfg.address_book}
        if j.chat_entry_ids:
            names = [emap[eid].remark.strip() or emap[eid].id for eid in j.chat_entry_ids if eid in emap]
            tgt_desc = "、".join(names) if names else t("sched.target_count", n=len(j.chat_entry_ids))
        elif j.chat_ids:
            tgt_desc = t("sched.target_chat_ids", n=len(j.chat_ids))
        else:
            tgt_desc = t("job_target.unset")
        delay_hint = ""
        if j.interval_mode == "txt" or items_use_txt_intervals(j.items):
            delays = [
                it.delay_after_minutes
                for it in j.items
                if not it.is_reminder and getattr(it, "interval_from_txt", False)
            ]
            if delays:
                delay_hint = t("sched.delay.txt", min_v=min(delays), max_v=max(delays))
        elif j.interval_mode == "mixed" or items_have_any_txt_interval(j.items):
            delay_hint = t(
                "sched.delay.txt_mixed",
                min_v=j.interval_min_minutes,
                max_v=j.interval_max_minutes,
            )
        elif j.interval_max_minutes > 0 or j.interval_min_minutes > 0:
            delay_hint = t(
                "sched.delay.fixed",
                min_v=j.interval_min_minutes,
                max_v=j.interval_max_minutes,
            )
        oc = Counter(it.original_label() for it in j.items if not it.is_reminder and it.original_label())
        dist = ""
        if oc:
            dist = t("sched.orig_prefix") + "、".join(
                t("sched.orig_item", k=k, v=v) for k, v in sorted(oc.items())
            )
        main_mapped = next(
            (
                it.effective_send_account_id()
                for it in j.items
                if not it.is_reminder
                and is_main_account_placeholder(it.original_label())
                and it.effective_send_account_id()
            ),
            None,
        )
        if main_mapped:
            dist += t("sched.main_mapped", acc=main_mapped)
        stotal, sdone, sremain = j.send_progress()
        prog = self._format_send_progress(stotal, sdone, sremain, step_total=j.item_count())
        note = operator_note_for_items(j.items, cursor=int(j.cursor or 0), max_len=40)
        note_part = t("sched.job_note", text=note) if note else ""
        return t(
            "sched.job_detail",
            tgt=tgt_desc,
            name=j.source_name,
            prog=prog,
            delay=delay_hint,
            dist=dist,
            status=status,
            note=note_part,
        )

    def _create_sched_job_row(self, j: ScheduledJob) -> None:
        row = ctk.CTkFrame(self._job_rows, fg_color=COLORS["card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        row.pack(fill="x", pady=4)
        detail_lbl = ctk.CTkLabel(
            row,
            text=self._job_detail_text(j),
            text_color=COLORS["text"],
            justify="left",
            wraplength=680,
        )
        detail_lbl.pack(anchor="w", padx=12, pady=(10, 6))
        acts = ctk.CTkFrame(row, fg_color="transparent")
        acts.pack(fill="x", padx=12, pady=(0, 10))
        btn_run = ctk.CTkButton(
            acts,
            text=(t("taskmgr.hint_resume") if j.state == "paused" else t("taskmgr.hint_pause")),
            fg_color=COLORS["border"],
            command=lambda jid=j.id: self._toggle_job_run_by_id(jid),
        )
        btn_run.pack(fill="x", pady=2)
        btn_en = ctk.CTkButton(
            acts,
            text=(t("dash.disabled") if j.enabled else t("dash.enabled")),
            fg_color=COLORS["border"],
            command=lambda jid=j.id: self._toggle_job_enabled_by_id(jid),
        )
        btn_en.pack(fill="x", pady=2)
        ctk.CTkButton(
            acts,
            text=t("sched.select_edit"),
            fg_color=COLORS["border"],
            command=lambda jid=j.id: self._select_sched_job_for_edit(jid),
        ).pack(fill="x", pady=2)
        ctk.CTkButton(
            acts,
            text=t("common.delete"),
            fg_color=COLORS["danger"],
            command=lambda jid=j.id: self._del_job_by_id(jid),
        ).pack(fill="x", pady=2)
        self._sched_job_row_widgets[j.id] = {"row": row, "detail": detail_lbl, "btn_run": btn_run, "btn_en": btn_en}
        self._sched_job_fingerprints[j.id] = self._sched_job_fingerprint(j)

    def _full_rebuild_sched_jobs(self, jobs: List[ScheduledJob]) -> None:
        for ch in self._job_rows.winfo_children():
            ch.destroy()
        self._sched_job_row_widgets.clear()
        self._sched_job_fingerprints.clear()
        if not jobs:
            ctk.CTkLabel(self._job_rows, text=t("sched.no_jobs"), text_color=COLORS["muted"]).pack(anchor="w", pady=8)
            return
        for j in jobs:
            self._create_sched_job_row(j)

    def _patch_sched_job_rows(self, jobs: List[ScheduledJob]) -> None:
        if self._sched_jobs_structure_changed(jobs):
            self._sched_listed_job_ids = [j.id for j in jobs]
            self._full_rebuild_sched_jobs(jobs)
            return
        for j in jobs:
            fp = self._sched_job_fingerprint(j)
            if self._sched_job_fingerprints.get(j.id) == fp:
                continue
            self._sched_job_fingerprints[j.id] = fp
            w = self._sched_job_row_widgets.get(j.id)
            if not w:
                continue
            w["detail"].configure(text=self._job_detail_text(j))
            w["btn_run"].configure(
                text=(t("sched.btn_resume") if j.state == "paused" else t("sched.btn_pause"))
            )
            w["btn_en"].configure(
                text=(t("sched.btn_disable") if j.enabled else t("sched.btn_enable"))
            )

    def _render_jobs(self, *, full: Optional[bool] = None) -> None:
        if getattr(self, "_job_rows", None) is None:
            return
        jobs = load_jobs()
        if full is None:
            full = self._sched_jobs_structure_changed(jobs)
        if full:
            self._sched_listed_job_ids = [j.id for j in jobs]
            self._full_rebuild_sched_jobs(jobs)
        else:
            self._patch_sched_job_rows(jobs)
        self._sync_sched_job_pick_combo()
        handler = getattr(self, "_scroll_wheel_handler", None)
        if handler:
            bind_scroll_tree_once(self._job_rows, handler)

    def _job_target_short(self, j: ScheduledJob) -> str:
        cfg = load_config()
        emap = {e.id: e for e in cfg.address_book}
        if j.chat_entry_ids:
            names: List[str] = []
            for eid in j.chat_entry_ids[:4]:
                ent = emap.get(str(eid))
                if ent:
                    names.append((ent.remark or "").strip() or ent.id)
            if names:
                s = "、".join(names)
                if len(j.chat_entry_ids) > 4:
                    s += t("sched.target_more_groups", n=len(j.chat_entry_ids))
                return s
        if j.chat_ids:
            if len(j.chat_ids) == 1:
                return t("sched.single_group_id", id=j.chat_ids[0])
            return t("sched.multi_group_ids", n=len(j.chat_ids))
        return t("job_target.unset")

    def _sched_job_label(self, j: ScheduledJob) -> str:
        return t(
            "sched.job_label",
            target=self._job_target_short(j),
            badge=schedule_kind_badge(j),
            name=j.source_name,
            steps=j.item_count(),
            jid=j.id[:8],
        )

    def _on_sched_job_pick_changed(self, _value: str) -> None:
        label = self._sched_job_pick.get().strip()
        jid = self._sched_job_label_to_id.get(label)
        if jid:
            self._sched_edit_job_id = jid
            jobs = load_jobs()
            job = next((x for x in jobs if x.id == jid), None)
            self._refresh_sched_bulk_combos(job)
            return

    def _refresh_sched_bulk_combos(self, job: Optional[ScheduledJob] = None) -> None:
        if job is None and self._sched_edit_job_id:
            for j in load_jobs():
                if j.id == self._sched_edit_job_id:
                    job = j
                    break
        acc_vals = self._account_id_values()
        if getattr(self, "_sched_bulk_to_combo", None) is not None:
            prev_t = self._sched_bulk_to_combo.get().strip()
            self._sched_bulk_to_combo.configure(values=acc_vals)
            if prev_t in acc_vals:
                self._sched_bulk_to_combo.set(prev_t)
            elif acc_vals:
                self._sched_bulk_to_combo.set(acc_vals[0])
        if getattr(self, "_sched_bulk_from_combo", None) is None:
            return
        originals: List[str] = []
        if job:
            originals = sorted(
                {it.original_label() for it in job.items if not it.is_reminder and it.original_label()}
            )
        vals_f = originals if originals else ["—"]
        prev_f = self._sched_bulk_from_combo.get().strip()
        self._sched_bulk_from_combo.configure(values=vals_f)
        if prev_f in vals_f:
            self._sched_bulk_from_combo.set(prev_f)
        else:
            self._sched_bulk_from_combo.set(vals_f[0])

    def _sync_sched_job_pick_combo(self) -> None:
        jobs = load_jobs()
        if getattr(self, "_sched_job_pick", None) is None:
            return
        self._sched_job_label_to_id = {}
        labels: List[str] = []
        for j in jobs:
            lab = self._sched_job_label(j)
            labels.append(lab)
            self._sched_job_label_to_id[lab] = j.id
        if not labels:
            labels = ["—"]
            self._sched_edit_job_id = None
        elif self._sched_edit_job_id:
            found = False
            for j in jobs:
                if j.id == self._sched_edit_job_id:
                    self._sched_job_pick.set(self._sched_job_label(j))
                    found = True
                    break
            if not found:
                self._sched_edit_job_id = jobs[0].id
                self._sched_job_pick.set(self._sched_job_label(jobs[0]))
        else:
            self._sched_edit_job_id = jobs[0].id
            self._sched_job_pick.set(self._sched_job_label(jobs[0]))
        self._sched_job_pick.configure(values=labels)
        sel = None
        for j in jobs:
            if j.id == self._sched_edit_job_id:
                sel = j
                break
        self._refresh_sched_bulk_combos(sel)

    def _select_sched_job_for_edit(self, job_id: str) -> None:
        self._sched_edit_job_id = job_id
        self._sync_sched_job_pick_combo()
        job = next((j for j in load_jobs() if j.id == job_id), None)
        if job:
            info_i18n(
                "sched.selected_job_hint",
                jid=job.id[:8],
                target=self._job_target_short(job),
                name=job.source_name,
            )
        else:
            info_i18n("log.job_selected_for_edit")

    def _schedule_bulk_replace_by_original(self) -> None:
        jid = (self._sched_edit_job_id or "").strip()
        if not jid:
            info_i18n("log.bulk_need_pick")
            return
        jobs = load_jobs()
        job = next((j for j in jobs if j.id == jid), None)
        if job is None:
            info_i18n("log.bulk_job_missing")
            return
        from_acc = self._sched_bulk_from_combo.get().strip()
        to_acc = self._sched_bulk_to_combo.get().strip()
        if from_acc in ("", "—") or not to_acc:
            info_i18n("log.bulk_from_to")
            return
        if from_acc == to_acc:
            info_i18n("log.bulk_same")
            return
        valid = {a.id for a in self._cfg.accounts}
        if valid and to_acc not in valid:
            info_i18n("log.bulk_target_missing", account=to_acc)
            return
        n = 0
        for it in job.items:
            if it.is_reminder:
                continue
            if it.original_label() == from_acc:
                it.send_as_account_id = to_acc
                n += 1
        if n == 0:
            info_i18n("log.bulk_no_from", account=from_acc)
            return
        save_jobs_patch([job])
        self._refresh_sched_bulk_combos(job)
        self._refresh_taskmgr_card(job.id)
        info_i18n("log.bulk_replaced", from_acc=from_acc, n=n, to_acc=to_acc)

    def _toggle_job_run_by_id(self, job_id: str) -> None:
        if self._taskmgr_toggle_busy:
            return
        self._taskmgr_toggle_busy = True
        try:
            j = next((x for x in load_jobs() if x.id == job_id), None)
            if j is None:
                return
            if self._doc_job_is_running(j):
                self._scheduler.pause_job(j.id, CODE_MANUAL)
            elif self._scheduler.resume_job(j.id):
                self._warn_if_tg_session_down()
            else:
                info_i18n("log.cannot_start_job")
            self._refresh_job_run_ui(job_id)
        finally:
            self._taskmgr_toggle_busy = False

    def _toggle_job_enabled_by_id(self, job_id: str) -> None:
        job = next((j for j in load_jobs() if j.id == job_id), None)
        if job is None:
            return
        job.enabled = not job.enabled
        if job.enabled and job.state == "paused":
            job.pause_reason = job.pause_reason or CODE_MANUAL
        save_jobs_patch([job])
        self._refresh_job_run_ui(job_id)

    def _del_job_by_id(self, job_id: str) -> None:
        jobs = load_jobs()
        dead = next((j for j in jobs if j.id == job_id), None)
        if dead is None:
            return
        target = self._job_target_short(dead)
        if not msg_askyesno(self, "msgbox.delete.title", "msgbox.delete.body", name=dead.source_name, target=target):
            return
        jobs = [j for j in jobs if j.id != job_id]
        if dead.id == self._sched_edit_job_id:
            self._sched_edit_job_id = None
        save_jobs(jobs)
        info_i18n("log.job_deleted", name=dead.source_name)
        self._render_taskmgr_cards(force=True)
        self._sync_sched_job_pick_combo()
        if getattr(self, "_sched_targets", None) is not None:
            self._refresh_schedule_target_checks()

    def _delete_all_jobs(self) -> None:
        jobs = load_jobs()
        if not jobs:
            info_i18n("log.delete_all_none")
            return
        single_txt, folder_done, folder_kept, to_delete, kept = bulk_delete_job_summary(jobs)
        if not to_delete:
            info_i18n("log.delete_all_nothing")
            if folder_kept > 0:
                info_i18n("log.delete_all_kept_folder", n=folder_kept)
            return
        msg = format_bulk_delete_confirm_message(
            single_txt=single_txt,
            folder_done=folder_done,
            folder_kept=folder_kept,
            total_delete=len(to_delete),
        )
        if not ask_yes_no(self, t("msgbox.delete_all.title"), msg):
            return
        save_jobs(kept)
        deleted_ids = {j.id for j in to_delete}
        if getattr(self, "_sched_edit_job_id", None) in deleted_ids:
            self._sched_edit_job_id = kept[0].id if kept else None
        self._render_jobs(full=True)
        self._render_taskmgr_cards(force=True)
        self._sync_sched_job_pick_combo()
        if getattr(self, "_sched_targets", None) is not None:
            self._refresh_schedule_target_checks()
        if folder_kept > 0:
            info_i18n(
                "log.delete_all_done_kept",
                n=len(to_delete),
                single_txt=single_txt,
                folder_done=folder_done,
                folder_kept=folder_kept,
            )
        else:
            info_i18n(
                "log.delete_all_done",
                n=len(to_delete),
                single_txt=single_txt,
                folder_done=folder_done,
            )

    def _page_logs(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")

        log_foot = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        lf = ctk.CTkFrame(log_foot, fg_color="transparent")
        lf.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(lf, text=t("common.refresh_logs"), command=self._flush_logs_ui, fg_color=COLORS["accent"]).pack(fill="x")

        wrap, finish_scroll = self._mount_main_scroll(page, footer=log_foot)
        ctk.CTkLabel(wrap, text=t("nav.logs_tg"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=(8, 12))

        self._log_box = ctk.CTkTextbox(
            wrap,
            height=520,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=COLORS["bg"],
            text_color=COLORS["muted"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self._log_box.pack(fill="both", expand=True, pady=(0, 8))
        bind_log_textbox_wheel(self._log_box)
        reload_log_textbox_from_memory(
            self._log_box,
            self._tg_log_lines,
            limit=LOG_TEXTBOX_MAX_LINES,
            log_queue=getattr(self, "_log_ui_queue", None),
        )

        finish_scroll()
        return page

    def _flush_logs_ui(self) -> None:
        lb = getattr(self, "_log_box", None)
        if lb is None:
            return
        reload_log_textbox_from_memory(
            lb,
            self._tg_log_lines,
            limit=LOG_TEXTBOX_MAX_LINES,
            max_lines=LOG_TEXTBOX_MAX_LINES,
            log_queue=getattr(self, "_log_ui_queue", None),
        )

    def _save_all_and_restart(self) -> None:
        if not getattr(self, "_pages_ready", False):
            info_i18n("log.ui_save_loading")
            return
        self._optional_merge_global_api_from_ui()
        try:
            if getattr(self, "_rate_entry", None) is not None:
                self._cfg.rate_limit_seconds = float(self._rate_entry.get().strip())
        except Exception:
            pass
        if getattr(self, "_stage_popup_var", None) is not None:
            self._cfg.stage_reminder_popup_enabled = bool(self._stage_popup_var.get())
        save_config(self._cfg)
        save_jobs(load_jobs())
        info_i18n("log.config_saved")

        def after_restart() -> None:
            self._render_account_rows()
            self._render_group_rows(force=True)
            self._refresh_schedule_combo()
            self._refresh_schedule_target_checks()
            self._sync_taskmgr_page()
            self._refresh_dashboard()
            self._schedule_login_probe()
            info_i18n("log.tg_services_restarted")

        self._invoke_restart_in_background(after_restart)


if __name__ == "__main__":
    from main import main

    main()
