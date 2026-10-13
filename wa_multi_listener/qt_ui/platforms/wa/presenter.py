"""WA 面板 Presenter/Controller：不创建任何控件。"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from .contracts import ConfigView, Translator, WaGateway


class WaPresenter(QObject):
    config_changed = Signal(object)
    tasks_changed = Signal(object)
    logs_changed = Signal(list)
    log_line = Signal(str)
    alert_received = Signal(object)
    reminder_received = Signal(object)
    qr_received = Signal(str, bytes)
    login_status = Signal(str, str)
    login_finished = Signal(str, bool)
    status_message = Signal(str)
    operation_done = Signal(str)
    operation_failed = Signal(str)
    audit_finished = Signal(object)
    image_busy = Signal(str)

    def __init__(
        self,
        gateway: WaGateway,
        tr: Translator,
        parent: QObject | None = None,
        image_paths_provider: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.gateway = gateway
        self.tr = tr
        self.image_paths_provider = image_paths_provider
        self._config: ConfigView | None = None
        self._log_listener = None
        self._login_cancel = None
        self.audit_flags: dict[str, str] = {}
        self.audit_details: dict[str, str] = {}
        self._reload_busy = False
        self._worker = None
        self._attach_logs()

    def _attach_logs(self) -> None:
        logger = getattr(getattr(self.gateway, "m", None), "logger", None)
        if logger is None:
            return

        def on_line(line: str) -> None:
            self.log_line.emit(str(line))

        self._log_listener = on_line
        try:
            logger.add_memory_listener(on_line)
        except Exception:
            self._log_listener = None

    def detach(self) -> None:
        logger = getattr(getattr(self.gateway, "m", None), "logger", None)
        if logger is not None and self._log_listener is not None:
            try:
                logger.remove_memory_listener(self._log_listener)
            except Exception:
                pass
        self._log_listener = None

    @property
    def config(self) -> ConfigView:
        if self._config is None:
            self._config = self.gateway.read_config()
        return self._config

    @Slot()
    def refresh(self) -> None:
        self._config = self.gateway.read_config()
        self.config_changed.emit(self._config)
        self.tasks_changed.emit(tuple(self.gateway.task_records()))

    def _run(self, operation, success_key: str = "common.save") -> bool:
        try:
            operation()
        except Exception as exc:
            key = str(exc)
            self.operation_failed.emit(self.tr(key) if "." in key else key)
            return False
        self.refresh()
        self.operation_done.emit(self.tr(success_key))
        return True

    def add_account(self, account_id: str, phone: str, proxy: str) -> None:
        self._run(lambda: self.gateway.add_account(account_id, phone, proxy), "acct.add")

    def update_account(self, account_id: str, enabled: bool, proxy: str) -> None:
        self._run(lambda: self.gateway.update_account(account_id, enabled, proxy))

    def delete_account(self, account_id: str) -> None:
        self._run(lambda: self.gateway.delete_account(account_id), "common.delete")

    def login_account(self, account_id: str) -> None:
        import threading

        if getattr(self, "_login_in_progress", False):
            try:
                busy = self.tr("qr.status_busy")
            except Exception:
                busy = "登录进行中，请稍候"
            self.login_status.emit(account_id, busy)
            return

        # 若仍有上一次登录线程，先取消并短等，避免连点导致连续换库
        old_thread = getattr(self, "_login_thread", None)
        self.cancel_login()
        if old_thread is not None and old_thread.is_alive():
            old_thread.join(timeout=2.5)

        cancel_event = threading.Event()
        self._login_cancel = cancel_event
        self._login_in_progress = True
        panel = self.parent()
        if panel is not None and hasattr(panel, "login_cancel"):
            panel.login_cancel = cancel_event

        self.login_status.emit(account_id, self.tr("qr.status_prepare"))

        def qr(data: bytes) -> None:
            self.qr_received.emit(account_id, data)

        def status(text: str) -> None:
            self.login_status.emit(account_id, text)

        def done(ok: bool, text: str) -> None:
            if self._login_cancel is cancel_event:
                self._login_cancel = None
                if panel is not None and getattr(panel, "login_cancel", None) is cancel_event:
                    panel.login_cancel = None
            self._login_in_progress = False
            self.login_status.emit(account_id, text)
            self.login_finished.emit(account_id, bool(ok))
            (self.operation_done if ok else self.operation_failed).emit(text)
            self.refresh()

        try:
            thread = self.gateway.start_qr_login(
                account_id, qr, status, done, cancel_event=cancel_event
            )
            self._login_thread = thread
        except TypeError:
            try:
                thread = self.gateway.start_qr_login(account_id, qr, status, done)
                self._login_thread = thread
            except Exception as exc:
                self._login_in_progress = False
                self.operation_failed.emit(str(exc))
        except Exception as exc:
            self._login_in_progress = False
            self.operation_failed.emit(str(exc))

    def cancel_login(self) -> None:
        event = self._login_cancel
        if event is not None:
            event.set()
        panel = self.parent()
        panel_event = getattr(panel, "login_cancel", None) if panel is not None else None
        if panel_event is not None:
            panel_event.set()

    def add_contact(
        self, remark: str, chat_ref: str, watch_user: str,
        listen_enabled: bool, owner: str, invite_link: str,
    ) -> None:
        self._run(lambda: self.gateway.add_contact(
            remark, chat_ref, watch_user, listen_enabled, owner, invite_link
        ), "common.add")

    def update_contact(self, entry_id: str, **changes: Any) -> None:
        self._run(lambda: self.gateway.update_contact(entry_id, **changes))

    def delete_contact(self, entry_id: str) -> None:
        self._run(lambda: self.gateway.delete_contact(entry_id), "common.delete")

    def move_contact(self, entry_id: str, offset: int) -> None:
        self._run(lambda: self.gateway.move_contact(entry_id, offset))

    def save_rules(self, listening: bool, popup: bool, rate: float) -> None:
        self._run(lambda: self.gateway.update_rules(listening, popup, rate))

    def sync_last_schedule(self) -> None:
        modules = getattr(self.gateway, "m", None)
        cfg = getattr(self.gateway, "cfg", None)
        if modules is None or cfg is None:
            return
        before = {
            row.id: (row.last_schedule_source_name or "").strip()
            for row in cfg.address_book
        }
        n_jobs = len(modules.scheduler.load_schedule2_jobs())
        modules.config.apply_last_schedule_from_current_jobs(cfg)
        modules.config.save_config(cfg)
        n_changed = sum(
            1
            for row in cfg.address_book
            if before.get(row.id, "") != (row.last_schedule_source_name or "").strip()
        )
        n_filled = sum(
            1
            for row in cfg.address_book
            if (row.last_schedule_source_name or "").strip()
        )
        self.refresh()
        if n_changed:
            self.operation_done.emit(self.tr(
                "log.sync_last_changed",
                n_jobs=n_jobs,
                n_changed=n_changed,
                n_filled=n_filled,
                n_empty=len(cfg.address_book) - n_filled,
            ))
        else:
            self.operation_done.emit(self.tr(
                "log.sync_last_unchanged",
                n_jobs=n_jobs,
                n_filled=n_filled,
            ))

    def reconnect_offline_accounts(self) -> None:
        """重连当前未在线的已启用账号；服务未运行则走保存并重载。"""
        from ...bridges.ui_call import call_on_ui

        if getattr(self, "_reconnect_busy", False) or getattr(self, "_reload_busy", False):
            self.operation_failed.emit(self.tr("log.reconnect_busy"))
            return
        online = set()
        coord = getattr(self.gateway, "coordinator", None)
        if coord is not None and hasattr(coord, "connected_account_ids"):
            online = set(coord.connected_account_ids())
        cfg = getattr(self.gateway, "cfg", None)
        if cfg is None:
            self.operation_failed.emit(self.tr("log.reconnect_none"))
            return
        targets = [
            acc for acc in cfg.accounts
            if getattr(acc, "enabled", True) and acc.id not in online
        ]
        if not targets:
            self.operation_done.emit(self.tr("log.reconnect_none"))
            return

        if coord is None or not getattr(coord, "is_running", lambda: False)():
            self.operation_done.emit(self.tr("log.reconnect_start"))
            self.save_and_reload()
            return

        def on_done(ok: int, fail: int, skip: int) -> None:
            def finish() -> None:
                self._reconnect_busy = False
                self.refresh()
                self.operation_done.emit(
                    self.tr("log.reconnect_done", ok=ok, fail=fail, skip=skip)
                )

            call_on_ui(self, finish)

        self._reconnect_busy = True
        self.operation_done.emit(self.tr("log.reconnect_start"))
        accepted = False
        try:
            accepted = bool(self.gateway.request_reconnect_offline(on_done))
        except Exception as exc:
            self._reconnect_busy = False
            self.operation_failed.emit(str(exc))
            return
        if not accepted:
            self._reconnect_busy = False
            self.save_and_reload()

    def save_and_reload(self) -> None:
        if getattr(self, "_reload_busy", False):
            self.operation_failed.emit(self.tr("log.reload_busy"))
            return
        self._reload_busy = True
        self.status_message.emit(self.tr("log.config_saved"))
        try:
            # 配置落盘在主线程；服务重启放到后台，避免卡死 UI，且不碰 Qt 控件。
            if hasattr(self.gateway, "save_config"):
                self.gateway.save_config()
            else:
                self.gateway.save_and_reload()
                self._reload_busy = False
                self.refresh()
                self.operation_done.emit(self.tr("log.services_reloaded"))
                return
        except Exception as exc:
            self._reload_busy = False
            self.operation_failed.emit(str(exc))
            return

        from ...core.worker import WorkerRunner

        if getattr(self, "_worker", None) is None:
            self._worker = WorkerRunner(self)

        def ok(_result: Any = None) -> None:
            self._reload_busy = False
            self.refresh()
            self.operation_done.emit(self.tr("log.services_reloaded"))

        def fail(err: Any) -> None:
            self._reload_busy = False
            message = getattr(err, "message", str(err))
            self.operation_failed.emit(self.tr("log.reload_fail", err=message))

        reload_fn = getattr(self.gateway, "reload_services", self.gateway.save_and_reload)
        self._worker.submit(reload_fn, on_result=ok, on_error=fail)

    def audit(self) -> None:
        try:
            from ...bridges.ui_call import call_on_ui

            if getattr(self, "_audit_busy", False):
                self.operation_failed.emit(self.tr("log.audit_busy"))
                return

            def on_done(result: Any) -> None:
                def finish() -> None:
                    self._audit_busy = False
                    self._apply_audit(result)
                    self.audit_finished.emit(result)

                call_on_ui(self, finish)

            self._audit_busy = True
            self.operation_done.emit(self.tr("log.audit_start"))
            accepted = self.gateway.request_audit(on_done)
            if not accepted:
                self._audit_busy = False
                self.operation_failed.emit(self.tr("log.audit_need_login"))
        except Exception as exc:
            self._audit_busy = False
            self.operation_failed.emit(str(exc))

    def _apply_audit(self, result: Any) -> None:
        from ...services.task_confirmations import audit_status_value

        flags: dict[str, str] = {}
        details: dict[str, str] = {}
        if isinstance(result, dict):
            for entry_id, row in result.items():
                flags[str(entry_id)] = audit_status_value(row)
                detail = str(getattr(row, "detail", "") or "").strip()
                if detail:
                    details[str(entry_id)] = detail
        self.audit_flags = flags
        self.audit_details = details
        self.refresh()
        if not flags:
            self.operation_done.emit(self.tr("log.audit_incomplete"))
            return
        ok = sum(1 for value in flags.values() if value == "ok")
        absent = sum(1 for value in flags.values() if value == "absent")
        err = sum(1 for value in flags.values() if value == "error")
        offline = sum(1 for value in flags.values() if value == "offline")
        checked = ok + absent
        if checked == 0 and err == 0 and offline == 0:
            self.operation_done.emit(self.tr("log.audit_no_targets"))
            return
        parts = [self.tr("log.audit_checked", n=checked)]
        if absent:
            parts.append(self.tr("log.audit_absent", n=absent))
        if err:
            parts.append(self.tr("log.audit_failed", n=err))
        if offline:
            parts.append(self.tr("log.audit_offline", n=offline))
        self.operation_done.emit(
            self.tr("log.audit_summary", summary="；".join(parts))
        )

    def import_schedule(self, path: str, targets: Sequence[str], interval: str) -> None:
        self._run(
            lambda: self.gateway.import_schedule(path, targets, interval),
            "sched.add_job",
        )

    def bulk_replace_account(
        self, job_id: str, from_account: str, to_account: str
    ) -> None:
        modules = getattr(self.gateway, "m", None)
        if modules is None:
            return
        from_acc = from_account.strip()
        to_acc = to_account.strip()
        if from_acc in ("", "—") or to_acc in ("", "—"):
            self.operation_failed.emit(self.tr("log.bulk_need_accounts"))
            return
        if from_acc == to_acc:
            self.operation_failed.emit(self.tr("log.bulk_same_account"))
            return
        jobs = modules.scheduler.load_schedule2_jobs()
        job = next((row for row in jobs if row.id == job_id), None)
        if job is None:
            self.operation_failed.emit(self.tr("log.job_not_found"))
            return
        changed = 0
        for row in job.rows:
            if not row.is_reminder and row.original_account_id == from_acc:
                row.send_as_account_id = to_acc
                changed += 1
        if changed == 0:
            self.operation_failed.emit(self.tr("log.bulk_no_match", account=from_acc))
            return
        modules.scheduler.save_schedule2_jobs(jobs)
        self.refresh()
        self.operation_done.emit(self.tr(
            "log.bulk_replaced", from_acc=from_acc, n=changed, to_acc=to_acc
        ))

    def refresh_logs(self) -> None:
        self.logs_changed.emit(self.gateway.recent_logs())

    def emit_alert(self, payload: Any) -> None:
        """后台线程可直接调用：先同步暂停，再排队 UI。"""
        try:
            if isinstance(payload, dict):
                self.gateway.task_action(
                    "listen_hit",
                    chat_key=str(payload.get("chat_key", "")),
                    event_title=str(payload.get("chat_title", "")),
                )
        finally:
            try:
                from stats import record_alert

                record_alert()
            except Exception:
                pass
            self.alert_received.emit(payload)
            self.tasks_changed.emit(tuple(self.gateway.task_records()))

    def emit_reminder(self, *payload: Any) -> None:
        self.reminder_received.emit(payload)
        self.tasks_changed.emit(tuple(self.gateway.task_records()))

    def _task(self, action: str, task_id: str = "", **kwargs: Any) -> None:
        silent = action in {"toggle", "pause", "resume"}
        try:
            self.gateway.task_action(action, task_id, **kwargs)
        except Exception as exc:
            key = str(exc)
            self.operation_failed.emit(self.tr(key) if "." in key else key)
            return
        self.refresh()
        if not silent:
            self.operation_done.emit(self.tr("common.save"))

    def toggle_task(self, task_id: str) -> None:
        self._task("toggle", task_id)

    def delete_task(self, task_id: str) -> None:
        from ...services.confirm import confirm_or_abort

        modules = getattr(self.gateway, "m", None)
        parent = self.parent()
        if modules is None:
            return
        job = next(
            (
                row
                for row in modules.scheduler.load_schedule2_jobs()
                if row.id == task_id
            ),
            None,
        )
        if job is None:
            return
        target = modules.scheduler.schedule2_job_target_remarks(
            getattr(self.gateway, "cfg", None), job
        )
        if not confirm_or_abort(
            parent,
            self.tr,
            self.tr("msgbox.delete.title"),
            self.tr(
                "msgbox.delete.body",
                name=job.source_name,
                target=target,
            ),
        ):
            return
        try:
            self.gateway.task_action("delete", task_id)
        except Exception as exc:
            self.operation_failed.emit(str(exc))
            return
        self.refresh()
        self.operation_done.emit(self.tr("log.job_deleted", name=job.source_name))

    def next_day_task(self, task_id: str) -> None:
        from schedule_folder import can_advance_folder_day, is_folder_job

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort
        from ...services.task_confirmations import manual_next_day_confirm_message

        modules = getattr(self.gateway, "m", None)
        parent = self.parent()
        if modules is None:
            return
        job = next(
            (
                row
                for row in modules.scheduler.load_schedule2_jobs()
                if row.id == task_id
            ),
            None,
        )
        if job is None:
            return
        if not is_folder_job(job):
            if parent is not None:
                show_message(
                    parent,
                    self.tr,
                    self.tr("msgbox.manual_day.title"),
                    self.tr("msgbox.manual_day.folder_only"),
                )
            return
        if not can_advance_folder_day(job):
            if parent is not None:
                show_message(
                    parent,
                    self.tr,
                    self.tr("msgbox.manual_day.title"),
                    self.tr("msgbox.manual_day.last_day"),
                )
            return
        target = modules.scheduler.schedule2_job_target_remarks(
            getattr(self.gateway, "cfg", None), job
        )
        if not confirm_or_abort(
            parent,
            self.tr,
            self.tr("msgbox.manual_day.title"),
            manual_next_day_confirm_message(self.tr, job, target),
        ):
            return
        ok, err = modules.scheduler.advance_schedule2_folder_day(
            job, getattr(self.gateway, "cfg", None)
        )
        if not ok:
            self.operation_failed.emit(self.tr("log.folder_advance_fail", err=err))
            return
        modules.scheduler.save_schedule2_jobs_patch([job])
        modules.config.apply_last_schedule_for_jobs(
            getattr(self.gateway, "cfg", None), [job]
        )
        self.refresh()
        self.operation_done.emit(
            self.tr(
                "log.folder_advance_ok",
                target=target,
                day=job.folder_day_index + 1,
            )
        )

    def resume_all(self) -> None:
        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort
        from ...services.task_confirmations import resume_all_confirm_message

        modules = getattr(self.gateway, "m", None)
        parent = self.parent()
        if modules is None:
            return
        jobs = modules.scheduler.load_schedule2_jobs()
        resumable, skipped = modules.scheduler.bulk_resume_schedule2_counts(jobs)
        message = resume_all_confirm_message(
            self.tr, resumable=resumable, skipped=skipped
        )
        if message is None:
            running = sum(
                1 for job in jobs if modules.scheduler.schedule2_job_is_running(job)
            )
            if running > 0:
                text = self.tr("log.resume_all_already_running", running=running)
            elif skipped > 0:
                text = self.tr("log.resume_all_none_skipped", skipped=skipped)
            else:
                text = self.tr("log.resume_all_none")
            if parent is not None:
                show_message(
                    parent, self.tr, self.tr("msgbox.resume_all.title"), text
                )
            return
        if not confirm_or_abort(
            parent,
            self.tr,
            self.tr("msgbox.resume_all.title"),
            message,
        ):
            return
        count = self.gateway.task_action("resume_all")
        self.refresh()
        if count:
            key = (
                "log.resume_all_done_skipped"
                if skipped > 0
                else "log.resume_all_done"
            )
            self.operation_done.emit(
                self.tr(key, n=count, skipped=skipped)
            )
        else:
            self.operation_done.emit(self.tr("log.resume_all_none"))

    def next_day_all(self) -> None:
        from schedule_folder import (
            can_advance_folder_day,
            split_folder_jobs_for_bulk_advance,
        )

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort
        from ...services.task_confirmations import next_day_all_confirm_message

        modules = getattr(self.gateway, "m", None)
        parent = self.parent()
        cfg = getattr(self.gateway, "cfg", None)
        if modules is None:
            return
        jobs = modules.scheduler.load_schedule2_jobs()
        candidates, stale = split_folder_jobs_for_bulk_advance(jobs)
        message = next_day_all_confirm_message(
            self.tr,
            candidates=candidates,
            stale=stale,
            target_label=lambda job: modules.scheduler.schedule2_job_target_remarks(
                cfg, job
            ),
            is_running=modules.scheduler.schedule2_job_is_running,
        )
        if message is None:
            if parent is not None:
                show_message(
                    parent,
                    self.tr,
                    self.tr("msgbox.next_day.title"),
                    self.tr("msgbox.next_day.no_folder"),
                )
            return
        if not confirm_or_abort(
            parent,
            self.tr,
            self.tr("msgbox.next_day.title"),
            message,
        ):
            return
        updated = []
        for job in candidates:
            live = next(
                (
                    row
                    for row in modules.scheduler.load_schedule2_jobs()
                    if row.id == job.id
                ),
                None,
            )
            if live is None or not can_advance_folder_day(live):
                continue
            ok, err = modules.scheduler.advance_schedule2_folder_day(live, cfg)
            if ok:
                updated.append(live)
            else:
                self.operation_failed.emit(
                    self.tr(
                        "log.folder_advance_job_fail",
                        target=modules.scheduler.schedule2_job_target_remarks(
                            cfg, live
                        ),
                        err=err,
                    )
                )
        stale_ids = {job.id for job in stale}
        if stale_ids:
            kept = [
                row
                for row in modules.scheduler.load_schedule2_jobs()
                if row.id not in stale_ids
            ]
            modules.scheduler.save_schedule2_jobs(kept)
        if updated:
            modules.scheduler.save_schedule2_jobs_patch(updated)
            modules.config.apply_last_schedule_for_jobs(cfg, updated)
        self.refresh()
        parts = []
        if updated:
            parts.append(self.tr("log.next_day_advanced", n=len(updated)))
        if stale_ids:
            parts.append(self.tr("log.next_day_deleted", n=len(stale_ids)))
        if not parts:
            self.operation_done.emit(self.tr("log.next_day_nothing"))
        else:
            self.operation_done.emit(
                self.tr("log.next_day_summary", summary="；".join(parts))
            )

    def manual_next_day_mode_changed(self, enabled: bool) -> None:
        self.operation_done.emit(self.tr(
            "log.manual_day_mode_on" if enabled else "log.manual_day_mode_off"
        ))

    def delete_all(self) -> None:
        from schedule_folder import (
            bulk_delete_job_summary,
            format_bulk_delete_confirm_message,
        )

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort

        modules = getattr(self.gateway, "m", None)
        parent = self.parent()
        if modules is None:
            return
        jobs = modules.scheduler.load_schedule2_jobs()
        if not jobs:
            if parent is not None:
                show_message(
                    parent,
                    self.tr,
                    self.tr("msgbox.delete_all.title"),
                    self.tr("log.delete_all_none"),
                )
            return
        single_txt, folder_done, folder_kept, to_delete, kept = (
            bulk_delete_job_summary(jobs)
        )
        if not to_delete:
            message = self.tr("log.delete_all_nothing")
            if folder_kept > 0:
                message = self.tr("log.delete_all_kept_folder", n=folder_kept)
            if parent is not None:
                show_message(
                    parent,
                    self.tr,
                    self.tr("msgbox.delete_all.title"),
                    message,
                )
            return
        msg = format_bulk_delete_confirm_message(
            single_txt=single_txt,
            folder_done=folder_done,
            folder_kept=folder_kept,
            total_delete=len(to_delete),
        )
        if not confirm_or_abort(
            parent,
            self.tr,
            self.tr("msgbox.delete_all.title"),
            msg,
        ):
            return
        modules.scheduler.save_schedule2_jobs(kept)
        self.refresh()
        if folder_kept > 0:
            self.operation_done.emit(self.tr(
                "log.delete_all_done_kept",
                n=len(to_delete),
                single_txt=single_txt,
                folder_done=folder_done,
                folder_kept=folder_kept,
            ))
        else:
            self.operation_done.emit(self.tr(
                "log.delete_all_done",
                n=len(to_delete),
                single_txt=single_txt,
                folder_done=folder_done,
            ))

    def reload_wa_folders(self) -> None:
        from schedule_folder import is_folder_job

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort

        modules = getattr(self.gateway, "m", None)
        parent = self.parent()
        if modules is None:
            return
        jobs = modules.scheduler.load_schedule2_jobs()
        folder_n = sum(1 for job in jobs if is_folder_job(job))
        if folder_n <= 0:
            if parent is not None:
                show_message(
                    parent,
                    self.tr,
                    self.tr("taskmgr.reload_folder_txt"),
                    self.tr("msgbox.reload_folder.none"),
                )
            return
        if not confirm_or_abort(
            parent,
            self.tr,
            self.tr("taskmgr.reload_folder_txt"),
            self.tr("msgbox.reload_folder.body", n=folder_n),
        ):
            return
        result = modules.scheduler.bulk_reload_schedule2_folder_scripts(
            cfg=getattr(self.gateway, "cfg", None)
        )
        self.refresh()
        if isinstance(result, tuple) and len(result) >= 2:
            ok_n, fail_n = int(result[0]), int(result[1])
            if ok_n > 0 and fail_n <= 0:
                self.operation_done.emit(self.tr("log.reload_folder_ok", n=ok_n))
            elif ok_n > 0:
                self.operation_done.emit(
                    self.tr("log.reload_folder_partial", ok=ok_n, fail=fail_n)
                )
            else:
                self.operation_failed.emit(
                    self.tr("log.reload_folder_fail", fail=fail_n)
                )
        else:
            self.operation_done.emit(self.tr("taskmgr.reload_folder_txt"))

    def send_images(self) -> None:
        self._start_image_flow(sync_to_customer=False)

    def send_images_sync(self) -> None:
        self._start_image_flow(sync_to_customer=True)

    def _start_image_flow(self, *, sync_to_customer: bool) -> None:
        from ...services.image_flow import run_one_click_image_flow

        parent = self.parent()
        modules = getattr(self.gateway, "m", None)
        if parent is None or modules is None:
            return
        jobs = modules.scheduler.load_schedule2_jobs()

        def request_send(job_ids, paths, **kwargs):
            return self.gateway.task_action(
                "send_images",
                job_ids=job_ids,
                image_paths=paths,
                **kwargs,
            )

        run_one_click_image_flow(
            parent,
            tr=self.tr,
            jobs=jobs,
            collect_fn=modules.images.collect_awaiting_image_jobs,
            group_fn=modules.images.group_awaiting_by_day,
            request_send=request_send,
            sync_to_customer=sync_to_customer,
            notes_fn=modules.images.notes_for_awaiting_jobs,
            on_busy=self.image_busy.emit,
            on_done_refresh=self.refresh,
        )
