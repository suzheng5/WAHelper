"""仪表盘、账号和日志页面。"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...common.column_widths import bind_resizable_columns
from ...common.dialogs import ask_text
from ...common.log_view import IncrementalLogView
from .common import DataTable, Translator, action_row, button, call_guarded, page_title


class DashboardPage(QWidget):
    def __init__(self, presenter: Any, tr: Translator) -> None:
        super().__init__()
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(page_title(tr, "nav.dash"))
        card = QFrame(self)
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)
        self.alerts = QLabel()
        self.state = QLabel()
        self.listen = QLabel()
        self.counts = QLabel()
        card_layout.addWidget(self.alerts)
        card_layout.addWidget(self.state)
        card_layout.addWidget(self.listen)
        card_layout.addWidget(self.counts)
        layout.addWidget(card)
        layout.addWidget(action_row(
            button("qt.tg.restart_services", tr, self.presenter.restart_services_async, kind="accent"),
            button("qt.tg.stop_services", tr, self._stop, kind="danger"),
        ))
        layout.addStretch(1)
        presenter.changed.connect(self.refresh)
        presenter.status_changed.connect(self.state.setText)
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        cfg = self.presenter.config
        jobs = self.presenter.m.scheduler.load_jobs()
        running = self.presenter.coordinator.is_running()
        try:
            from tg_multi_listener.stats import today_alert_count

            count = today_alert_count()
        except Exception:
            count = 0
        self.alerts.setText(self.tr("dash.today_count", n=count))
        self.state.setText(
            self.tr("qt.tg.service_running" if running else "qt.tg.service_stopped")
        )
        listen_parts = [
            self.tr("dash.listen_on" if cfg.listening_enabled else "dash.listen_off"),
            self.tr("dash.tg_connected" if running else "dash.tg_disconnected"),
        ]
        if cfg.listening_enabled and running:
            listen_parts.append(self.tr("dash.listening_active"))
        elif cfg.listening_enabled:
            listen_parts.append(self.tr("dash.listen_on_disconnected_tg"))
        self.listen.setText("  ·  ".join(listen_parts))
        self.counts.setText(
            self.tr(
                "qt.tg.dashboard_counts",
                accounts=len(cfg.accounts),
                contacts=len(cfg.address_book),
                jobs=len(jobs),
            )
        )

    def _stop(self) -> None:
        self.presenter.coordinator.stop()
        self.refresh()


class AccountsPage(QWidget):
    def __init__(self, presenter: Any, tr: Translator) -> None:
        super().__init__()
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.addWidget(page_title(tr, "nav.acct"))
        api_form = QFormLayout()
        self.api_id = QLineEdit(str(presenter.config.api_id or ""))
        self.api_hash = QLineEdit(presenter.config.api_hash)
        self.api_hash.setEchoMode(QLineEdit.Password)
        api_form.addRow(tr("qt.tg.api_id"), self.api_id)
        api_form.addRow(tr("qt.tg.api_hash"), self.api_hash)
        layout.addLayout(api_form)
        layout.addWidget(button("qt.tg.save_api", tr, self._save_api, kind="primary"))
        add_row = QHBoxLayout()
        self.account_id, self.phone = QLineEdit(), QLineEdit()
        self.account_id.setPlaceholderText(tr("acct.id_ph"))
        self.phone.setPlaceholderText(tr("acct.phone_ph"))
        self.account_id.setMaximumWidth(140)
        self.phone.setMaximumWidth(160)
        add_row.addWidget(self.account_id)
        add_row.addWidget(self.phone)
        add_row.addWidget(button("common.add", tr, self._add, kind="primary"))
        layout.addLayout(add_row)
        self.table = DataTable(["acct.id_ph", "acct.phone_ph", "dash.enabled"], tr)
        bind_resizable_columns(self.table, "tg.accounts", [463, 488, 53])
        layout.addWidget(self.table)
        layout.addWidget(action_row(
            button("acct.login", tr, self._login, kind="accent"),
            button("acct.reconnect_offline", tr, presenter.reconnect_offline_accounts, kind="accent"),
            button("acct.rename", tr, self._rename),
            button("common.delete", tr, self._remove, kind="danger"),
            button("qt.tg.restart_services", tr, presenter.restart_services_async),
        ))
        hint = QLabel(tr("acct.reconnect_offline_hint"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)
        login_hint = QLabel(tr("login.tg.batch_hint"))
        login_hint.setWordWrap(True)
        login_hint.setProperty("muted", True)
        layout.addWidget(login_hint)
        presenter.changed.connect(self.refresh)
        presenter.status_changed.connect(lambda _=None: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        rows = self.presenter.config.accounts
        online = set()
        try:
            online = set(self.presenter.connected_account_ids())
        except Exception:
            online = set()
        filled = []
        for row in rows:
            enabled = self.tr(
                "dash.enabled" if getattr(row, "enabled", True) else "dash.disabled"
            )
            link = self.tr(
                "acct.connected" if row.id in online else "acct.logged_in_disconnected"
            )
            filled.append([row.id, row.phone, f"{enabled} · {link}"])
        self.table.fill(filled, [row.id for row in rows])

    def _save_api(self) -> None:
        call_guarded(
            self, self.tr,
            lambda: self.presenter.save_api(self.api_id.text(), self.api_hash.text()),
        )

    def _add(self) -> None:
        result = call_guarded(
            self, self.tr,
            lambda: self.presenter.add_account(
                self.account_id.text(), self.phone.text()
            ),
        )
        if result is not None:
            self.account_id.clear()
            self.phone.clear()

    def _login(self) -> None:
        account_id = self.table.selected_id()
        if account_id:
            call_guarded(
                self, self.tr,
                lambda: self.presenter.login(self, account_id),
            )

    def _rename(self) -> None:
        account_id = self.table.selected_id()
        if not account_id:
            return
        new_id = ask_text(
            self,
            self.tr,
            self.tr("acct.rename"),
            self.tr("acct.rename_prompt"),
            initial=account_id,
            allow_empty=False,
        )
        if new_id is None:
            return
        call_guarded(
            self,
            self.tr,
            lambda: self.presenter.rename_account(account_id, new_id),
        )

    def _remove(self) -> None:
        account_id = self.table.selected_id()
        if account_id:
            self.presenter.remove_account(account_id)


class LogsPage(QWidget):
    def __init__(self, presenter: Any, tr: Translator) -> None:
        super().__init__()
        self.presenter = presenter
        layout = QVBoxLayout(self)
        layout.addWidget(page_title(tr, "nav.logs_tg"))
        layout.addWidget(button("common.refresh_logs", tr, self._refresh))
        self.view = IncrementalLogView(self, max_lines=250)
        self.view.replace_lines(presenter.recent_logs())
        layout.addWidget(self.view)
        presenter.log_received.connect(self.view.append_line)

    def _refresh(self) -> None:
        self.view.replace_lines(self.presenter.recent_logs())
