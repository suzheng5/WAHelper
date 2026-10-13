"""生产组合根：把 Qt 视图接到现有 WA/TG 业务内核。"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .shell import LicenseStatus, PanelMount
from .task_manager import TaskManagerWidget


def _wa_task_factory(tr: Callable[..., str]):
    def factory(parent, records, presenter):
        widget = TaskManagerWidget(
            actions=presenter,
            tr=tr,
            parent=parent,
            hidden_commands=("reload_wa_folders",),
            refresh_provider=lambda: presenter.gateway.task_records(),
        )
        widget.replace_records(records)
        return widget

    return factory


def _tg_task_factory(presenter, tr, parent=None):
    widget = TaskManagerWidget(
        actions=presenter,
        tr=tr,
        parent=parent,
        hidden_commands=("reload_wa_folders",),
        refresh_provider=presenter.task_records,
    )
    records = presenter.task_records() if hasattr(presenter, "task_records") else ()
    widget.replace_records(records)
    if hasattr(presenter, "tasks_changed"):
        presenter.tasks_changed.connect(widget.replace_records)
    elif hasattr(presenter, "changed"):
        presenter.changed.connect(
            lambda: widget.replace_records(presenter.task_records())
        )
    return widget


def create_wa_panel_factory(tr: Callable[..., str]):
    """创建 WA 后台一次，并由 PanelMount 管理其生命周期。"""

    def factory(parent):
        from listener import ListenerController
        from schedule2_runner import Schedule2Runner, pause_all_schedule2_jobs_on_startup
        from shutdown import shutdown_application
        from wa_coordinator import WaCoordinator

        from .platforms.wa import LegacyWaGateway, WaPanel

        pause_all_schedule2_jobs_on_startup()
        listener = ListenerController()
        runner = Schedule2Runner()
        coordinator = WaCoordinator(listener, runner)
        panel_holder: list[Any] = [None]

        def restart(cfg) -> None:
            coordinator.stop(join_timeout=3.0)
            listener.stop()
            runner.stop()
            panel = panel_holder[0]
            listener.start(cfg, panel.alert_callback)
            runner.set_reminder_callback(panel.reminder_callback)
            runner.start(cfg)
            coordinator.start(cfg)

        gateway = LegacyWaGateway(
            coordinator=coordinator,
            listener=listener,
            schedule_runner=runner,
            reload_callback=restart,
        )
        panel = WaPanel(
            gateway,
            tr=tr,
            task_manager_factory=_wa_task_factory(tr),
            parent=parent,
        )
        panel_holder[0] = panel
        listener.start(gateway.cfg, panel.alert_callback)
        runner.set_reminder_callback(panel.reminder_callback)
        runner.start(gateway.cfg)

        from PySide6.QtCore import QTimer

        def _start_wa_backend() -> None:
            coordinator.start(gateway.cfg)

        # 延后启动 neonize，避免切 WA 标签时与 TG 同时抢资源；冷启动不立刻 StopAll
        QTimer.singleShot(2000, _start_wa_backend)

        stopped = False

        def shutdown() -> None:
            nonlocal stopped
            if stopped:
                return
            stopped = True
            from shutdown import EXIT_JOIN_TIMEOUT

            shutdown_application(
                coord=coordinator,
                listener=listener,
                schedule2=runner,
                login_cancel=getattr(panel, "login_cancel", None),
                join_timeout=EXIT_JOIN_TIMEOUT,
                kill_children=False,
            )

        return PanelMount(panel, shutdown)

    return factory


def create_tg_panel_factory(tr: Callable[..., str]):
    """Telegram 面板保持懒加载，并在首次挂载时启动唯一 coordinator。"""

    def factory(parent):
        from legacy_tg_import import ensure_tg_data_ready
        from platform_paths import tg_data_root

        os.environ["TG_HELPER_DATA_ROOT"] = tg_data_root()
        from .platforms.wa.runtime import ensure_legacy_import_root

        ensure_legacy_import_root()
        wa_root = Path(__file__).resolve().parents[1]
        repo_root = wa_root.parent
        for root in (str(wa_root), str(repo_root)):
            if root not in sys.path:
                sys.path.insert(0, root)
        ensure_tg_data_ready()
        from startup_bootstrap import bootstrap_tg_logging, bootstrap_tg_runtime

        bootstrap_tg_runtime()
        bootstrap_tg_logging()

        from tg_multi_listener.scheduler import pause_all_doc_jobs_on_startup

        from .platforms.tg import TgPanel, TgPresenter

        pause_all_doc_jobs_on_startup()
        presenter = TgPresenter(tr=tr)
        panel = TgPanel(
            presenter=presenter,
            task_manager_factory=_tg_task_factory,
            tr=tr,
            parent=parent,
        )
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, presenter.restart_services_async)
        return PanelMount(panel, lambda: presenter.close(join_timeout=8.0))

    return factory


def build_runtime_kwargs(tr: Callable[..., str]) -> dict[str, Any]:
    """生成 app.run_app 所需依赖，数据仍位于原安装目录。"""
    from license_service import check_license
    from platform_paths import combo_root

    valid, message, _expires = check_license()

    return {
        "tr": tr,
        "wa_panel_factory": create_wa_panel_factory(tr),
        "tg_panel_factory": create_tg_panel_factory(tr),
        "data_directory": combo_root(),
        "license_status": LicenseStatus(valid, message),
        "on_exit": lambda: True,
    }
