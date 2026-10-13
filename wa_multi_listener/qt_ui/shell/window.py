"""Dependency-injected WhatsApp/Telegram application shell."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeAlias

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..common.file_dialogs import pick_folder
from ..common.theme import COLORS, style_button

Translator: TypeAlias = Callable[..., str]


@dataclass(slots=True)
class PanelMount:
    widget: QWidget
    shutdown: Callable[[], None] | None = None


PanelFactory: TypeAlias = Callable[[QWidget], QWidget | PanelMount]


@dataclass(frozen=True, slots=True)
class LicenseStatus:
    active: bool
    text: str


class MessengerShell(QMainWindow):
    """Main window with lazy WA/TG dependency-injected panels."""

    def __init__(
        self,
        *,
        tr: Translator,
        wa_panel_factory: PanelFactory,
        tg_panel_factory: PanelFactory | None = None,
        title: str,
        data_directory: str = "",
        license_status: LicenseStatus | None = None,
        on_import_tg: Callable[[str], bool | None] | None = None,
        on_exit: Callable[[], bool | None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tr = tr
        self._wa_factory = wa_panel_factory
        self._tg_factory = tg_panel_factory
        self._on_import_tg = on_import_tg
        self._on_exit = on_exit
        self._on_error = on_error
        self._wa_mount: PanelMount | None = None
        self._tg_mount: PanelMount | None = None
        self._closing = False
        self.setWindowTitle(title)
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self._build_ui(data_directory, license_status)
        # 默认 Telegram：避免启动即加载 neonize（多账号时易堆损坏闪退）
        if self._tg_factory is not None and self.tabs.count() > 1:
            self.tabs.setCurrentIndex(1)
            # setCurrentIndex 会触发 _on_tab_changed → ensure_tg_mounted，勿重复调度

    def _build_ui(
        self,
        data_directory: str,
        license_status: LicenseStatus | None,
    ) -> None:
        root = QWidget(self)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)
        chrome = QFrame(root)
        chrome.setObjectName("shellChrome")
        chrome_row = QHBoxLayout(chrome)
        chrome_row.setContentsMargins(14, 10, 14, 10)
        chrome_row.setSpacing(12)
        brand = QLabel(str(self._tr("app.brand")), chrome)
        brand.setObjectName("shellBrand")
        chrome_row.addWidget(brand)
        chrome_row.addStretch(1)
        self.license_label = QLabel(chrome)
        self.license_label.setObjectName("shellLicense")
        if license_status is not None:
            self.set_license_status(license_status)
        else:
            self.license_label.hide()
        chrome_row.addWidget(self.license_label)
        self.data_label = QLabel(chrome)
        self.data_label.setProperty("muted", True)
        self.data_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        if data_directory:
            self.set_data_directory(data_directory)
        else:
            self.data_label.hide()
        chrome_row.addWidget(self.data_label)
        if self._on_import_tg is not None:
            import_button = QPushButton(str(self._tr("shell.import_tg")), chrome)
            style_button(import_button, "ghost")
            import_button.clicked.connect(self._import_tg)
            chrome_row.addWidget(import_button)
        outer.addWidget(chrome)
        self.tabs = QTabWidget(root)
        self.wa_container = QWidget(self.tabs)
        self.tg_container = QWidget(self.tabs)
        self._set_container_layout(self.wa_container)
        self._set_container_layout(self.tg_container)
        self.tabs.addTab(self.wa_container, str(self._tr("shell.tab_wa")))
        self.tabs.addTab(self.tg_container, str(self._tr("shell.tab_tg")))
        self.tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self.tabs, 1)
        self.setCentralWidget(root)

    def set_data_directory(self, path: str) -> None:
        self.data_label.setText(str(self._tr("shell.data_dir", path=path)))
        self.data_label.setVisible(bool(path))

    def set_license_status(self, status: LicenseStatus) -> None:
        self.license_label.setText(status.text)
        color = COLORS["success"] if status.active else COLORS["danger"]
        soft = COLORS["accent_soft"] if status.active else COLORS["danger_soft"]
        self.license_label.setStyleSheet(
            f"color: {color}; background: {soft}; border: 1px solid {color};"
            " padding: 4px 10px; border-radius: 999px; font-weight: 600;"
        )
        self.license_label.show()

    @staticmethod
    def _set_container_layout(container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

    def _normalize_mount(self, result: QWidget | PanelMount) -> PanelMount:
        if isinstance(result, PanelMount):
            return result
        if not isinstance(result, QWidget):
            raise TypeError(str(self._tr("common.unknown_error")))
        return PanelMount(result)

    def _mount_panel(
        self,
        factory: PanelFactory,
        container: QWidget,
    ) -> PanelMount:
        mount = self._normalize_mount(factory(container))
        mount.widget.setParent(container)
        container.layout().addWidget(mount.widget)
        return mount

    def _mount_wa(self) -> None:
        if self._wa_mount is not None:
            return
        try:
            self._wa_mount = self._mount_panel(self._wa_factory, self.wa_container)
        except BaseException as exc:
            self._show_mount_error(self.wa_container, exc, "common.unknown_error")

    def _on_tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.wa_container:
            QTimer.singleShot(0, self._mount_wa)
        elif widget is self.tg_container:
            QTimer.singleShot(0, self.ensure_tg_mounted)

    def ensure_tg_mounted(self) -> None:
        if self._tg_mount is not None or self._tg_factory is None:
            return
        try:
            self._tg_mount = self._mount_panel(self._tg_factory, self.tg_container)
        except BaseException as exc:
            self._show_mount_error(self.tg_container, exc, "shell.tg_load_fail")

    def reload_tg(self) -> None:
        self._shutdown_mount(self._tg_mount)
        self._tg_mount = None
        self._clear_container(self.tg_container)
        if self.tabs.currentWidget() is self.tg_container:
            self.ensure_tg_mounted()

    def _import_tg(self) -> None:
        if self._on_import_tg is None:
            return
        path = pick_folder(
            self,
            tr=self._tr,
            title=str(self._tr("shell.import_dir_title")),
            store_key="tg_import",
        )
        if path and self._on_import_tg(path):
            self.reload_tg()

    def _show_mount_error(
        self,
        container: QWidget,
        exc: BaseException,
        title_key: str,
    ) -> None:
        self._clear_container(container)
        label = QLabel(
            f"{self._tr(title_key)}\n{exc}",
            container,
        )
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {COLORS['danger']};")
        container.layout().addWidget(label)
        if self._on_error:
            self._on_error(exc)

    @staticmethod
    def _clear_container(container: QWidget) -> None:
        layout = container.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @staticmethod
    def _shutdown_mount(mount: PanelMount | None) -> None:
        if mount and mount.shutdown:
            mount.shutdown()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        if self._on_exit is not None and self._on_exit() is False:
            event.ignore()
            return
        self._closing = True
        self.setWindowTitle(f"{self.windowTitle()} …")
        # WA / TG 并行停服，总等待封顶约 3 秒（随后进程强制退出）
        import threading
        import time

        errors: list[BaseException] = []

        def _run(mount: PanelMount | None) -> None:
            try:
                self._shutdown_mount(mount)
            except BaseException as exc:
                errors.append(exc)

        workers = [
            threading.Thread(target=_run, args=(mount,), daemon=True)
            for mount in (self._tg_mount, self._wa_mount)
            if mount is not None
        ]
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + 3.0
        for worker in workers:
            remain = deadline - time.monotonic()
            worker.join(timeout=max(0.05, remain))
        for exc in errors:
            if self._on_error:
                self._on_error(exc)
        event.accept()
