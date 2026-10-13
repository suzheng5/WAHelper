"""可嵌入主窗口的 PySide6 WA 七页面板。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...common.dialogs import show_message
from ...common.notifications import show_alert, show_stage_reminder
from ...common.theme import style_button
from .contracts import TaskManagerFactory, Translator, WaGateway
from .pages.accounts import AccountsPage
from .pages.contacts import ContactsPage
from .pages.dashboard import DashboardPage
from .pages.logs import LogsPage
from .pages.rules import RulesPage
from .pages.schedule import SchedulePage
from .pages.tasks import TaskManagerPage
from .presenter import WaPresenter
from .runtime import default_translator


class WaPanel(QWidget):
    def __init__(
        self,
        gateway: WaGateway,
        *,
        presenter: WaPresenter | None = None,
        tr: Translator | None = None,
        task_manager_factory: TaskManagerFactory | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.tr = tr or default_translator()
        self.presenter = presenter or WaPresenter(gateway, self.tr, self)
        self.login_cancel = None
        self.setObjectName("waPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._sidebar(), 0)
        self.stack = QStackedWidget(self)
        row.addWidget(self.stack, 1)
        root.addLayout(row, 1)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setProperty("muted", True)
        root.addWidget(self.status)
        self.pages = (
            DashboardPage(self.tr),
            AccountsPage(self.presenter, self.tr),
            ContactsPage(self.presenter, self.tr),
            RulesPage(self.presenter, self.tr),
            SchedulePage(self.presenter, self.tr),
            TaskManagerPage(self.presenter, self.tr, task_manager_factory),
            LogsPage(self.presenter, self.tr),
        )
        for page in self.pages:
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.presenter.config_changed.connect(self.pages[0].set_config)
        self.presenter.operation_failed.connect(self._show_error)
        self.presenter.operation_done.connect(self._show_done)
        self.presenter.status_message.connect(self._set_status)
        self.presenter.alert_received.connect(self._show_alert)
        self.presenter.reminder_received.connect(self._show_reminder)
        self.presenter.image_busy.connect(self._set_status)
        # 检测完成后跳到通讯录，避免仍停在规则页看不出标记
        self.presenter.audit_finished.connect(lambda _=None: self.nav.setCurrentRow(2))
        self.presenter.refresh()
        self.presenter.refresh_logs()

    def _sidebar(self) -> QWidget:
        side = QFrame(self)
        side.setObjectName("sideNav")
        side.setFixedWidth(90)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(6, 10, 6, 8)
        layout.setSpacing(6)
        brand = QLabel(self.tr("wa.brand"))
        brand.setObjectName("sideBrand")
        brand.setWordWrap(True)
        layout.addWidget(brand)
        self.nav = QListWidget(side)
        self.nav.setObjectName("sideNavList")
        self.nav.setFixedWidth(78)
        for key in (
            "nav.dash", "nav.acct", "nav.grp", "nav.rules",
            "nav.sched", "nav.taskmgr", "nav.logs",
        ):
            item = QListWidgetItem(self.tr(key))
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.nav.addItem(item)
        layout.addWidget(self.nav, 1)
        save = QPushButton(self.tr("common.save_reload"), side)
        style_button(save, "primary", compact=True)
        save.setMinimumHeight(40)
        save.clicked.connect(self.presenter.save_and_reload)
        layout.addWidget(save)
        return side

    @Slot(str)
    def _set_status(self, message: str) -> None:
        self.status.setText(str(message or ""))

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self._set_status(message)
        show_message(self, self.tr, self.tr("common.unknown_error"), message)

    @Slot(str)
    def _show_done(self, message: str) -> None:
        if message:
            self._set_status(message)
            show_message(self, self.tr, self.tr("common.save"), message)
            self.presenter.refresh_logs()

    @Slot(object)
    def _show_alert(self, payload: object) -> None:
        data = payload if isinstance(payload, dict) else {}
        remark = _wa_alert_remark(self.presenter.config.contacts, data)
        show_alert(
            self,
            tr=self.tr,
            title=self.tr("alert.title_wa"),
            chat_title=str(data.get("chat_title", "")),
            sender_name=str(data.get("sender_name", "")),
            message_text=str(data.get("message_text", payload)),
            remark=remark,
        )

    @Slot(object)
    def _show_reminder(self, payload: object) -> None:
        args = payload if isinstance(payload, tuple) else (payload,)
        job = args[0] if args else None
        item = args[1] if len(args) > 1 else None
        step = int(args[2]) if len(args) > 2 else 1
        paused = int(args[3]) if len(args) > 3 else 0
        cfg = self.presenter.config
        if not getattr(cfg, "stage_reminder_popup_enabled", True):
            return
        name = getattr(job, "source_name", "") or self.tr("taskmgr.title")
        note = (
            getattr(item, "reminder_note", "")
            or getattr(item, "content", "")
            or self.tr("stage.no_note")
        )
        subtitle = self.tr("stage.subtitle", step=step, name=name)
        body = str(note)
        if paused > 0:
            body += self.tr("stage.paused_related", n=paused)
        show_stage_reminder(
            self,
            tr=self.tr,
            title=self.tr("stage.title_wa"),
            subtitle=subtitle,
            body=body,
        )

    def alert_callback(self, payload: object) -> None:
        self.presenter.emit_alert(payload)

    def reminder_callback(self, *payload: object) -> None:
        self.presenter.emit_reminder(*payload)

    def closeEvent(self, event) -> None:
        self.presenter.detach()
        super().closeEvent(event)


def _wa_alert_remark(contacts: Any, data: dict) -> str:
    chat_key = str(data.get("chat_key") or "").strip()
    chat_jid = str(data.get("chat_jid") or "").strip()
    chat_id = str(data.get("chat_id") or "").strip()
    keys = {value for value in (chat_key, chat_jid, chat_id) if value}
    if not keys:
        return ""
    for contact in contacts or ():
        remark = str(getattr(contact, "remark", "") or "").strip()
        ref = str(getattr(contact, "chat_ref", "") or "").strip()
        if not remark or not ref:
            continue
        if ref in keys or any(ref in key or key in ref for key in keys):
            return remark
    return ""
