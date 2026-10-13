"""PySide6 任务管理组件离屏生产验证。"""
from __future__ import annotations

import ctypes
import gc
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

WA_ROOT = Path(__file__).resolve().parents[1]
for package_root in (WA_ROOT, WA_ROOT / "qt_ui"):
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem, QWidget

from task_manager import TaskManagerWidget, TaskRecord


TEXT = {
    "task_manager.command.resume_all": "全部开始",
    "task_manager.command.next_day_all": "一键下一天",
    "task_manager.command.manual_next_day": "手动下一天",
    "task_manager.command.delete_all": "删除全部",
    "task_manager.command.reload_wa_folders": "WA 重读文件夹",
    "task_manager.command.send_images": "一键发图",
    "task_manager.command.send_images_sync": "发图同步客户",
    "task_manager.option.all_platforms": "全部平台",
    "task_manager.option.wa": "WhatsApp",
    "task_manager.option.tg": "Telegram",
    "task_manager.option.all_statuses": "全部状态",
    "task_manager.option.running": "运行中",
    "task_manager.option.paused": "已暂停",
    "task_manager.option.stopped": "已停止",
    "task_manager.sort.semantic": "按状态",
    "task_manager.sort.title": "按名称",
    "task_manager.sort.platform": "按平台",
    "task_manager.search.placeholder": "搜索任务、目标或文件",
    "task_manager.summary": "显示 {visible} / {total}",
    "task_manager.card.next_day_hint": "点击进入下一天",
    "task_manager.card.pause_hint": "点击暂停",
    "task_manager.card.resume_hint": "点击继续",
    "task_manager.card.status": "{status} · {step}",
    "task_manager.card.source_target": "{source} · {target}",
    "task_manager.card.folder_day": "文件夹第 {day}/{total} 天",
    "task_manager.card.not_folder": "单文件任务",
    "task_manager.card.progress": "游标 {cursor}/{total} · {folder}",
    "task_manager.card.error": "错误：{text}",
    "task_manager.card.pause": "暂停：{text}",
    "task_manager.card.action": "{text}",
    "task_manager.card.next_day": "下一天",
    "task_manager.card.delete": "删除",
}


def tr(key: str, **kwargs) -> str:
    value = TEXT.get(key, key)
    return value.format(**kwargs)


class ActionRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def toggle_task(self, task_id: str) -> None:
        self.calls.append(("toggle_task", task_id))

    def delete_task(self, task_id: str) -> None:
        self.calls.append(("delete_task", task_id))

    def next_day_task(self, task_id: str) -> None:
        self.calls.append(("next_day_task", task_id))

    def resume_all(self) -> None:
        self.calls.append(("resume_all", None))

    def next_day_all(self) -> None:
        self.calls.append(("next_day_all", None))

    def manual_next_day_mode_changed(self, enabled: bool) -> None:
        self.calls.append(("manual_next_day_mode_changed", enabled))

    def delete_all(self) -> None:
        self.calls.append(("delete_all", None))

    def reload_wa_folders(self) -> None:
        self.calls.append(("reload_wa_folders", None))

    def send_images(self) -> None:
        self.calls.append(("send_images", None))

    def send_images_sync(self) -> None:
        self.calls.append(("send_images_sync", None))


def make_records(count: int) -> list[TaskRecord]:
    reasons = ("", "listen_hit", "stage_reminder", "manual")
    records = []
    for index in range(count):
        running = index % 4 == 0
        records.append(
            TaskRecord(
                task_id=f"task-{index}",
                platform="WA" if index % 2 == 0 else "TG",
                title=f"任务 {index:05d}",
                target=f"客户群 {index % 37}",
                source_name=f"day-{index % 30 + 1}.txt",
                running=running,
                enabled=index % 9 != 0,
                status="运行中" if running else "已暂停",
                step=f"步骤 {index % 5 + 1}",
                pause_reason="" if running else reasons[index % len(reasons)],
                last_error="发送失败" if index % 97 == 0 else "",
                cursor=index % 20,
                total=20,
                folder_day=index % 8 + 1,
                folder_total=10,
                is_folder=True,
                source_order=index,
            )
        )
    return records


def user_objects() -> int:
    if os.name != "nt":
        return 0
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetGuiResources.restype = ctypes.c_uint
    return int(user32.GetGuiResources(kernel32.GetCurrentProcess(), 1))


def flush(app: QApplication, cycles: int = 5) -> None:
    for _ in range(cycles):
        app.processEvents()


