"""WhatsApp 客户端公共配置与连接辅助。"""
from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING, Optional, Tuple

from config import Account

if TYPE_CHECKING:
    from listener import ListenerController
from logger_util import info, warning
from neonize.aioze.client import ClientFactory, NewAClient
from neonize.aioze.events import EVENT_TO_INT, MessageEv
from neonize.aioze.events import ConnectedEv, ConnectFailureEv, LoggedOutEv
from neonize.proto.waCompanionReg.WAWebProtobufsCompanionReg_pb2 import DeviceProps
from wa_proxy import apply_proxy, clear_proxy

_CONNECT_TIMEOUT_DIRECT = 30.0
_CONNECT_TIMEOUT_PROXY = 30.0

_CONNECT_FAIL_ZH = {
    1: "连接失败（一般错误）",
    2: "已登出，请重新扫码",
    3: "账号被临时限制，请稍后再试",
    4: "主设备已离线，请先在手机上打开 WhatsApp",
    5: "未知登出，请清除会话后重新扫码",
    6: "客户端版本过旧，请更新本软件或 neonize",
    7: "设备标识异常",
    8: "WhatsApp 服务器错误，请稍后重试",
    9: "实验功能限制",
    10: "WhatsApp 服务不可用，请稍后重试",
}


def make_device_props() -> DeviceProps:
    """模拟官方 WhatsApp Web（Chrome），降低「无法关联设备」概率。"""
    return DeviceProps(os="Windows", platformType=DeviceProps.CHROME)


def connect_failure_message(reason: int, raw: str = "") -> str:
    base = _CONNECT_FAIL_ZH.get(int(reason), f"连接失败（代码 {reason}）")
    raw = (raw or "").strip()
    if raw:
        return f"{base}：{raw}"
    return base


def pair_error_message(err: str) -> str:
    t = (err or "").strip()
    if not t:
        return "配对失败（手机显示无法关联设备）"
    low = t.lower()
    if "link" in low or "关联" in t or "pair" in low:
        return (
            f"无法关联设备：{t}\n\n"
            "建议：① 手机 WhatsApp 升级到最新版 ② 点「清除会话并重新扫码」"
            " ③ 在手机「已连接的设备」里删掉旧的本程序设备 ④ 关闭 VPN 后重试"
        )
    return f"配对失败：{t}"


def new_client(acc: Account, listener: Optional["ListenerController"] = None) -> NewAClient:
    factory = ClientFactory(acc.db_path())
    if listener is not None:
        listener.ensure_message_subscription(factory)
        listener.ensure_group_info_subscription(factory)
    client = factory.new_client(uuid=acc.id, props=make_device_props())
    if listener is not None:
        listener.wrap_client_execute(client)
    if (acc.proxy or "").strip():
        apply_proxy(client, acc.id, acc.proxy)
    else:
        clear_proxy(client, acc.id)
    return client


def connect_timeout_seconds(acc: Account) -> float:
    if (acc.proxy or "").strip():
        return _CONNECT_TIMEOUT_PROXY
    return _CONNECT_TIMEOUT_DIRECT


async def establish_connection(client: NewAClient, acc: Account) -> Tuple[bool, str]:
    """启动连接并等待 ConnectedEv；勿 await connect_task（Neonize 长期运行，超时会被取消）。"""
    connected_ev = asyncio.Event()
    failed_ev = asyncio.Event()
    fail_msg: list[str] = [""]

    @client.event(ConnectedEv)
    async def _on_connected(_c, _ev: ConnectedEv) -> None:
        connected_ev.set()

    @client.event(ConnectFailureEv)
    async def _on_failure(_c, ev: ConnectFailureEv) -> None:
        fail_msg[0] = connect_failure_message(ev.Reason, ev.Message or "")
        failed_ev.set()

    @client.event(LoggedOutEv)
    async def _on_logged_out(_c, ev: LoggedOutEv) -> None:
        fail_msg[0] = connect_failure_message(ev.Reason, "已登出，请重新扫码")
        failed_ev.set()

    try:
        from neonize.aioze.events import EVENT_TO_INT, MessageEv

        msg_code = EVENT_TO_INT[MessageEv]
        codes = sorted(client.event.list_func.keys())
        if msg_code in client.event.list_func:
            info(f"账号「{acc.id}」连接前已登记 MessageEv（事件码 {msg_code}）")
        else:
            warning(
                f"账号「{acc.id}」连接前未登记 MessageEv，当前事件码={codes}；"
                "将无法接收群消息监听"
            )
    except Exception:
        pass

    t0 = time.monotonic()
    note_neonize_go_runtime()
    await client.connect()
    timeout = connect_timeout_seconds(acc)
    proxy_note = "（经 SOCKS5 代理）" if (acc.proxy or "").strip() else ""
    info(f"账号「{acc.id}」已向 WhatsApp 发起连接{proxy_note}，最长等待 {int(timeout)} 秒")
    deadline = time.monotonic() + timeout
    next_log_at = 15.0
    while time.monotonic() < deadline:
        if failed_ev.is_set():
            return False, fail_msg[0] or "连接失败"
        if connected_ev.is_set() or client.connected:
            elapsed = time.monotonic() - t0
            info(f"账号「{acc.id}」连接完成，耗时 {elapsed:.1f} 秒")
            return True, ""
        elapsed = time.monotonic() - t0
        if elapsed >= next_log_at:
            info(
                f"账号「{acc.id}」仍在等待 WhatsApp 响应… 已 {int(elapsed)} 秒"
                "（含代理握手 / WebSocket / 密钥同步，网络慢时会更久）"
            )
            next_log_at += 30.0
        await asyncio.sleep(0.25)
    hint = "连接超时"
    if (acc.proxy or "").strip():
        hint += "（已配置代理，请确认代理可用且格式正确）"
    else:
        hint += "（可尝试配置 SOCKS5 代理或重新扫码）"
    return False, hint


