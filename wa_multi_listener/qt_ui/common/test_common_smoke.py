"""Minimal offscreen smoke coverage for shared Qt infrastructure."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QLabel, QWidget

from ..app import build_shell
from ..shell import LicenseStatus, PanelMount
from .dialogs import ButtonOptionDialog, ConfirmDialog, MessageDialog, TextInputDialog
from .layouts import FixedActionPage
from .log_view import IncrementalLogView
from .notifications import ReminderWindow


def tr(key: str, **kwargs: object) -> str:
    return key.format(**kwargs)


class CommonSmokeTest(unittest.TestCase):
    def tearDown(self) -> None:
        QCoreApplication.processEvents()

    def test_common_widgets_construct(self) -> None:
        _, shell = build_shell(
            tr=tr,
            wa_panel_factory=lambda parent: QWidget(parent),
            title="smoke",
        )
        page = FixedActionPage(shell)
        page.action_bar.add_button("action", lambda: None, primary=True)
        log = IncrementalLogView(page, max_lines=2)
        log.append_lines(["one", "two", "three"])
        QCoreApplication.processEvents()
        self.assertEqual(log.toPlainText().splitlines(), ["two", "three"])
        dialogs = [
            MessageDialog(shell, tr=tr, title="title", message="message"),
            ConfirmDialog(shell, tr=tr, title="title", message="message"),
            TextInputDialog(shell, tr=tr, title="title", prompt="prompt"),
            ButtonOptionDialog(
                shell,
                tr=tr,
                title="title",
                prompt="prompt",
                options=["option"],
            ),
        ]
        self.assertTrue(all(dialog.isModal() for dialog in dialogs))
        for dialog in dialogs:
            dialog.close()
        shell.close()

    def test_shell_mounts_tg_lazily_and_shuts_down(self) -> None:
        calls: list[str] = []

        def wa_factory(parent: QWidget) -> PanelMount:
            return PanelMount(QLabel("wa", parent), lambda: calls.append("wa_shutdown"))

        def tg_factory(parent: QWidget) -> PanelMount:
            calls.append("tg_mount")
            return PanelMount(QLabel("tg", parent), lambda: calls.append("tg_shutdown"))

        _, shell = build_shell(
            tr=tr,
            wa_panel_factory=wa_factory,
            tg_panel_factory=tg_factory,
            title="smoke",
            data_directory="data",
            license_status=LicenseStatus(True, "active"),
            on_exit=lambda: calls.append("exit"),
        )
        QCoreApplication.processEvents()
        self.assertNotIn("tg_mount", calls)
        shell.tabs.setCurrentWidget(shell.tg_container)
        QCoreApplication.processEvents()
        self.assertIn("tg_mount", calls)
        shell.close()
        self.assertIn("exit", calls)
        self.assertIn("tg_shutdown", calls)
        self.assertIn("wa_shutdown", calls)
        self.assertLess(calls.index("exit"), calls.index("tg_shutdown"))
        self.assertLess(calls.index("exit"), calls.index("wa_shutdown"))

    def test_reminder_is_non_modal(self) -> None:
        _, shell = build_shell(
            tr=tr,
            wa_panel_factory=lambda parent: QWidget(parent),
            title="smoke",
        )
        reminder = ReminderWindow(
            shell,
            tr=tr,
            title="title",
            heading="heading",
            subtitle="subtitle",
            body="body",
            close_key="close",
        )
        self.assertFalse(reminder.isModal())
        reminder.close()
        shell.close()


if __name__ == "__main__":
    unittest.main()
