"""独立 PySide6 任务管理原型，不修改现有 Tk 界面与任务数据。"""

from .records import TaskRecord, load_task_records, make_stress_records

__all__ = ["TaskRecord", "load_task_records", "make_stress_records"]
