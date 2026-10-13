"""仪表盘 View。"""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ..contracts import ConfigView, Translator


class DashboardPage(QWidget):
    def __init__(self, tr: Translator, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tr = tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.title = QLabel(tr("nav.dash"))
        self.title.setProperty("title", True)
        card = QFrame(self)
        card.setProperty("card", True)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)
        self.alerts = QLabel(tr("dash.today_alerts"))
        self.listen = QLabel()
        self.accounts = QLabel()
        self.account_lines = QLabel()
        self.account_lines.setWordWrap(True)
        self.account_lines.setProperty("muted", True)
        card_layout.addWidget(self.alerts)
        card_layout.addWidget(self.listen)
        card_layout.addWidget(self.accounts)
        card_layout.addWidget(self.account_lines)
        layout.addWidget(self.title)
        layout.addWidget(card)
        layout.addStretch(1)

    def set_config(self, config: ConfigView) -> None:
        try:
            from stats import today_alert_count

            count = today_alert_count()
        except Exception:
            count = 0
        self.alerts.setText(self.tr("dash.today_count", n=count))
        online = sum(account.online for account in config.accounts)
        listen_parts = [
            self.tr("dash.listen_on" if config.listening_enabled else "dash.listen_off"),
            self.tr("dash.wa_connected" if online > 0 else "dash.wa_disconnected"),
        ]
        if config.listening_enabled and online > 0:
            listen_parts.append(self.tr("dash.listening_active"))
        elif config.listening_enabled:
            listen_parts.append(self.tr("dash.listen_on_disconnected"))
        self.listen.setText("  ·  ".join(listen_parts))
        self.accounts.setText(self.tr(
            "dash.accounts_online", n=online, total=len(config.accounts)
        ))
        lines = []
        for account in config.accounts:
            if account.online:
                status = self.tr("acct.connected")
            else:
                status = self.tr("acct.logged_in_disconnected")
            lines.append(
                self.tr(
                    "dash.account_line",
                    id=account.account_id,
                    status=status,
                    enabled=self.tr(
                        "dash.enabled" if account.enabled else "dash.disabled"
                    ),
                )
            )
        self.account_lines.setText(
            "\n".join(lines) or self.tr("dash.no_accounts_configured")
        )
