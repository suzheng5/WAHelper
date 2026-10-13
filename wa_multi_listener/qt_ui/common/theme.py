"""Shared PySide6 palette and stylesheet."""
from __future__ import annotations

from typing import Final, Literal

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

ButtonKind = Literal["default", "primary", "danger", "ghost", "accent"]

COLORS: Final[dict[str, str]] = {
    "bg": "#0e1218",
    "surface": "#151b24",
    "surface_raised": "#1a2230",
    "card": "#1c2431",
    "card_hover": "#222b3a",
    "border": "#2c3648",
    "border_strong": "#3a4660",
    "text": "#e8eef7",
    "muted": "#8b97ab",
    "accent": "#25d366",
    "accent_hover": "#1fbf5a",
    "accent_pressed": "#18a84e",
    "accent_soft": "#143528",
    "accent_blue": "#3b82f6",
    "accent_blue_hover": "#2563eb",
    "success": "#34d399",
    "danger": "#ef4444",
    "danger_hover": "#dc2626",
    "danger_soft": "#3a1a1a",
    "warning": "#fbbf24",
    "button": "#243044",
    "button_hover": "#2e3c54",
    "button_muted": "#243044",
    "input": "#111822",
    "focus": "#25d366",
    "sidebar": "#121820",
    "nav_selected": "#1a2f24",
    "scroll": "#3a4658",
}

