"""Qt 与后台服务之间的桥接接口。"""
from .signal_bridge import UiSignalBridge
from .ui_call import call_on_ui, ensure_ui_bridge

__all__ = ["UiSignalBridge", "call_on_ui", "ensure_ui_bridge"]
