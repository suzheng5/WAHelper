"""原型自身的双语文案，避免影响生产版 i18n 资源。"""
from __future__ import annotations

from typing import Any

TEXTS: dict[str, dict[str, str]] = {
    "zh": {
        "window.title": "PySide6 任务管理原型",
        "toolbar.platform": "平台",
        "toolbar.status": "状态",
        "toolbar.search": "搜索任务、目标或文件",
        "toolbar.refresh": "重新读取",
        "option.all": "全部",
        "option.running": "运行中",
        "option.paused": "已暂停",
        "option.stopped": "已停止",
        "status.running": "运行中",
        "status.listen": "监听暂停",
        "status.paused": "已暂停",
        "status.stopped": "已停止",
        "summary": "显示 {visible} / 全部 {total} 个任务",
        "footer": "虚拟列表：数据 {total} 条，仅绘制可见区域 · USER 对象 {user}",
        "progress": "进度 {cursor}/{total}",
        "target.none": "未设置目标",
        "empty": "没有匹配任务",
    },
    "en": {
        "window.title": "PySide6 Task Manager Prototype",
        "toolbar.platform": "Platform",
        "toolbar.status": "Status",
        "toolbar.search": "Search task, target, or file",
        "toolbar.refresh": "Reload",
        "option.all": "All",
        "option.running": "Running",
        "option.paused": "Paused",
        "option.stopped": "Stopped",
        "status.running": "Running",
        "status.listen": "Listener pause",
        "status.paused": "Paused",
        "status.stopped": "Stopped",
        "summary": "Showing {visible} of {total} tasks",
        "footer": "Virtual list: {total} records, visible area only · USER objects {user}",
        "progress": "Progress {cursor}/{total}",
        "target.none": "No target",
        "empty": "No matching tasks",
    },
}


def translator(language: str):
    lang = language if language in TEXTS else "zh"

    def tr(key: str, **kwargs: Any) -> str:
        text = TEXTS[lang].get(key, TEXTS["zh"].get(key, key))
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text

    return tr


def assert_locale_parity() -> None:
    assert set(TEXTS["zh"]) == set(TEXTS["en"])
