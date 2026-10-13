"""监听规则 View。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ....common.dialogs import show_message
from ....common.lang_controls import add_language_controls
from ....common.theme import style_button
from ....services.task_confirmations import audit_status_label
from ..contracts import ConfigView, Translator
from ..presenter import WaPresenter


class RulesPage(QWidget):
    def __init__(self, presenter: WaPresenter, tr: Translator, parent=None) -> None:
        super().__init__(parent)
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel(tr("rules.title"))
        title.setProperty("title", True)
        layout.addWidget(title)
        form = QFormLayout()
        self.listening = QCheckBox(tr("rules.enable_listen"))
        self.popup = QCheckBox(tr("rules.stage_popup"))
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 86400)
        self.rate.setSuffix(" " + tr("rules.rate_limit_ph"))
        form.addRow(self.listening)
        form.addRow(self.popup)
        form.addRow(tr("rules.rate_limit"), self.rate)
        add_language_controls(
            form,
            tr=tr,
            parent=self,
            on_saved=lambda text: show_message(
                self, tr, tr("rules.lang_label"), text
            ),
        )
        layout.addLayout(form)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        save = QPushButton(tr("common.save"))
        style_button(save, "primary")
        save.clicked.connect(self._save)
        sync = QPushButton(tr("rules.sync_btn"))
        style_button(sync, "accent")
        sync.clicked.connect(presenter.sync_last_schedule)
        audit = QPushButton(tr("rules.audit_btn"))
        style_button(audit, "default")
        audit.clicked.connect(presenter.audit)
        actions.addWidget(save)
        actions.addWidget(sync)
        actions.addWidget(audit)
        actions.addStretch(1)
        layout.addLayout(actions)
        hint = QLabel(tr("rules.audit_hint"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        sync_hint = QLabel(tr("rules.sync_hint"))
        sync_hint.setWordWrap(True)
        sync_hint.setProperty("muted", True)
        self._audit_label = QLabel(tr("qt.tg.audit_pending"))
        self._audit_label.setWordWrap(True)
        layout.addWidget(sync_hint)
        layout.addWidget(hint)
        layout.addWidget(self._audit_label)
        layout.addStretch(1)
        presenter.config_changed.connect(self.set_config)
        presenter.audit_finished.connect(self._show_audit)

    def set_config(self, config: ConfigView) -> None:
        self.listening.setChecked(config.listening_enabled)
        self.popup.setChecked(config.stage_reminder_popup_enabled)
        self.rate.setValue(config.rate_limit_seconds)

    def _save(self) -> None:
        self.presenter.save_rules(
            self.listening.isChecked(), self.popup.isChecked(), self.rate.value()
        )

    def _show_audit(self, result: object) -> None:
        from ....services.task_confirmations import audit_status_value

        if not isinstance(result, dict) or not result:
            self._audit_label.setText(self.tr("qt.tg.audit_empty"))
            return
        parts = []
        for entry_id, row in result.items():
            value = audit_status_value(row)
            if value in ("", "skip"):
                continue
            detail = str(getattr(row, "detail", "") or "")
            label = audit_status_label(self.tr, value, detail) or value
            parts.append(
                self.tr("qt.tg.audit_row", entry_id=entry_id, status=label)
            )
        self._audit_label.setText(
            "\n".join(parts) or self.tr("log.audit_no_targets")
        )
