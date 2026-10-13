"""Offscreen smoke：只构建页面并验证配置视图只读，不连接真实账号。"""
from __future__ import annotations

import os
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from .contracts import AccountItem, ConfigView, ContactItem
from .gateway import LegacyWaGateway
from .panel import WaPanel


def tr(key: str, **kwargs) -> str:
    return key.format(**kwargs) if kwargs else key


class FakeGateway:
    def __init__(self) -> None:
        self.view = ConfigView(
            accounts=(AccountItem("main", "15550001", "", True, False),),
            contacts=(ContactItem(
                "c1", "Group A", "123@g.us", "15550002", True,
                "main", "https://chat.whatsapp.com/example", "",
            ),),
            listening_enabled=True,
            stage_reminder_popup_enabled=True,
            rate_limit_seconds=12.0,
        )

    def read_config(self): return self.view
    def task_records(self): return ()
    def recent_logs(self, limit=250): return []
    def add_account(self, *args): pass
    def update_account(self, *args): pass
    def delete_account(self, *args): pass
    def start_qr_login(self, *args, **kwargs): pass
    def add_contact(self, *args): pass
    def update_contact(self, *args, **kwargs): pass
    def delete_contact(self, *args): pass
    def move_contact(self, *args): pass
    def update_rules(self, *args): pass
    def save_and_reload(self): pass
    def request_audit(self, callback): return False
    def request_reconnect_offline(self, callback): return False
    def import_schedule(self, *args): return 0
    def task_action(self, *args, **kwargs): pass


class TaskStub(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.records = ()
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(QLabel("shared task manager"))

    def set_records(self, records) -> None:
        self.records = tuple(records)


class WaPanelSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_builds_seven_pages_with_injected_task_factory(self) -> None:
        calls = []

        def factory(parent, records, actions):
            calls.append((tuple(records), actions))
            return TaskStub(parent)

        panel = WaPanel(FakeGateway(), tr=tr, task_manager_factory=factory)
        self.app.processEvents()
        self.assertEqual(panel.stack.count(), 7)
        self.assertEqual(panel.nav.count(), 7)
        self.assertEqual(len(calls), 1)
        self.assertEqual(panel.presenter.config.accounts[0].account_id, "main")
        panel.close()

    def test_config_projection_is_frozen(self) -> None:
        gateway = LegacyWaGateway.__new__(LegacyWaGateway)
        gateway.coordinator = None
        gateway.cfg = SimpleNamespace(
            accounts=[SimpleNamespace(
                id="main", phone="15550001", proxy="", enabled=True
            )],
            address_book=[SimpleNamespace(
                id="c1", remark="Group A", chat_ref="123@g.us",
                watch_user="15550002", listen_enabled=True,
                owner_account_id="main",
                invite_link="https://chat.whatsapp.com/example",
                last_schedule_source_name="",
            )],
            listening_enabled=True,
            stage_reminder_popup_enabled=True,
            rate_limit_seconds=12.0,
        )
        view = gateway.read_config()
        with self.assertRaises(FrozenInstanceError):
            view.rate_limit_seconds = 1.0
        self.assertEqual(view.contacts[0].invite_link,
                         "https://chat.whatsapp.com/example")


if __name__ == "__main__":
    unittest.main()
