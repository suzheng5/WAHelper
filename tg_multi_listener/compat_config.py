"""整合版与独立运行双模式下的 config 导入。"""
from __future__ import annotations

try:
    from tg_multi_listener import config as _config
except ImportError:
    import config as _config  # type: ignore[no-redef]


def __getattr__(name: str):
    """转发至 config（含 SCHEDULE_FILE 等由 config.__getattr__ 动态解析的路径）。"""
    return getattr(_config, name)


def __dir__() -> list[str]:
    return sorted({*globals().keys(), *dir(_config)})
