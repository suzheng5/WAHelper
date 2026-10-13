"""现有 WA 业务模块到 Qt Presenter 的适配器。"""
from __future__ import annotations

import copy
import os
import re
import uuid
from typing import Any, Callable, Sequence

from .contracts import AccountItem, ConfigView, ContactItem
from .runtime import WaModules, load_wa_modules


class LegacyWaGateway:
    def __init__(
        self,
        *,
        modules: WaModules | None = None,
        coordinator: Any = None,
        listener: Any = None,
        schedule_runner: Any = None,
        reload_callback: Callable[[Any], None] | None = None,
    ) -> None:
        self.m = modules or load_wa_modules()
        self.coordinator = coordinator
        self.listener = listener
        self.runner = schedule_runner
        self.reload_callback = reload_callback
        self.cfg = self.m.config.load_config()

    def read_config(self) -> ConfigView:
        online = self.coordinator.connected_account_ids() if self.coordinator else set()
        accounts = tuple(
            AccountItem(a.id, a.phone, a.proxy, a.enabled, a.id in online)
            for a in self.cfg.accounts
        )
        contacts = tuple(
            ContactItem(
                e.id, e.remark, e.chat_ref, e.watch_user, e.listen_enabled,
                e.owner_account_id, e.invite_link, e.last_schedule_source_name,
            )
            for e in self.cfg.address_book
        )
        return ConfigView(
            accounts, contacts, self.cfg.listening_enabled,
            self.cfg.stage_reminder_popup_enabled, self.cfg.rate_limit_seconds,
        )

    def _save(self) -> None:
        self.m.config.save_config(self.cfg)
        if self.runner:
            self.runner.refresh_accounts(self.cfg)

    def add_account(self, account_id: str, phone: str, proxy: str) -> None:
        account_id = account_id.strip()
        if not account_id or any(a.id == account_id for a in self.cfg.accounts):
            raise ValueError("log.acct_exists" if account_id else "log.acct_id_required")
        if proxy.strip():
            self.m.proxy.normalize_proxy_url(proxy)
        self.cfg.accounts.append(
            self.m.config.Account(account_id, account_id, True, phone.strip(), proxy.strip())
        )
        self._save()

    def update_account(self, account_id: str, enabled: bool, proxy: str) -> None:
        account = next(a for a in self.cfg.accounts if a.id == account_id)
        if proxy.strip():
            self.m.proxy.normalize_proxy_url(proxy)
        account.enabled, account.proxy = bool(enabled), proxy.strip()
        self._save()

    def delete_account(self, account_id: str) -> None:
        self.cfg.accounts = [a for a in self.cfg.accounts if a.id != account_id]
        self._save()

    def start_qr_login(self, account_id, on_qr, on_status, on_done, cancel_event=None):
        account = next(a for a in self.cfg.accounts if a.id == account_id)
        before = None
        if self.coordinator:
            self.coordinator.begin_login_hold(account_id)
            before = lambda: self.coordinator.prepare_for_login(account_id)

        def done(ok: bool, message: str) -> None:
            if self.coordinator:
                self.coordinator.release_login_hold(account_id)
                if ok:
                    self.coordinator.connect_account_after_login(self.cfg, account_id)
            on_done(ok, message)

        return self.m.auth.run_qr_login_in_thread(
            account,
            on_qr,
            done,
            on_status=on_status,
            before_connect=before,
            cancel_event=cancel_event,
        )

    def _resolve_chat_ref(self, chat_ref: str, invite_link: str = "") -> str:
        ref = (chat_ref or "").strip()
        invite = (invite_link or "").strip()
        if not ref and invite:
            ref = invite
        if not ref and not invite:
            from i18n import t

            raise ValueError(t("grp.need_chat_or_invite"))
        return self.m.config.parse_chat_ref_input(ref)

    def add_contact(
        self, remark: str, chat_ref: str, watch_user: str,
        listen_enabled: bool, owner_account_id: str, invite_link: str = "",
    ) -> None:
        parsed = self._resolve_chat_ref(chat_ref, invite_link)
        watched = self.m.config.parse_watch_user_input(watch_user) if listen_enabled else ""
        self.cfg.address_book.append(self.m.config.AddressEntry(
            id=uuid.uuid4().hex[:12], remark=remark.strip() or "—", chat_ref=parsed,
            watch_user=watched, listen_enabled=bool(listen_enabled),
            owner_account_id=owner_account_id.strip(), invite_link=invite_link.strip(),
        ))
        self._save()
        self._apply_listen_hot()

    def update_contact(self, entry_id: str, **changes: Any) -> None:
        entry = next(e for e in self.cfg.address_book if e.id == entry_id)
        allowed = {
            "remark", "chat_ref", "watch_user", "listen_enabled",
            "owner_account_id", "invite_link",
        }
        invite = str(changes.get("invite_link", entry.invite_link) or "")
        if "chat_ref" in changes or "invite_link" in changes:
            chat = str(changes.get("chat_ref", entry.chat_ref) or "")
            changes["chat_ref"] = self._resolve_chat_ref(chat, invite)
        if changes.get("listen_enabled") and "watch_user" in changes:
            changes["watch_user"] = self.m.config.parse_watch_user_input(
                str(changes["watch_user"])
            )
        for key, value in changes.items():
            if key in allowed:
                setattr(entry, key, value)
        self._save()
        self._apply_listen_hot()

    def delete_contact(self, entry_id: str) -> None:
        self.cfg.address_book = [e for e in self.cfg.address_book if e.id != entry_id]
        self._save()
        self._apply_listen_hot()

    def move_contact(self, entry_id: str, offset: int) -> None:
        index = next(i for i, e in enumerate(self.cfg.address_book) if e.id == entry_id)
        target = index + offset
        if 0 <= target < len(self.cfg.address_book):
            self.cfg.address_book[index], self.cfg.address_book[target] = (
                self.cfg.address_book[target], self.cfg.address_book[index],
            )
            self._save()

    def update_rules(self, listening: bool, popup: bool, rate_seconds: float) -> None:
        self.cfg.listening_enabled = bool(listening)
        self.cfg.stage_reminder_popup_enabled = bool(popup)
        self.cfg.rate_limit_seconds = max(0.0, float(rate_seconds))
        self._save()
        self._apply_listen_hot()

    def _apply_listen_hot(self) -> None:
        """规则/通讯录变更后立即热更新监听；无在线客户端时至少刷新本地监听开关。"""
        if self.coordinator and self.coordinator.has_connected_clients():
            self.coordinator.apply_config_hot(self.cfg)
            return
        if self.listener is not None:
            try:
                self.listener.load_config(self.cfg)
            except Exception:
                pass

    def save_config(self) -> None:
        self._save()

    def reload_services(self) -> None:
        if self.reload_callback:
            self.reload_callback(self.cfg)
        elif self.coordinator:
            self.coordinator.apply_config_hot(self.cfg)

    def save_and_reload(self) -> None:
        self.save_config()
        self.reload_services()

    def request_audit(self, callback) -> bool:
        return bool(self.coordinator and self.coordinator.request_watch_membership_audit(
            self.cfg, callback
        ))

    def request_reconnect_offline(self, callback) -> bool:
        return bool(
            self.coordinator
            and self.coordinator.request_reconnect_offline(self.cfg, callback)
        )

    @staticmethod
    def _interval(raw: str) -> tuple[float, float]:
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*", raw)
        if not match:
            raise ValueError("log.interval_invalid")
        first, second = float(match.group(1)), float(match.group(2) or match.group(1))
        if min(first, second) <= 0:
            raise ValueError("log.interval_invalid")
        return min(first, second), max(first, second)

    def _rows(self, path: str) -> list[Any]:
        with open(path, encoding="utf-8") as stream:
            items, errors = self.m.txt_import.import_doc_items(stream.read(), valid_accounts=None)
        for message in errors[:10]:
            self.m.logger.info(message)
        if not items:
            raise ValueError("log.txt_no_items")
        rows = []
        for item in items:
            original, actual = self.m.schedule_account.mark_row_primary_auto(
                item.account_id, item.account_id
            )
            rows.append(self.m.scheduler.Schedule2Row(
                id=uuid.uuid4().hex[:12], original_account_id=original,
                send_as_account_id=actual, content=item.content,
                is_reminder=item.is_reminder, reminder_note=item.reminder_note,
                delay_after_minutes=item.delay_after_minutes,
                want_reactions=bool(getattr(item, "want_reactions", False)),
                is_image_send=bool(getattr(item, "is_image_send", False)),
            ))
        return rows

    def import_schedule(self, source: str, target_ids: Sequence[str], interval: str) -> int:
        low, high = self._interval(interval)
        folder_files: list[str] = []
        source_path = source
        if os.path.isdir(source):
            folder_files, errors = self.m.folder.scan_schedule_folder(source)
            if errors or not folder_files:
                raise ValueError(errors[0] if errors else "log.path_invalid")
            source_path = self.m.folder.folder_txt_abs_path(source, folder_files[0])
        elif not os.path.isfile(source):
            raise ValueError("log.path_invalid")
        rows = self._rows(source_path)
        entries = {e.id: e for e in self.cfg.address_book}
        jobs = self.m.scheduler.load_schedule2_jobs()
        created = []
        for entry_id in target_ids:
            entry = entries.get(entry_id)
            if not entry:
                continue
            job = self.m.scheduler.Schedule2Job.new(
                [entry.chat_ref], low, high, source_path, copy.deepcopy(rows), [entry_id],
            )
            if folder_files:
                job.source_kind, job.folder_path = "folder", os.path.abspath(source)
                job.folder_files, job.folder_day_index = list(folder_files), 0
            jobs.append(job)
            created.append(job)
        if not created:
            raise ValueError("log.need_select_group")
        self.m.scheduler.save_schedule2_jobs(jobs)
        self.m.config.apply_last_schedule_for_jobs(self.cfg, created)
        return len(created)

    def recent_logs(self, limit: int = 250) -> list[str]:
        return self.m.logger.get_recent_lines(limit)

    def task_records(self):
        from i18n.job_card import operator_note_for_items

        from ...task_manager.types import TaskRecord
        records = []
        for order, job in enumerate(self.m.scheduler.load_schedule2_jobs()):
            target = self.m.scheduler.schedule2_job_target_remarks(self.cfg, job)
            note = operator_note_for_items(
                job.rows, cursor=int(job.cursor or 0), max_len=56
            )
            records.append(TaskRecord(
                task_id=job.id, platform="wa",
                title=(target or job.source_name or "").strip() or job.source_name,
                target=target,
                source_name=job.source_name, running=job.state == "running",
                enabled=job.enabled, status=self.m.scheduler.schedule2_job_status_label(job),
                step=self.m.scheduler.schedule2_job_step_label(job),
                pause_reason=job.pause_reason, last_error=job.last_error,
                reminder_note=note,
                cursor=job.cursor, total=job.row_count(),
                folder_day=job.folder_day_index + 1 if job.source_kind == "folder" else 0,
                folder_total=len(job.folder_files), is_folder=job.source_kind == "folder",
                source_order=order,
            ))
        return records

    def task_action(self, action: str, task_id: str = "", **kwargs: Any) -> Any:
        runner = self.runner
        if action == "toggle":
            job = next(j for j in self.m.scheduler.load_schedule2_jobs() if j.id == task_id)
            return runner.pause_job(task_id) if job.state == "running" else runner.resume_job(task_id)
        if action == "delete":
            jobs = [j for j in self.m.scheduler.load_schedule2_jobs() if j.id != task_id]
            return self.m.scheduler.save_schedule2_jobs(jobs)
        if action == "next_day":
            job = next(j for j in self.m.scheduler.load_schedule2_jobs() if j.id == task_id)
            result = self.m.scheduler.advance_schedule2_folder_day(job, self.cfg)
            if result[0]:
                self.m.scheduler.save_schedule2_jobs_patch([job])
            return result
        if action == "resume_all":
            return runner.resume_all_jobs()
        if action == "next_day_all":
            changed = []
            for job in self.m.scheduler.load_schedule2_jobs():
                ok, _ = self.m.scheduler.advance_schedule2_folder_day(job, self.cfg)
                if ok:
                    changed.append(job)
            if changed:
                self.m.scheduler.save_schedule2_jobs_patch(changed)
            return len(changed)
        if action == "delete_all":
            from schedule_folder import bulk_delete_job_summary

            jobs = self.m.scheduler.load_schedule2_jobs()
            _single, _done, _kept_n, _to_delete, kept = bulk_delete_job_summary(jobs)
            return self.m.scheduler.save_schedule2_jobs(kept)
        if action == "reload_folders":
            return self.m.scheduler.bulk_reload_schedule2_folder_scripts(cfg=self.cfg)
        if action == "listen_hit":
            return runner.pause_by_chat(
                kwargs.get("chat_key", ""),
                self.m.scheduler.LISTEN_HIT_PAUSE_REASON_S2,
                event_title=kwargs.get("event_title"),
            )
        if action == "send_images" and self.coordinator:
            jobs = self.m.images.collect_awaiting_image_jobs(
                self.m.scheduler.load_schedule2_jobs()
            )
            job_ids = kwargs.pop("job_ids", [job.id for job in jobs])
            return self.coordinator.request_bulk_image_send(job_ids, **kwargs)
        raise ValueError(f"unsupported task action: {action}")
