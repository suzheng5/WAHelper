"""图形界面驱动的 Telethon 登录（供主程序集成）。"""
from __future__ import annotations

import asyncio
import io
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional, Protocol

from telethon import TelegramClient, utils
from telethon.errors import (
    AuthRestartError,
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberFloodError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.tl.functions.auth import ResendCodeRequest, SendCodeRequest
from telethon.tl.types import CodeSettings
from telethon.tl.types.auth import SentCodeSuccess

from i18n import t
from .compat_config import Account, AppConfig, ensure_dirs
from .logger_util import error_i18n, info, warning
from .ui.login_dialog import LoginUIBridge

if TYPE_CHECKING:
    import customtkinter as ctk


RESEND_TOKEN = "__RESEND__"
QR_TOKEN = "__QR__"
_SMS_TYPES = {
    "SentCodeTypeSms",
    "SentCodeTypeFragmentSms",
    "SentCodeTypeSmsWord",
    "SentCodeTypeSmsPhrase",
}
_APP_LIKE_TYPES = {
    "SentCodeTypeApp",
    "SentCodeTypeCall",
    "SentCodeTypeFlashCall",
    "SentCodeTypeMissedCall",
    "SentCodeTypeFirebaseSms",
}


class _PreLogin(Protocol):
    def __call__(self) -> None: ...


def describe_sent_via(sent: object) -> str:
    """把 Telegram 返回的验证码通道翻成界面文案。"""
    name = type(getattr(sent, "type", None)).__name__
    mapping = {
        "SentCodeTypeApp": "login.tg.via_app",
        "SentCodeTypeSms": "login.tg.via_sms",
        "SentCodeTypeCall": "login.tg.via_call",
        "SentCodeTypeFlashCall": "login.tg.via_flash",
        "SentCodeTypeMissedCall": "login.tg.via_missed",
        "SentCodeTypeEmailCode": "login.tg.via_email",
        "SentCodeTypeSetUpEmailRequired": "login.tg.via_email",
        "SentCodeTypeFragmentSms": "login.tg.via_sms",
        "SentCodeTypeFirebaseSms": "login.tg.via_sms",
        "SentCodeTypeSmsWord": "login.tg.via_sms",
        "SentCodeTypeSmsPhrase": "login.tg.via_sms",
    }
    return t(mapping.get(name, "login.tg.via_unknown"))


def is_sms_sent(sent: object) -> bool:
    return type(getattr(sent, "type", None)).__name__ in _SMS_TYPES


def is_app_like_sent(sent: object) -> bool:
    return type(getattr(sent, "type", None)).__name__ in _APP_LIKE_TYPES


def _qr_png(url: str) -> bytes:
    import segno

    buf = io.BytesIO()
    segno.make_qr(url).save(buf, kind="png", scale=8, border=2)
    return buf.getvalue()


def _new_login_client(path: str, cfg: AppConfig) -> TelegramClient:
    # 登录专用：不自动吞掉 FloodWait，并尽量按桌面端指纹请求短信。
    return TelegramClient(
        path,
        cfg.api_id,
        cfg.api_hash,
        device_model="Desktop",
        system_version="Windows 10",
        app_version="5.16.2 x64",
        lang_code="en",
        system_lang_code="en-US",
        flood_sleep_threshold=0,
    )


def _remember_sent(client: TelegramClient, phone: str, sent: object) -> None:
    code_hash = getattr(sent, "phone_code_hash", "") or ""
    if code_hash:
        client._phone_code_hash[phone] = code_hash
    client._phone = phone


async def _request_login_code(
    client: TelegramClient,
    phone: str,
    *,
    resend: bool = False,
    retry: int = 0,
) -> object:
    phone_hash = client._phone_code_hash.get(phone)
    try:
        if resend and phone_hash:
            sent = await client(ResendCodeRequest(phone, phone_hash))
        else:
            sent = await client(
                SendCodeRequest(
                    phone,
                    client.api_id,
                    client.api_hash,
                    CodeSettings(
                        allow_flashcall=False,
                        current_number=False,
                        allow_app_hash=False,
                        allow_missed_call=False,
                        allow_firebase=False,
                    ),
                )
            )
    except AuthRestartError:
        if retry >= 2:
            raise
        return await _request_login_code(client, phone, resend=False, retry=retry + 1)
    except FloodWaitError as exc:
        if exc.seconds <= 25 and retry < 2:
            info(f"验证码发送被短暂限流，等待 {exc.seconds} 秒后重试")
            await asyncio.sleep(int(exc.seconds) + 1)
            return await _request_login_code(
                client, phone, resend=resend, retry=retry + 1
            )
        raise
    if isinstance(sent, SentCodeSuccess):
        raise RuntimeError("logged in right after sending the code")
    _remember_sent(client, phone, sent)
    return sent


async def _send_code_prefer_sms(client: TelegramClient, phone: str) -> object:
    sent = await _request_login_code(client, phone, resend=False)
    via = type(getattr(sent, "type", None)).__name__
    info(f"已请求登录验证码：通道={via}")
    if is_app_like_sent(sent):
        try:
            resent = await _request_login_code(client, phone, resend=True)
            via2 = type(getattr(resent, "type", None)).__name__
            info(f"首次验证码走客户端/来电，已改发下一路：通道={via2}")
            return resent
        except Exception as exc:
            warning(f"改发短信失败，仍使用首次通道：{exc}")
    return sent


def _ask_method(bridge: LoginUIBridge) -> Optional[str]:
    fn = getattr(bridge, "ask_method", None)
    if callable(fn):
        return fn(
            t("login.tg.method_title"),
            t("login.tg.method_prompt"),
        )
    return "sms"


def _ask_code(bridge: LoginUIBridge, title: str, prompt: str) -> Optional[str]:
    fn = getattr(bridge, "ask_code", None)
    if callable(fn):
        return fn(title, prompt)
    return bridge.ask_string(title, prompt)


def _ask_string(
    bridge: LoginUIBridge,
    title: str,
    prompt: str,
    *,
    placeholder: str = "",
    secret: bool = False,
    initial: str = "",
) -> Optional[str]:
    try:
        return bridge.ask_string(
            title,
            prompt,
            placeholder=placeholder,
            secret=secret,
            initial=initial,
        )
    except TypeError:
        return bridge.ask_string(title, prompt, placeholder=placeholder, secret=secret)


def _qr_remaining_seconds(qr: object) -> float:
    expires = getattr(qr, "expires", None)
    if expires is None:
        return 25.0
    if getattr(expires, "tzinfo", None) is None:
        expires = expires.replace(tzinfo=timezone.utc)
    now = datetime.now(tz=expires.tzinfo)
    return max(5.0, (expires - now).total_seconds())


async def _qr_login(client: TelegramClient, bridge: LoginUIBridge) -> tuple[bool, str]:
    show = getattr(bridge, "show_qr", None)
    update = getattr(bridge, "update_qr", None)
    close = getattr(bridge, "close_qr", None)
    cancelled = getattr(bridge, "is_qr_cancelled", None)
    if not callable(show):
        return False, t("login.tg.qr_unavailable")

    qr = await client.qr_login()
    show(_qr_png(qr.url), t("login.tg.qr_hint"))
    info("已展示 Telegram 扫码登录二维码")
    try:
        while True:
            if callable(cancelled) and cancelled():
                return False, t("login.tg.qr_cancelled")
            remaining = _qr_remaining_seconds(qr)
            wait_task = asyncio.create_task(qr.wait(timeout=min(28.0, remaining)))
            try:
                while not wait_task.done():
                    if callable(cancelled) and cancelled():
                        wait_task.cancel()
                        try:
                            await wait_task
                        except (asyncio.CancelledError, Exception):
                            pass
                        return False, t("login.tg.qr_cancelled")
                    await asyncio.sleep(0.25)
                try:
                    user = await wait_task
                except SessionPasswordNeededError:
                    pwd = _ask_string(
                        bridge,
                        t("login.tg.step3_title"),
                        t("login.tg.step3_prompt"),
                        secret=True,
                    )
                    if not pwd:
                        return False, t("login.tg.cancelled")
                    await client.sign_in(password=pwd)
                    if not await client.is_user_authorized():
                        return False, t("login.tg.incomplete")
                    me = await client.get_me()
                    label = getattr(me, "username", None) or str(me.id)
                    return True, t("login.tg.success", label=label)
                except asyncio.TimeoutError:
                    await qr.recreate()
                    if callable(update):
                        update(_qr_png(qr.url), t("login.tg.qr_refresh"))
                    else:
                        show(_qr_png(qr.url), t("login.tg.qr_refresh"))
                    info("扫码登录二维码已过期，已刷新")
                    continue
                label = getattr(user, "username", None) or str(getattr(user, "id", ""))
                return True, t("login.tg.success", label=label)
            finally:
                if not wait_task.done():
                    wait_task.cancel()
    finally:
        if callable(close):
            close()


def _can_qr(bridge: LoginUIBridge) -> bool:
    return callable(getattr(bridge, "show_qr", None))


async def _sms_login(
    client: TelegramClient,
    bridge: LoginUIBridge,
    *,
    initial_phone: str = "",
) -> tuple[bool, str]:
    phone = _ask_string(
        bridge,
        t("login.tg.step1_title"),
        t("login.tg.step1_prompt"),
        placeholder=t("login.tg.phone_ph"),
        initial=initial_phone,
    )
    if not phone:
        return False, t("login.tg.cancelled")
    phone = utils.parse_phone(phone) or phone

    try:
        sent = await _send_code_prefer_sms(client, phone)
    except PhoneNumberInvalidError:
        return False, t("login.tg.phone_invalid")
    except FloodWaitError as exc:
        if _can_qr(bridge):
            warning(f"验证码通道被限流 {exc.seconds}s，改走扫码登录")
            return await _qr_login(client, bridge)
        return False, t("login.tg.flood_wait", seconds=exc.seconds)
    except PhoneNumberFloodError:
        if _can_qr(bridge):
            warning("该号码验证码发送次数过多，改走扫码登录")
            return await _qr_login(client, bridge)
        return False, t("login.tg.phone_flood")
    except RPCError as exc:
        return False, t("login.tg.code_send_fail", err=exc)

    while True:
        prompt = t("login.tg.step2_prompt_typed", via=describe_sent_via(sent))
        raw = _ask_code(bridge, t("login.tg.step2_title"), prompt)
        if not raw:
            return False, t("login.tg.cancelled")
        if raw == QR_TOKEN:
            return await _qr_login(client, bridge)
        if raw == RESEND_TOKEN:
            try:
                sent = await _request_login_code(client, phone, resend=True)
                info(
                    f"用户点了重发验证码：通道={type(getattr(sent, 'type', None)).__name__}"
                )
            except FloodWaitError as exc:
                if _can_qr(bridge):
                    warning(f"重发验证码被限流 {exc.seconds}s，改走扫码登录")
                    return await _qr_login(client, bridge)
                return False, t("login.tg.flood_wait", seconds=exc.seconds)
            except PhoneNumberFloodError:
                if _can_qr(bridge):
                    warning("重发验证码次数过多，改走扫码登录")
                    return await _qr_login(client, bridge)
                return False, t("login.tg.phone_flood")
            except PhoneCodeExpiredError:
                try:
                    client._phone_code_hash.pop(phone, None)
                    sent = await _send_code_prefer_sms(client, phone)
                    info("原验证码已过期，已重新申请")
                except Exception as exc:
                    return False, t("login.tg.resend_fail", err=exc)
            except RPCError as exc:
                return False, t("login.tg.resend_fail", err=exc)
            continue

        try:
            await client.sign_in(phone, raw.strip())
        except SessionPasswordNeededError:
            pwd = _ask_string(
                bridge,
                t("login.tg.step3_title"),
                t("login.tg.step3_prompt"),
                secret=True,
            )
            if not pwd:
                return False, t("login.tg.cancelled")
            await client.sign_in(password=pwd)
        except PhoneCodeInvalidError:
            return False, t("login.tg.code_invalid")
        except PhoneCodeExpiredError:
            try:
                client._phone_code_hash.pop(phone, None)
                sent = await _send_code_prefer_sms(client, phone)
                info("验证码已过期，已重新申请，请输入新验证码")
                continue
            except Exception as exc:
                return False, t("login.tg.code_expired", err=exc)
        except RPCError as exc:
            return False, t("login.tg.login_fail", err=exc)
        break

    if not await client.is_user_authorized():
        return False, t("login.tg.incomplete")
    me = await client.get_me()
    label = getattr(me, "username", None) or str(me.id)
    return True, t("login.tg.success", label=label)


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
            client = _new_login_client(path, cfg)
            try:
                await asyncio.sleep(0.45)
                await client.connect()
                if await client.is_user_authorized():
                    me = await client.get_me()
                    name = getattr(me, "username", None) or str(me.id)
                    await client.disconnect()
                    return True, t("login.tg.already", name=name)

                mode = _ask_method(bridge)
                if not mode:
                    await client.disconnect()
                    return False, t("login.tg.cancelled")

                if mode == "qr":
                    ok, msg = await _qr_login(client, bridge)
                else:
                    ok, msg = await _sms_login(
                        client,
                        bridge,
                        initial_phone=getattr(account, "phone", "") or "",
                    )
                await client.disconnect()
                return ok, msg
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
