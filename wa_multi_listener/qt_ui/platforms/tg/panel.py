"""可嵌入主程序的 PySide6 Telegram 七页面板。"""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...common.notifications import show_alert, show_stage_reminder
from ...services.image_flow import run_one_click_image_flow
from .common import Translator, button, shared_tr
from .pages_contacts import ContactsPage, RulesPage
from .pages_core import AccountsPage, DashboardPage, LogsPage
from .pages_tasks import SchedulePage, TaskManagerFactory, TaskManagerPlaceholder
from .presenter import TgPresenter


class TgPanel(QWidget):
    """只管理视图组合；业务状态均由 TgPresenter 持有。"""

    alert_received = Signal(object)
    reminder_received = Signal(object, object, int, int, object)

    def __init__(
        self,
        *,
        presenter: Optional[TgPresenter] = None,
        task_manager_factory: Optional[TaskManagerFactory] = None,
        tr: Optional[Translator] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.tr = tr or shared_tr
        self.presenter = presenter or TgPresenter(tr=self.tr, parent=self)
        if self.presenter.parent() is None:
            self.presenter.setParent(self)
        self._owns_presenter = presenter is None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        side = QFrame(self)
        side.setObjectName("sideNav")
        side.setFixedWidth(90)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(6, 10, 6, 8)
        side_layout.setSpacing(6)
        brand = QLabel(self.tr("tg.brand"), side)
        brand.setObjectName("sideBrand")
        brand.setWordWrap(True)
        side_layout.addWidget(brand)
        self.nav = QListWidget(side)
        self.nav.setObjectName("sideNavList")
        self.nav.setFixedWidth(78)
        side_layout.addWidget(self.nav, 1)
        save = button(
            "common.save_reload",
            self.tr,
            self.presenter.save_all_and_restart,
            kind="primary",
            compact=True,
        )
        save.setMinimumHeight(40)
        side_layout.addWidget(save)
        self.stack = QStackedWidget(self)
        outer.addWidget(side)
        outer.addWidget(self.stack, 1)
        root.addLayout(outer, 1)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        root.addWidget(self.status)

        factory = task_manager_factory or TaskManagerPlaceholder
        pages: list[tuple[str, QWidget]] = [
            ("nav.dash", DashboardPage(self.presenter, self.tr)),
            ("nav.acct", AccountsPage(self.presenter, self.tr)),
            ("nav.grp", ContactsPage(self.presenter, self.tr)),
            ("nav.rules", RulesPage(self.presenter, self.tr)),
            ("nav.sched", SchedulePage(self.presenter, self.tr)),
            ("nav.taskmgr", factory(self.presenter, self.tr, self)),
            ("nav.logs_tg", LogsPage(self.presenter, self.tr)),
        ]
        for key, widget in pages:
            self.nav.addItem(QListWidgetItem(self.tr(key)))
            self.stack.addWidget(widget)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.presenter.alert_received.connect(self._on_alert)
        self.presenter.reminder_received.connect(self._on_reminder)
        self.presenter.image_flow_requested.connect(self._on_image_flow)
        self.presenter.status_changed.connect(self._set_status)
        self.presenter.image_busy.connect(self._set_status)
        # 检测完成后跳到通讯录，便于立刻看到 ✓在群 / ⚠不在群 标记
        self.presenter.audit_completed.connect(lambda _=None: self.nav.setCurrentRow(2))

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self.status.setText(str(message or ""))

    @Slot(object)
    def _on_alert(self, payload: object) -> None:
        self.alert_received.emit(payload)
        data = payload if isinstance(payload, dict) else {}
        remark = _tg_alert_remark(self.presenter.config.address_book, data)
        show_alert(
            self,
            tr=self.tr,
            title=self.tr("alert.title_tg"),
            chat_title=str(data.get("chat_title", "")),
            sender_name=str(data.get("sender_name", "")),
            message_text=str(data.get("message_text", payload)),
            remark=remark,
        )

    @Slot(object, object, int, int, object)
    def _on_reminder(self, job, item, step: int, paused: int, _ids) -> None:
        self.reminder_received.emit(job, item, step, paused, _ids)
        if not getattr(self.presenter.config, "stage_reminder_popup_enabled", True):
            return
        name = getattr(job, "source_name", "") or self.tr("taskmgr.title")
        note = getattr(item, "reminder_note", "") or self.tr("stage.no_note")
        body = str(note)
        if paused > 0:
            body += self.tr("stage.paused_related", n=paused)
        show_stage_reminder(
            self,
            tr=self.tr,
            title=self.tr("stage.title_tg"),
            subtitle=self.tr("stage.subtitle", step=step, name=name),
            body=body,
        )

    @Slot(bool)
    def _on_image_flow(self, sync_to_customer: bool) -> None:
        from .common import call_guarded

        def run() -> None:
            jobs = self.presenter.m.scheduler.load_jobs()
            run_one_click_image_flow(
                self,
                tr=self.tr,
                jobs=jobs,
                collect_fn=self.presenter.m.images.collect_awaiting_image_jobs,
                group_fn=self.presenter.m.images.group_awaiting_by_day,
                request_send=self.presenter.request_bulk_images,
                sync_to_customer=sync_to_customer,
                notes_fn=self.presenter.m.images.notes_for_awaiting_jobs,
                on_busy=self.presenter.image_busy.emit,
                on_done_refresh=lambda: self.presenter.tasks_changed.emit(
                    self.presenter.task_records()
                ),
            )

        call_guarded(self, self.tr, run)

    def closeEvent(self, event: Any) -> None:
        if self._owns_presenter:
            self.presenter.close()
        super().closeEvent(event)


def _tg_alert_remark(address_book: Any, data: dict) -> str:
    chat_id = data.get("chat_id")
    raw_id = data.get("chat_id_raw")
    username = str(data.get("chat_username") or "").strip() or None
    title = str(data.get("chat_title") or "").strip() or None
    peers: list[int] = []
    for value in (chat_id, raw_id):
        try:
            peers.append(int(value))
        except (TypeError, ValueError):
            continue
    match_fn = None
    try:
        from tg_multi_listener.config import telegram_chat_matches_address_ref

        match_fn = telegram_chat_matches_address_ref
    except Exception:
        match_fn = None
    for row in address_book or ():
        remark = str(getattr(row, "remark", "") or "").strip()
        ref = str(getattr(row, "chat_ref", "") or "").strip()
        if not remark:
            continue
        if match_fn is not None and peers:
            peer = peers[0]
            raw = peers[1] if len(peers) > 1 else peer
            try:
                if match_fn(
                    ref,
                    peer_id=peer,
                    raw_chat_id=raw,
                    event_username=username,
                    event_title=title,
                ):
                    return remark
            except Exception:
                pass
        keys = {str(p) for p in peers}
        if ref and (ref in keys or ref.lstrip("-") in {k.lstrip("-") for k in keys}):
            return remark
        if username and ref:
            handle = username.lstrip("@").lower()
            frag = ref.lstrip("@").lower()
            if handle and (frag == handle or handle in frag):
                return remark
    return ""