APP_STYLESHEET: Final[str] = f"""
QWidget {{
    background: {COLORS["bg"]};
    color: {COLORS["text"]};
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {COLORS["bg"]};
}}
QFrame[card="true"], QFrame#shellChrome, QFrame#sideNav {{
    background: {COLORS["card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
}}
QLabel[muted="true"] {{
    color: {COLORS["muted"]};
}}
QLabel[title="true"], QLabel#pageTitle {{
    font-size: 18px;
    font-weight: 700;
    color: {COLORS["text"]};
    padding: 2px 0 6px 0;
}}
QLabel#shellBrand {{
    font-size: 18px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QLabel#sideBrand {{
    font-size: 12px;
    font-weight: 700;
}}
QLabel#shellLicense {{
    padding: 4px 10px;
    border-radius: 999px;
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
}}

/* —— Buttons —— */
QPushButton {{
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    background: {COLORS["button"]};
    color: {COLORS["text"]};
    font-weight: 600;
}}
QPushButton:hover {{
    background: {COLORS["button_hover"]};
    border-color: {COLORS["border_strong"]};
}}
QPushButton:pressed {{
    background: {COLORS["surface"]};
}}
QPushButton:disabled {{
    color: {COLORS["muted"]};
    background: {COLORS["surface"]};
    border-color: {COLORS["border"]};
}}
QPushButton[primary="true"] {{
    color: #0b1a12;
    background: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
}}
QPushButton[primary="true"]:hover {{
    background: {COLORS["accent_hover"]};
    border-color: {COLORS["accent_hover"]};
}}
QPushButton[primary="true"]:pressed {{
    background: {COLORS["accent_pressed"]};
}}
QPushButton[accent="true"] {{
    color: #ffffff;
    background: {COLORS["accent_blue"]};
    border-color: {COLORS["accent_blue"]};
}}
QPushButton[accent="true"]:hover {{
    background: {COLORS["accent_blue_hover"]};
}}
QPushButton[danger="true"] {{
    color: #fecaca;
    background: {COLORS["danger_soft"]};
    border-color: #7f1d1d;
}}
QPushButton[danger="true"]:hover {{
    color: #ffffff;
    background: {COLORS["danger"]};
    border-color: {COLORS["danger"]};
}}
QPushButton[ghost="true"] {{
    background: transparent;
    border-color: {COLORS["border"]};
    color: {COLORS["muted"]};
    font-weight: 500;
}}
QPushButton[ghost="true"]:hover {{
    color: {COLORS["text"]};
    background: {COLORS["surface_raised"]};
}}
QPushButton[compact="true"] {{
    min-height: 28px;
    padding: 0 10px;
    font-size: 12px;
    border-radius: 6px;
}}
QPushButton:checked {{
    background: {COLORS["accent_soft"]};
    border-color: {COLORS["accent"]};
    color: {COLORS["accent"]};
}}

/* —— Inputs —— */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background: {COLORS["input"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {COLORS["accent"]};
    selection-color: #0b1a12;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COLORS["focus"]};
}}
QComboBox {{
    min-height: 34px;
    padding: 0 10px;
    background: {COLORS["input"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
}}
QComboBox::drop-down {{
    border: 0;
    width: 28px;
}}
QComboBox QAbstractItemView {{
    background: {COLORS["card"]};
    border: 1px solid {COLORS["border"]};
    selection-background-color: {COLORS["accent_soft"]};
    selection-color: {COLORS["accent"]};
    outline: 0;
    padding: 4px;
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {COLORS["border_strong"]};
    background: {COLORS["input"]};
}}
QCheckBox::indicator:checked {{
    background: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
}}

/* —— Lists / tables —— */
QListWidget, QTableWidget, QTreeWidget {{
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 10px;
    outline: 0;
    padding: 4px;
    alternate-background-color: {COLORS["surface_raised"]};
}}
QListWidget::item, QTableWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}
QListWidget::item:selected, QTableWidget::item:selected {{
    background: {COLORS["accent_soft"]};
    color: {COLORS["accent"]};
}}
QListWidget::item:hover, QTableWidget::item:hover {{
    background: {COLORS["card_hover"]};
}}
QHeaderView::section {{
    background: {COLORS["card"]};
    color: {COLORS["muted"]};
    border: 0;
    border-bottom: 1px solid {COLORS["border"]};
    padding: 8px 10px;
    font-weight: 600;
}}
QTableWidget {{
    gridline-color: {COLORS["border"]};
}}
QTableCornerButton::section {{
    background: {COLORS["card"]};
    border: 0;
}}

/* —— Side navigation —— */
QListWidget#sideNavList {{
    background: transparent;
    border: 0;
    padding: 2px;
    font-size: 12px;
}}
QListWidget#sideNavList::item {{
    min-height: 30px;
    margin: 1px 0;
    padding: 4px 6px;
    border-radius: 6px;
    color: {COLORS["muted"]};
}}
QListWidget#sideNavList::item:hover {{
    background: {COLORS["card_hover"]};
    color: {COLORS["text"]};
}}
QListWidget#sideNavList::item:selected {{
    background: {COLORS["nav_selected"]};
    color: {COLORS["accent"]};
    font-weight: 700;
    border-left: 3px solid {COLORS["accent"]};
}}

/* —— Tabs —— */
QTabWidget::pane {{
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
    background: {COLORS["bg"]};
    top: -1px;
}}
QTabBar::tab {{
    min-width: 120px;
    padding: 10px 20px;
    margin-right: 4px;
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    border-bottom: 0;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    color: {COLORS["muted"]};
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {COLORS["text"]};
    background: {COLORS["card"]};
}}
QTabBar::tab:selected {{
    background: {COLORS["card"]};
    color: {COLORS["accent"]};
    border-color: {COLORS["border"]};
}}

/* —— Scrollbars —— */
QScrollArea {{
    border: 0;
    background: transparent;
}}
QScrollBar:vertical {{
    width: 10px;
    background: transparent;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    min-height: 28px;
    border-radius: 5px;
    background: {COLORS["scroll"]};
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS["border_strong"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    height: 10px;
    background: transparent;
}}
QScrollBar::handle:horizontal {{
    min-width: 28px;
    border-radius: 5px;
    background: {COLORS["scroll"]};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* —— Status / tooltips —— */
QToolTip {{
    background: {COLORS["card"]};
    color: {COLORS["text"]};
    border: 1px solid {COLORS["border"]};
    padding: 6px 8px;
}}
QStatusBar {{
    background: {COLORS["surface"]};
    color: {COLORS["muted"]};
}}
"""


def repolish(widget: QWidget) -> None:
    """Force Qt to re-evaluate dynamic stylesheet properties."""
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def style_button(
    button: QPushButton,
    kind: ButtonKind = "default",
    *,
    compact: bool = False,
) -> QPushButton:
    """Apply a named button variant used by the shared stylesheet."""
    for key in ("primary", "danger", "ghost", "accent"):
        button.setProperty(key, kind == key)
    button.setProperty("compact", compact)
    repolish(button)
    return button


def apply_theme(target: QApplication | QWidget) -> None:
    """Apply the shared dark palette and stylesheet."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["surface_raised"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["button"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#0b1a12"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(COLORS["muted"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["card"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text"]))
    target.setPalette(palette)
    if isinstance(target, QApplication):
        font = QFont("Microsoft YaHei UI", 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        target.setFont(font)
    target.setStyleSheet(APP_STYLESHEET)
