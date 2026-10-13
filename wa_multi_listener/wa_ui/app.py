"""主窗口：监听 + 定时任务（WhatsApp）。"""
from __future__ import annotations

import copy
import os
import queue
import re
import sys
import threading
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, TYPE_CHECKING

import customtkinter as ctk

_pkg_root = Path(__file__).resolve().parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from config import (
    Account,
    AddressEntry,
    apply_last_schedule_for_jobs,
    apply_last_schedule_from_current_jobs,
    format_job_targets_label,
    load_config,
    parse_chat_ref_input,
    parse_watch_user_input,
    save_config,
    sync_last_schedule_from_disk,
)
from listener import ListenerController
from logger_util import add_memory_listener, error, error_i18n, get_recent_lines, info, info_i18n, remove_memory_listener, warning
from i18n import get_lang, set_lang_for_next_launch, t
from i18n.ui_helpers import (
    combo_label_for_lang,
    lang_combo_labels,
    lang_from_combo_label,
    msg_askyesno,
    msg_info,
)
from wa_ui.log_view_filter import filter_lines_for_wa_log_view, is_visible_in_wa_log_view
from notifier import AlertPopup
from stats import record_alert, today_alert_count
from paths import app_root, resource_path
from schedule_txt_import import import_doc_items
from schedule_account import mark_row_primary_auto, row_needs_per_group_owner
from schedule_folder import (
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
from i18n.pause_reason import CODE_MANUAL
from i18n.job_card import operator_note_for_items
from schedule2_runner import (
    Schedule2Job,
    Schedule2Row,
    Schedule2Runner,
    LISTEN_HIT_PAUSE_REASON_S2,
    advance_schedule2_folder_day,
    bulk_reload_schedule2_folder_scripts,
    bulk_resume_schedule2_counts,
    load_schedule2_jobs,
    save_schedule2_jobs,
    save_schedule2_jobs_patch,
    schedule2_job_is_running,
    schedule2_job_status_label,
    schedule2_job_step_label,
    schedule2_job_target_remarks,
)
from session_check import has_saved_session
from watch_membership_audit import WatchAuditRow, WatchAuditStatus
from wa_ui.qr_dialog import QrLoginDialog
from wa_ui.card_grid import TASKMGR_COLS, configure_equal_columns, grid_place, reorder_taskmgr_grid
from wa_ui.taskmgr_tile_theme import (
    format_taskmgr_count_summary,
    taskmgr_card_status_text,
    taskmgr_count_jobs,
    taskmgr_fonts,
    taskmgr_sort_jobs_for_display,
    taskmgr_tile_palette,
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

from wa_ui.theme import COLORS, SIDEBAR_WIDTH
from wa_auth import run_qr_login_in_thread
from wa_proxy import normalize_proxy_url, proxy_supported

if TYPE_CHECKING:
    from wa_coordinator import WaCoordinator

MAIN_GEOMETRY = "1152x720"


class WaPanel(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTk | ctk.CTkFrame,
        listener: ListenerController,
        schedule2: Schedule2Runner,
    ) -> None:
        super().__init__(master)
        self._listener = listener
        self._schedule2 = schedule2
        self._coord: Optional[WaCoordinator] = None
        self._cfg = load_config()
        sync_last_schedule_from_disk(self._cfg)
        self._nav: Dict[str, ctk.CTkFrame] = {}
        self._content: Optional[ctk.CTkFrame] = None
        self._schedule2.set_reminder_callback(self._schedule2_reminder)
        self._log_queue: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._log_pump_on = True
        self._current_nav: str = "dash"
        self._login_dlg: Optional[QrLoginDialog] = None
        self._login_cancel: Optional[threading.Event] = None
        self._login_busy = False
        self._login_account_id: Optional[str] = None
        self._s2_edit_job_id: Optional[str] = None
        self._sched2_target_vars: List[ctk.BooleanVar] = []
        self._sched2_target_rows: List[Tuple[AddressEntry, ctk.BooleanVar]] = []
        self._pages_ready = False
        self._taskmgr_widgets: Dict[str, Dict[str, Any]] = {}
        self._taskmgr_listed_ids: List[str] = []
        self._taskmgr_display_ids: List[str] = []
        self._taskmgr_fp_cache: Dict[str, tuple] = {}
        self._taskmgr_toggle_busy = False
        self._manual_folder_advance_mode = False
        self._watch_audit_flags: Dict[str, str] = {}
        self._watch_audit_details: Dict[str, str] = {}
        self._watch_audit_busy = False

        self.configure(fg_color=COLORS["bg"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._content = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        self._content.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self._build_pages()
        self._pages_ready = True
        self._show_nav("dash")
        add_memory_listener(self._on_log_line)
        self.after(LOG_PUMP_MS, self._pump_logs)

    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, fg_color=COLORS["sidebar"], corner_radius=0)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        ctk.CTkLabel(side, text=t("wa.brand"), font=ctk.CTkFont(size=20, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", padx=16, pady=(20, 4)
        )
        ctk.CTkLabel(side, text=t("wa.subtitle"), font=ctk.CTkFont(size=12), text_color=COLORS["muted"]).pack(anchor="w", padx=16, pady=(0, 16))
        for nid, label in (
            ("dash", t("nav.dash")),
            ("acct", t("nav.acct")),
            ("grp", t("nav.grp")),
            ("rules", t("nav.rules")),
            ("sched", t("nav.sched")),
            ("taskmgr", t("nav.taskmgr")),
            ("logs", t("nav.logs")),
        ):
            ctk.CTkButton(
                side,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color=COLORS["border"],
                text_color=COLORS["text"],
                command=lambda n=nid: self._show_nav(n),
            ).pack(fill="x", padx=10, pady=2)
        ctk.CTkButton(
            side,
            text=t("common.save_reload"),
            fg_color=COLORS["accent"],
            hover_color="#1da851",
            command=self._save_and_reload,
        ).pack(side="bottom", fill="x", padx=12, pady=16)

    def _build_pages(self) -> None:
        assert self._content is not None
        self._nav = {
            "dash": self._page_dash(),
            "acct": self._page_accounts(),
            "grp": self._page_address(),
            "rules": self._page_rules(),
            "sched": self._page_schedule(),
            "taskmgr": self._page_task_manager(),
            "logs": self._page_logs(),
        }
        for f in self._nav.values():
            f.grid(row=0, column=0, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

    def _show_nav(self, nav_id: str) -> None:
        # 切换页面前清 grab/topmost，避免弹窗/选文件后界面卡死、底栏异常
        try:
            release_modal_grabs(self)
        except Exception:
            pass
        self._current_nav = nav_id
        for k, f in self._nav.items():
            if k == nav_id:
                f.tkraise()
            else:
                f.grid_remove()
        self._nav[nav_id].grid(row=0, column=0, sticky="nsew")
        if nav_id == "dash":
            self._refresh_dashboard()
        elif nav_id == "acct":
            self._render_accounts()
        elif nav_id == "grp":
            self._refresh_owner_account_combos()
            self._render_address()
            foot = getattr(self, "_addr_foot", None)
            if foot is not None:
                try:
                    foot.lift()
                    foot.grid(row=2, column=0, sticky="ew")
                except Exception:
                    pass
        elif nav_id == "rules":
            pass
        elif nav_id == "sched":
            self._refresh_s2_target_checks()
            foot = getattr(self, "_sched_foot", None)
            if foot is not None:
                try:
                    foot.lift()
                    foot.grid(row=1, column=0, sticky="ew", pady=(10, 0))
                except Exception:
                    pass
        elif nav_id == "taskmgr":
            self._sync_taskmgr_page()
        elif nav_id == "logs":
            self._reload_logs_page()

    def bind_coordinator(self, coord: WaCoordinator) -> None:
        self._coord = coord

    def _schedule2_reminder(
        self, job_or_name: Any, step: int, note: str, paused_count: int = 0, affected_job_ids: Optional[List[str]] = None
    ) -> None:
        """阶段提醒：runner 已暂停，patch 任务卡片；可选置顶弹窗。"""
        ids = list(dict.fromkeys(affected_job_ids or []))
        overrides: Dict[str, Schedule2Job] = {}
        job = job_or_name if hasattr(job_or_name, "id") else None
        if job is not None:
            overrides[job.id] = job
            if job.id not in ids:
                ids.append(job.id)

        def run() -> None:
            if ids:
                self._patch_taskmgr_cards(ids, reorder=True, job_overrides=overrides or None)
            if not getattr(self._cfg, "stage_reminder_popup_enabled", True):
                return
            if job is None:
                return
            try:
                from notifier import show_stage_reminder
                from i18n.pause_reason import CODE_JOIN_GROUP_FAILED, pause_reason_is

                grp = format_job_targets_label(self._cfg, job)
                is_join = pause_reason_is(job.pause_reason or "", CODE_JOIN_GROUP_FAILED)
                if is_join:
                    # note 首行常含账号信息；subtitle 用文档名
                    acc = ""
                    for line in (note or "").splitlines():
                        if "账号" in line:
                            acc = line.strip()
                            break
                    subtitle = t("join.subtitle", name=job.source_name, account=acc or "—")
                    if grp:
                        subtitle += t("join.subtitle_group", grp=grp)
                    title = t("join.title_wa")
                else:
                    subtitle = t("stage.subtitle", step=step, name=job.source_name)
                    if grp:
                        subtitle += t("stage.subtitle_group", grp=grp)
                    title = t("stage.title_wa")
                body = (note or "").strip() or t("stage.no_note")
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

    def alert_callback(self, payload: Dict[str, Any]) -> None:
        p = dict(payload)
        chat_key = str(p.get("chat_key", ""))
        # 立即暂停（勿等 Tk 主线程），避免与排程发送竞态
        touched_ids = self._schedule2.pause_by_chat(
            chat_key,
            LISTEN_HIT_PAUSE_REASON_S2,
            event_title=str(p.get("chat_title", "")),
        )

        def run() -> None:
            record_alert()
            if touched_ids:
                info_i18n("log.listen_hit_paused", n=len(touched_ids))
                self._patch_taskmgr_cards(touched_ids, reorder=True)
            self._refresh_dashboard()
            try:
                AlertPopup(
                    self,
                    chat_title=str(p.get("chat_title", "")),
                    sender_name=str(p.get("sender_name", "")),
                    message_text=str(p.get("message_text", "")),
                    chat_jid=p.get("chat_jid"),
                )
            except Exception as exc:
                error_i18n("log.alert_popup_fail", err=exc)

        self.after(0, run)

    def shutdown_services(self, join_timeout: float = 2.0) -> None:
        from shutdown import shutdown_application

        if self._login_dlg:
            try:
                self._login_dlg.destroy()
            except Exception:
                pass
            self._login_dlg = None
        shutdown_application(
            coord=self._coord,
            listener=self._listener,
            schedule2=self._schedule2,
            login_cancel=self._login_cancel,
            join_timeout=join_timeout,
            kill_children=False,
        )

    def shutdown_ui(self) -> None:
        self._log_pump_on = False
        remove_memory_listener(self._on_log_line)

    def _on_exit(self) -> None:
        try:
            self.shutdown_services(join_timeout=2.0)
        except Exception as exc:
            error_i18n("log.exit_cleanup_fail", err=exc)
        self.shutdown_ui()

    def _on_log_line(self, line: str) -> None:
        if not is_visible_in_wa_log_view(line):
            return
        try:
            self._log_queue.put_nowait(line)
        except Exception:
            pass

    def _wa_log_lines(self, limit: int) -> List[str]:
        return filter_lines_for_wa_log_view(get_recent_lines(limit))

    def _drain_log_queue_to_textbox(self) -> None:
        lb = getattr(self, "_log_box", None)
        if lb is None:
            return
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            append_log_line_capped(lb, line, max_lines=LOG_TEXTBOX_MAX_LINES)

    def _reload_logs_page(self) -> None:
        lb = getattr(self, "_log_box", None)
        if lb is None:
            return
        reload_log_textbox_from_memory(
            lb,
            self._wa_log_lines,
            limit=LOG_TEXTBOX_MAX_LINES,
            max_lines=LOG_TEXTBOX_MAX_LINES,
            log_queue=getattr(self, "_log_queue", None),
        )

    def _pump_logs(self) -> None:
        if not self._log_pump_on:
            return
        on_logs = getattr(self, "_current_nav", "") == "logs"
        if on_logs:
            self._drain_log_queue_to_textbox()
        if self._log_pump_on:
            delay = LOG_PUMP_MS if on_logs else LOG_PUMP_IDLE_MS
            self.after(delay, self._pump_logs)

    def _save_and_reload(self) -> None:
        if getattr(self, "_stage_popup_var", None) is not None:
            self._cfg.stage_reminder_popup_enabled = bool(self._stage_popup_var.get())
        save_config(self._cfg)
        info_i18n("log.config_saved")
        threading.Thread(
            target=self._reload_services, name="wa-reload", daemon=True
        ).start()

    def _reload_services(self) -> None:
        if self._coord:
            self._coord.stop(join_timeout=12.0)
        self._cfg = load_config()
        self._listener.start(self._cfg, self.alert_callback)
        self._schedule2.start(self._cfg)
        if self._coord:
            self._coord.start(self._cfg)
        self.after(0, self._on_services_reloaded)

    def _on_services_reloaded(self) -> None:
        info_i18n("log.services_reloaded")
        self._render_accounts()
        self._refresh_dashboard()

    def _card(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        card.grid(row=row, column=0, sticky="ew", pady=8)
        card.grid_columnconfigure(0, weight=1)
        return card

    def _wrap_page(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        inner, canvas, finish = mount_page_scroll(parent, bg=COLORS["bg"])
        self._scroll_wheel_handler = lambda e, c=canvas: scroll_wheel(c, e)
        inner.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            inner,
            text=title,
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["text"],
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(8, 16))
        finish()
        return inner

    def _elastic_wraplabels(self, scroll_widget: ctk.CTkFrame, labels: List[ctk.CTkLabel], inset: int = 56) -> None:
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
        self.after(200, sync)

    def _refresh_dashboard(self) -> None:
        if not getattr(self, "_pages_ready", False):
            return
        n = today_alert_count()
        if hasattr(self, "_dash_today"):
            self._dash_today.configure(text=t("dash.today_count", n=n))
        listen_on = bool(self._cfg.listening_enabled)
        online = len(self._online_account_ids())
        conn = self._listener.is_running() and online > 0
        parts = [
            t("dash.listen_on") if listen_on else t("dash.listen_off"),
            t("dash.wa_connected") if conn else t("dash.wa_disconnected"),
        ]
        if listen_on and conn:
            parts.append(t("dash.listening_active"))
        elif listen_on and not conn:
            parts.append(t("dash.listen_on_disconnected"))
        if hasattr(self, "_dash_listen"):
            self._dash_listen.configure(text="  ·  ".join(parts))
        lines = []
        for a in self._cfg.accounts:
            if a.id in self._online_account_ids():
                st_txt = t("acct.connected")
            elif has_saved_session(a):
                st_txt = t("acct.logged_in_disconnected")
            else:
                st_txt = t("acct.not_logged_in")
            en_txt = t("dash.enabled") if a.enabled else t("dash.disabled")
            lines.append(t("dash.account_line", id=a.id, status=st_txt, enabled=en_txt))
        if hasattr(self, "_dash_acct"):
            self._dash_acct.configure(text="\n".join(lines) if lines else t("dash.no_accounts_configured"))

    # --- 仪表盘 ---
    def _page_dash(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        wrap = self._wrap_page(page, t("nav.dash"))

        c1 = self._card(wrap, 1)
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
        )
        self._dash_acct.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        self._elastic_wraplabels(wrap, [self._dash_listen, self._dash_acct])
        self._refresh_dashboard()
        return page

    # --- 账号 ---
    def _page_accounts(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        inner, canvas, finish = mount_page_scroll(page, bg=COLORS["bg"])
        self._scroll_wheel_handler = lambda e, c=canvas: scroll_wheel(c, e)
        ctk.CTkLabel(inner, text=t("acct.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=8)
        ctk.CTkLabel(
            inner,
            text=t("acct.wa_hint") + t("acct.wa_proxy_hint"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        proxy_hint = t("acct.proxy_ok") if proxy_supported() else t("acct.proxy_need_dll")
        ctk.CTkLabel(inner, text=proxy_hint, text_color=COLORS["muted"], wraplength=700, justify="left").pack(
            anchor="w", pady=(0, 12)
        )

        form = ctk.CTkFrame(inner, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        form.pack(fill="x", pady=8)
        self._acc_id = ctk.CTkEntry(form, placeholder_text=t("acct.id_ph"))
        self._acc_id.pack(fill="x", padx=12, pady=(12, 6))
        self._acc_phone = ctk.CTkEntry(form, placeholder_text=t("acct.phone_ph"))
        self._acc_phone.pack(fill="x", padx=12, pady=(0, 6))
        self._acc_proxy = ctk.CTkEntry(
            form,
            placeholder_text=t("acct.proxy_ph"),
        )
        self._acc_proxy.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkButton(form, text=t("acct.add"), fg_color=COLORS["accent"], command=self._add_account).pack(fill="x", padx=12, pady=(0, 12))

        self._acc_list = ctk.CTkFrame(inner, fg_color="transparent")
        self._acc_list.pack(fill="x")
        self._render_accounts()
        finish()
        return page

    def _online_account_ids(self) -> Set[str]:
        if self._coord is not None:
            return self._coord.connected_account_ids()
        return set()

    def _account_status_text(self, acc: Account) -> tuple[str, str]:
        if self._login_busy and acc.id == self._login_account_id:
            return t("acct.logging_in"), COLORS["accent"]
        if acc.id in self._online_account_ids():
            return t("acct.connected"), COLORS["success"]
        if has_saved_session(acc):
            return t("acct.logged_in_disconnected"), "#e6c84f"
        return t("acct.not_logged_in"), COLORS["danger"]

    def _render_accounts(self) -> None:
        for w in self._acc_list.winfo_children():
            w.destroy()
        handler = getattr(self, "_scroll_wheel_handler", None)
        for acc in self._cfg.accounts:
            row = ctk.CTkFrame(self._acc_list, fg_color=COLORS["card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
            row.pack(fill="x", pady=4)
            var = ctk.BooleanVar(value=acc.enabled)
            def _on_enabled_toggle(a: Account = acc, v: ctk.BooleanVar = var) -> None:
                a.enabled = bool(v.get())
                save_config(self._cfg)
                self._refresh_owner_account_combos()

            ctk.CTkCheckBox(row, text="", variable=var, width=24, command=_on_enabled_toggle).pack(side="left", padx=8)
            mid = ctk.CTkFrame(row, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True, padx=4, pady=6)
            ctk.CTkLabel(mid, text=acc.id, font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text"], anchor="w").pack(anchor="w")
            sub = acc.phone or t("acct.no_phone")
            st_txt, st_color = self._account_status_text(acc)
            ctk.CTkLabel(mid, text=f"{sub} · {st_txt}", text_color=st_color, anchor="w").pack(anchor="w")
            proxy_row = ctk.CTkFrame(mid, fg_color="transparent")
            proxy_row.pack(fill="x", pady=(4, 0))
            proxy_ent = ctk.CTkEntry(
                proxy_row,
                placeholder_text=t("acct.proxy_inline_ph"),
                height=28,
            )
            if acc.proxy:
                proxy_ent.insert(0, acc.proxy)
            proxy_ent.pack(side="left", fill="x", expand=True)

            def _save_proxy(a: Account = acc, ent: ctk.CTkEntry = proxy_ent) -> None:
                raw = ent.get().strip()
                if raw:
                    try:
                        normalize_proxy_url(raw)
                    except ValueError as exc:
                        info_i18n("log.proxy_invalid", id=a.id, err=exc)
                        return
                a.proxy = raw
                save_config(self._cfg)
                if raw:
                    info_i18n("log.proxy_saved", id=a.id)

            ctk.CTkButton(proxy_row, text=t("acct.save_proxy"), width=72, height=28, command=_save_proxy).pack(side="right", padx=(6, 0))
            login_state = "normal"
            if self._login_busy:
                login_state = "disabled"
            ctk.CTkButton(
                row,
                text=t("acct.login"),
                width=72,
                fg_color=COLORS["accent"],
                state=login_state,
                command=lambda a=acc: self._login_account(a),
            ).pack(side="right", padx=4, pady=6)
            ctk.CTkButton(row, text=t("common.delete"), width=60, fg_color=COLORS["danger"], command=lambda a=acc: self._del_account(a)).pack(side="right", padx=4, pady=6)
        if handler:
            bind_scroll_tree_once(self._acc_list, handler)

    def _add_account(self) -> None:
        aid = self._acc_id.get().strip()
        if not aid:
            info_i18n("log.acct_id_required")
            return
        if any(a.id == aid for a in self._cfg.accounts):
            info_i18n("log.acct_exists")
            return
        proxy_raw = self._acc_proxy.get().strip()
        if proxy_raw:
            try:
                normalize_proxy_url(proxy_raw)
            except ValueError as exc:
                info_i18n("log.proxy_format_invalid", err=exc)
                return
        self._cfg.accounts.append(
            Account(
                id=aid,
                session_name=aid,
                enabled=True,
                phone=self._acc_phone.get().strip(),
                proxy=proxy_raw,
            )
        )
        save_config(self._cfg)
        self._schedule2.refresh_accounts(self._cfg)
        self._acc_id.delete(0, "end")
        self._acc_phone.delete(0, "end")
        self._acc_proxy.delete(0, "end")
        self._render_accounts()
        self._refresh_owner_account_combos()
        info_i18n("log.acct_added", id=aid)

    def _del_account(self, acc: Account) -> None:
        self._cfg.accounts = [a for a in self._cfg.accounts if a.id != acc.id]
        save_config(self._cfg)
        self._render_accounts()

    def _login_account(self, acc: Account) -> None:
        if self._login_busy:
            info_i18n("log.login_busy")
            return
        if self._login_dlg:
            try:
                self._login_dlg.destroy()
            except Exception:
                pass
        self._login_cancel = threading.Event()
        self._login_busy = True
        self._login_account_id = acc.id
        self._render_accounts()
        login_acc = acc

        def on_qr(data: bytes) -> None:
            def show(d: bytes = data) -> None:
                if self._login_dlg:
                    self._login_dlg.update_qr(d)

            self.after(0, show)

        def on_status(text: str) -> None:
            def show(s: str = text) -> None:
                if self._login_dlg:
                    self._login_dlg.set_status(s)

            self.after(0, show)

        def on_done(ok: bool, msg: str) -> None:
            def finish() -> None:
                dlg = self._login_dlg
                self._login_dlg = None
                if dlg:
                    try:
                        dlg.grab_release()
                    except Exception:
                        pass
                    try:
                        dlg.withdraw()
                    except Exception:
                        pass
                    try:
                        dlg.destroy()
                    except Exception:
                        pass
                self._login_busy = False
                self._login_account_id = None
                if self._coord and not ok:
                    self._coord.release_login_hold(login_acc.id)
                self._render_accounts()
                self.update_idletasks()
                if ok:
                    info_i18n("log.login_ok_connecting", id=login_acc.id, msg=msg)
                    save_config(self._cfg)
                    # 等待后台释放登录客户端的数据库锁后再连接
                    self.after(1500, lambda: self._on_account_logged_in(login_acc.id))
                else:
                    info_i18n("log.login_incomplete", msg=msg)
                    if msg and msg != t("common.cancelled"):
                        show_message(self, t("acct.login_fail_title"), msg)

            try:
                self.after(0, finish)
            except Exception:
                finish()

        def on_cancel() -> None:
            if self._login_cancel:
                self._login_cancel.set()
            # hold 在 on_done 里释放，避免取消瞬间被批量连接抢库

        def before_connect() -> None:
            if self._coord:
                self._coord.prepare_for_login(login_acc.id)

        # 立刻弹窗并占住 hold，其它账号连接中也可扫码
        if self._coord:
            self._coord.begin_login_hold(login_acc.id)
        self._login_dlg = QrLoginDialog(
            self,
            account_id=login_acc.id,
            on_cancel=on_cancel,
        )
        self._login_dlg.set_status(t("qr.preparing"))
        info_i18n("log.login_wait_qr", id=login_acc.id)
        run_qr_login_in_thread(
            login_acc,
            on_qr,
            on_done,
            cancel_event=self._login_cancel,
            on_status=on_status,
            before_connect=before_connect,
        )

    def _on_account_logged_in(self, account_id: str) -> None:
        self._cfg = load_config()
        self._schedule2.refresh_accounts(self._cfg)
        if self._coord:
            self._coord.connect_account_after_login(self._cfg, account_id)
        self._render_accounts()
        self._refresh_owner_account_combos()
        self._refresh_dashboard()

    # --- 通讯录 ---
    def _page_address(self) -> ctk.CTkFrame:
        """列表可伸缩占满中部；底部添加表单用 grid 固定，避免被固定高度列表挤没。"""
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        page.grid_rowconfigure(2, weight=0)
        self._addr_page = page

        header = ctk.CTkFrame(page, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text=t("grp.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", pady=(8, 4)
        )
        ctk.CTkLabel(
            header,
            text=t("grp.hint"),
            text_color=COLORS["muted"],
            wraplength=680,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))

        list_host = ctk.CTkFrame(page, fg_color="transparent")
        list_host.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        list_card = ctk.CTkFrame(
            list_host, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"]
        )
        list_card.pack(fill="both", expand=True)
        ctk.CTkLabel(list_card, text=t("grp.list_title"), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=(10, 4))
        # 不用固定 400 高：小窗口下会把底栏顶出可视区
        list_inner, list_canvas, finish_list = mount_page_scroll(list_card, bg=COLORS["bg"])
        self._ab_list_scroll_handler = lambda e, c=list_canvas: scroll_wheel(c, e)
        self._ab_rows = ctk.CTkFrame(list_inner, fg_color="transparent")
        self._ab_rows.pack(fill="x")
        self._ab_scroll_bound = False
        self._render_address()
        finish_list()

        addr_foot = ctk.CTkFrame(
            page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"]
        )
        addr_foot.grid(row=2, column=0, sticky="ew")
        self._addr_foot = addr_foot
        form = ctk.CTkFrame(addr_foot, fg_color="transparent")
        form.pack(fill="x", padx=10, pady=8)

        def _addr_field_row(label: str, placeholder: str) -> ctk.CTkEntry:
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, text_color=COLORS["muted"], width=52, anchor="w").pack(side="left", padx=(0, 6))
            ent = ctk.CTkEntry(row, placeholder_text=placeholder, height=28)
            ent.pack(side="left", fill="x", expand=True)
            return ent

        self._ab_remark = _addr_field_row(t("grp.remark"), t("grp.display_name_ph"))
        self._ab_chat = _addr_field_row(t("grp.group"), t("grp.chat_ph"))
        self._ab_user = _addr_field_row(t("grp.user"), t("grp.user_ph"))

        action = ctk.CTkFrame(form, fg_color="transparent")
        action.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(action, text=t("grp.owner"), text_color=COLORS["muted"], width=52, anchor="w").pack(
            side="left", padx=(0, 6)
        )
        acc_own = self._owner_account_values()
        self._ab_owner = ctk.CTkComboBox(action, width=88, height=28, values=acc_own or ["—"])
        self._ab_owner.pack(side="left", padx=(0, 8))
        if acc_own:
            self._ab_owner.set(acc_own[0])
        else:
            self._ab_owner.set("—")
        self._ab_listen = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            action,
            text=t("grp.listen"),
            variable=self._ab_listen,
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
            command=self._add_address,
        ).pack(side="left")
        return page

    def _owner_account_values(self) -> List[str]:
        """通讯录归属账号：列出账号管理中全部账号（不限于勾选启用）。"""
        return [a.id for a in self._cfg.accounts]

    def _refresh_owner_account_combos(self) -> None:
        vals = self._owner_account_values()
        if not getattr(self, "_ab_owner", None):
            return
        cur = self._ab_owner.get().strip()
        if vals:
            self._ab_owner.configure(values=vals)
            self._ab_owner.set(cur if cur in vals else vals[0])
        else:
            self._ab_owner.configure(values=["—"])
            self._ab_owner.set("—")

    def _after_address_book_order_changed(self) -> None:
        self._render_address()
        if hasattr(self, "_s2_targets"):
            self._refresh_s2_target_checks()

    def _move_address_book_entry(self, idx: int, delta: int) -> None:
        book = self._cfg.address_book
        j = idx + delta
        if idx < 0 or idx >= len(book) or j < 0 or j >= len(book):
            return
        book[idx], book[j] = book[j], book[idx]
        save_config(self._cfg)
        self._after_address_book_order_changed()

    def _persist_address_remark(self, idx: int, remark: str) -> None:
        text = (remark or "").strip() or t("grp.unnamed")
        if idx < 0 or idx >= len(self._cfg.address_book):
            return
        ent = self._cfg.address_book[idx]
        if ent.remark == text:
            return
        ent.remark = text
        save_config(self._cfg)
        if hasattr(self, "_s2_targets"):
            self._refresh_s2_target_checks()
        info_i18n("log.remark_updated", text=text)

    def _persist_address_owner(self, idx: int, owner_id: str) -> None:
        """通讯录归属账号变更后立即写入 config.json。"""
        val = (owner_id or "").strip()
        if not val or val in ("—", t("grp.please_select")):
            return
        if idx < 0 or idx >= len(self._cfg.address_book):
            return
        ent = self._cfg.address_book[idx]
        if ent.owner_account_id == val:
            return
        ent.owner_account_id = val
        save_config(self._cfg)
        if hasattr(self, "_s2_targets"):
            self._refresh_s2_target_checks()
        self._render_address()

    def _render_address(self) -> None:
        for w in self._ab_rows.winfo_children():
            w.destroy()
        acc_vals = self._owner_account_values()
        n_book = len(self._cfg.address_book)
        for i, ent in enumerate(self._cfg.address_book):
            audit_extra, border_color = self._watch_audit_display(ent)
            row = ctk.CTkFrame(
                self._ab_rows,
                fg_color=COLORS["card"],
                corner_radius=10,
                border_width=1,
                border_color=border_color,
            )
            row.pack(fill="x", pady=4)
            tag = t("grp.listen_tag") if ent.listen_enabled else t("grp.schedule_only")
            owner_txt = (ent.owner_account_id or "").strip() or t("grp.not_selected")
            head = ctk.CTkFrame(row, fg_color="transparent")
            head.pack(fill="x", padx=12, pady=(8, 0))
            title_txt = f"{i + 1}. {ent.remark or ent.id}"
            if self._watch_audit_flags.get(ent.id) == WatchAuditStatus.ABSENT.value:
                title_txt += t("grp.not_in_group_badge")
            ctk.CTkLabel(
                head,
                text=title_txt,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=COLORS["danger"] if audit_extra else COLORS["text"],
            ).pack(side="left")
            order_btns = ctk.CTkFrame(head, fg_color="transparent")
            order_btns.pack(side="right")
            ctk.CTkButton(
                order_btns,
                text="↑",
                width=36,
                height=28,
                fg_color=COLORS["border"],
                state="normal" if i > 0 else "disabled",
                command=lambda idx=i: self._move_address_book_entry(idx, -1),
            ).pack(side="left", padx=(0, 4))
            ctk.CTkButton(
                order_btns,
                text="↓",
                width=36,
                height=28,
                fg_color=COLORS["border"],
                state="normal" if i < n_book - 1 else "disabled",
                command=lambda idx=i: self._move_address_book_entry(idx, 1),
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=t(
                    "grp.entry_summary",
                    tag=tag,
                    chat=ent.chat_ref,
                    user=ent.watch_user or "—",
                    owner=owner_txt,
                    audit=audit_extra,
                ),
                text_color=COLORS["danger"] if audit_extra else COLORS["text"],
                justify="left",
            ).pack(anchor="w", padx=12, pady=(10, 4))
            ctrl = ctk.CTkFrame(row, fg_color="transparent")
            ctrl.pack(fill="x", padx=12, pady=(0, 10))
            remark_row = ctk.CTkFrame(ctrl, fg_color="transparent")
            remark_row.pack(fill="x", pady=(0, 6))
            ctk.CTkLabel(remark_row, text=t("grp.remark"), text_color=COLORS["muted"]).pack(side="left", padx=(0, 8))
            remark_entry = ctk.CTkEntry(remark_row, width=220)
            remark_entry.insert(0, ent.remark or "")
            remark_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

            def make_remark_save(idx: int, entry: ctk.CTkEntry):
                def _save() -> None:
                    self._persist_address_remark(idx, entry.get())

                return _save

            ctk.CTkButton(
                remark_row,
                text=t("grp.save_remark"),
                width=88,
                fg_color=COLORS["border"],
                command=make_remark_save(i, remark_entry),
            ).pack(side="left")
            own_row = ctk.CTkFrame(ctrl, fg_color="transparent")
            own_row.pack(fill="x", pady=(0, 6))
            ctk.CTkLabel(own_row, text=t("grp.owner_account"), text_color=COLORS["muted"]).pack(side="left", padx=(0, 8))

            def make_owner_change(idx: int):
                def on_pick(choice: str) -> None:
                    self._persist_address_owner(idx, choice)

                return on_pick

            please_select = t("grp.please_select")
            vals = ([please_select] + acc_vals) if acc_vals else [please_select]
            own_combo = ctk.CTkComboBox(own_row, width=140, values=vals, command=make_owner_change(i))
            cur_own = (ent.owner_account_id or "").strip()
            if cur_own and cur_own in acc_vals:
                own_combo.set(cur_own)
            else:
                own_combo.set(please_select)
            own_combo.pack(side="left")
            ctk.CTkButton(ctrl, text=t("common.delete"), fg_color=COLORS["danger"], command=lambda e=ent: self._del_address(e)).pack(
                fill="x", pady=(4, 0)
            )
        if not getattr(self, "_ab_scroll_bound", False):
            self._ab_scroll_bound = True
            handler = getattr(self, "_ab_list_scroll_handler", None)
            if handler:
                bind_scroll_tree_once(self._ab_rows, handler)

    def _commit_address_book(self, *, resolve_online: bool = True) -> None:
        save_config(self._cfg)
        self._render_address()
        if hasattr(self, "_s2_targets"):
            self._refresh_s2_target_checks()
        if not resolve_online:
            return
        if self._coord and self._coord.has_connected_clients():
            self._coord.apply_config_hot(self._cfg)
            self.after(800, self._render_address)
            info_i18n("log.address_updated_online")
        else:
            info_i18n("log.address_saved_offline")

    def _add_address(self) -> None:
        try:
            chat_ref = parse_chat_ref_input(self._ab_chat.get())
            watch_user = ""
            if self._ab_listen.get():
                raw_u = self._ab_user.get().strip()
                if raw_u:
                    watch_user = parse_watch_user_input(raw_u)
                elif not self._ab_user.get().strip():
                    info_i18n("log.watch_user_required")
                    return
        except ValueError as exc:
            info(str(exc))
            return
        acc_vals = self._owner_account_values()
        if not acc_vals:
            info_i18n("log.need_account_first")
            return
        owner_acc = self._ab_owner.get().strip() if getattr(self, "_ab_owner", None) else ""
        please_select = t("grp.please_select")
        if owner_acc in ("", "—", please_select):
            owner_acc = acc_vals[0]
        if owner_acc not in acc_vals:
            info_i18n("log.need_owner_account")
            return
        ent = AddressEntry(
            id=uuid.uuid4().hex[:12],
            remark=self._ab_remark.get().strip() or t("grp.unnamed"),
            chat_ref=chat_ref,
            watch_user=watch_user,
            listen_enabled=bool(self._ab_listen.get()),
            owner_account_id=owner_acc,
        )
        self._cfg.address_book.append(ent)
        self._ab_remark.delete(0, "end")
        self._ab_chat.delete(0, "end")
        self._ab_user.delete(0, "end")
        self._ab_listen.set(True)
        if acc_vals:
            self._ab_owner.set(acc_vals[0])
        try:
            self._commit_address_book()
            info_i18n("log.address_added", remark=ent.remark, owner=owner_acc)
        except Exception as exc:
            error_i18n("log.address_add_fail", err=exc)
            self._cfg.address_book = [e for e in self._cfg.address_book if e.id != ent.id]

    def _del_address(self, ent: AddressEntry) -> None:
        self._cfg.address_book = [e for e in self._cfg.address_book if e.id != ent.id]
        self._commit_address_book()

    # --- 监听规则 ---
    def _page_rules(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        wrap = ctk.CTkScrollableFrame(page, fg_color="transparent")
        wrap.pack(fill="both", expand=True)
        ctk.CTkLabel(wrap, text=t("rules.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(anchor="w", pady=8)
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
            text=t("rules.enable_listen"),
            variable=self._listen_var,
            command=lambda: setattr(self._cfg, "listening_enabled", self._listen_var.get()),
            text_color=COLORS["text"],
        ).pack(anchor="w", padx=14, pady=(0, 4))
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
        ctk.CTkLabel(box, text=t("rules.rate_limit"), text_color=COLORS["muted"]).pack(anchor="w", padx=14)
        self._rate_entry = ctk.CTkEntry(box)
        self._rate_entry.insert(0, str(self._cfg.rate_limit_seconds))
        self._rate_entry.pack(fill="x", padx=14, pady=(4, 14))
        self._rate_entry.bind("<FocusOut>", lambda _e: self._save_rate())

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
            hover_color="#1da851",
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
            hover_color="#1da851",
            command=self._check_watch_memberships,
        ).pack(fill="x", padx=14, pady=(0, 14))
        return page

    def _on_lang_combo_changed(self, choice: str) -> None:
        lang = lang_from_combo_label(choice)
        set_lang_for_next_launch(lang)
        info_i18n("rules.lang_saved", lang=combo_label_for_lang(lang))

    def _watch_audit_display(self, ent: AddressEntry) -> Tuple[str, str]:
        st = self._watch_audit_flags.get(ent.id, "")
        if st == WatchAuditStatus.ABSENT.value:
            return (
                t("audit.absent"),
                COLORS["danger"],
            )
        if st == WatchAuditStatus.ERROR.value:
            detail = (self._watch_audit_details.get(ent.id) or "").strip()
            msg = detail or t("audit.parse_fail")
            return (t("audit.error", msg=msg), COLORS["border"])
        if st == WatchAuditStatus.OFFLINE.value:
            return (t("audit.offline"), COLORS["border"])
        return "", COLORS["border"]

    def _check_watch_memberships(self) -> None:
        if getattr(self, "_watch_audit_busy", False):
            info_i18n("log.audit_busy")
            return
        if not self._coord or not self._coord.has_connected_clients():
            info_i18n("log.audit_need_login")
            return
        self._watch_audit_busy = True
        info_i18n("log.audit_start")

        def on_done(result: Dict[str, WatchAuditRow]) -> None:
            def finish() -> None:
                self._watch_audit_busy = False
                self._apply_watch_membership_audit(result)

            self.after(0, finish)

        if not self._coord.request_watch_membership_audit(self._cfg, on_done):
            self._watch_audit_busy = False
            info_i18n("log.audit_no_online")

    def _apply_watch_membership_audit(self, result: Dict[str, WatchAuditRow]) -> None:
        flags: Dict[str, str] = {eid: row.status.value for eid, row in result.items()}
        details: Dict[str, str] = {
            eid: (row.detail or "").strip()
            for eid, row in result.items()
            if (row.detail or "").strip()
        }
        ok = sum(1 for r in result.values() if r.status == WatchAuditStatus.OK)
        absent = sum(1 for r in result.values() if r.status == WatchAuditStatus.ABSENT)
        err = sum(1 for r in result.values() if r.status == WatchAuditStatus.ERROR)
        offline = sum(1 for r in result.values() if r.status == WatchAuditStatus.OFFLINE)
        self._watch_audit_flags = flags
        self._watch_audit_details = details
        self._render_address()
        if not result:
            info_i18n("log.audit_incomplete")
            return
        parts = [t("log.audit_checked", n=ok + absent)]
        if absent:
            parts.append(t("log.audit_absent", n=absent))
        if err:
            parts.append(t("log.audit_failed", n=err))
            sample = [
                (ent.remark or ent.id, details.get(ent.id, ""))
                for ent in self._cfg.address_book
                if flags.get(ent.id) == WatchAuditStatus.ERROR.value and details.get(ent.id)
            ][:3]
            for name, det in sample:
                info_i18n("log.audit_fail_sample", name=name, detail=det)
        if offline:
            parts.append(t("log.audit_offline", n=offline))
        info(t("log.audit_summary", summary="；".join(parts)))

    def _sync_last_schedule_from_jobs(self) -> None:
        from schedule2_runner import load_schedule2_jobs

        before = {e.id: (e.last_schedule_source_name or "").strip() for e in self._cfg.address_book}
        n_jobs = len(load_schedule2_jobs())
        apply_last_schedule_from_current_jobs(self._cfg)
        n_changed = sum(
            1
            for e in self._cfg.address_book
            if before.get(e.id, "") != (e.last_schedule_source_name or "").strip()
        )
        n_filled = sum(1 for e in self._cfg.address_book if (e.last_schedule_source_name or "").strip())
        self._refresh_s2_target_checks()
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

    def _save_rate(self) -> None:
        try:
            self._cfg.rate_limit_seconds = float(self._rate_entry.get().strip())
            save_config(self._cfg)
        except ValueError:
            pass

    # --- 定时任务（多任务 + 发送账号覆盖） ---
    def _schedule_doc_path(self) -> str:
        for p in (resource_path("docs", "定时任务导入说明与示例.txt"), os.path.join(app_root(), "docs", "定时任务导入说明与示例.txt")):
            if os.path.isfile(p):
                return p
        return os.path.join(app_root(), "docs", "定时任务导入说明与示例.txt")

    def _account_id_values(self) -> List[str]:
        ids = [a.id for a in self._cfg.accounts]
        return ids if ids else ["—"]

    def _page_schedule(self) -> ctk.CTkFrame:
        """群勾选在滚动区；间隔/TXT/添加用 grid 固定页底，避免被滚动区盖住。"""
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)

        scroll_host = ctk.CTkFrame(page, fg_color="transparent")
        scroll_host.grid(row=0, column=0, sticky="nsew")

        sched_foot = ctk.CTkFrame(
            page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"]
        )
        sched_foot.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self._sched_foot = sched_foot
        sf = ctk.CTkFrame(sched_foot, fg_color="transparent")
        sf.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(
            sf,
            text=t("sched.interval_hint"),
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(0, 4))
        self._s2_interval = ctk.CTkEntry(sf)
        self._s2_interval.insert(0, "5-10")
        self._s2_interval.pack(fill="x", pady=(0, 6))
        self._s2_file = ctk.CTkEntry(sf, placeholder_text=t("sched.file_ph"))
        self._s2_file.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(sf, text=t("sched.pick_source"), fg_color=COLORS["border"], command=self._pick_s2_source).pack(
            fill="x", pady=(0, 6)
        )
        ctk.CTkButton(sf, text=t("sched.add_job"), fg_color=COLORS["accent"], command=self._add_s2_job).pack(fill="x")

        inner, canvas, finish = mount_page_scroll(scroll_host, bg=COLORS["bg"])
        self._scroll_wheel_handler = lambda e, c=canvas: scroll_wheel(c, e)
        ctk.CTkLabel(inner, text=t("sched.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", pady=8
        )
        ctk.CTkLabel(
            inner,
            text=t("sched.wa_hint"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        ctk.CTkButton(
            inner,
            text=t("sched.txt_format"),
            fg_color=COLORS["border"],
            command=lambda: webbrowser.open(Path(self._schedule_doc_path()).as_uri())
            if os.path.isfile(self._schedule_doc_path())
            else info_i18n("log.doc_not_found"),
        ).pack(anchor="w", pady=4)

        form = ctk.CTkFrame(inner, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        form.pack(fill="x", pady=8)
        ctk.CTkLabel(form, text=t("sched.targets"), text_color=COLORS["muted"]).pack(anchor="w", padx=12, pady=(10, 4))
        self._s2_targets = ctk.CTkFrame(form, fg_color="transparent")
        self._s2_targets.pack(fill="x", padx=10, pady=(4, 12))
        self._refresh_s2_target_checks()

        edit_card = ctk.CTkFrame(inner, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        edit_card.pack(fill="x", pady=8)
        ctk.CTkLabel(
            edit_card, text=t("sched.advanced"), font=ctk.CTkFont(size=13, weight="bold"), text_color=COLORS["text"]
        ).pack(anchor="w", padx=12, pady=(12, 8))
        pr = ctk.CTkFrame(edit_card, fg_color="transparent")
        pr.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(pr, text=t("sched.pick_job"), text_color=COLORS["muted"]).pack(side="left", padx=(0, 8))
        self._s2_job_pick = ctk.CTkComboBox(pr, width=280, values=["—"], command=self._on_s2_job_pick_changed)
        self._s2_job_pick.pack(side="left", fill="x", expand=True)
        br = ctk.CTkFrame(edit_card, fg_color="transparent")
        br.pack(fill="x", padx=12, pady=(4, 12))
        ctk.CTkLabel(br, text=t("sched.from_account"), text_color=COLORS["muted"]).grid(
            row=0, column=0, padx=(0, 8), pady=4, sticky="w"
        )
        self._s2_bulk_from = ctk.CTkComboBox(br, width=160, values=["—"])
        self._s2_bulk_from.grid(row=0, column=1, pady=4, sticky="w")
        ctk.CTkLabel(br, text=t("sched.to_account"), text_color=COLORS["muted"]).grid(
            row=1, column=0, padx=(0, 8), pady=4, sticky="w"
        )
        self._s2_bulk_to = ctk.CTkComboBox(br, width=160, values=self._account_id_values())
        self._s2_bulk_to.grid(row=1, column=1, pady=4, sticky="w")
        ctk.CTkButton(br, text=t("sched.bulk_replace"), fg_color=COLORS["border"], command=self._s2_bulk_replace).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=8
        )

        ctk.CTkLabel(
            inner,
            text=t("sched.status_hint"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(8, 4))
        finish()
        return page

    def _page_task_manager(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")
        inner, canvas, finish = mount_page_scroll(page, bg=COLORS["bg"])
        self._taskmgr_scroll_handler = lambda e, c=canvas: scroll_wheel(c, e)
        ctk.CTkLabel(inner, text=t("taskmgr.title"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", pady=(8, 4)
        )
        ctk.CTkLabel(
            inner,
            text=t("taskmgr.legend"),
            text_color=COLORS["muted"],
            wraplength=700,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        self._taskmgr_count_lbl = ctk.CTkLabel(
            inner,
            text=t("taskmgr.count.total", total=0),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
        )
        self._taskmgr_count_lbl.pack(anchor="w", pady=(0, 10))
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(
            top,
            text=t("taskmgr.resume_all"),
            fg_color=COLORS["accent"],
            hover_color="#1da851",
            height=40,
            command=self._resume_all_s2_jobs,
        ).pack(fill="x")
        img_row = ctk.CTkFrame(top, fg_color="transparent")
        img_row.pack(fill="x", pady=(8, 0))
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
            top,
            text=t("taskmgr.next_day"),
            fg_color="#5a4a12",
            hover_color="#6d5a18",
            height=38,
            command=lambda: self.after(10, self._start_next_s2_folder_day),
        ).pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            top,
            text=t("taskmgr.reload_folder_txt"),
            fg_color="#3a3a55",
            hover_color="#4a4a68",
            height=38,
            command=self._reload_s2_folder_scripts,
        ).pack(fill="x", pady=(8, 0))
        self._btn_manual_folder_day = ctk.CTkButton(
            top,
            text=t("taskmgr.manual_day"),
            fg_color="#2a4a5a",
            hover_color="#356878",
            height=38,
            command=self._toggle_manual_folder_advance_mode,
        )
        self._btn_manual_folder_day.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            top,
            text=t("taskmgr.delete_all"),
            fg_color=COLORS["danger"],
            hover_color="#b63a3a",
            height=38,
            command=self._delete_all_s2_jobs,
        ).pack(fill="x", pady=(8, 0))
        self._taskmgr_cards = ctk.CTkFrame(inner, fg_color="transparent")
        self._taskmgr_cards.pack(fill="both", expand=True, pady=4)
        self._render_taskmgr_cards(force=True)
        finish()
        return page

    def _bind_task_card_click(self, widget: ctk.CTkBaseClass, job_id: str) -> None:
        def on_click(_event: Any = None) -> None:
            if self._manual_folder_advance_mode:
                self._manual_advance_s2_folder_day_by_id(job_id)
            else:
                self._toggle_s2_run_by_id(job_id)

        widget.bind("<Button-1>", on_click)
        for child in widget.winfo_children():
            self._bind_task_card_click(child, job_id)

    def _taskmgr_fingerprint(self, j: Schedule2Job, cfg: Any) -> tuple:
        return (
            schedule2_job_is_running(j),
            j.enabled,
            j.state,
            (j.pause_reason or "")[:40],
            j.cursor,
            j.source_name,
            getattr(j, "folder_day_index", 0),
            is_folder_job(j),
            schedule2_job_step_label(j),
            schedule2_job_target_remarks(cfg, j),
            self._task_reminder_summary(j),
        )

    def _task_reminder_summary(self, j: Schedule2Job) -> str:
        return operator_note_for_items(j.rows, cursor=int(j.cursor or 0), max_len=56)

    def _apply_taskmgr_tile(self, w: Dict[str, Any], j: Schedule2Job, cfg: Any) -> None:
        running = schedule2_job_is_running(j)
        pal = taskmgr_tile_palette(running=running, enabled=bool(j.enabled), pause_reason=j.pause_reason or "")
        w["card"].configure(fg_color=pal["fg"], border_color=pal["border"])
        w["title"].configure(text=schedule2_job_target_remarks(cfg, j), text_color=pal["title"])
        w["status"].configure(
            text=taskmgr_card_status_text(
                schedule2_job_status_label(j),
                schedule2_job_step_label(j),
            ),
            text_color=pal["status"],
        )
        fname = taskmgr_job_file_label(j)
        w["file"].configure(
            text=fname,
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
            hint = t("taskmgr.hint_next_day") if can_advance_folder_day(j) else t("taskmgr.hint_last_day")
        w["hint"].configure(text=hint, text_color=pal["hint"])

    def _build_taskmgr_tile(self, j: Schedule2Job, cfg: Any, index: int) -> Dict[str, Any]:
        running = schedule2_job_is_running(j)
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
            text=schedule2_job_target_remarks(cfg, j),
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
            command=lambda jid=j.id: self._del_s2_job_by_id(jid),
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
        self._apply_taskmgr_tile(widgets, j, cfg)
        self._bind_task_card_click(body, j.id)
        return widgets

    def _full_rebuild_taskmgr_grid(self, jobs: List[Schedule2Job], cfg: Any) -> None:
        for w in self._taskmgr_cards.winfo_children():
            w.destroy()
        self._taskmgr_widgets.clear()
        self._taskmgr_fp_cache.clear()
        configure_equal_columns(self._taskmgr_cards, TASKMGR_COLS, uniform="wa_task")
        for i, j in enumerate(jobs):
            self._taskmgr_widgets[j.id] = self._build_taskmgr_tile(j, cfg, i)
            self._taskmgr_fp_cache[j.id] = self._taskmgr_fingerprint(j, cfg)

    def _patch_taskmgr_cards(
        self,
        job_ids: Iterable[str],
        *,
        reorder: bool = True,
        job_overrides: Optional[Dict[str, Schedule2Job]] = None,
    ) -> None:
        """只更新指定卡片的文案/颜色；可选重排一次（保留置顶规则）。"""
        if not hasattr(self, "_taskmgr_cards"):
            return
        unique_ids = list(dict.fromkeys(job_ids))
        if not unique_ids:
            return
        overrides = dict(job_overrides or {})
        jobs = load_schedule2_jobs()
        job_map = {j.id: j for j in jobs}
        job_map.update(overrides)
        merged_jobs: List[Schedule2Job] = []
        seen: Set[str] = set()
        for j in jobs:
            merged_jobs.append(job_map[j.id])
            seen.add(j.id)
        for jid, oj in overrides.items():
            if jid not in seen:
                merged_jobs.append(oj)
        cfg = self._cfg
        for jid in unique_ids:
            j = job_map.get(jid)
            if j is None:
                continue
            w = self._taskmgr_widgets.get(jid)
            if w is None:
                continue
            self._taskmgr_fp_cache[jid] = self._taskmgr_fingerprint(j, cfg)
            self._apply_taskmgr_tile(w, j, cfg)
        self._update_taskmgr_count_label(merged_jobs)
        if reorder:
            self._sync_taskmgr_display_order(merged_jobs)

    def _refresh_taskmgr_card(self, job_id: str) -> None:
        """单卡暂停/继续：只 patch 该卡并重排。"""
        if not hasattr(self, "_taskmgr_cards"):
            return
        jobs = load_schedule2_jobs()
        if next((x for x in jobs if x.id == job_id), None) is None:
            self._render_taskmgr_cards(force=True)
            return
        if self._taskmgr_widgets.get(job_id) is None:
            self._sync_taskmgr_page()
            return
        self._patch_taskmgr_cards([job_id], reorder=True)

    def _sync_taskmgr_page(self) -> None:
        """进入任务管理页时手动同步（非定时刷新）。"""
        if not hasattr(self, "_taskmgr_cards"):
            return
        jobs = load_schedule2_jobs()
        if not jobs:
            self._render_taskmgr_cards(force=False)
            return
        ids = [j.id for j in jobs]
        if ids != self._taskmgr_listed_ids:
            self._render_taskmgr_cards(force=True)
            return
        self._patch_taskmgr_cards([j.id for j in jobs], reorder=True)

    def _sync_taskmgr_display_order(self, jobs: List[Schedule2Job]) -> None:
        display_jobs = taskmgr_sort_jobs_for_display(jobs, is_running=schedule2_job_is_running)
        display_ids = [j.id for j in display_jobs]
        if display_ids == self._taskmgr_display_ids:
            return
        reorder_taskmgr_grid(self._taskmgr_widgets, display_jobs, cols=TASKMGR_COLS, padx=6, pady=6)
        self._taskmgr_display_ids = display_ids

    def _update_taskmgr_count_label(self, jobs: List[Schedule2Job]) -> None:
        lbl = getattr(self, "_taskmgr_count_lbl", None)
        if lbl is None:
            return
        counts = taskmgr_count_jobs(jobs, is_running=schedule2_job_is_running)
        lbl.configure(text=format_taskmgr_count_summary(counts))

    def _render_taskmgr_cards(self, *, force: bool = False) -> None:
        """增删任务或结构变化时重建网格；不做定时刷新，也不联动定时任务页控件。"""
        if not hasattr(self, "_taskmgr_cards"):
            return
        jobs = load_schedule2_jobs()
        cfg = self._cfg
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
                    text=t("taskmgr.empty"),
                    text_color=COLORS["muted"],
                ).grid(row=0, column=0, columnspan=TASKMGR_COLS, sticky="w", padx=8, pady=12)
            self._update_taskmgr_count_label(jobs)
            return
        display_jobs = taskmgr_sort_jobs_for_display(jobs, is_running=schedule2_job_is_running)
        display_ids = [j.id for j in display_jobs]
        if force or ids != self._taskmgr_listed_ids:
            self._taskmgr_listed_ids = ids
            self._full_rebuild_taskmgr_grid(display_jobs, cfg)
            self._taskmgr_display_ids = display_ids
        self._update_taskmgr_count_label(jobs)
        handler = getattr(self, "_taskmgr_scroll_handler", None)
        if handler:
            bind_scroll_tree_once(self._taskmgr_cards, handler)

    def _job_target_short(self, j: Schedule2Job) -> str:
        return schedule2_job_target_remarks(self._cfg, j) or j.source_name or j.id

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

    def _one_click_send_images_flow(
        self, *, sync_to_customer: bool, customer_extra_text: str
    ) -> None:
        if getattr(self, "_bulk_image_busy", False):
            info_i18n("img.busy")
            return
        from one_click_image import (
            collect_awaiting_image_jobs,
            group_awaiting_by_day,
            notes_for_awaiting_jobs,
        )

        jobs = collect_awaiting_image_jobs(load_schedule2_jobs())
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
        group_jobs: List[Schedule2Job],
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
        # 确认关闭后再选图：加长延时，确保 grab/topmost 已清干净
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
        group_jobs: List[Schedule2Job],
        *,
        sync_to_customer: bool,
        customer_extra_text: str,
        title_key: str,
    ) -> None:
        from one_click_image import MAX_BULK_IMAGES

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

    def _toggle_s2_run_by_id(self, job_id: str) -> None:
        if self._taskmgr_toggle_busy:
            return
        self._taskmgr_toggle_busy = True
        try:
            j = next((x for x in load_schedule2_jobs() if x.id == job_id), None)
            if j is None:
                return
            if schedule2_job_is_running(j):
                self._schedule2.pause_job(j.id, CODE_MANUAL)
            elif self._schedule2.resume_job(j.id):
                pass
            else:
                info_i18n("log.cannot_start_job")
            self._refresh_taskmgr_card(job_id)
        finally:
            self._taskmgr_toggle_busy = False

    def _resume_all_s2_jobs(self) -> None:
        jobs = load_schedule2_jobs()
        resumable, skipped = bulk_resume_schedule2_counts(jobs)
        if resumable <= 0:
            running = sum(1 for j in jobs if schedule2_job_is_running(j))
            if running > 0:
                info_i18n("log.resume_all_already_running", running=running)
            elif skipped > 0:
                info_i18n("log.resume_all_none_skipped", skipped=skipped)
            else:
                info_i18n("log.resume_all_none")
            return
        body_kwargs: Dict[str, Any] = {"resumable": resumable}
        if skipped > 0:
            body_kwargs["skipped_line"] = t("msgbox.resume_all.skipped", skipped=skipped)
        else:
            body_kwargs["skipped_line"] = ""
        if not msg_askyesno(self, "msgbox.resume_all.title", "msgbox.resume_all.body", **body_kwargs):
            return
        n = self._schedule2.resume_all_jobs()
        self._cfg = load_config()
        self._refresh_s2_target_checks()
        jobs = load_schedule2_jobs()
        if jobs and self._taskmgr_listed_ids == [j.id for j in jobs]:
            self._patch_taskmgr_cards([j.id for j in jobs], reorder=True)
        else:
            self._render_taskmgr_cards(force=True)
        if n > 0:
            if skipped > 0:
                info_i18n("log.resume_all_done_skipped", n=n, skipped=skipped)
            else:
                info_i18n("log.resume_all_done", n=n)
            return
        running = sum(1 for j in load_schedule2_jobs() if schedule2_job_is_running(j))
        if running > 0:
            info_i18n("log.resume_all_already_running", running=running)
        else:
            info_i18n("log.resume_all_none")

    def _reload_s2_folder_scripts(self) -> None:
        """重新扫描各文件夹任务目录，并用磁盘 TXT 更新当前天话术。"""
        jobs = load_schedule2_jobs()
        folder_n = sum(1 for j in jobs if is_folder_job(j))
        if folder_n <= 0:
            msg_info(self, "taskmgr.reload_folder_txt", "msgbox.reload_folder.none")
            return
        if not msg_askyesno(
            self,
            "taskmgr.reload_folder_txt",
            "msgbox.reload_folder.body",
            n=folder_n,
        ):
            return
        ok_n, fail_n, fails = bulk_reload_schedule2_folder_scripts(jobs, self._cfg)
        self._cfg = load_config()
        jobs2 = load_schedule2_jobs()
        if jobs2 and self._taskmgr_listed_ids == [j.id for j in jobs2]:
            self._patch_taskmgr_cards([j.id for j in jobs2], reorder=True)
        else:
            self._render_taskmgr_cards(force=True)
        if ok_n > 0 and fail_n <= 0:
            info_i18n("log.reload_folder_ok", n=ok_n)
        elif ok_n > 0:
            info_i18n("log.reload_folder_partial", ok=ok_n, fail=fail_n)
            for line in fails:
                warning(line)
        else:
            info_i18n("log.reload_folder_fail", fail=fail_n)
            for line in fails:
                warning(line)

    def _clear_s2_target_selection(self) -> None:
        for _ent, var in getattr(self, "_sched2_target_rows", []):
            var.set(False)
        for v in getattr(self, "_sched2_target_vars", []):
            v.set(False)

    def _refresh_s2_target_checks(self) -> None:
        if not hasattr(self, "_s2_targets"):
            return
        sync_last_schedule_from_disk(self._cfg)
        jobs = load_schedule2_jobs()
        for w in self._s2_targets.winfo_children():
            w.destroy()
        self._sched2_target_vars = []
        self._sched2_target_rows = []
        if not self._cfg.address_book:
            ctk.CTkLabel(self._s2_targets, text=t("grp.no_groups_hint"), text_color=COLORS["muted"]).pack(anchor="w", padx=4)
            return
        for ent in self._cfg.address_book:
            v = ctk.BooleanVar(value=False)
            self._sched2_target_vars.append(v)
            self._sched2_target_rows.append((ent, v))
            cref = ent.chat_ref
            cref_disp = f"{cref[:48]}…" if len(cref) > 48 else cref
            kind_hint = entry_schedule_kind_hint(jobs, ent.id)
            last_fn = (getattr(ent, "last_schedule_source_name", "") or "").strip()
            last_hint = t("sched.last_task", name=last_fn) if last_fn else t("sched.last_task_empty")
            disp = f"{ent.remark}{kind_hint}（{cref_disp}{last_hint}）"
            ctk.CTkCheckBox(self._s2_targets, text=disp, variable=v, text_color=COLORS["text"]).pack(anchor="w", padx=4, pady=2)

    def _pick_s2_source(self) -> None:
        cur = self._s2_file.get() if hasattr(self, "_s2_file") else ""
        path = pick_txt_or_folder(self, current_path=cur)
        if path and hasattr(self, "_s2_file"):
            self._s2_file.delete(0, "end")
            self._s2_file.insert(0, path)

    def _parse_interval(self, s: str) -> Optional[tuple[float, float]]:
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$", (s or "").strip())
        if not m:
            return None
        a, b = float(m.group(1)), float(m.group(2))
        if a <= 0 or b <= 0:
            return None
        return (min(a, b), max(a, b))

    def _s2_job_label(self, j: Schedule2Job) -> str:
        tgt = schedule2_job_target_remarks(self._cfg, j)
        return f"{tgt}{schedule_kind_badge(j)} · {j.source_name}{t('sched.job_steps', n=j.row_count())}"

    def _on_s2_job_pick_changed(self, _value: str) -> None:
        for j in load_schedule2_jobs():
            if self._s2_job_label(j) == self._s2_job_pick.get().strip():
                self._s2_edit_job_id = j.id
                self._refresh_s2_bulk_combos(j)
                return

    def _refresh_s2_bulk_combos(self, job: Optional[Schedule2Job] = None) -> None:
        if job is None and self._s2_edit_job_id:
            job = next((j for j in load_schedule2_jobs() if j.id == self._s2_edit_job_id), None)
        acc_vals = self._account_id_values()
        if hasattr(self, "_s2_bulk_to"):
            self._s2_bulk_to.configure(values=acc_vals)
            if acc_vals and acc_vals[0] != "—":
                cur = self._s2_bulk_to.get().strip()
                if cur not in acc_vals:
                    self._s2_bulk_to.set(acc_vals[0])
        if not hasattr(self, "_s2_bulk_from") or job is None:
            return
        originals = sorted({r.original_account_id for r in job.rows if not r.is_reminder and r.original_account_id.strip()})
        vals = originals if originals else ["—"]
        self._s2_bulk_from.configure(values=vals)
        self._s2_bulk_from.set(vals[0])

    def _sync_s2_job_pick_combo(self) -> None:
        jobs = load_schedule2_jobs()
        labels = [self._s2_job_label(j) for j in jobs] or ["—"]
        if hasattr(self, "_s2_job_pick"):
            self._s2_job_pick.configure(values=labels)
            if jobs:
                if not self._s2_edit_job_id or not any(j.id == self._s2_edit_job_id for j in jobs):
                    self._s2_edit_job_id = jobs[0].id
                sel = next(j for j in jobs if j.id == self._s2_edit_job_id)
                self._s2_job_pick.set(self._s2_job_label(sel))
            else:
                self._s2_edit_job_id = None
        sel_job = next((j for j in jobs if j.id == self._s2_edit_job_id), None)
        self._refresh_s2_bulk_combos(sel_job)

    def _add_s2_job(self) -> None:
        selected: List[str] = []
        rows = getattr(self, "_sched2_target_rows", None) or []
        if rows:
            for ent, var in rows:
                if var.get():
                    selected.append(ent.id)
        else:
            for i, ent in enumerate(self._cfg.address_book):
                if i < len(self._sched2_target_vars) and self._sched2_target_vars[i].get():
                    selected.append(ent.id)
        if not selected:
            info_i18n("log.need_select_group")
            return
        interval = self._parse_interval(self._s2_interval.get())
        if not interval:
            info_i18n("log.interval_invalid")
            return
        path = self._s2_file.get().strip()
        if not path:
            info_i18n("log.need_txt_or_folder")
            return
        if os.path.isdir(path):
            self._add_s2_folder_jobs(path, selected, interval)
            return
        if not os.path.isfile(path):
            info_i18n("log.path_invalid")
            return
        try:
            text = open(path, encoding="utf-8").read()
        except OSError as exc:
            info_i18n("log.read_fail", err=exc)
            return
        items, errs = import_doc_items(text, valid_accounts=None)
        if not items:
            info_i18n("log.txt_no_items")
            for e in errs[:5]:
                info(e)
            return
        for e in errs[:10]:
            info(e)
        rows: List[Schedule2Row] = []
        for it in items:
            orig, send = mark_row_primary_auto(it.account_id, it.account_id)
            rows.append(
                Schedule2Row(
                    id=uuid.uuid4().hex[:12],
                    original_account_id=orig,
                    send_as_account_id=send,
                    content=it.content,
                    is_reminder=it.is_reminder,
                    reminder_note=it.reminder_note,
                    delay_after_minutes=it.delay_after_minutes,
                    want_reactions=bool(getattr(it, "want_reactions", False)),
                )
            )
        by_eid = {e.id: e for e in self._cfg.address_book}
        if row_needs_per_group_owner(rows):
            for eid in selected:
                ent = by_eid.get(eid)
                if not ent or not (ent.owner_account_id or "").strip():
                    info_i18n("log.need_group_owner", group=ent.remark if ent else eid)
                    return
        jobs = load_schedule2_jobs()
        created: List[Schedule2Job] = []
        for eid in selected:
            ent = by_eid.get(eid)
            if not ent:
                continue
            job_rows = copy.deepcopy(rows)
            job = Schedule2Job.new(
                [ent.chat_ref],
                interval[0],
                interval[1],
                path,
                job_rows,
                chat_entry_ids=[eid],
            )
            jobs.append(job)
            created.append(job)
        if not created:
            info_i18n("log.job_create_failed")
            return
        save_schedule2_jobs(jobs)
        apply_last_schedule_for_jobs(self._cfg, created)
        self._s2_edit_job_id = created[-1].id
        self._render_taskmgr_cards(force=True)
        if len(created) > 1:
            info_i18n(
                "log.job_added_multi",
                n=len(created),
                name=created[0].source_name,
                steps=len(rows),
            )
        else:
            info_i18n(
                "log.job_added_single",
                name=created[0].source_name,
                steps=len(rows),
            )
        self._clear_s2_target_selection()
        self._refresh_s2_target_checks()

    def _add_s2_folder_jobs(self, folder_path: str, selected: List[str], interval: tuple[float, float]) -> None:
        rel_files, scan_errs = scan_schedule_folder(folder_path)
        if scan_errs:
            info("\n".join(scan_errs))
            return
        folder_abs = os.path.abspath(folder_path)
        first_path = folder_txt_abs_path(folder_abs, rel_files[0])
        try:
            text = open(first_path, encoding="utf-8").read()
        except OSError as exc:
            info_i18n("log.read_fail", err=exc)
            return
        items, errs = import_doc_items(text, valid_accounts=None)
        if not items:
            info_i18n("log.folder_first_no_items")
            for e in errs[:5]:
                info(e)
            return
        for e in errs[:10]:
            info(e)
        rows: List[Schedule2Row] = []
        for it in items:
            orig, send = mark_row_primary_auto(it.account_id, it.account_id)
            rows.append(
                Schedule2Row(
                    id=uuid.uuid4().hex[:12],
                    original_account_id=orig,
                    send_as_account_id=send,
                    content=it.content,
                    is_reminder=it.is_reminder,
                    reminder_note=it.reminder_note,
                    delay_after_minutes=it.delay_after_minutes,
                    want_reactions=bool(getattr(it, "want_reactions", False)),
                )
            )
        by_eid = {e.id: e for e in self._cfg.address_book}
        if row_needs_per_group_owner(rows):
            for eid in selected:
                ent = by_eid.get(eid)
                if not ent or not (ent.owner_account_id or "").strip():
                    info_i18n("log.need_group_owner", group=ent.remark if ent else eid)
                    return
        jobs = load_schedule2_jobs()
        created: List[Schedule2Job] = []
        for eid in selected:
            ent = by_eid.get(eid)
            if not ent:
                continue
            job_rows = copy.deepcopy(rows)
            job = Schedule2Job.new(
                [ent.chat_ref],
                interval[0],
                interval[1],
                first_path,
                job_rows,
                chat_entry_ids=[eid],
            )
            job.source_kind = "folder"
            job.folder_path = folder_abs
            job.folder_files = list(rel_files)
            job.folder_day_index = 0
            jobs.append(job)
            created.append(job)
        if not created:
            info_i18n("log.job_create_failed")
            return
        save_schedule2_jobs(jobs)
        apply_last_schedule_for_jobs(self._cfg, created)
        self._s2_edit_job_id = created[-1].id
        self._render_taskmgr_cards(force=True)
        if len(created) > 1:
            info_i18n("log.folder_job_added_multi", n=len(created), days=len(rel_files))
        else:
            info_i18n(
                "log.folder_job_added_single",
                days=len(rel_files),
                name=created[0].source_name,
                steps=len(rows),
            )
        self._clear_s2_target_selection()
        self._refresh_s2_target_checks()

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
        jobs = load_schedule2_jobs()
        if jobs:
            self._patch_taskmgr_cards([j.id for j in jobs], reorder=False)
        if self._manual_folder_advance_mode:
            info_i18n("log.manual_day_mode_on")
        else:
            info_i18n("log.manual_day_mode_off")

    def _manual_advance_s2_folder_day_by_id(self, job_id: str) -> None:
        if self._taskmgr_toggle_busy:
            return
        j = next((x for x in load_schedule2_jobs() if x.id == job_id), None)
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
            target=schedule2_job_target_remarks(self._cfg, j),
            current=j.source_name or unnamed,
            next_file=j.folder_files[nxt],
            day=nxt + 1,
            total=len(j.folder_files),
        ):
            return
        self._cfg = load_config()
        ok, err = advance_schedule2_folder_day(j, self._cfg)
        if not ok:
            info_i18n("log.folder_advance_fail", err=err)
            return
        save_schedule2_jobs_patch([j])
        apply_last_schedule_for_jobs(self._cfg, [j])
        self._refresh_taskmgr_card(j.id)
        info_i18n(
            "log.folder_advance_ok",
            target=schedule2_job_target_remarks(self._cfg, j),
            day=j.folder_day_index + 1,
        )

    def _start_next_s2_folder_day(self) -> None:
        jobs = load_schedule2_jobs()
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
                    target_label=schedule2_job_target_remarks(self._cfg, j),
                    current_name=j.source_name or unnamed,
                    next_name=j.folder_files[nxt],
                    next_day_one_based=nxt + 1,
                    total_days=len(j.folder_files),
                )
            )
            if schedule2_job_is_running(j):
                running_n += 1

        del_lines: List[str] = []
        for j in stale:
            idx = max(0, int(j.folder_day_index))
            del_lines.append(
                format_folder_last_day_delete_line(
                    target_label=schedule2_job_target_remarks(self._cfg, j),
                    current_name=j.source_name or unnamed,
                    day_one_based=idx + 1,
                    total_days=len(j.folder_files),
                )
            )

        body_kwargs: Dict[str, Any] = {
            "advance_block": "",
            "delete_block": "",
        }
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
        updated: List[Schedule2Job] = []
        for j in candidates:
            live = next((x for x in load_schedule2_jobs() if x.id == j.id), None)
            if live is None or not can_advance_folder_day(live):
                continue
            ok, err = advance_schedule2_folder_day(live, self._cfg)
            if ok:
                updated.append(live)
            else:
                info_i18n("log.folder_advance_job_fail", target=schedule2_job_target_remarks(self._cfg, live), err=err)

        stale_ids = {j.id for j in stale}
        if stale_ids:
            kept = [x for x in load_schedule2_jobs() if x.id not in stale_ids]
            save_schedule2_jobs(kept)
            if self._s2_edit_job_id in stale_ids:
                self._s2_edit_job_id = None

        if updated:
            save_schedule2_jobs_patch(updated)
            apply_last_schedule_for_jobs(self._cfg, updated)

        if not updated and not stale_ids:
            info_i18n("log.next_day_nothing")
            return

        self._render_taskmgr_cards(force=True)
        parts: List[str] = []
        if updated:
            parts.append(t("log.next_day_advanced", n=len(updated)))
        if stale_ids:
            parts.append(t("log.next_day_deleted", n=len(stale_ids)))
        info(t("log.next_day_summary", summary="；".join(parts)))

    def _select_s2_job(self, job_id: str) -> None:
        self._s2_edit_job_id = job_id
        self._sync_s2_job_pick_combo()
        info_i18n("log.job_selected_for_edit")

    def _toggle_s2_enabled(self, idx: int) -> None:
        jobs = load_schedule2_jobs()
        if idx < len(jobs):
            jid = jobs[idx].id
            jobs[idx].enabled = not jobs[idx].enabled
            save_schedule2_jobs(jobs)
            self._refresh_taskmgr_card(jid)

    def _del_s2_job_by_id(self, job_id: str) -> None:
        jobs = load_schedule2_jobs()
        dead = next((x for x in jobs if x.id == job_id), None)
        if dead is None:
            return
        target = schedule2_job_target_remarks(load_config(), dead)
        if not msg_askyesno(
            self,
            "msgbox.delete.title",
            "msgbox.delete.body",
            name=dead.source_name,
            target=target,
        ):
            return
        jobs = [x for x in jobs if x.id != job_id]
        if dead.id == self._s2_edit_job_id:
            self._s2_edit_job_id = None
        save_schedule2_jobs(jobs)
        info_i18n("log.job_deleted", name=dead.source_name)
        self._render_taskmgr_cards(force=True)
        self._sync_s2_job_pick_combo()
        if hasattr(self, "_s2_targets"):
            self._refresh_s2_target_checks()

    def _delete_all_s2_jobs(self) -> None:
        jobs = load_schedule2_jobs()
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
        save_schedule2_jobs(kept)
        deleted_ids = {j.id for j in to_delete}
        if getattr(self, "_s2_edit_job_id", None) in deleted_ids:
            self._s2_edit_job_id = kept[0].id if kept else None
        self._render_taskmgr_cards(force=True)
        self._sync_s2_job_pick_combo()
        if hasattr(self, "_s2_targets"):
            self._refresh_s2_target_checks()
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

    def _s2_bulk_replace(self) -> None:
        jobs = load_schedule2_jobs()
        jid = self._s2_edit_job_id
        if not jid:
            info_i18n("log.bulk_need_job")
            return
        job = next((j for j in jobs if j.id == jid), None)
        if not job:
            info_i18n("log.job_not_found")
            return
        from_acc = self._s2_bulk_from.get().strip()
        to_acc = self._s2_bulk_to.get().strip()
        if from_acc in ("", "—") or to_acc in ("", "—"):
            info_i18n("log.bulk_need_accounts")
            return
        if from_acc == to_acc:
            info_i18n("log.bulk_same_account")
            return
        n = 0
        for r in job.rows:
            if not r.is_reminder and r.original_account_id == from_acc:
                r.send_as_account_id = to_acc
                n += 1
        if n == 0:
            info_i18n("log.bulk_no_match", account=from_acc)
            return
        save_schedule2_jobs(jobs)
        self._refresh_s2_bulk_combos(job)
        info_i18n("log.bulk_replaced", from_acc=from_acc, n=n, to_acc=to_acc)

    # --- 日志 ---
    def _page_logs(self) -> ctk.CTkFrame:
        page = ctk.CTkFrame(self._content, fg_color="transparent")

        log_foot = ctk.CTkFrame(page, fg_color=COLORS["card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        lf = ctk.CTkFrame(log_foot, fg_color="transparent")
        lf.pack(fill="x", padx=12, pady=10)
        ctk.CTkButton(lf, text=t("common.refresh_logs"), command=self._reload_logs_page, fg_color=COLORS["accent"]).pack(fill="x")

        inner, canvas, finish = mount_page_scroll(page, footer=log_foot, bg=COLORS["bg"])
        self._scroll_wheel_handler = lambda e, c=canvas: scroll_wheel(c, e)

        ctk.CTkLabel(inner, text=t("nav.logs"), font=ctk.CTkFont(size=22, weight="bold"), text_color=COLORS["text"]).pack(
            anchor="w", pady=(8, 12)
        )
        self._log_box = ctk.CTkTextbox(
            inner,
            height=480,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=COLORS["card"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self._log_box.pack(fill="both", expand=True, pady=(0, 8))
        bind_log_textbox_wheel(self._log_box)
        reload_log_textbox_from_memory(
            self._log_box,
            self._wa_log_lines,
            limit=LOG_TEXTBOX_MAX_LINES,
            log_queue=getattr(self, "_log_queue", None),
        )
        finish()
        return page


# 兼容旧入口名
MainWindow = WaPanel
