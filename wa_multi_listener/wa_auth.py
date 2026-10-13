"""后台线程扫码登录 WhatsApp（清除旧会话后重新扫码；有代理则走代理）。"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Optional

from neonize.aioze.client import NewAClient
from neonize.aioze.events import ConnectedEv, ConnectFailureEv, DisconnectedEv, LoggedOutEv, PairStatusEv
from neonize.proto.Neonize_pb2 import PairStatus as PairStatusMsg

from config import Account
from i18n import t
from logger_util import error, info, warning
from session_check import has_saved_session
from wa_client import (
    clear_session_files,
    connect_failure_message,
    force_stop_account_uuid,
    new_client,
    pair_error_message,
)

_SESSION_WAIT_SEC = 25.0
_CLIENT_STOP_TIMEOUT_SEC = 8.0
_PAIR_WAIT_SEC = 180.0


async def _wait_session_persisted(acc: Account, timeout: float = _SESSION_WAIT_SEC) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if has_saved_session(acc):
            return True
        await asyncio.sleep(0.35)
    return False


async def _release_login_client(client: NewAClient, timeout: float = _CLIENT_STOP_TIMEOUT_SEC) -> None:
    task = getattr(client, "connect_task", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except Exception:
            pass
    try:
        await asyncio.wait_for(client.stop(), timeout=timeout)
    except asyncio.TimeoutError:
        warning("登录客户端停止超时（会话已保存，可继续上线）")
    except Exception as exc:
        warning(f"停止登录客户端时：{exc}")


def _release_client_background(client: NewAClient, account_id: str) -> None:
    def _run() -> None:
        try:
            asyncio.run(_release_login_client(client))
        except Exception as exc:
            warning(f"后台释放登录连接「{account_id}」：{exc}")

    threading.Thread(
        target=_run, name=f"wa-login-release-{account_id}", daemon=True
    ).start()


def run_qr_login_in_thread(
    acc: Account,
    on_qr: Callable[[bytes], None],
    on_done: Callable[[bool, str], None],
    *,
    cancel_event: Optional[threading.Event] = None,
    on_status: Optional[Callable[[str], None]] = None,
    before_connect: Optional[Callable[[], None]] = None,
) -> threading.Thread:
    """扫码登录：有代理则经代理连接；独立事件循环，不阻塞其它账号连接。"""

    def _status(s: str) -> None:
        if on_status:
            try:
                on_status(s)
            except Exception:
                pass

    def work() -> None:
        ok = False
        msg = ""
        fail_msg: list[str] = [""]
        client: Optional[NewAClient] = None
        ui_notified = False

        def notify_ui(success: bool, text: str) -> None:
            nonlocal ui_notified
            if ui_notified:
                return
            ui_notified = True
            try:
                on_done(success, text)
            except Exception as exc:
                error(f"登录完成回调异常：{exc}")

        async def main() -> None:
            nonlocal ok, msg, client

            _status(t("qr.status_prepare"))
            if before_connect:
                try:
                    before_connect()
                except Exception as exc:
                    warning(f"登录准备：{exc}")

            _status(t("qr.status_clear_session"))
            old_session = (acc.session_name or "").strip()
            # 重登一律先换新空库，避免旧 .db 被 neonize 占用导致无法扫码
            if not clear_session_files(
                acc,
                retries=8,
                delay_sec=0.35,
                allow_rotate=True,
                rotate_first=True,
            ):
                msg = t("qr.clear_session_fail")
                error(f"账号「{acc.id}」{msg}")
                return
            if (acc.session_name or "").strip() != old_session:
                try:
                    from config import load_config, save_config

                    cfg = load_config()
                    for row in cfg.accounts:
                        if row.id == acc.id:
                            row.session_name = acc.session_name
                            break
                    save_config(cfg)
                    info(
                        f"账号「{acc.id}」会话文件名已更新为 {acc.session_name}.db"
                    )
                except Exception as exc:
                    warning(f"写回新会话文件名失败：{exc}")

            if cancel_event and cancel_event.is_set():
                msg = t("common.cancelled")
                return

            _status(t("qr.status_prepare"))
            # 清掉同账号 uuid 在 Go 侧的残留连接，否则新会话库可能永远不出码
            await force_stop_account_uuid(acc.id, acc.db_path())
            await asyncio.sleep(0.6)

            client = new_client(acc)
            if (acc.proxy or "").strip():
                info(f"账号「{acc.id}」扫码登录将走已配置代理")
                _status(t("qr.status_via_proxy"))
            else:
                _status(t("qr.status_wait_qr"))

            connected_ev = asyncio.Event()
            failed_ev = asyncio.Event()
            qr_seen = {"n": 0}

            @client.qr
            async def _qr(_c, data: bytes) -> None:
                if cancel_event and cancel_event.is_set():
                    return
                qr_seen["n"] += 1
                if qr_seen["n"] == 1:
                    info(f"账号「{acc.id}」已生成扫码二维码")
                _status(t("qr.status_scan"))
                try:
                    on_qr(data)
                except Exception as exc:
                    warning(f"账号「{acc.id}」推送二维码到界面失败：{exc}")

            @client.event(PairStatusEv)
            async def _pair(_c, ev: PairStatusEv) -> None:
                if ev.Status == PairStatusMsg.SUCCESS:
                    _status(t("qr.status_pair_ok"))
                    info(f"账号「{acc.id}」配对成功")
                elif ev.Status == PairStatusMsg.ERROR:
                    fail_msg[0] = pair_error_message(ev.Error)
                    failed_ev.set()
                    error(f"账号「{acc.id}」配对失败：{ev.Error}")

            @client.event(ConnectedEv)
            async def _connected(_c, _ev: ConnectedEv) -> None:
                nonlocal ok, msg
                ok = True
                msg = t("qr.status_login_ok")
                connected_ev.set()
                info(f"账号「{acc.id}」已连接 WhatsApp")

            @client.event(ConnectFailureEv)
            async def _cf(_c, ev: ConnectFailureEv) -> None:
                fail_msg[0] = connect_failure_message(ev.Reason, ev.Message or "")
                failed_ev.set()

            @client.event(LoggedOutEv)
            async def _lo(_c, ev: LoggedOutEv) -> None:
                fail_msg[0] = connect_failure_message(ev.Reason, "已登出")
                failed_ev.set()

            @client.event(DisconnectedEv)
            async def _dc(_c, _ev: DisconnectedEv) -> None:
                pass

            _status(t("qr.status_connecting"))
            await client.connect()
            if not (acc.proxy or "").strip():
                _status(t("qr.status_wait_qr"))

            deadline = time.monotonic() + _PAIR_WAIT_SEC
            while time.monotonic() < deadline:
                if cancel_event and cancel_event.is_set():
                    msg = t("common.cancelled")
                    return
                if failed_ev.is_set():
                    msg = fail_msg[0] or t("qr.pair_fail")
                    return
                if connected_ev.is_set() or getattr(client, "connected", False):
                    ok = True
                    msg = t("qr.status_login_ok")
                    _status(t("qr.status_saving"))
                    if await _wait_session_persisted(acc):
                        info(f"账号「{acc.id}」会话已写入本地")
                    else:
                        warning(f"账号「{acc.id}」会话文件尚未检测到，仍将尝试上线")
                    # 先通知 UI 关闭弹窗，再在后台释放连接（避免 stop 卡住界面）
                    notify_ui(True, msg)
                    return
                await asyncio.sleep(0.2)

            msg = fail_msg[0] or t("qr.timeout")

        try:
            asyncio.run(main())
        except Exception as exc:
            if not ok:
                msg = fail_msg[0] or str(exc) or t("qr.login_fail")
                error(f"登录异常：{exc}")
        finally:
            if client is not None:
                _release_client_background(client, acc.id)

        if cancel_event and cancel_event.is_set() and not ok:
            msg = t("common.cancelled")
        if not ui_notified:
            notify_ui(
                ok,
                msg or (t("qr.status_login_ok") if ok else t("qr.login_fail")),
            )

    from shutdown import track_background_thread

    login_thread = track_background_thread(
        threading.Thread(target=work, name=f"wa-qr-login-{acc.id}", daemon=True)
    )
    login_thread.start()
    return login_thread
