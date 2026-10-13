# PySide6 任务管理原型

这是与生产版 Tk/CustomTkinter 界面隔离的只读原型：

- 读取现有 WhatsApp 与 Telegram 任务 JSON，不保存、不发送、不改任务状态。
- 使用 `QAbstractListModel + QSortFilterProxyModel + QStyledItemDelegate`。
- 任务卡片由单个 Delegate 绘制，不为每条任务创建 QWidget。
- 支持平台、状态、文本筛选，以及任意数量的压力测试数据。

在 `wa_multi_listener` 目录运行：

```powershell
..\.venv\Scripts\python.exe -m qt_ui_prototype.main --lang zh
```

用 1000 条任务测试滚动：

```powershell
..\.venv\Scripts\python.exe -m qt_ui_prototype.main --lang zh --stress 1000
```

指定安装版数据目录：

```powershell
..\.venv\Scripts\python.exe -m qt_ui_prototype.main --data-root "D:\WAHelper"
```

离屏自检：

```powershell
..\.venv\Scripts\python.exe -m qt_ui_prototype.test_smoke
```
