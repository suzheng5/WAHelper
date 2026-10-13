"""图形界面驱动的 Telethon 登录（供主程序集成）。"""
from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Callable, Optional, Protocol

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)

from i18n import t
from .compat_config import Account, AppConfig, ensure_dirs
from .logger_util import error_i18n, info
from .ui.login_dialog import LoginUIBridge

if TYPE_CHECKING:
    import customtkinter as ctk


class _PreLogin(Protocol):
    def __call__(self) -> None: ...


def run_login_in_thread(
    root: "ctk.CTk",
    account: Account,
    cfg: AppConfig,
    on_done: Callable[[bool, str], None],
    *,
    pre_login: Optional[_PreLogin] = None,
) -> None:
    """在后台线程执行登录；回调在主线程执行（通过 root.after）。
    Telegram 应用的 api_id / api_hash 来自 cfg（所有账号共用一套）。
    pre_login：在连接 session 之前执行（例如停止统一会话线程并 join，避免 sqlite 锁死）。
    """

    def worker() -> None:
        if pre_login is not None:
            try:
                pre_login()
            except Exception as exc:
                root.after(0, lambda: on_done(False, t("login.tg.pre_login_fail", err=exc)))
                return
        bridge = LoginUIBridge(root)

        async def inner() -> tuple[bool, str]:
            ensure_dirs()
            if not int(cfg.api_id) or not str(cfg.api_hash).strip():
                return False, t("login.tg.api_required")
            path = account.session_path()
            client = TelegramClient(path, cfg.api_id, cfg.api_hash)
            try:
                await asyncio.sleep(0.45)
                await client.connect()
                if await client.is_user_authorized():
                    me = await client.get_me()
                    name = getattr(me, "username", None) or str(me.id)
                    await client.disconnect()
                    return True, t("login.tg.already", name=name)

                phone = bridge.ask_string(
                    t("login.tg.step1_title"),
                    t("login.tg.step1_prompt"),
                    placeholder=t("login.tg.phone_ph"),
                )
                if not phone:
                    await client.disconnect()
                    return False, t("login.tg.cancelled")

                try:
                    await client.send_code_request(phone)
                except PhoneNumberInvalidError:
                    await client.disconnect()
                    return False, t("login.tg.phone_invalid")
                except FloodWaitError as exc:
                    await client.disconnect()
                    return False, t("login.tg.flood_wait", seconds=exc.seconds)
                except RPCError as exc:
                    await client.disconnect()
                    return False, t("login.tg.code_send_fail", err=exc)

                code = bridge.ask_string(
                    t("login.tg.step2_title"),
                    t("login.tg.step2_prompt"),
                )
                if not code:
                    await client.disconnect()
                    return False, t("login.tg.cancelled")

                try:
                    await client.sign_in(phone, code.strip())
                except SessionPasswordNeededError:
                    pwd = bridge.ask_string(
                        t("login.tg.step3_title"),
                        t("login.tg.step3_prompt"),
                        secret=True,
                    )
                    if not pwd:
                        await client.disconnect()
                        return False, t("login.tg.cancelled")
                    await client.sign_in(password=pwd)
                except PhoneCodeInvalidError:
                    await client.disconnect()
                    return False, t("login.tg.code_invalid")
                except RPCError as exc:
                    await client.disconnect()
                    return False, t("login.tg.login_fail", err=exc)

                if not await client.is_user_authorized():
                    await client.disconnect()
                    return False, t("login.tg.incomplete")

                me = await client.get_me()
                label = getattr(me, "username", None) or str(me.id)
                await client.disconnect()
                return True, t("login.tg.success", label=label)
            except Exception as exc:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                error_i18n("login.tg.exception", err=exc)
                return False, str(exc)

        try:
            ok, msg = asyncio.run(inner())
        except Exception as exc:
            ok, msg = False, str(exc)

        root.after(0, lambda: on_done(ok, msg))

    threading.Thread(target=worker, name="tg-login", daemon=True).start()
