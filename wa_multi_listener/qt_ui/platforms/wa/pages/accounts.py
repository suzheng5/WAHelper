"""账号管理 View。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ....common.column_widths import bind_resizable_columns
from ....common.qr_image import qr_payload_to_qimage
from ....common.theme import style_button
from ..contracts import ConfigView, Translator
from ..presenter import WaPresenter


class AccountsPage(QWidget):
    def __init__(self, presenter: WaPresenter, tr: Translator, parent=None) -> None:
        super().__init__(parent)
        self.presenter, self.tr = presenter, tr
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel(tr("acct.title"))
        title.setProperty("title", True)
        layout.addWidget(title)
        hint = QLabel(tr("acct.wa_hint") + tr("acct.wa_proxy_hint"))
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(hint)
        form = QHBoxLayout()
        form.setSpacing(8)
        self.account_id = QLineEdit()
        self.account_id.setPlaceholderText(tr("acct.id_ph"))
        self.phone = QLineEdit()
        self.phone.setPlaceholderText(tr("acct.phone_ph"))
        self.proxy = QLineEdit()
        self.proxy.setPlaceholderText(tr("acct.proxy_ph"))
        add = QPushButton(tr("acct.add"))
        style_button(add, "primary")
        add.clicked.connect(self._add)
        for widget in (self.account_id, self.phone, self.proxy, add):
            form.addWidget(widget)
        layout.addLayout(form)
        self.table = QTableWidget(0, 6)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setShowGrid(False)
        self.table.setHorizontalHeaderLabels([
            tr("acct.id_ph"), tr("acct.phone_ph"), tr("acct.proxy_inline_ph"),
            tr("dash.enabled"), tr("acct.login"), tr("common.delete"),
        ])
        bind_resizable_columns(
            self.table,
            "wa.accounts",
            [171, 145, 479, 48, 88, 72],
        )
        layout.addWidget(self.table)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        reconnect = QPushButton(tr("acct.reconnect_offline"))
        style_button(reconnect, "accent")
        reconnect.clicked.connect(presenter.reconnect_offline_accounts)
        actions.addWidget(reconnect)
        actions.addStretch(1)
        layout.addLayout(actions)
        reconnect_hint = QLabel(tr("acct.reconnect_offline_hint"))
        reconnect_hint.setWordWrap(True)
        reconnect_hint.setProperty("muted", True)
        layout.addWidget(reconnect_hint)
        presenter.config_changed.connect(self.set_config)
        presenter.qr_received.connect(self._show_qr)
        presenter.login_status.connect(self._on_login_status)
        presenter.login_finished.connect(self._on_login_finished)
        self._qr_dialog = None
        self._qr_status = None
        self._qr_label = None
        self._qr_account_id = ""

    def _add(self) -> None:
        self.presenter.add_account(
            self.account_id.text(), self.phone.text(), self.proxy.text()
        )

    def set_config(self, config: ConfigView) -> None:
        self.table.setRowCount(len(config.accounts))
        for row, account in enumerate(config.accounts):
            self.table.setItem(row, 0, QTableWidgetItem(account.account_id))
            self.table.setItem(row, 1, QTableWidgetItem(account.phone))
            proxy = QLineEdit(account.proxy)
            proxy.setMinimumHeight(32)
            proxy.setPlaceholderText(self.tr("acct.proxy_inline_ph"))
            enabled = QCheckBox()
            enabled.setChecked(account.enabled)
            save = QPushButton(self.tr("acct.save_proxy"))
            style_button(save, "ghost", compact=True)
            save.clicked.connect(
                lambda _=False, aid=account.account_id, e=enabled, p=proxy:
                self.presenter.update_account(aid, e.isChecked(), p.text())
            )
            login = QPushButton(
                self.tr("acct.connected") if account.online else self.tr("acct.login")
            )
            style_button(login, "accent")
            login.setMinimumWidth(76)
            login.setMinimumHeight(32)
            login.clicked.connect(
                lambda _=False, aid=account.account_id: self.presenter.login_account(aid)
            )
            delete = QPushButton(self.tr("common.delete"))
            style_button(delete, "danger")
            delete.setMinimumWidth(64)
            delete.setMinimumHeight(32)
            delete.clicked.connect(
                lambda _=False, aid=account.account_id: self.presenter.delete_account(aid)
            )
            proxy_box = QWidget()
            proxy_layout = QHBoxLayout(proxy_box)
            proxy_layout.setContentsMargins(4, 4, 4, 4)
            proxy_layout.setSpacing(6)
            proxy_layout.addWidget(proxy, 1)
            proxy_layout.addWidget(save)
            self.table.setCellWidget(row, 2, proxy_box)
            self.table.setCellWidget(row, 3, enabled)
            self.table.setCellWidget(row, 4, login)
            self.table.setCellWidget(row, 5, delete)
            self.table.setRowHeight(row, 46)

    def _ensure_login_dialog(self, account_id: str) -> None:
        if self._qr_dialog is not None:
            if account_id:
                self._qr_dialog.setWindowTitle(f"{self.tr('acct.login')} · {account_id}")
            self._qr_dialog.show()
            self._qr_dialog.raise_()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{self.tr('acct.login')} · {account_id}")
        box = QVBoxLayout(dialog)
        label = QLabel(self.tr("qr.status_wait_qr"))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(360, 360)
        status = QLabel(self.tr("qr.status_prepare"))
        status.setWordWrap(True)
        close = QPushButton(self.tr("common.cancel"))
        style_button(close, "ghost")
        close.clicked.connect(dialog.reject)
        box.addWidget(label)
        box.addWidget(status)
        box.addWidget(close)
        dialog.resize(420, 500)
        self._qr_dialog = dialog
        self._qr_label = label
        self._qr_status = status
        self._qr_account_id = account_id
        dialog.finished.connect(self._on_qr_finished)
        dialog.show()
        dialog.raise_()

    def _show_qr(self, account_id: str, data: bytes) -> None:
        self._ensure_login_dialog(account_id)
        image = qr_payload_to_qimage(data)
        if image.isNull():
            if self._qr_status is not None:
                self._qr_status.setText(f"{account_id}: {self.tr('qr.gen_fail')}")
            return
        self._qr_account_id = account_id
        self._qr_label.setPixmap(QPixmap.fromImage(image).scaled(
            360, 360, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        if self._qr_status is not None:
            self._qr_status.setText(f"{account_id}: {self.tr('qr.status_scan')}")
        self._qr_dialog.setWindowTitle(f"{self.tr('acct.login')} · {account_id}")
        self._qr_dialog.show()
        self._qr_dialog.raise_()

    def _on_login_status(self, account_id: str, text: str) -> None:
        self._ensure_login_dialog(account_id)
        if self._qr_status is not None:
            self._qr_status.setText(f"{account_id}: {text}")

    def _on_login_finished(self, account_id: str, ok: bool) -> None:
        if self._qr_dialog is None:
            return
        if account_id and self._qr_account_id and account_id != self._qr_account_id:
            return
        if ok:
            self._qr_dialog.accept()
        elif self._qr_status is not None:
            self._qr_status.setText(f"{account_id}: {self.tr('qr.login_fail')}")

    def _on_qr_finished(self, result: int) -> None:
        if result != int(QDialog.DialogCode.Accepted):
            self.presenter.cancel_login()
        self._clear_qr()

    def _clear_qr(self, *_args) -> None:
        self._qr_dialog = None
        self._qr_status = None
        self._qr_label = None
        self._qr_account_id = ""
