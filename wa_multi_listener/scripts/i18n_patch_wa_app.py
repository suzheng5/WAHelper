"""一次性脚本：为 wa_ui/app.py 注入 t() 调用（开发用）。"""
from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "wa_ui" / "app.py"
text = APP.read_text(encoding="utf-8")

# 确保 import
if "from i18n import t, get_lang" not in text:
    text = text.replace(
        "from i18n.pause_reason import CODE_MANUAL",
        "from i18n import t, get_lang\nfrom i18n.pause_reason import CODE_MANUAL\n"
        "from i18n.ui_helpers import combo_label_for_lang, lang_combo_labels, lang_from_combo_label, msg_askyesno, msg_info\n"
        "from i18n import set_lang_for_next_launch",
    )

REPLACEMENTS = [
    ('text="WA 助手"', 'text=t("wa.brand")'),
    ('text="监听 · 定时群发"', 'text=t("wa.subtitle")'),
    ('("dash", "仪表盘")', '("dash", t("nav.dash"))'),
    ('("acct", "账号管理")', '("acct", t("nav.acct"))'),
    ('("grp", "通讯录")', '("grp", t("nav.grp"))'),
    ('("rules", "监听规则")', '("rules", t("nav.rules"))'),
    ('("sched", "定时任务")', '("sched", t("nav.sched"))'),
    ('("taskmgr", "任务管理")', '("taskmgr", t("nav.taskmgr"))'),
    ('("logs", "日志")', '("logs", t("nav.logs"))'),
    ('text="保存并重载"', 'text=t("common.save_reload")'),
    ('text="今日提醒次数"', 'text=t("dash.today_alerts")'),
    ('text="监听状态"', 'text=t("dash.listen_status")'),
    ('text="账号摘要"', 'text=t("dash.account_summary")'),
    ('text="账号管理"', 'text=t("acct.title")'),
    ('text="添加账号"', 'text=t("acct.add")'),
    ('text="保存代理"', 'text=t("acct.save_proxy")'),
    ('text="登录"', 'text=t("acct.login")'),
    ('text="删除"', 'text=t("common.delete")'),
    ('text="通讯录"', 'text=t("grp.title")'),
    ('text="通讯录列表"', 'text=t("grp.list_title")'),
    ('text="归属"', 'text=t("grp.owner")'),
    ('text="监听"', 'text=t("grp.listen")'),
    ('text="添加"', 'text=t("common.add")'),
    ('text="备注"', 'text=t("grp.remark")'),
    ('text="保存备注"', 'text=t("grp.save_remark")'),
    ('text="归属账号"', 'text=t("grp.owner_account")'),
    ('text="监听规则"', 'text=t("rules.title")'),
    ('text="启用消息监听"', 'text=t("rules.enable_listen")'),
    ('text="阶段提醒时弹出置顶窗口"', 'text=t("rules.stage_popup")'),
    ('text="同群限流（秒）"', 'text=t("rules.rate_limit")'),
    ('text="从任务管理同步上次任务"', 'text=t("rules.sync_btn")'),
    ('text="检测不在群内的监听用户"', 'text=t("rules.audit_btn")'),
    ('text="定时任务"', 'text=t("sched.title")'),
    ('text="选择 TXT / 文件夹"', 'text=t("sched.pick_source")'),
    ('text="添加文档任务"', 'text=t("sched.add_job")'),
    ('text="勾选群发目标"', 'text=t("sched.targets")'),
    ('text="打开 TXT 格式说明"', 'text=t("sched.txt_format")'),
    ('text="选定任务"', 'text=t("sched.pick_job")'),
    ('text="原文账号"', 'text=t("sched.from_account")'),
    ('text="改由账号发送"', 'text=t("sched.to_account")'),
    ('text="批量替换"', 'text=t("sched.bulk_replace")'),
    ('text="任务管理"', 'text=t("taskmgr.title")'),
    ('text="任务数量：0"', 'text=t("taskmgr.count.total", total=0)'),
    ('text="一键开始全部任务"', 'text=t("taskmgr.resume_all")'),
    ('text="一键开始下一天"', 'text=t("taskmgr.next_day")'),
    ('text="手动下一天"', 'text=t("taskmgr.manual_day")'),
    ('text="一键删除全部任务"', 'text=t("taskmgr.delete_all")'),
    ('text="刷新日志"', 'text=t("common.refresh_logs")'),
    ('text="日志"', 'text=t("nav.logs")'),
    ('placeholder_text="账号简称，如 主号"', 'placeholder_text=t("acct.id_ph")'),
    ('placeholder_text="备注手机号（可选）"', 'placeholder_text=t("acct.phone_ph")'),
    ('placeholder_text="SOCKS5 代理（可选）socks5://IP:端口:用户:密码"', 'placeholder_text=t("acct.proxy_ph")'),
    ('placeholder_text="SOCKS5 代理（留空=直连）"', 'placeholder_text=t("acct.proxy_inline_ph")'),
    ('placeholder_text="选择 TXT 或文件夹（文件夹内按数字前缀排序）"', 'placeholder_text=t("sched.file_ph")'),
    ('messagebox.showerror("登录失败", msg)', 'messagebox.showerror(t("acct.login_fail_title"), msg)'),
    ('messagebox.askyesno("一键开始全部任务"', 'msg_askyesno(self, "msgbox.resume_all.title"'),
    ('messagebox.showinfo("手动下一天", "仅文件夹任务可手动切换下一天。"', 'msg_info(self, "msgbox.manual_day.title", "msgbox.manual_day.folder_only"'),
    ('messagebox.askyesno("手动下一天"', 'msg_askyesno(self, "msgbox.manual_day.title"'),
    ('messagebox.askyesno("一键开始下一天"', 'msg_askyesno(self, "msgbox.next_day.title"'),
    ('messagebox.askyesno("确认删除"', 'msg_askyesno(self, "msgbox.delete.title"'),
    ('messagebox.askyesno("一键删除任务"', 'msg_askyesno(self, "msgbox.delete_all.title"'),
    ('info("配置已保存，正在重载服务…")', 'info_i18n("log.config_saved")'),
    ('info("服务已重载")', 'info_i18n("log.services_reloaded")'),
    ('info("成员检测进行中，请稍候…")', 'info_i18n("log.audit_busy")'),
    ('info("请先登录 WhatsApp 账号并点「保存并重载服务」后再检测。")', 'info_i18n("log.audit_need_login")'),
    ('info("正在检测各群监听用户是否在群内…")', 'info_i18n("log.audit_start")'),
    ('info("当前无在线账号，无法检测群成员。")', 'info_i18n("log.audit_no_online")'),
    ('info(f"监听命中：已自动暂停 {len(touched_ids)} 个定时任务，请手动点「继续」")',
     'info_i18n("log.listen_hit_paused", n=len(touched_ids))'),
    ('info("无法启动该任务")', 'info_i18n("log.cannot_start_job")'),
    ('title="定时任务阶段提醒"', 'title=t("stage.title_wa")'),
    ('btn.configure(text="取消手动下一天"', 'btn.configure(text=t("taskmgr.manual_day_cancel")'),
    ('btn.configure(text="手动下一天"', 'btn.configure(text=t("taskmgr.manual_day")'),
    ('text=(f"提醒：{rem}" if rem else "提醒：无")',
     'text=(t("taskmgr.reminder", text=rem) if rem else t("taskmgr.reminder_none"))'),
    ('hint = "点击暂停" if running else ("点击继续" if j.enabled else "点击重新开始")',
     'hint = t("taskmgr.hint_pause") if running else (t("taskmgr.hint_resume") if j.enabled else t("taskmgr.hint_restart"))'),
    ('hint = (\n                "点击切换下一天"\n                if can_advance_folder_day(j)\n                else "已是最后一天（一键下一天可删）"\n            )',
     'hint = t("taskmgr.hint_next_day") if can_advance_folder_day(j) else t("taskmgr.hint_last_day")'),
    ('self._dash_today.configure(text=f"今日已提醒 {n} 次")',
     'self._dash_today.configure(text=t("dash.today_count", n=n))'),
    ('"\\n⚠ 用户不在群内，建议清空监听用户或删除条目"',
     't("audit.absent")'),
    ('msg = detail or "群或用户解析失败"', 'msg = detail or t("audit.parse_fail")'),
    ('return (f"\\n⚠ 未能检测：{msg}", COLORS["border"])',
     'return (t("audit.error", msg=msg), COLORS["border"])'),
    ('return ("\\n⚠ 归属账号未在线，未检测", COLORS["border"])',
     'return (t("audit.offline"), COLORS["border"])'),
]

for old, new in REPLACEMENTS:
    if old not in text:
        print("SKIP:", old[:60])
        continue
    text = text.replace(old, new)

# logger import
if "info_i18n" not in text:
    text = text.replace(
        "from logger_util import add_memory_listener, error, get_recent_lines, info, remove_memory_listener",
        "from logger_util import add_memory_listener, error, get_recent_lines, info, info_i18n, remove_memory_listener",
    )

# messagebox askyesno with parent - fix pattern
text = re.sub(
    r'msg_askyesno\(self, "([^"]+)", msg, parent=self\)',
    r'msg_askyesno(self, "\1", msg, parent=self)',
    text,
)
# broken: msg_askyesno needs body key not msg - leave manual fix for messagebox bodies

APP.write_text(text, encoding="utf-8")
print("patched", APP)
