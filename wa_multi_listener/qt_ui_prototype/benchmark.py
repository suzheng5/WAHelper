"""短时可见窗口基准：滚动 1000 条并输出 USER 对象和耗时。"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from .window import TaskManagerWindow, current_user_objects


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--data-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    window = TaskManagerWindow(
        data_root=args.data_root,
        stress_count=args.count,
        language="zh",
    )
    window.show()
    for _ in range(8):
        app.processEvents()

    before_user = current_user_objects()
    started = time.perf_counter()
    rows = window.proxy_model.rowCount()
    step = max(1, rows // 100)
    for row in range(0, rows, step):
        window.task_view.scrollTo(window.proxy_model.index(row, 0))
        app.processEvents()
    if rows:
        window.task_view.scrollTo(window.proxy_model.index(rows - 1, 0))
        app.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000
    after_user = current_user_objects()
    widget_count = len(window.findChildren(QWidget))

    print(f"tasks={rows}")
    print(f"scroll_100_steps_ms={elapsed_ms:.1f}")
    print(f"qwidgets_total={widget_count}")
    print(f"user_objects={before_user}->{after_user}")
    window.close()
    app.processEvents()


if __name__ == "__main__":
    main()
