"""TG 七页面板的 Presenter；不包含控件创建。"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from PySide6.QtCore import QObject, Signal

from .event_flow import handle_listener_alert
from .login_bridge import run_login_with_qt
from .runtime import TgModules, load_tg_modules
from .task_adapter import TgTaskAdapter


class TgPresenter(QObject):
    changed = Signal()
    status_changed = Signal(str)
    alert_received = Signal(object)
    reminder_received = Signal(object, object, int, int, object)
    audit_completed = Signal(object)
    log_received = Signal(str)
    tasks_changed = Signal(object)
    image_flow_requested = Signal(bool)
    image_busy = Signal(str)
    address_group_warning = Signal(str, str, int)

    def __init__(
        self,
        *,
        modules: Optional[TgModules] = None,
        login_runner: Callable[..., None] = run_login_with_qt,
        tr: Optional[Callable[[str], str]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr or _shared_tr
        self.m = modules or load_tg_modules()
        self.login_runner = login_runner
        self.config = self.m.config.load_config()
        self.listener = self.m.listener.ListenerController()
        self.scheduler = self.m.scheduler.ScheduleRunner()
        self.coordinator = self.m.coordinator.TelethonCoordinator(
            self.listener, self.scheduler
        )
        bind_warning = getattr(self.coordinator, "set_address_warning_callback", None)
        if callable(bind_warning):
            bind_warning(
                lambda label, kind, peer_id: self.address_group_warning.emit(
                    label, kind, peer_id
                )
            )
        self.task_adapter = TgTaskAdapter(self)
        self.scheduler.set_reminder_callback(self._on_reminder)
        self._log_callback = self.log_received.emit
        self.m.logger.add_memory_listener(self._log_callback)
        self.audit_flags: dict[str, str] = {}
        self.audit_details: dict[str, str] = {}
        self._reload_busy = False
        self._worker = None
        self._connect_watch_timer = None
        self._connect_watch_left = 0

    def close(self, join_timeout: float = 2.0) -> None:
        """关窗用短超时；残留会话线程由进程退出收掉。"""
        self._stop_connection_watch()
        self.coordinator.stop(join_timeout=join_timeout)
        self.m.logger.remove_memory_listener(self._log_callback)

    def save_api(self, api_id: str, api_hash: str) -> None:
        try:
            parsed = int(api_id.strip())
        except ValueError as exc:
            raise ValueError(self._tr("qt.tg.api_id_int")) from exc
        if parsed <= 0 or not api_hash.strip():
            raise ValueError(self._tr("qt.tg.api_required"))
        self.config.api_id = parsed
        self.config.api_hash = api_hash.strip()
        self._save()

    def add_account(self, account_id: str, phone: str = "") -> Any:
        aid = account_id.strip()
        if not aid:
            raise ValueError(self._tr("log.acct_id_required"))
        if any(row.id == aid for row in self.config.accounts):
            raise ValueError(self._tr("log.acct_exists"))
        account = self.m.config.Account(
            id=aid, session_name=uuid.uuid4().hex, phone=phone.strip()
        )
        self.config.accounts.append(account)
        self._save()
        return account

    def remove_account(self, account_id: str) -> None:
        self.config.accounts = [
            row for row in self.config.accounts if row.id != account_id
        ]
        self._save()

    def login(self, parent: Any, account_id: str) -> None:
        account = self._account(account_id)
        was_online = account_id in self.connected_account_ids()

        def done(ok: bool, message: str) -> None:
            self.status_changed.emit(message)
            if not ok:
                return
            self.config = self.m.config.load_config()
            connect_one = getattr(
                self.coordinator, "request_connect_account", None
            )
            if (
                not was_online
                and self.coordinator.is_running()
                and callable(connect_one)
            ):
                from ...bridges.ui_call import call_on_ui

                def connected(connected_ok: bool, detail: str) -> None:
                    def finish() -> None:
                        self.status_changed.emit(detail)
                        self.changed.emit()
                        if not connected_ok and not self.coordinator.is_running():
                            self.restart_services_async()

                    call_on_ui(self, finish)

                if connect_one(self.config, account_id, connected):
                    return
            self.restart_services_async()

        def stop_existing_session() -> None:
            if not self.coordinator.stop():
                raise RuntimeError(
                    "Telegram 后台仍在退出，已取消登录以避免会话锁冲突。"
                )

        self.login_runner(
            self.m.auth,
            parent,
            account,
            self.config,
            done,
            pre_login=stop_existing_session if was_online else None,
        )

    def restart_services(self) -> bool:
        self._stop_connection_watch()
        if not self.coordinator.stop():
            self.m.logger.error(
                "Telegram 服务重启失败：上一会话线程仍在退出中。"
                "请等待约半分钟后再点「保存并重载」，或完全退出程序后重开。"
            )
            self.status_changed.emit(self._tr("qt.tg.restart_fail"))
            return False
        self.listener.start(self.config, self._on_alert)
        self.scheduler.start(self.config)
        ok = self.coordinator.start(self.config)
        if ok:
            self._start_connection_watch()
        self.status_changed.emit(
            self._tr("qt.tg.restart_ok" if ok else "qt.tg.restart_fail")
        )
        return ok

    def _start_connection_watch(self) -> None:
        """连接 40+ 账号需 1–2 分钟；定时刷新账号页在线状态。"""
        from PySide6.QtCore import QTimer

        self._stop_connection_watch()
        self._connect_watch_left = 50
        timer = QTimer(self)
        timer.setInterval(3000)

        def _tick() -> None:
            self._connect_watch_left -= 1
            self.changed.emit()
            if self._connect_watch_left <= 0:
                self._stop_connection_watch()

        timer.timeout.connect(_tick)
        timer.start()
        self._connect_watch_timer = timer
        _tick()

    def _stop_connection_watch(self) -> None:
        timer = self._connect_watch_timer
        self._connect_watch_timer = None
        self._connect_watch_left = 0
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def restart_services_async(self) -> bool:
        """后台重启服务，避免登录成功/按钮点击卡住主线程。"""
        if self._reload_busy:
            self.status_changed.emit(self._tr("log.reload_busy"))
            return False
        self._reload_busy = True
        self.status_changed.emit(self._tr("log.config_saved"))
        from ...core.worker import WorkerRunner

        if self._worker is None:
            self._worker = WorkerRunner(self)

        def ok(result: Any = None) -> None:
            self._reload_busy = False
            success = bool(result)
            self.status_changed.emit(
                self._tr("qt.tg.restart_ok" if success else "qt.tg.restart_fail")
            )
            self.changed.emit()

        def fail(err: Any) -> None:
            self._reload_busy = False
            message = getattr(err, "message", str(err))
            self.status_changed.emit(self._tr("log.reload_fail", err=message))

        self._worker.submit(self.restart_services, on_result=ok, on_error=fail)
        return True

    def connected_account_ids(self) -> set[str]:
        fn = getattr(self.coordinator, "connected_account_ids", None)
        if callable(fn):
            try:
                return set(fn())
            except Exception:
                return set()
        return set(getattr(self.coordinator, "_clients_by_id", {}) or {})

    def reconnect_offline_accounts(self) -> bool:
        """重连未在线的已启用账号；服务未运行则全量启动。"""
        from ...bridges.ui_call import call_on_ui

        if getattr(self, "_reconnect_busy", False) or self._reload_busy:
            self.status_changed.emit(self._tr("log.reconnect_busy"))
            return False
        online = self.connected_account_ids()
        targets = [
            row for row in self.config.accounts
            if getattr(row, "enabled", True) and row.id not in online
        ]
        if not targets:
            self.status_changed.emit(self._tr("log.reconnect_none"))
            return False

        if not self.coordinator.is_running():
            self.status_changed.emit(self._tr("log.reconnect_start"))
            return self.restart_services_async()

        def done(ok: int, fail: int, skip: int) -> None:
            def finish() -> None:
                self._reconnect_busy = False
                self.status_changed.emit(
                    self._tr("log.reconnect_done", ok=ok, fail=fail, skip=skip)
                )
                self.changed.emit()

            call_on_ui(self, finish)

        self._reconnect_busy = True
        self.status_changed.emit(self._tr("log.reconnect_start"))
        accepted = self.coordinator.request_reconnect_offline(self.config, done)
        if not accepted:
            self._reconnect_busy = False
            return self.restart_services_async()
        return True

    def _resolve_chat_ref(self, chat_ref: str, invite_link: str = "") -> str:
        ref = (chat_ref or "").strip()
        invite = (invite_link or "").strip()
        if not ref and invite:
            ref = invite
        if not ref and not invite:
            raise ValueError(self._tr("grp.need_chat_or_invite"))
        parsed = self.m.config.parse_chat_ref_input(ref)
        return str(parsed)

    def add_address(
        self,
        remark: str,
        chat_ref: str,
        *,
        watch_user: str = "",
        owner_account_id: str = "",
        invite_link: str = "",
        listen_enabled: bool = True,
    ) -> Any:
        resolved = self._resolve_chat_ref(chat_ref, invite_link)
        if watch_user.strip():
            self.m.config.parse_watch_user_input(watch_user)
        row = self.m.config.AddressEntry(
            id=uuid.uuid4().hex[:12],
            remark=remark.strip(),
            chat_ref=resolved,
            watch_user=watch_user.strip(),
            owner_account_id=owner_account_id.strip(),
            invite_link=invite_link.strip(),
            listen_enabled=listen_enabled,
        )
        self.config.address_book.append(row)
        self._save_hot()
        return row

    def update_address(self, entry_id: str, **values: Any) -> None:
        row = self._address(entry_id)
        invite = str(values.get("invite_link", row.invite_link) or "")
        if "chat_ref" in values or "invite_link" in values:
            chat = str(values.get("chat_ref", row.chat_ref) or "")
            values["chat_ref"] = self._resolve_chat_ref(chat, invite)
        if values.get("watch_user"):
            self.m.config.parse_watch_user_input(str(values["watch_user"]))
        allowed = {
            "remark", "chat_ref", "watch_user", "owner_account_id",
            "invite_link", "listen_enabled",
        }
        for key, value in values.items():
            if key in allowed:
                setattr(row, key, value.strip() if isinstance(value, str) else value)
        self._save_hot()

    def rename_account(self, old_id: str, new_id: str) -> None:
        old = (old_id or "").strip()
        new = (new_id or "").strip()
        if not old or not new:
            raise ValueError(self._tr("log.acct_id_required"))
        if old == new:
            return
        if any(row.id == new for row in self.config.accounts):
            raise ValueError(self._tr("log.acct_exists"))
        account = self._account(old)
        account.id = new
        for row in self.config.address_book:
            if (row.owner_account_id or "").strip() == old:
                row.owner_account_id = new
        self._save()

    def remove_address(self, entry_id: str) -> None:
        self.config.address_book = [
            row for row in self.config.address_book if row.id != entry_id
        ]
        self._save_hot()

    def move_address(self, entry_id: str, delta: int) -> None:
        rows = self.config.address_book
        index = next(i for i, row in enumerate(rows) if row.id == entry_id)
        target = max(0, min(len(rows) - 1, index + delta))
        rows.insert(target, rows.pop(index))
        self._save()

    def save_rules(
        self, enabled: bool, popup: bool, rate_seconds: float
    ) -> None:
        self.config.listening_enabled = bool(enabled)
        self.config.stage_reminder_popup_enabled = bool(popup)
        self.config.rate_limit_seconds = max(0.0, float(rate_seconds))
        self._save_hot()

    def sync_last_schedule(self) -> None:
        before = {
            row.id: (row.last_schedule_source_name or "").strip()
            for row in self.config.address_book
        }
        n_jobs = len(self.m.scheduler.load_jobs())
        self.m.config.apply_last_schedule_from_current_jobs(self.config)
        self._save()
        n_changed = sum(
            1
            for row in self.config.address_book
            if before.get(row.id, "")
            != (row.last_schedule_source_name or "").strip()
        )
        n_filled = sum(
            1
            for row in self.config.address_book
            if (row.last_schedule_source_name or "").strip()
        )
        if n_changed:
            self.status_changed.emit(
                self._tr(
                    "log.sync_last_changed",
                    n_jobs=n_jobs,
                    n_changed=n_changed,
                    n_filled=n_filled,
                    n_empty=len(self.config.address_book) - n_filled,
                )
            )
        else:
            self.status_changed.emit(
                self._tr(
                    "log.sync_last_unchanged",
                    n_jobs=n_jobs,
                    n_filled=n_filled,
                )
            )
        self.changed.emit()

    def bulk_replace_account(
        self, job_id: str, from_account: str, to_account: str
    ) -> None:
        from_acc = from_account.strip()
        to_acc = to_account.strip()
        if from_acc in ("", "—") or to_acc in ("", "—"):
            raise ValueError(self._tr("log.bulk_need_accounts"))
        if from_acc == to_acc:
            raise ValueError(self._tr("log.bulk_same_account"))
        jobs = self.m.scheduler.load_jobs()
        job = next((row for row in jobs if row.id == job_id), None)
        if job is None:
            raise ValueError(self._tr("log.job_not_found"))
        changed = 0
        for item in job.items:
            original = (
                getattr(item, "original_account_id", None)
                or getattr(item, "account_id", "")
                or ""
            )
            if getattr(item, "is_reminder", False):
                continue
            if original == from_acc:
                item.send_as_account_id = to_acc
                changed += 1
        if changed == 0:
            raise ValueError(self._tr("log.bulk_no_match", account=from_acc))
        self.m.scheduler.save_jobs_patch([job])
        self.status_changed.emit(
            self._tr(
                "log.bulk_replaced",
                from_acc=from_acc,
                n=changed,
                to_acc=to_acc,
            )
        )
        self.changed.emit()
        self.tasks_changed.emit(self.task_records())

    def audit_rules(self) -> bool:
        from ...bridges.ui_call import call_on_ui

        if getattr(self, "_audit_busy", False):
            self.status_changed.emit(self._tr("log.audit_busy"))
            return False

        def done(result: Any) -> None:
            def finish() -> None:
                self._audit_busy = False
                self._apply_audit(result)
                self.audit_completed.emit(result)

            call_on_ui(self, finish)

        self._audit_busy = True
        self.status_changed.emit(self._tr("log.audit_start"))
        accepted = self.coordinator.request_watch_membership_audit(
            self.config, done
        )
        if not accepted:
            self._audit_busy = False
            self.status_changed.emit(self._tr("log.audit_need_login_tg"))
        return accepted

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
        self.changed.emit()
        if not flags:
            self.status_changed.emit(self._tr("log.audit_incomplete"))
            return
        ok = sum(1 for value in flags.values() if value == "ok")
        absent = sum(1 for value in flags.values() if value == "absent")
        err = sum(1 for value in flags.values() if value == "error")
        offline = sum(1 for value in flags.values() if value == "offline")
        checked = ok + absent
        if checked == 0 and err == 0 and offline == 0:
            self.status_changed.emit(self._tr("log.audit_no_targets"))
            return
        parts = [self._tr("log.audit_checked", n=checked)]
        if absent:
            parts.append(self._tr("log.audit_absent", n=absent))
        if err:
            parts.append(self._tr("log.audit_failed", n=err))
        if offline:
            parts.append(self._tr("log.audit_offline", n=offline))
        self.status_changed.emit(
            self._tr("log.audit_summary", summary="；".join(parts))
        )

    def import_txt(
        self, path: str, entry_ids: Iterable[str], interval: tuple[float, float]
    ) -> list[Any]:
        source = Path(path)
        text = source.read_text(encoding="utf-8-sig")
        valid = {row.id for row in self.config.accounts}
        items, errors = self.m.txt_import.import_doc_items(
            text, valid_accounts=valid, require_per_item_interval=False
        )
        if not items:
            raise ValueError(errors[0] if errors else self._tr("log.txt_no_items"))
        return self._create_jobs(source, entry_ids, items, interval)

    def import_folder(
        self, path: str, entry_ids: Iterable[str], interval: tuple[float, float]
    ) -> list[Any]:
        files, errors = self.m.folder.scan_schedule_folder(path)
        if errors:
            raise ValueError(errors[0])
        first = Path(path) / files[0]
        jobs = self.import_txt(str(first), entry_ids, interval)
        for job in jobs:
            job.source_kind = "folder"
            job.folder_path = os.path.abspath(path)
            job.folder_files = list(files)
            job.folder_day_index = 0
        self.m.scheduler.save_jobs_patch(jobs)
        return jobs

    def task_action(self, action: str, job_id: str = "") -> Any:
        actions = {
            "toggle": lambda: self.task_adapter.toggle(job_id),
            "pause": lambda: self.scheduler.pause_job(job_id),
            "resume": lambda: self.scheduler.resume_job(job_id),
            "delete": lambda: self.task_adapter.delete(job_id),
            "next_day": lambda: self.task_adapter.next_day(job_id),
            "resume_all": self.scheduler.resume_all_jobs,
            "next_day_all": self.task_adapter.next_day_all,
            "delete_all": self.task_adapter.delete_all,
            "reload": lambda: self.m.scheduler.load_jobs(force=True),
        }
        if action not in actions:
            raise ValueError(self._tr("qt.tg.unknown_action", action=action))
        result = actions[action]()
        self.changed.emit()
        self.tasks_changed.emit(self.task_records())
        return result

    def task_records(self):
        return self.task_adapter.records()

    def toggle_task(self, task_id: str) -> None:
        self.task_action("toggle", task_id)

    def delete_task(self, task_id: str) -> None:
        from ...services.confirm import confirm_or_abort

        parent = self.parent()
        job = next(
            (row for row in self.m.scheduler.load_jobs() if row.id == task_id),
            None,
        )
        if job is None:
            return
        target = self.m.config.format_job_targets_label(self.config, job)
        if not confirm_or_abort(
            parent,
            self._tr,
            self._tr("msgbox.delete.title"),
            self._tr(
                "msgbox.delete.body",
                name=job.source_name,
                target=target,
            ),
        ):
            return
        self.task_action("delete", task_id)
        self.status_changed.emit(self._tr("log.job_deleted", name=job.source_name))

    def next_day_task(self, task_id: str) -> None:
        from schedule_folder import can_advance_folder_day, is_folder_job

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort
        from ...services.task_confirmations import manual_next_day_confirm_message

        parent = self.parent()
        job = next(
            (row for row in self.m.scheduler.load_jobs() if row.id == task_id),
            None,
        )
        if job is None:
            return
        if not is_folder_job(job):
            if parent is not None:
                show_message(
                    parent,
                    self._tr,
                    self._tr("msgbox.manual_day.title"),
                    self._tr("msgbox.manual_day.folder_only"),
                )
            return
        if not can_advance_folder_day(job):
            if parent is not None:
                show_message(
                    parent,
                    self._tr,
                    self._tr("msgbox.manual_day.title"),
                    self._tr("msgbox.manual_day.last_day"),
                )
            return
        target = self.m.config.format_job_targets_label(self.config, job)
        if not confirm_or_abort(
            parent,
            self._tr,
            self._tr("msgbox.manual_day.title"),
            manual_next_day_confirm_message(self._tr, job, target),
        ):
            return
        ok, message = self.m.scheduler.advance_scheduled_folder_day(job, self.config)
        if not ok:
            self.status_changed.emit(self._tr("log.folder_advance_fail", err=message))
            return
        self.m.scheduler.save_jobs_patch([job])
        self.m.config.apply_last_schedule_for_jobs(self.config, [job])
        self.changed.emit()
        self.tasks_changed.emit(self.task_records())
        self.status_changed.emit(
            self._tr(
                "log.folder_advance_ok",
                target=target,
                day=job.folder_day_index + 1,
            )
        )

    def resume_all(self) -> None:
        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort
        from ...services.task_confirmations import resume_all_confirm_message

        parent = self.parent()
        jobs = self.m.scheduler.load_jobs()
        resumable, skipped = self.m.scheduler.bulk_resume_job_counts(jobs)
        message = resume_all_confirm_message(
            self._tr,
            resumable=resumable,
            skipped=skipped,
            body_key="msgbox.resume_all.body_doc",
        )
        if message is None:
            text = self._tr("log.resume_all_none")
            if parent is not None:
                show_message(
                    parent, self._tr, self._tr("msgbox.resume_all.title"), text
                )
            return
        if not confirm_or_abort(
            parent,
            self._tr,
            self._tr("msgbox.resume_all.title"),
            message,
        ):
            return
        count = self.scheduler.resume_all_jobs()
        self.changed.emit()
        self.tasks_changed.emit(self.task_records())
        key = (
            "log.resume_all_done_skipped" if skipped > 0 else "log.resume_all_done"
        )
        self.status_changed.emit(self._tr(key, n=count, skipped=skipped))

    def next_day_all(self) -> None:
        from schedule_folder import (
            can_advance_folder_day,
            split_folder_jobs_for_bulk_advance,
        )

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort
        from ...services.task_confirmations import next_day_all_confirm_message

        parent = self.parent()
        jobs = self.m.scheduler.load_jobs()
        candidates, stale = split_folder_jobs_for_bulk_advance(jobs)
        message = next_day_all_confirm_message(
            self._tr,
            candidates=candidates,
            stale=stale,
            target_label=lambda job: self.m.config.format_job_targets_label(
                self.config, job
            ),
            is_running=lambda job: bool(
                getattr(job, "enabled", False)
                and getattr(job, "state", "") == "running"
            ),
        )
        if message is None:
            if parent is not None:
                show_message(
                    parent,
                    self._tr,
                    self._tr("msgbox.next_day.title"),
                    self._tr("msgbox.next_day.no_folder"),
                )
            return
        if not confirm_or_abort(
            parent,
            self._tr,
            self._tr("msgbox.next_day.title"),
            message,
        ):
            return
        updated = []
        for job in candidates:
            live = next(
                (row for row in self.m.scheduler.load_jobs() if row.id == job.id),
                None,
            )
            if live is None or not can_advance_folder_day(live):
                continue
            ok, err = self.m.scheduler.advance_scheduled_folder_day(live, self.config)
            if ok:
                updated.append(live)
            else:
                self.status_changed.emit(
                    self._tr(
                        "log.folder_advance_job_fail",
                        target=self.m.config.format_job_targets_label(
                            self.config, live
                        ),
                        err=err,
                    )
                )
        stale_ids = {job.id for job in stale}
        if stale_ids:
            kept = [
                row for row in self.m.scheduler.load_jobs() if row.id not in stale_ids
            ]
            self.m.scheduler.save_jobs(kept)
        if updated:
            self.m.scheduler.save_jobs_patch(updated)
            self.m.config.apply_last_schedule_for_jobs(self.config, updated)
        self.changed.emit()
        self.tasks_changed.emit(self.task_records())
        parts = []
        if updated:
            parts.append(self._tr("log.next_day_advanced", n=len(updated)))
        if stale_ids:
            parts.append(self._tr("log.next_day_deleted", n=len(stale_ids)))
        if not parts:
            self.status_changed.emit(self._tr("log.next_day_nothing"))
        else:
            self.status_changed.emit(
                self._tr("log.next_day_summary", summary="；".join(parts))
            )

    def manual_next_day_mode_changed(self, enabled: bool) -> None:
        self.status_changed.emit(
            self._tr(
                "log.manual_day_mode_on"
                if enabled
                else "log.manual_day_mode_off"
            )
        )

    def delete_all(self) -> None:
        from schedule_folder import (
            bulk_delete_job_summary,
            format_bulk_delete_confirm_message,
        )

        from ...common.dialogs import show_message
        from ...services.confirm import confirm_or_abort

        jobs = self.m.scheduler.load_jobs()
        parent = self.parent()
        if not jobs:
            if parent is not None:
                show_message(
                    parent,
                    self._tr,
                    self._tr("msgbox.delete_all.title"),
                    self._tr("log.delete_all_none"),
                )
            return
        single_txt, folder_done, folder_kept, to_delete, kept = (
            bulk_delete_job_summary(jobs)
        )
        if not to_delete:
            message = self._tr("log.delete_all_nothing")
            if folder_kept > 0:
                message = self._tr("log.delete_all_kept_folder", n=folder_kept)
            if parent is not None:
                show_message(
                    parent,
                    self._tr,
                    self._tr("msgbox.delete_all.title"),
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
            self._tr,
            self._tr("msgbox.delete_all.title"),
            msg,
        ):
            return
        self.m.scheduler.save_jobs(kept)
        self.changed.emit()
        self.tasks_changed.emit(self.task_records())
        if folder_kept > 0:
            self.status_changed.emit(
                self._tr(
                    "log.delete_all_done_kept",
                    n=len(to_delete),
                    single_txt=single_txt,
                    folder_done=folder_done,
                    folder_kept=folder_kept,
                )
            )
        else:
            self.status_changed.emit(
                self._tr(
                    "log.delete_all_done",
                    n=len(to_delete),
                    single_txt=single_txt,
                    folder_done=folder_done,
                )
            )

    def reload_wa_folders(self) -> None:
        """TG 任务管理不提供 WA 文件夹重读；保留空实现以兼容共享接口。"""
        return None

    def save_all_and_restart(self) -> bool:
        if self._reload_busy:
            self.status_changed.emit(self._tr("log.reload_busy"))
            return False
        self._reload_busy = True
        self._save()
        self.status_changed.emit(self._tr("log.config_saved"))
        from ...core.worker import WorkerRunner

        if self._worker is None:
            self._worker = WorkerRunner(self)

        def ok(result: Any = None) -> None:
            self._reload_busy = False
            success = bool(result)
            self.status_changed.emit(
                self._tr("log.services_reloaded" if success else "qt.tg.restart_fail")
            )
            self.changed.emit()

        def fail(err: Any) -> None:
            self._reload_busy = False
            message = getattr(err, "message", str(err))
            self.status_changed.emit(self._tr("log.reload_fail", err=message))

        self._worker.submit(
            self.restart_services, on_result=ok, on_error=fail
        )
        return True

    def send_images(self) -> None:
        self.image_flow_requested.emit(False)

    def send_images_sync(self) -> None:
        self.image_flow_requested.emit(True)

    def request_bulk_images(
        self,
        job_ids: list[str],
        paths: list[str],
        *,
        sync_to_customer: bool = False,
        customer_extra_text: str = "",
        on_progress=None,
        on_done=None,
    ) -> bool:
        return self.coordinator.request_bulk_image_send(
            job_ids,
            image_paths=paths,
            sync_to_customer=sync_to_customer,
            customer_extra_text=customer_extra_text,
            on_progress=on_progress,
            on_done=on_done,
        )

    def recent_logs(self) -> list[str]:
        return self.m.logger.get_recent_lines()

    def _create_jobs(
        self, source: Path, entry_ids: Iterable[str], items: list[Any],
        interval: tuple[float, float],
    ) -> list[Any]:
        by_id = {row.id: row for row in self.config.address_book}
        jobs = self.m.scheduler.load_jobs()
        created = []
        for eid in dict.fromkeys(entry_ids):
            row = by_id.get(eid)
            if row is None:
                continue
            chat = self.m.config.chat_ref_to_optional_int(row.chat_ref)
            job = self.m.scheduler.ScheduledJob.new(
                [chat] if chat is not None else [], str(source), list(items),
                [eid], interval_min_minutes=interval[0],
                interval_max_minutes=interval[1], interval_mode="fixed",
                start_paused=True,
            )
            jobs.append(job)
            created.append(job)
        if not created:
            raise ValueError(self._tr("log.need_select_group"))
        self.m.scheduler.save_jobs(jobs)
        self.m.config.apply_last_schedule_for_jobs(self.config, created)
        self.changed.emit()
        return created

    def _save(self) -> None:
        self.m.config.save_config(self.config)
        self.changed.emit()

    def _save_hot(self) -> None:
        self._save()
        self.coordinator.apply_config_hot(self.config)

    def _account(self, account_id: str) -> Any:
        return next(row for row in self.config.accounts if row.id == account_id)

    def _address(self, entry_id: str) -> Any:
        return next(row for row in self.config.address_book if row.id == entry_id)

    def _on_reminder(self, job: Any, item: Any, step: int, paused: int = 0,
                     ids: Optional[list[str]] = None) -> None:
        self.tasks_changed.emit(self.task_records())
        self.reminder_received.emit(job, item, step, paused, ids or [job.id])

    def _on_alert(self, payload: Any) -> None:
        handle_listener_alert(self, payload)


def _shared_tr(text: str) -> str:
    from i18n import t

    return t(text)
