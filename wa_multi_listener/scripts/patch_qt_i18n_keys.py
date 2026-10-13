from __future__ import annotations

import json
from pathlib import Path

zh_path = Path(__file__).resolve().parents[1] / "i18n" / "locales" / "zh.json"
en_path = Path(__file__).resolve().parents[1] / "i18n" / "locales" / "en.json"
zh = json.loads(zh_path.read_text(encoding="utf-8"))
en = json.loads(en_path.read_text(encoding="utf-8"))

zh_add = {
    "shell.tab_wa": "WhatsApp",
    "shell.tab_tg": "Telegram",
    "qt.tg.restart_services": "启动 / 重启服务",
    "qt.tg.stop_services": "停止服务",
    "qt.tg.service_running": "服务状态：运行中",
    "qt.tg.service_stopped": "服务状态：已停止",
    "qt.tg.dashboard_counts": "账号 {accounts} 个 · 通讯录 {contacts} 条 · 任务 {jobs} 个",
    "qt.tg.api_id": "API ID",
    "qt.tg.api_hash": "API Hash",
    "qt.tg.save_api": "保存 API 凭证",
    "qt.tg.invite_link": "邀请链接",
    "qt.tg.move_up": "上移",
    "qt.tg.move_down": "下移",
    "qt.tg.audit_pending": "尚未执行审计",
    "qt.tg.audit_empty": "审计未返回结果",
    "qt.tg.interval_max": "最大间隔（分钟）",
    "qt.tg.jobs_created": "已创建 {count} 个任务",
    "qt.tg.folder_jobs_created": "已创建 {count} 个文件夹任务",
    "qt.tg.api_id_int": "API ID 必须为整数",
    "qt.tg.api_required": "API ID 和 API Hash 均不能为空",
    "qt.tg.restart_ok": "Telegram 服务已重启",
    "qt.tg.restart_fail": "Telegram 服务重启失败",
    "qt.tg.unknown_action": "未知任务动作：{action}",
    "task_manager.command.resume_all": "一键开始全部任务",
    "task_manager.command.next_day_all": "一键开始下一天",
    "task_manager.command.manual_next_day": "手动下一天",
    "task_manager.command.delete_all": "一键删除全部任务",
    "task_manager.command.reload_wa_folders": "重新读取文件夹话术",
    "task_manager.command.send_images": "一键发送图片",
    "task_manager.command.send_images_sync": "一键发图并同步客户",
    "task_manager.option.all_platforms": "全部平台",
    "task_manager.option.wa": "WhatsApp",
    "task_manager.option.tg": "Telegram",
    "task_manager.option.all_statuses": "全部状态",
    "task_manager.option.running": "运行中",
    "task_manager.option.paused": "已暂停",
    "task_manager.option.stopped": "已停止",
    "task_manager.sort.semantic": "按状态排序",
    "task_manager.sort.title": "按标题排序",
    "task_manager.sort.platform": "按平台排序",
    "task_manager.search.placeholder": "搜索任务、目标或文件",
    "task_manager.summary": "显示 {visible} / 全部 {total} 个任务",
}
en_add = {
    "shell.tab_wa": "WhatsApp",
    "shell.tab_tg": "Telegram",
    "qt.tg.restart_services": "Start / restart services",
    "qt.tg.stop_services": "Stop services",
    "qt.tg.service_running": "Service status: running",
    "qt.tg.service_stopped": "Service status: stopped",
    "qt.tg.dashboard_counts": "{accounts} accounts · {contacts} contacts · {jobs} jobs",
    "qt.tg.api_id": "API ID",
    "qt.tg.api_hash": "API Hash",
    "qt.tg.save_api": "Save API credentials",
    "qt.tg.invite_link": "Invite link",
    "qt.tg.move_up": "Move up",
    "qt.tg.move_down": "Move down",
    "qt.tg.audit_pending": "Audit not run yet",
    "qt.tg.audit_empty": "Audit returned no results",
    "qt.tg.interval_max": "Max interval (minutes)",
    "qt.tg.jobs_created": "Created {count} jobs",
    "qt.tg.folder_jobs_created": "Created {count} folder jobs",
    "qt.tg.api_id_int": "API ID must be an integer",
    "qt.tg.api_required": "API ID and API Hash are required",
    "qt.tg.restart_ok": "Telegram services restarted",
    "qt.tg.restart_fail": "Telegram service restart failed",
    "qt.tg.unknown_action": "Unknown task action: {action}",
    "task_manager.command.resume_all": "Resume all jobs",
    "task_manager.command.next_day_all": "Start next day",
    "task_manager.command.manual_next_day": "Manual next day",
    "task_manager.command.delete_all": "Delete all jobs",
    "task_manager.command.reload_wa_folders": "Reload folder scripts",
    "task_manager.command.send_images": "Send images",
    "task_manager.command.send_images_sync": "Send images and sync customers",
    "task_manager.option.all_platforms": "All platforms",
    "task_manager.option.wa": "WhatsApp",
    "task_manager.option.tg": "Telegram",
    "task_manager.option.all_statuses": "All statuses",
    "task_manager.option.running": "Running",
    "task_manager.option.paused": "Paused",
    "task_manager.option.stopped": "Stopped",
    "task_manager.sort.semantic": "Sort by status",
    "task_manager.sort.title": "Sort by title",
    "task_manager.sort.platform": "Sort by platform",
    "task_manager.search.placeholder": "Search task, target, or file",
    "task_manager.summary": "Showing {visible} of {total} tasks",
}

zh.update(zh_add)
en.update(en_add)
assert set(zh) == set(en), (set(zh) - set(en), set(en) - set(zh))
zh_path.write_text(json.dumps(zh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
en_path.write_text(json.dumps(en, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"added {len(zh_add)} keys; total {len(zh)}")
