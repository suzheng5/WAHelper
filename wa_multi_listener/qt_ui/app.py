"""PySide6 application composition with panel factories as dependencies."""
from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QApplication

from app_version import APP_VERSION
from .common.theme import apply_theme
from .shell import LicenseStatus, MessengerShell, PanelFactory


def ensure_application(argv: Sequence[str] | None = None) -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv) if argv is not None else sys.argv)
    return app


def build_shell(
    *,
    tr: Callable[..., str],
    wa_panel_factory: PanelFactory,
    tg_panel_factory: PanelFactory | None = None,
    title: str | None = None,
    data_directory: str = "",
    license_status: LicenseStatus | None = None,
    on_import_tg: Callable[[str], bool | None] | None = None,
    on_exit: Callable[[], bool | None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
    argv: Sequence[str] | None = None,
) -> tuple[QApplication, MessengerShell]:
    """Create, theme, and wire the shell without importing panel modules."""
    app = ensure_application(argv)
    apply_theme(app)
    window = MessengerShell(
        tr=tr,
        wa_panel_factory=wa_panel_factory,
        tg_panel_factory=tg_panel_factory,
        title=title or f"{tr('app.brand')} {APP_VERSION} {tr('app.title_suffix')}",
        data_directory=data_directory,
        license_status=license_status,
        on_import_tg=on_import_tg,
        on_exit=on_exit,
        on_error=on_error,
    )
    return app, window


def run_app(**kwargs) -> int:
    """Build and run the injected PySide6 application."""
    app, window = build_shell(**kwargs)
    window.show()
    return app.exec()
