"""PySide6 WhatsApp 面板公共入口。"""

from .contracts import TaskManagerFactory, WaGateway
from .gateway import LegacyWaGateway
from .panel import WaPanel
from .presenter import WaPresenter

__all__ = [
    "LegacyWaGateway",
    "TaskManagerFactory",
    "WaGateway",
    "WaPanel",
    "WaPresenter",
]
