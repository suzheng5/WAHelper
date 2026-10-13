"""日志 View：增量实时流。"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ....common.log_view import IncrementalLogView
from ....common.theme import style_button
from ..contracts import Translator
from ..presenter import WaPresenter


class LogsPage(QWidget):
    def __init__(self, presenter: WaPresenter, tr: Translator, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title = QLabel(tr("nav.logs"))
        title.setProperty("title", True)
        layout.addWidget(title)
        refresh = QPushButton(tr("common.refresh_logs"))
        style_button(refresh, "ghost")
        refresh.clicked.connect(presenter.refresh_logs)
        layout.addWidget(refresh)
        self.view = IncrementalLogView(self, max_lines=250)
        layout.addWidget(self.view)
        presenter.logs_changed.connect(self.set_lines)
        presenter.log_line.connect(self.view.append_line)

    def set_lines(self, lines: list[str]) -> None:
        self.view.replace_lines(lines)
