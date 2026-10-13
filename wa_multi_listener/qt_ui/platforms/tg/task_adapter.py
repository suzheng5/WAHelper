"""Telegram 任务到共享 Qt 任务管理组件的适配层。"""
from __future__ import annotations

from typing import Any

from i18n.job_card import format_job_status_label, operator_note_for_items

from ...task_manager.types import TaskRecord


class TgTaskAdapter:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    @property
    def m(self):
        return self.presenter.m

    def records(self) -> list[TaskRecord]:
        records: list[TaskRecord] = []
        for order, job in enumerate(self.m.scheduler.load_jobs()):
            total = job.item_count()
            target = self.m.config.format_job_targets_label(
                self.presenter.config, job
            )
            note = operator_note_for_items(
                job.items, cursor=int(job.cursor or 0), max_len=56
            )
            records.append(
                TaskRecord(
                    task_id=job.id,
                    platform="tg",
                    title=(target or job.source_name or "").strip() or job.source_name,
                    target=target,
                    source_name=job.source_name,
                    running=bool(job.enabled and job.state == "running"),
                    enabled=job.enabled,
                    status=format_job_status_label(
                        enabled=job.enabled,
                        state=job.state,
                        pause_reason=job.pause_reason,
                    ),
                    step=f"{job.cursor}/{total}",
                    pause_reason=job.pause_reason,
                    last_error=job.last_error,
                    reminder_note=note,
                    cursor=job.cursor,
                    total=total,
                    folder_day=(
                        job.folder_day_index + 1
                        if job.source_kind == "folder"
                        else 0
                    ),
                    folder_total=len(job.folder_files),
                    is_folder=job.source_kind == "folder",
                    source_order=order,
                )
            )
        return records

    def toggle(self, job_id: str) -> Any:
        job = self._job(job_id)
        if job.enabled and job.state == "running":
            return self.presenter.scheduler.pause_job(job_id)
        return self.presenter.scheduler.resume_job(job_id)

    def delete(self, job_id: str) -> None:
        self.m.scheduler.save_jobs(
            [job for job in self.m.scheduler.load_jobs() if job.id != job_id]
        )

    def next_day(self, job_id: str) -> tuple[bool, str]:
        job = self._job(job_id)
        ok, message = self.m.scheduler.advance_scheduled_folder_day(
            job, self.presenter.config
        )
        if ok:
            self.m.scheduler.save_jobs_patch([job])
        return ok, message

    def next_day_all(self) -> int:
        changed = []
        for job in self.m.scheduler.load_jobs():
            ok, _message = self.m.scheduler.advance_scheduled_folder_day(
                job, self.presenter.config
            )
            if ok:
                changed.append(job)
        if changed:
            self.m.scheduler.save_jobs_patch(changed)
        return len(changed)

    def delete_all(self) -> None:
        from schedule_folder import bulk_delete_job_summary

        jobs = self.m.scheduler.load_jobs()
        _single, _done, _kept_n, _to_delete, kept = bulk_delete_job_summary(jobs)
        self.m.scheduler.save_jobs(kept)

    def _job(self, job_id: str):
        return next(
            job for job in self.m.scheduler.load_jobs() if job.id == job_id
        )
