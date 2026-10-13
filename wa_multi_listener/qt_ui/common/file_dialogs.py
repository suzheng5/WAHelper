"""QFileDialog helpers with persistent last-used directories."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QWidget

from .dialogs import choose_button_option

Translator: TypeAlias = Callable[..., str]
IMAGE_EXTENSIONS = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.bmp")


class DialogDirectoryStore:
    """Persist dialog locations without coupling to application config."""

    def __init__(
        self,
        *,
        organization: str = "wa_multi_listener",
        application: str = "qt_ui",
        settings: QSettings | None = None,
    ) -> None:
        self._settings = settings or QSettings(organization, application)

    def get(self, kind: str, fallback: str = "") -> str:
        value = str(self._settings.value(f"dialogs/{kind}", fallback) or "")
        return value if value and Path(value).is_dir() else fallback

    def remember_path(self, kind: str, path: str) -> None:
        selected = Path(path)
        directory = selected if selected.is_dir() else selected.parent
        if directory.is_dir():
            self._settings.setValue(f"dialogs/{kind}", str(directory.resolve()))


_STORE = DialogDirectoryStore()


def pick_images(
    parent: QWidget | None,
    *,
    tr: Translator,
    title: str | None = None,
    initial_dir: str = "",
    store: DialogDirectoryStore = _STORE,
) -> list[str]:
    start = initial_dir or store.get("images", str(Path.home()))
    image_label = str(tr("img.pick_files"))
    all_label = str(tr("picker.all_files"))
    filters = f"{image_label} ({' '.join(IMAGE_EXTENSIONS)});;{all_label} (*)"
    paths, _ = QFileDialog.getOpenFileNames(
        parent,
        title or str(tr("img.pick_files")),
        start,
        filters,
    )
    selected = [str(Path(path).resolve()) for path in paths]
    if selected:
        store.remember_path("images", selected[0])
    return selected


def pick_txt_file(
    parent: QWidget | None,
    *,
    tr: Translator,
    title: str | None = None,
    initial_dir: str = "",
    store: DialogDirectoryStore = _STORE,
) -> str:
    start = initial_dir or store.get("txt", str(Path.home()))
    filters = (
        f"{tr('picker.txt_filter')} (*.txt);;"
        f"{tr('picker.all_files')} (*)"
    )
    path, _ = QFileDialog.getOpenFileName(
        parent,
        title or str(tr("picker.txt_dialog")),
        start,
        filters,
    )
    if path:
        store.remember_path("txt", path)
        return str(Path(path).resolve())
    return ""


def pick_folder(
    parent: QWidget | None,
    *,
    tr: Translator,
    title: str | None = None,
    initial_dir: str = "",
    store_key: str = "folder",
    store: DialogDirectoryStore = _STORE,
) -> str:
    start = initial_dir or store.get(store_key, str(Path.home()))
    path = QFileDialog.getExistingDirectory(
        parent,
        title or str(tr("picker.folder_dialog")),
        start,
        QFileDialog.Option.ShowDirsOnly,
    )
    if path:
        store.remember_path(store_key, path)
        return str(Path(path).resolve())
    return ""


def pick_txt_or_folder(
    parent: QWidget | None,
    *,
    tr: Translator,
    initial_dir: str = "",
    store: DialogDirectoryStore = _STORE,
) -> str:
    choice = choose_button_option(
        parent,
        tr,
        str(tr("picker.title")),
        str(tr("picker.prompt")),
        [str(tr("picker.txt_file")), str(tr("picker.folder"))],
    )
    if choice == 0:
        return pick_txt_file(
            parent,
            tr=tr,
            initial_dir=initial_dir,
            store=store,
        )
    if choice == 1:
        return pick_folder(
            parent,
            tr=tr,
            initial_dir=initial_dir,
            store_key="txt_folder",
            store=store,
        )
    return ""
