"""任务 pause_reason：内部原因码 + 旧版中文兼容 + 展示翻译。"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# --- 原因码（写入 schedule JSON；v2.1+ 新数据）---
CODE_STAGE_REMINDER = "stage_reminder"
CODE_AWAIT_IMAGE_SEND = "await_image_send"
CODE_AWAIT_IMAGE_LISTEN_HIT = "await_image_listen_hit"
CODE_LISTEN_HIT = "listen_hit"
CODE_STAGE_LISTEN_HIT = "stage_listen_hit"
CODE_STOPPED_LISTEN_HIT = "stopped_listen_hit"
CODE_JOIN_GROUP_FAILED = "join_group_failed"
CODE_ROUND_COMPLETE = "round_complete"
CODE_NEW_JOB = "new_job"
CODE_STARTUP_TASKMGR = "startup_taskmgr"
CODE_SHUTDOWN_TASKMGR = "shutdown_taskmgr"
CODE_STARTUP_DOC = "startup_doc"
CODE_STARTUP_SCHEDULE2_TG = "startup_schedule2_tg"
CODE_MANUAL = "manual"
CODE_MIGRATED = "migrated"
CODE_GENERIC_PAUSED = "generic_paused"
CODE_UNKNOWN = "unknown"

KNOWN_CODES = frozenset(
    {
        CODE_STAGE_REMINDER,
        CODE_AWAIT_IMAGE_SEND,
        CODE_AWAIT_IMAGE_LISTEN_HIT,
        CODE_LISTEN_HIT,
        CODE_STAGE_LISTEN_HIT,
        CODE_STOPPED_LISTEN_HIT,
        CODE_JOIN_GROUP_FAILED,
        CODE_ROUND_COMPLETE,
        CODE_NEW_JOB,
        CODE_STARTUP_TASKMGR,
        CODE_SHUTDOWN_TASKMGR,
        CODE_STARTUP_DOC,
        CODE_STARTUP_SCHEDULE2_TG,
        CODE_MANUAL,
        CODE_MIGRATED,
        CODE_GENERIC_PAUSED,
        CODE_UNKNOWN,
    }
)

# 旧版完整中文 → 码
LEGACY_ZH_EXACT: Dict[str, str] = {
    "定时任务阶段提醒，已自动暂停": CODE_STAGE_REMINDER,
    "待发送图片，请在任务管理点「一键发送图片」": CODE_AWAIT_IMAGE_SEND,
    "待发图且监听命中，请先发图": CODE_AWAIT_IMAGE_LISTEN_HIT,
    "发送账号入群失败，任务已暂停": CODE_JOIN_GROUP_FAILED,
    "监听命中目标用户，自动暂停": CODE_LISTEN_HIT,
    "阶段提醒后监听命中，自动暂停": CODE_STAGE_LISTEN_HIT,
    "已停止任务监听命中，请关注": CODE_STOPPED_LISTEN_HIT,
    "一轮发送完成，任务自动停止": CODE_ROUND_COMPLETE,
    "新建任务，请点「继续」后开始": CODE_NEW_JOB,
    "程序启动后已自动暂停，请在「任务管理」点「一键开始全部任务」。": CODE_STARTUP_TASKMGR,
    "程序已关闭，再次打开后请在「任务管理」点「一键开始全部任务」。": CODE_SHUTDOWN_TASKMGR,
    "程序启动后已自动暂停，请在定时任务中点「继续」后再运行。": CODE_STARTUP_DOC,
    "程序启动后已自动暂停，请在「定时任务2」中点「继续」后再运行。": CODE_STARTUP_SCHEDULE2_TG,
    "已从定时任务2迁移": CODE_MIGRATED,
    "手动暂停": CODE_MANUAL,
    "已暂停": CODE_GENERIC_PAUSED,
}

# 截断/变体：按前缀匹配（长串优先）
LEGACY_ZH_PREFIX: Tuple[Tuple[str, str], ...] = (
    ("程序已关闭，再次打开后请在「任务管理」", CODE_SHUTDOWN_TASKMGR),
    ("程序启动后已自动暂停，请在「任务管理」", CODE_STARTUP_TASKMGR),
    ("程序启动后已自动暂停，请在定时任务中点", CODE_STARTUP_DOC),
    ("程序启动后已自动暂停，请在「定时任务2」", CODE_STARTUP_SCHEDULE2_TG),
    ("程序启动后已自动暂停", CODE_STARTUP_DOC),
    ("定时任务阶段提醒，已自动暂停", CODE_STAGE_REMINDER),
    ("待发图且监听命中", CODE_AWAIT_IMAGE_LISTEN_HIT),
    ("待发送图片，请在任务管理点", CODE_AWAIT_IMAGE_SEND),
    ("待发送图片", CODE_AWAIT_IMAGE_SEND),
    ("发送账号入群失败", CODE_JOIN_GROUP_FAILED),
    ("阶段提醒后监听命中，自动暂停", CODE_STAGE_LISTEN_HIT),
    ("已停止任务监听命中，请关注", CODE_STOPPED_LISTEN_HIT),
    ("监听命中目标用户，自动暂停", CODE_LISTEN_HIT),
    ("一轮发送完成，任务自动停止", CODE_ROUND_COMPLETE),
    ("新建任务，请点「继续」后开始", CODE_NEW_JOB),
    ("已从定时任务2迁移", CODE_MIGRATED),
)


def normalize_pause_reason(raw: str) -> str:
    """将磁盘/内存中的 pause_reason 归一为原因码。"""
    s = (raw or "").strip()
    if not s:
        return CODE_GENERIC_PAUSED
    if s in KNOWN_CODES:
        return s
    if s in LEGACY_ZH_EXACT:
        return LEGACY_ZH_EXACT[s]
    for prefix, code in LEGACY_ZH_PREFIX:
        if s.startswith(prefix):
            return code
    if ("待发图" in s or "待发送图片" in s) and "监听命中" in s:
        return CODE_AWAIT_IMAGE_LISTEN_HIT
    if "待发送图片" in s or "待发图" in s:
        return CODE_AWAIT_IMAGE_SEND
    if "入群失败" in s:
        return CODE_JOIN_GROUP_FAILED
    if "阶段提醒" in s and "监听命中" in s:
        return CODE_STAGE_LISTEN_HIT
    if "已停止" in s and "监听命中" in s:
        return CODE_STOPPED_LISTEN_HIT
    if "监听命中" in s:
        return CODE_LISTEN_HIT
    if "阶段提醒" in s and "已自动暂停" in s:
        return CODE_STAGE_REMINDER
    if "一轮发送完成" in s:
        return CODE_ROUND_COMPLETE
    if "新建任务" in s:
        return CODE_NEW_JOB
    if "程序启动后已自动暂停" in s:
        return CODE_STARTUP_DOC
    if "手动" in s and "暂停" in s:
        return CODE_MANUAL
    return CODE_UNKNOWN


def pause_reason_is(raw: str, code: str) -> bool:
    return normalize_pause_reason(raw) == code


def compose_listen_pause_reason(previous_reason: str, listen_reason: str) -> str:
    """监听命中后写入的原因码（非展示文案）。"""
    prev = normalize_pause_reason(previous_reason)
    # 待发图 + 监听 → 保留可一键发图，卡片变紫（排序进监听置顶）
    if prev in (CODE_AWAIT_IMAGE_SEND, CODE_AWAIT_IMAGE_LISTEN_HIT):
        return CODE_AWAIT_IMAGE_LISTEN_HIT
    if prev == CODE_STAGE_LISTEN_HIT:
        return CODE_STAGE_LISTEN_HIT
    if prev == CODE_STAGE_REMINDER:
        return CODE_STAGE_LISTEN_HIT
    lr = normalize_pause_reason(listen_reason)
    if lr in KNOWN_CODES and lr != CODE_UNKNOWN:
        return lr
    return CODE_LISTEN_HIT


def resolve_listen_pause_reason(*, enabled: bool, previous_reason: str, listen_reason: str) -> str:
    if not enabled:
        return CODE_STOPPED_LISTEN_HIT
    return compose_listen_pause_reason(previous_reason, listen_reason)


def is_await_image_send(raw: str) -> bool:
    """仍处于待发图流程（含监听后的紫色态），可被一键发图匹配。"""
    return normalize_pause_reason(raw) in (CODE_AWAIT_IMAGE_SEND, CODE_AWAIT_IMAGE_LISTEN_HIT)


def display_pause_reason(raw: str, *, max_len: Optional[int] = None) -> str:
    """按当前界面语言返回 pause_reason 展示文案。"""
    from i18n import t

    code = normalize_pause_reason(raw)
    text = t(f"pause_reason.{code}")
    if max_len is not None and len(text) > max_len:
        return text[: max(0, max_len - 1)] + "…"
    return text
