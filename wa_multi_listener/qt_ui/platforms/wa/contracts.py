"""WA Qt 面板的稳定数据与依赖契约。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence


Translator = Callable[..., str]


@dataclass(frozen=True, slots=True)
class AccountItem:
    account_id: str
    phone: str
    proxy: str
    enabled: bool
    online: bool = False


@dataclass(frozen=True, slots=True)
class ContactItem:
    entry_id: str
    remark: str
    chat_ref: str
    watch_user: str
    listen_enabled: bool
    owner_account_id: str
    invite_link: str
    last_schedule_source_name: str


@dataclass(frozen=True, slots=True)
class ConfigView:
    accounts: tuple[AccountItem, ...]
    contacts: tuple[ContactItem, ...]
    listening_enabled: bool
    stage_reminder_popup_enabled: bool
    rate_limit_seconds: float


class WaGateway(Protocol):
    """Presenter 唯一依赖的业务端口。"""

    def read_config(self) -> ConfigView: ...
    def add_account(self, account_id: str, phone: str, proxy: str) -> None: ...
    def update_account(self, account_id: str, enabled: bool, proxy: str) -> None: ...
    def delete_account(self, account_id: str) -> None: ...
    def start_qr_login(
        self,
        account_id: str,
        on_qr: Callable[[bytes], None],
        on_status: Callable[[str], None],
        on_done: Callable[[bool, str], None],
        cancel_event: Any = None,
    ) -> Any: ...
    def add_contact(
        self, remark: str, chat_ref: str, watch_user: str,
        listen_enabled: bool, owner_account_id: str, invite_link: str = "",
    ) -> None: ...
    def update_contact(self, entry_id: str, **changes: Any) -> None: ...
    def delete_contact(self, entry_id: str) -> None: ...
    def move_contact(self, entry_id: str, offset: int) -> None: ...
    def update_rules(self, listening: bool, popup: bool, rate_seconds: float) -> None: ...
    def save_and_reload(self) -> None: ...
    def request_audit(self, callback: Callable[[dict[str, Any]], None]) -> bool: ...
    def request_reconnect_offline(self, callback: Callable[[int, int, int], None]) -> bool: ...
    def import_schedule(self, source: str, target_ids: Sequence[str], interval: str) -> int: ...
    def recent_logs(self, limit: int = 250) -> list[str]: ...
    def task_records(self) -> Sequence[Any]: ...
    def task_action(self, action: str, task_id: str = "", **kwargs: Any) -> Any: ...


TaskManagerFactory = Callable[[Any, Sequence[Any], Any], Any]
