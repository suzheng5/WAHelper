"""离屏 smoke：不导入 Telethon 核心、不连接 Telegram。"""
from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from .panel import TgPanel
from .presenter import TgPresenter
from .runtime import DataRootNotConfigured, load_tg_modules


@dataclass
class Account:
    id: str
    session_name: str
    enabled: bool = True
    phone: str = ""


@dataclass
class Address:
    id: str
    remark: str
    chat_ref: str
    watch_user: str = ""
    listen_enabled: bool = True
    owner_account_id: str = ""
    last_schedule_source_name: str = ""
    invite_link: str = ""


@dataclass
class Config:
    api_id: int = 0
    api_hash: str = ""
    accounts: list[Any] = field(default_factory=list)
    address_book: list[Any] = field(default_factory=list)
    listening_enabled: bool = True
    rate_limit_seconds: float = 10.0


@dataclass
class Job:
    id: str
    source_name: str = "demo.txt"
    state: str = "paused"
    cursor: int = 0
    items: list[Any] = field(default_factory=lambda: [object()])

    def item_count(self) -> int:
        return len(self.items)

    @staticmethod
    def new(_chats: list[int], source: str, items: list[Any],
            _entries: list[str], **_kwargs: Any) -> "Job":
        return Job("job-1", Path(source).name, items=items)


class FakeListener:
    def __init__(self) -> None:
        self.read_tracker = None

    def start(self, _cfg: Any, callback: Any) -> None:
        self.callback = callback

    def stop(self) -> None:
        pass


class FakeRunner:
    def __init__(self) -> None:
        self.jobs: list[Job] = []

    def bind_read_tracker(self, _tracker: Any) -> None:
        pass

    def set_reminder_callback(self, callback: Any) -> None:
        self.reminder = callback

    def start(self, _cfg: Any) -> None:
        pass

    def stop(self) -> None:
        pass

    def pause_job(self, _job_id: str) -> bool:
        return True

    def resume_job(self, _job_id: str) -> bool:
        return True

    def resume_all_jobs(self) -> int:
        return len(self.jobs)


class FakeCoordinator:
    def __init__(self, _listener: Any, _runner: Any) -> None:
        self.running = False

    def start(self, _cfg: Any) -> bool:
        self.running = True
        return True

    def stop(self, *_args: Any, **_kwargs: Any) -> bool:
        self.running = False
        return True

    def is_running(self) -> bool:
        return self.running

    def apply_config_hot(self, _cfg: Any) -> None:
        pass

    def request_watch_membership_audit(self, _cfg: Any, done: Any) -> bool:
        done({})
        return True

    def request_bulk_image_send(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


def fake_modules() -> Any:
    cfg = Config()
    jobs: list[Job] = []
    config_mod = SimpleNamespace(
        load_config=lambda: cfg,
        save_config=lambda _cfg: None,
        Account=Account,
        AddressEntry=Address,
        parse_chat_ref_input=lambda value: value or (_ for _ in ()).throw(
            ValueError("empty")
        ),
        parse_watch_user_input=lambda value: value,
        chat_ref_to_optional_int=lambda value: int(value)
        if str(value).lstrip("-").isdigit() else None,
        apply_last_schedule_for_jobs=lambda *_args: None,
    )
    scheduler_mod = SimpleNamespace(
        ScheduleRunner=FakeRunner,
        ScheduledJob=Job,
        load_jobs=lambda **_kwargs: jobs,
        save_jobs=lambda value: jobs.__setitem__(slice(None), value),
        save_jobs_patch=lambda _value: None,
    )
    listeners: list[Any] = []
    logger = SimpleNamespace(
        add_memory_listener=lambda cb: listeners.append(cb),
        remove_memory_listener=lambda cb: listeners.remove(cb),
        get_recent_lines=lambda: [],
    )
    return SimpleNamespace(
        config=config_mod,
        coordinator=SimpleNamespace(TelethonCoordinator=FakeCoordinator),
        auth=SimpleNamespace(),
        listener=SimpleNamespace(ListenerController=FakeListener),
        scheduler=scheduler_mod,
        images=SimpleNamespace(),
        txt_import=SimpleNamespace(
            import_doc_items=lambda *_args, **_kwargs: ([object()], [])
        ),
        folder=SimpleNamespace(
            scan_schedule_folder=lambda _path: (["1.txt"], [])
        ),
        logger=logger,
    )


class OffscreenSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.presenter = TgPresenter(
            modules=fake_modules(),
            tr=lambda key, **kwargs: key.format(**kwargs) if kwargs else key,
        )

    def tearDown(self) -> None:
        self.presenter.close()

    def test_seven_pages_and_injected_task_factory(self) -> None:
        seen: list[bool] = []

        def factory(_presenter: Any, _tr: Any, parent: QWidget) -> QWidget:
            seen.append(True)
            return QLabel("shared", parent)

        panel = TgPanel(
            presenter=self.presenter,
            task_manager_factory=factory,
            tr=lambda key, **kwargs: key.format(**kwargs) if kwargs else key,
        )
        self.assertEqual(panel.nav.count(), 7)
        self.assertEqual(panel.stack.count(), 7)
        self.assertTrue(seen)
        panel.close()

    def test_presenter_crud_and_service_without_network(self) -> None:
        self.presenter.save_api("123", "hash")
        self.presenter.add_account("main", "+100")
        row = self.presenter.add_address(
            "群", "-1001", watch_user="@user", owner_account_id="main",
            invite_link="https://t.me/+invite",
        )
        self.assertEqual(row.owner_account_id, "main")
        self.assertTrue(self.presenter.restart_services())
        self.presenter.save_rules(False, False, 3)
        self.assertFalse(self.presenter.config.listening_enabled)
        self.assertFalse(self.presenter.config.stage_reminder_popup_enabled)

    def test_txt_import_uses_scheduler_model(self) -> None:
        self.presenter.add_account("main")
        row = self.presenter.add_address("群", "-1001")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "job.txt"
            path.write_text("stub", encoding="utf-8")
            jobs = self.presenter.import_txt(str(path), [row.id], (1, 2))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source_name, "job.txt")

    def test_runtime_requires_data_root(self) -> None:
        old = os.environ.pop("TG_HELPER_DATA_ROOT", None)
        try:
            with self.assertRaises(DataRootNotConfigured):
                load_tg_modules()
        finally:
            if old is not None:
                os.environ["TG_HELPER_DATA_ROOT"] = old


if __name__ == "__main__":
    unittest.main()