def assert_virtual_growth(
    app: QApplication,
    widget: TaskManagerWidget,
) -> tuple[int, int, int, int]:
    widget.replace_records(make_records(1000))
    flush(app)
    widgets_1k = len(widget.findChildren(QWidget))
    user_1k = user_objects()
    assert widget.model.rowCount() == 1000
    assert widget.proxy.rowCount() == 1000
    for row in (0, 499, 999):
        assert widget.view.indexWidget(widget.proxy.index(row, 0)) is None

    widget.replace_records(make_records(10000))
    widget.view.scrollTo(widget.proxy.index(9999, 0))
    flush(app, 8)
    widgets_10k = len(widget.findChildren(QWidget))
    user_10k = user_objects()
    assert widget.model.rowCount() == 10000
    assert widget.proxy.rowCount() == 10000
    for row in (0, 4999, 9999):
        assert widget.view.indexWidget(widget.proxy.index(row, 0)) is None
    assert widgets_10k <= widgets_1k + 2, (widgets_1k, widgets_10k)
    if user_1k > 0 and user_10k > 0:
        assert user_10k <= user_1k + 8, (user_1k, user_10k)
    return widgets_1k, widgets_10k, user_1k, user_10k


def assert_patch_filter_sort(widget: TaskManagerWidget, app: QApplication) -> None:
    reset_before = widget.model.reset_count
    original = widget.model.record_at(100)
    assert original is not None
    changed = widget.patch_records(
        {
            original.task_id: {
                "title": "唯一增量任务",
                "running": False,
                "enabled": True,
                "pause_reason": "listen_hit",
            }
        }
    )
    flush(app)
    assert changed == [original.task_id]
    assert widget.model.reset_count == reset_before
    assert widget.model.patch_count == 1
    widget._search.setText("唯一增量任务")
    flush(app)
    assert widget.proxy.rowCount() == 1
    widget._search.clear()
    widget._platform.setCurrentIndex(1)
    flush(app)
    assert widget.proxy.rowCount() == 5000
    widget._platform.setCurrentIndex(0)
    widget._sort.setCurrentIndex(1)
    flush(app)


def visible_index_and_option(widget: TaskManagerWidget, app: QApplication):
    widget.view.scrollTo(widget.proxy.index(0, 0), widget.view.ScrollHint.PositionAtTop)
    flush(app, 8)
    index = widget.proxy.index(0, 0)
    assert index.isValid()
    option = QStyleOptionViewItem()
    option.rect = widget.view.visualRect(index)
    option.font = widget.view.font()
    assert widget.view.indexAt(option.rect.center()) == index
    return index, option


def assert_hit_tests(
    widget: TaskManagerWidget,
    actions: ActionRecorder,
    app: QApplication,
) -> None:
    widget._search.clear()
    widget._platform.setCurrentIndex(0)
    widget._sort.setCurrentIndex(0)
    widget.command_button("manual_next_day").click()
    flush(app)
    assert ("manual_next_day_mode_changed", True) in actions.calls

    index, option = visible_index_and_option(widget, app)
    record = index.data(widget.model.RecordRole)
    rects = widget.delegate.action_rects(option, index)
    assert {"delete", "next_day"} <= set(rects)
    QTest.mouseClick(widget.view.viewport(), Qt.MouseButton.LeftButton, pos=rects["delete"].center())
    QTest.mouseClick(widget.view.viewport(), Qt.MouseButton.LeftButton, pos=rects["next_day"].center())
    card_point = QPoint(option.rect.left() + 20, option.rect.top() + 20)
    QTest.mouseClick(widget.view.viewport(), Qt.MouseButton.LeftButton, pos=card_point)
    widget.command_button("manual_next_day").click()
    flush(app)
    assert ("manual_next_day_mode_changed", False) in actions.calls
    QTest.mouseClick(widget.view.viewport(), Qt.MouseButton.LeftButton, pos=card_point)
    flush(app)
    assert ("delete_task", record.task_id) in actions.calls
    assert ("next_day_task", record.task_id) in actions.calls
    assert ("toggle_task", record.task_id) in actions.calls


def assert_command_callbacks(widget: TaskManagerWidget, actions: ActionRecorder) -> None:
    for command in (
        "resume_all",
        "next_day_all",
        "delete_all",
        "reload_wa_folders",
        "send_images",
        "send_images_sync",
    ):
        widget.command_button(command).click()
        assert (command, None) in actions.calls


def main() -> None:
    app = QApplication.instance() or QApplication([])
    actions = ActionRecorder()
    widget = TaskManagerWidget(actions=actions, tr=tr)
    widget.resize(1280, 760)
    widget.show()
    flush(app)
    growth = assert_virtual_growth(app, widget)
    assert_patch_filter_sort(widget, app)
    assert_hit_tests(widget, actions, app)
    assert_command_callbacks(widget, actions)
    widget.close()
    flush(app)
    gc.collect()
    print(
        "PASS: 1000/10000 virtual rows; QWidget "
        f"{growth[0]}->{growth[1]}; USER {growth[2]}->{growth[3]}; "
        "patch/hit-test/callbacks verified"
    )


if __name__ == "__main__":
    main()
