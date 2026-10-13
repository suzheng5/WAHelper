"""Qt 许可证激活窗口；不创建 Tk 根窗口。"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from license_service import activate, check_license, get_machine_id
from .common.theme import COLORS, style_button


class ActivationDialog(QDialog):
    activation_finished = Signal(bool, str)

    def __init__(self, tr: Callable[..., str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tr = tr
        self.activated = False
        self.setWindowTitle(str(tr("activation.title")))
        self.setMinimumWidth(500)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(12)
        title = QLabel(str(tr("activation.brand")), self)
        title.setObjectName("shellBrand")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        hint = QLabel(str(tr("activation.hint")), self)
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        layout.addWidget(title)
        layout.addWidget(hint)

        form = QFormLayout()
        self.machine_id = QLineEdit(get_machine_id(), self)
        self.machine_id.setReadOnly(True)
        machine_row = QWidget(self)
        machine_layout = QVBoxLayout(machine_row)
        machine_layout.setContentsMargins(0, 0, 0, 0)
        machine_layout.setSpacing(8)
        machine_layout.addWidget(self.machine_id)
        copy_button = QPushButton(str(tr("common.copy")), machine_row)
        style_button(copy_button, "ghost")
        copy_button.clicked.connect(self._copy_machine_id)
        machine_layout.addWidget(copy_button)
        form.addRow(str(tr("activation.machine_id")), machine_row)

        self.code = QLineEdit(self)
        self.code.setPlaceholderText(str(tr("activation.code_ph")))
        self.code.returnPressed.connect(self._activate)
        form.addRow(str(tr("activation.code")), self.code)
        layout.addLayout(form)

        self.status = QLabel("", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.buttons = QDialogButtonBox(self)
        self.activate_button = self.buttons.addButton(
            str(tr("activation.activate")), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.exit_button = self.buttons.addButton(
            str(tr("activation.exit")), QDialogButtonBox.ButtonRole.RejectRole
        )
        style_button(self.activate_button, "primary")
        style_button(self.exit_button, "ghost")
        self.activate_button.clicked.connect(self._activate)
        self.exit_button.clicked.connect(self.reject)
        layout.addWidget(self.buttons)
        self.activation_finished.connect(self._finish_activation)

    def _copy_machine_id(self) -> None:
        QApplication.clipboard().setText(self.machine_id.text())
        self.status.setText(str(self._tr("common.copied")))

    def _activate(self) -> None:
        code = self.code.text().strip()
        if not code:
            self.status.setText(str(self._tr("activation.enter_code")))
            return
        self.activate_button.setEnabled(False)
        self.activate_button.setText(str(self._tr("activation.verifying")))
        threading.Thread(
            target=lambda: self.activation_finished.emit(*activate(code)),
            name="qt-license-activate",
            daemon=True,
        ).start()

    def _finish_activation(self, ok: bool, message: str) -> None:
        self.status.setText(message)
        self.status.setStyleSheet(
            f"color: {COLORS['success']}; font-weight: 600;"
            if ok
            else f"color: {COLORS['danger']}; font-weight: 600;"
        )
        self.activate_button.setEnabled(not ok)
        self.activate_button.setText(str(self._tr("activation.activate")))
        if ok:
            self.activated = True
            self.accept()


def ensure_activated_qt(tr: Callable[..., str]) -> bool:
    valid, _message, _expires = check_license()
    if valid:
        return True
    dialog = ActivationDialog(tr)
    dialog.exec()
    return dialog.activated
