"""离屏验证真实格式加载、1000 条筛选和零行控件。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from .localization import assert_locale_parity
from .records import load_task_records
from .window import TaskManagerWindow


def _write_fixture(root: Path) -> None:
    (root / "whatsapp" / "data").mkdir(parents=True)
    (root / "telegram" / "data").mkdir(parents=True)
    wa_job = {
        "id": "wa-1",
        "enabled": True,
        "state": "running",
        "source_name": "wa.txt",
        "chat_entry_ids": ["wa-group"],
        "cursor": 3,
        "rows": [{"content": str(index)} for index in range(20)],
    }
    tg_job = {
        "id": "tg-1",
        "enabled": True,
        "state": "paused",
        "pause_reason": "manual",
        "source_name": "tg.txt",
        "chat_ids": ["-10001"],
        "cursor": 8,
        "items": [{"content": str(index)} for index in range(30)],
    }
    (root / "whatsapp" / "data" / "schedule2.json").write_text(
        json.dumps([wa_job], ensure_ascii=False), encoding="utf-8"
    )
    (root / "telegram" / "data" / "schedules.json").write_text(
        json.dumps({"jobs": [tg_job]}, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    assert_locale_parity()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _write_fixture(root)
        records = load_task_records(root)
        assert [record.platform for record in records] == ["WA", "TG"]

        app = QApplication.instance() or QApplication([])
        window = TaskManagerWindow(data_root=root, stress_count=1000, language="zh")
        window.show()
        for _ in range(5):
            app.processEvents()

        assert window.source_model.rowCount() == 1000
        assert window.proxy_model.rowCount() == 1000
        for row in (0, 499, 999):
            assert window.task_view.indexWidget(window.proxy_model.index(row, 0)) is None

        window.task_view.scrollTo(window.proxy_model.index(999, 0))
        for _ in range(5):
            app.processEvents()
        child_widgets = window.task_view.findChildren(QWidget)
        assert len(child_widgets) < 20, len(child_widgets)
        window.close()
        app.processEvents()

    print("PASS: 1000 tasks use model/delegate with zero per-row widgets")


if __name__ == "__main__":
    main()