async def force_stop_account_uuid(account_id: str, db_path: str = "") -> None:
    """按账号 uuid 强制停止 Go 侧残留客户端（掉设备重登前必做）。"""
    aid = (account_id or "").strip()
    if not aid:
        return
    path = (db_path or "").strip() or ":memory:"
    try:
        note_neonize_go_runtime()
        ghost = NewAClient(path, None, make_device_props(), aid)
        await asyncio.wait_for(ghost.stop(), timeout=6.0)
    except Exception as exc:
        warning(f"强制停止账号「{aid}」残留连接时：{exc}")


async def release_wa_client(client: NewAClient, account_id: str = "") -> None:
    """彻底停止客户端并释放会话库文件句柄（重登前必须调用）。"""
    label = f"「{account_id}」" if account_id else ""
    task = getattr(client, "connect_task", None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except Exception:
            pass
    try:
        await asyncio.wait_for(client.stop(), timeout=8.0)
    except Exception as exc:
        warning(f"停止账号{label}客户端时：{exc}")
        try:
            await client.disconnect()
        except Exception:
            pass
    # Windows 上 neonize/SQLite 释放 .db 句柄往往滞后；多等一会再粉碎文件
    await asyncio.sleep(3.5)


def _session_sidecars(db_path: str) -> list[str]:
    return [db_path, db_path + "-shm", db_path + "-wal"]


def _clear_readonly(path: str) -> None:
    try:
        import stat

        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _win_force_delete(path: str) -> bool:
    """Windows：清属性后 DeleteFileW；失败再 DELAY_UNTIL_REBOOT（不阻塞当前登录）。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        kernel32.SetFileAttributesW.restype = wintypes.BOOL
        kernel32.DeleteFileW.argtypes = [wintypes.LPCWSTR]
        kernel32.DeleteFileW.restype = wintypes.BOOL
        kernel32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        kernel32.MoveFileExW.restype = wintypes.BOOL

        FILE_ATTRIBUTE_NORMAL = 0x80
        MOVEFILE_DELAY_UNTIL_REBOOT = 0x4

        kernel32.SetFileAttributesW(path, FILE_ATTRIBUTE_NORMAL)
        if kernel32.DeleteFileW(path):
            return True
        # 仍占用：登记重启后删除（当前路径若已改名则无影响）
        kernel32.MoveFileExW(path, None, MOVEFILE_DELAY_UNTIL_REBOOT)
    except Exception:
        return False
    return not os.path.isfile(path)


def _force_shred_file(path: str) -> bool:
    """尽量粉碎单个文件：清只读 → 删除 → Win API → 改名让出路径。"""
    if not os.path.isfile(path):
        return True
    _clear_readonly(path)
    try:
        os.remove(path)
        return True
    except OSError:
        pass
    if _win_force_delete(path):
        return True
    # 改名让出原路径（登录可建新库）；后台再删 stale
    stamp = int(time.time() * 1000)
    bak = f"{path}.shatter_{stamp}"
    try:
        os.replace(path, bak)
    except OSError:
        return False
    try:
        _clear_readonly(bak)
        os.remove(bak)
    except OSError:
        _win_force_delete(bak)
        if os.path.isfile(bak):
            warning(f"会话碎片暂无法删除（已让出路径）：{bak}")
    return True


def clear_session_files(
    acc: Account,
    *,
    retries: int = 8,
    delay_sec: float = 0.35,
    allow_rotate: bool = True,
    rotate_first: bool = False,
) -> bool:
    """删除会话库；强制粉碎仍失败时可换新 session_name 让出路径。成功返回 True。

    allow_rotate=True 且删不掉时会修改 ``acc.session_name``，调用方应写回 config。
    rotate_first=True：扫码重登时先换新空库路径，旧文件后台粉碎，避免占用拖死登录。
    """
    import threading
    import uuid

    def _shred_list(paths: list[str], label: str) -> None:
        for attempt in range(max(1, retries)):
            remaining: list[str] = []
            for p in paths:
                if not os.path.isfile(p):
                    continue
                if _force_shred_file(p):
                    continue
                remaining.append(p)
            if not remaining:
                return
            if attempt + 1 < retries:
                if attempt == 0 or (attempt + 1) % 4 == 0:
                    warning(
                        f"强制粉碎会话仍被占用（账号「{label}」，"
                        f"第 {attempt + 1}/{retries} 次）：{remaining[0]}"
                    )
                time.sleep(max(0.05, delay_sec))
        for p in paths:
            if not os.path.isfile(p):
                continue
            stamp = int(time.time() * 1000)
            bak = f"{p}.stale_{stamp}"
            try:
                os.replace(p, bak)
                warning(f"会话文件改名避让：{p} → {bak}")
                _force_shred_file(bak)
            except OSError as exc:
                warning(f"无法粉碎或改名会话文件 {p}：{exc}")

    old_path = acc.db_path()
    old_targets = _session_sidecars(old_path)

    if rotate_first and allow_rotate:
        # 先让出路径：登录立刻用全新空库，旧库稍后再清（常被 neonize 句柄占用）
        acc.session_name = uuid.uuid4().hex
        info(
            f"账号「{acc.id}」重登改用新会话文件 {acc.session_name}.db"
            "（旧文件将后台清理）"
        )

        def _bg() -> None:
            time.sleep(1.0)
            _shred_list(old_targets, acc.id)

        threading.Thread(
            target=_bg, name=f"wa-shred-{acc.id}", daemon=True
        ).start()
        return True

    path = acc.db_path()
    targets = _session_sidecars(path)
    last_err: OSError | None = None
    rotated = False

    for attempt in range(max(1, retries)):
        remaining: list[str] = []
        for p in targets:
            if not os.path.isfile(p):
                continue
            if _force_shred_file(p):
                continue
            remaining.append(p)
            last_err = OSError(f"仍被占用: {p}")
        if not remaining:
            info(
                f"已清除账号「{acc.id}」的本地会话"
                + ("（已换新会话文件名）" if rotated else "")
                + "，请重新扫码"
            )
            return True
        if attempt + 1 < retries:
            if attempt == 0 or (attempt + 1) % 4 == 0:
                warning(
                    f"强制粉碎会话仍被占用（账号「{acc.id}」，第 {attempt + 1}/{retries} 次）："
                    f"{remaining[0]}"
                    + (f" → {last_err}" if last_err else "")
                )
            time.sleep(max(0.05, delay_sec))

    if allow_rotate:
        old_targets = list(targets)
        acc.session_name = uuid.uuid4().hex
        rotated = True
        _shred_list(old_targets, acc.id)
        if not any(os.path.isfile(p) for p in _session_sidecars(acc.db_path())):
            info(
                f"已清除账号「{acc.id}」的本地会话（强制换新文件 "
                f"{acc.session_name}.db），请重新扫码"
            )
            return True

    warning(f"清除账号「{acc.id}」会话失败：{last_err}")
    return False


_go_runtime_touched = False


def note_neonize_go_runtime() -> None:
    """标记已调用 Go/neonize 运行时（连接或强制停号后需 StopAll 清理）。"""
    global _go_runtime_touched
    _go_runtime_touched = True


def neonize_runtime_active() -> bool:
    return _go_runtime_touched


async def stop_all_clients(*, linger_sec: float = 0.15, force: bool = False) -> None:
    global _go_runtime_touched
    if not force and not _go_runtime_touched:
        return
    try:
        await ClientFactory.stop()
    except Exception as exc:
        warning(f"停止 WhatsApp 连接时：{exc}")
    finally:
        _go_runtime_touched = False
    await asyncio.sleep(max(0.0, float(linger_sec)))


def stop_all_clients_sync(*, linger_sec: float = 0.15) -> None:
    try:
        asyncio.run(stop_all_clients(linger_sec=linger_sec))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(stop_all_clients(linger_sec=linger_sec))
        finally:
            loop.close()
