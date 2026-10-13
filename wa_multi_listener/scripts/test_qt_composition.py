"""验证 Qt 组合根、TaskManager 适配和覆盖升级清单。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QWidget

from qt_ui.composition import _tg_task_factory, _wa_task_factory
from qt_ui.task_manager.types import TaskRecord
from scripts.overlay_install import PRESERVE_TOP_LEVEL, REPLACE_TOP_LEVEL, overlay_install, verify_userdata_present


class _FakeActions:
    def toggle_task(self, task_id: str) -> None: ...
    def delete_task(self, task_id: str) -> None: ...
    def next_day_task(self, task_id: str) -> None: ...
    def resume_all(self) -> None: ...
    def next_day_all(self) -> None: ...
    def manual_next_day_mode_changed(self, enabled: bool) -> None: ...
    def delete_all(self) -> None: ...
    def reload_wa_folders(self) -> None: ...
    def send_images(self) -> None: ...
    def send_images_sync(self) -> None: ...


class QtCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_wa_task_factory_uses_replace_records(self) -> None:
        tr = lambda key, **kwargs: key
        factory = _wa_task_factory(tr)
        parent = QWidget()
        presenter = _FakeActions()
        records = [
            TaskRecord("1", "wa", "demo", running=True, enabled=True, status="running")
        ]
        widget = factory(parent, records, presenter)
        self.assertEqual(widget.model.rowCount(), 1)
        widget.replace_records([])
        self.assertEqual(widget.model.rowCount(), 0)

    def test_tg_task_factory_binds_records(self) -> None:
        tr = lambda key, **kwargs: key
        presenter = MagicMock()
        presenter.task_records.return_value = [
            TaskRecord("tg-1", "tg", "demo", running=False, enabled=True, status="paused")
        ]
        parent = QWidget()
        widget = _tg_task_factory(presenter, tr, parent)
        self.assertEqual(widget.model.rowCount(), 1)

    def test_overlay_preserves_userdata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "new"
            target = Path(temp) / "old"
            (source / "_internal").mkdir(parents=True)
            (source / "超群小帮手.exe").write_text("exe", encoding="utf-8")
            (source / "whatsapp").mkdir()
            (source / "whatsapp" / "config.example.json").write_text("{}", encoding="utf-8")
            (target / "whatsapp" / "data").mkdir(parents=True)
            (target / "whatsapp" / "config.json").write_text('{"keep":1}', encoding="utf-8")
            (target / "whatsapp" / "data" / "schedule2.json").write_text("[]", encoding="utf-8")
            (target / "telegram" / "sessions").mkdir(parents=True)
            (target / "ui_locale.json").write_text('{"lang":"zh"}', encoding="utf-8")
            (target / "license_ws.dat").write_text("lic", encoding="utf-8")
            (target / "_internal").mkdir()
            (target / "超群小帮手.exe").write_text("old", encoding="utf-8")

            actions = overlay_install(source, target, backup=True)
            self.assertTrue(any(a.startswith("backup=") for a in actions))
            self.assertEqual((target / "whatsapp" / "config.json").read_text(encoding="utf-8"), '{"keep":1}')
            self.assertEqual((target / "超群小帮手.exe").read_text(encoding="utf-8"), "exe")
            checks = verify_userdata_present(target)
            self.assertTrue(checks["whatsapp"])
            self.assertTrue(checks["telegram"])
            self.assertTrue(checks["ui_locale"])
            self.assertTrue(checks["license"])
            self.assertIn("whatsapp", PRESERVE_TOP_LEVEL)
            self.assertIn("_internal", REPLACE_TOP_LEVEL)


if __name__ == "__main__":
    unittest.main()
