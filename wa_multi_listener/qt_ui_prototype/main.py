"""启动独立任务管理原型。"""
from __future__ import annotations

import argparse
import locale
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .localization import assert_locale_parity
from .window import TaskManagerWindow


def _default_data_root() -> Path:
    project = Path(__file__).resolve().parents[1]
    release = project / "dist" / "WAHelper"
    return release if release.exists() else project


def _system_language() -> str:
    language = (locale.getlocale()[0] or "").casefold()
    return "zh" if language.startswith("zh") else "en"


def _dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#10161F"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#DCE4EE"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#10161F"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#19212C"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#DCE4EE"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#19212C"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#DCE4EE"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#2D5F98"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    return palette


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PySide6 task manager prototype")
    parser.add_argument("--data-root", type=Path, default=_default_data_root())
    parser.add_argument("--stress", type=int, default=0, metavar="COUNT")
    parser.add_argument("--lang", choices=("zh", "en"), default=_system_language())
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    assert_locale_parity()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("WAHelper Qt Prototype")
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    window = TaskManagerWindow(
        data_root=args.data_root,
        stress_count=args.stress,
        language=args.lang,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
