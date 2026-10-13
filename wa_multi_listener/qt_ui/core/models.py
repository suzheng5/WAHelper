"""Qt 界面与业务适配器之间传递的不可变视图模型。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Tuple

KeyValuePairs = Tuple[Tuple[str, Any], ...]
BackendKind = Literal["wa", "tg"]


@dataclass(frozen=True, slots=True)
class AlertViewModel:
    backend: BackendKind
    chat_id: str
    chat_title: str
    sender_name: str
    message_text: str
    metadata: KeyValuePairs = ()


@dataclass(frozen=True, slots=True)
class ReminderViewModel:
    backend: BackendKind
    reminder_id: str
    title_key: str
    body_key: str
    params: KeyValuePairs = ()


@dataclass(frozen=True, slots=True)
class ProgressViewModel:
    operation_id: str
    current: int
    total: int
    message_key: str = ""
    params: KeyValuePairs = ()


@dataclass(frozen=True, slots=True)
class BackendStateViewModel:
    backend: BackendKind
    state: str
    connected_accounts: int = 0
    total_accounts: int = 0
    detail_key: str = ""
    detail_params: KeyValuePairs = ()


@dataclass(frozen=True, slots=True)
class JobViewModel:
    job_id: str
    backend: BackendKind
    name: str
    state: str
    enabled: bool
    pause_reason_code: str = ""
    current_step: int = 0
    total_steps: int = 0
    next_run_ts: float = 0.0
    account_id: str = ""
    target_ids: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobsChangedViewModel:
    backend: BackendKind
    jobs: Tuple[JobViewModel, ...]
    changed_ids: Tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LogViewModel:
    level: str
    message: str
    created_ts: float
    backend: BackendKind | None = None
