"""单线程 asyncio：监听与定时任务共享同一套 TelegramClient，避免 .session 数据库锁冲突。"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple, Any

from telethon import TelegramClient
from telethon.errors import RPCError

from .compat_config import Account, AppConfig
from .listener import (
    AddressBookResolver,
    ListenerController,
    _resolve_watch_rules,
    resolve_address_book_refs_with_owner_retry,
)
from .logger_util import error, info, warning
from .scheduler import ScheduleRunner, load_jobs
from .watch_membership_audit import WatchAuditRow, audit_address_book_watch_users

# 与登录前停服务一致：重载/关闭须等旧 asyncio 线程退出，避免双 loop 共用 client 导致发送失败与重复重试。
DEFAULT_JOIN_TIMEOUT = 28.0


class TelethonCoordinator:
    def __init__(self, listener: ListenerController, scheduler: ScheduleRunner) -> None:
        self._listener = listener
        self._scheduler = scheduler
        scheduler.bind_read_tracker(listener.read_tracker)
        self._thread: Optional[threading.Thread] = None
        self._orphan_thread: Optional[threading.Thread] = None
        self._svc_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._clients_by_id: Dict[str, TelegramClient] = {}
        self._address_resolver = AddressBookResolver()
        self._reconnect_busy = False
        self._address_warning_callback: Optional[Callable[[str, str, int], None]] = None

    def set_address_warning_callback(
        self, callback: Optional[Callable[[str, str, int], None]]
    ) -> None:
        """通讯录新增/变更解析成非超级群时通知 UI。"""
        self._address_warning_callback = callback

    def has_connected_clients(self) -> bool:
        return bool(self._clients_by_id)

    def connected_account_ids(self) -> Set[str]:
        return set(self._clients_by_id.keys())

    def apply_config_hot(self, cfg: AppConfig) -> None:
        """通讯录/监听变更后在线解析群并刷新监听，无需整程序重启。"""
        if self._orphan_thread is not None and self._orphan_thread.is_alive():
            warning(
                "无法热更新：上一 Telegram 会话线程仍在退出中。"
                "请稍候再试，或点「保存并重载服务」。"
            )
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            info("通讯录已保存；请点侧栏「保存并重载服务」，或等待 Telegram 连接完成后再试。")
            return
        if not self._clients_by_id:
            info("通讯录已保存；当前无在线账号，请先登录账号或「保存并重载服务」。")
            return
        asyncio.run_coroutine_threadsafe(self._apply_config_async(cfg), loop)

    async def _apply_config_async(self, cfg: AppConfig) -> None:
        clients = self._clients_by_id
        if not clients:
            return
        client = next(iter(clients.values()))
        await resolve_address_book_refs_with_owner_retry(
            client,
            cfg,
            clients,
            resolver=self._address_resolver,
            full=False,
            on_non_supergroup=self._address_warning_callback,
        )
        self._scheduler.refresh_config(cfg)
        # 须按最新 cfg 同步开关：此前若启动时监听为关，仅改规则页保存不会生效
        if not self._listener.apply_config(cfg):
            info("通讯录已更新：群标识已解析（监听未开启）")
            return
        rules = await _resolve_watch_rules(
            client, cfg, clients, resolver=self._address_resolver, full=False
        )
        rate = float(cfg.rate_limit_seconds)
        if rules:
            for c in clients.values():
                self._listener.register_client_handlers(c, rules, rate)
            info(f"通讯录已更新：已解析 {len(rules)} 条监听绑定并立即生效")
        else:
            self._listener.set_watch_rules({})
            warning("通讯录已更新，但未能解析任何「参与监听」的群/用户绑定")

    def request_watch_membership_audit(
        self,
        cfg: AppConfig,
        on_done: Callable[[Dict[str, WatchAuditRow]], None],
    ) -> bool:
        loop = self._loop
        clients = dict(self._clients_by_id)
        if loop is None or not loop.is_running() or not clients:
            return False

        def worker() -> None:
            fut = asyncio.run_coroutine_threadsafe(
                audit_address_book_watch_users(cfg, clients), loop
            )
            try:
                result = fut.result(timeout=600)
            except Exception as exc:
                warning(f"群成员检测失败：{exc}")
                result = {}
            try:
                on_done(result)
            except Exception:
                pass

        threading.Thread(target=worker, name="tg-watch-audit", daemon=True).start()
        return True

    def request_bulk_image_send(
        self,
        job_ids: List[str],
        image_path: str = "",
        *,
        image_paths: Optional[List[str]] = None,
        on_progress: Optional[Callable[[int, int, Any], None]] = None,
        on_done: Optional[Callable[[int, int, int], None]] = None,
        sync_to_customer: bool = False,
        customer_extra_text: str = "",
    ) -> bool:
        """在统一会话线程排队发图。成功返回 True（已提交）；无 loop/无连接则 False。"""
        loop = self._loop
        if loop is None or not loop.is_running() or not self._clients_by_id:
            return False
        ids = list(job_ids)
        paths = list(image_paths or [])
        if (image_path or "").strip():
            paths.append(image_path.strip())
        extra = (customer_extra_text or "").strip()
        timeout_sec = 3600.0
        if sync_to_customer:
            timeout_sec = max(3600.0, 120.0 * max(1, len(ids)) + 600.0)

        def worker() -> None:
            fut = asyncio.run_coroutine_threadsafe(
                self._scheduler.run_bulk_image_send(
                    ids,
                    image_paths=paths,
                    on_progress=on_progress,
                    sync_to_customer=sync_to_customer,
                    customer_extra_text=extra,
                ),
                loop,
            )
            try:
                ok, fail, resumed = fut.result(timeout=timeout_sec)
            except Exception as exc:
                warning(f"一键发图失败：{exc}")
                ok = fail = resumed = 0
                fail = max(fail, len(ids))
            if on_done:
                try:
                    on_done(ok, fail, resumed)
                except Exception:
                    pass

        threading.Thread(target=worker, name="tg-bulk-image", daemon=True).start()
        return True

    def _session_threads(self) -> List[threading.Thread]:
        out: List[threading.Thread] = []
        for t in (self._thread, self._orphan_thread):
            if t is not None and t not in out:
                out.append(t)
        return out

    def session_thread_alive(self) -> bool:
        return any(t.is_alive() for t in self._session_threads())

    def start(self, cfg: AppConfig) -> bool:
        if self._svc_running and self.session_thread_alive():
            warning("Telegram 统一会话已在运行，跳过重复启动")
            return True
        if not self.stop(join_timeout=DEFAULT_JOIN_TIMEOUT):
            error(
                "无法启动 Telegram 统一会话：上一会话线程仍在运行。"
                "请先暂停全部定时任务，等待约半分钟后再点「保存并重载服务」；"
                "若仍失败，请完全退出程序后重新打开。"
            )
            self._svc_running = False
            return False
        self._svc_running = True

        def run() -> None:
            try:
                asyncio.run(self._async_run(cfg))
            finally:
                if self._thread is threading.current_thread():
                    self._thread = None

        t = threading.Thread(target=run, name="telethon-coordinator", daemon=True)
        self._thread = t
        self._orphan_thread = None
        t.start()
        info("Telegram 统一会话线程已启动（监听 + 定时任务）")
        return True

    def stop(self, join_timeout: float = DEFAULT_JOIN_TIMEOUT) -> bool:
        """请求停止并等待后台线程结束。返回 True 表示可安全再次 start。"""
        self._svc_running = False
        loop = self._loop
        if loop is not None and loop.is_running():
            def _cancel_tasks() -> None:
                for task in asyncio.all_tasks(loop):
                    task.cancel()

            try:
                loop.call_soon_threadsafe(_cancel_tasks)
            except RuntimeError:
                pass
        self._listener.stop()
        self._scheduler.stop()
        to_join = [t for t in self._session_threads() if t.is_alive()]

        still_alive: List[threading.Thread] = []
        deadline = time.monotonic() + max(0.05, float(join_timeout))
        for t in to_join:
            if t is threading.current_thread():
                continue
            while t.is_alive() and time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                t.join(timeout=min(1.0, max(0.05, remaining)))
            if t.is_alive():
                still_alive.append(t)

        if still_alive:
            self._orphan_thread = still_alive[0]
            names = ", ".join(t.name or "telethon-coordinator" for t in still_alive)
            warning(
                f"Telegram 统一会话线程在 {join_timeout:.0f}s 内仍未退出（{names}）。"
                "已禁止启动新会话，以免 event loop 冲突导致发送失败或重复消息。"
                "请先暂停定时任务，稍候再重载；或完全退出程序后重开。"
            )
            return False

        self._thread = None
        self._orphan_thread = None
        self._loop = None
        self._clients_by_id = {}
        self._address_resolver.clear()
        info("Telegram 统一会话线程已停止")
        return True

    def is_running(self) -> bool:
        return bool(self._svc_running and self.session_thread_alive())

    def request_reconnect_offline(
        self,
        cfg: AppConfig,
        on_done: Optional[Callable[[int, int, int], None]] = None,
    ) -> bool:
        """在已运行的会话线程上补连未在线的已启用账号。成功提交返回 True。"""
        loop = self._loop
        if (
            loop is None
            or not loop.is_running()
            or not self._svc_running
            or self._reconnect_busy
        ):
            return False
        self._reconnect_busy = True

        def worker() -> None:
            ok = fail = skip = 0
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._reconnect_offline_async(cfg), loop
                )
                ok, fail, skip = fut.result(timeout=900)
            except Exception as exc:
                warning(f"重连未连接账号失败：{exc}")
                fail = max(fail, 1)
            finally:
                self._reconnect_busy = False
            if on_done:
                try:
                    on_done(ok, fail, skip)
                except Exception:
                    pass

        threading.Thread(target=worker, name="tg-reconnect-offline", daemon=True).start()
        return True

    def request_connect_account(
        self,
        cfg: AppConfig,
        account_id: str,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ) -> bool:
        """不停止现有服务，只把指定的新登录账号热接入统一会话线程。"""
        loop = self._loop
        aid = (account_id or "").strip()
        if (
            not aid
            or loop is None
            or not loop.is_running()
            or not self._svc_running
        ):
            return False

        def worker() -> None:
            ok = False
            message = ""
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._connect_account_async(cfg, aid), loop
                )
                ok, message = fut.result(timeout=180)
            except Exception as exc:
                message = str(exc)
                warning(f"热接入账号「{aid}」失败：{exc}")
            if on_done:
                try:
                    on_done(ok, message)
                except Exception:
                    pass

        threading.Thread(
            target=worker,
            name=f"tg-connect-{aid}",
            daemon=True,
        ).start()
        return True

    async def _connect_account_async(
        self, cfg: AppConfig, account_id: str
    ) -> Tuple[bool, str]:
        if account_id in self._clients_by_id:
            return True, f"账号「{account_id}」已在线"
        acc = next(
            (
                row
                for row in cfg.accounts
                if row.id == account_id and row.enabled
            ),
            None,
        )
        if acc is None:
            return False, f"账号「{account_id}」不存在或未启用"
        if not int(cfg.api_id) or not str(cfg.api_hash).strip():
            return False, "未配置 api_id / api_hash"

        client = await self._try_connect_account(acc, cfg)
        if client is None:
            return False, f"账号「{account_id}」登录成功，但热接入失败"
        if not self._svc_running:
            try:
                await client.disconnect()
            except Exception:
                pass
            return False, "Telegram 服务已停止"

        self._clients_by_id[account_id] = client
        clients_by_id = dict(self._clients_by_id)
        self._scheduler.refresh_config(cfg)
        self._scheduler.bind_telegram_clients(clients_by_id)
        if self._listener.listen_enabled():
            try:
                primary = next(iter(clients_by_id.values()))
                resolved = await _resolve_watch_rules(
                    primary,
                    cfg,
                    clients_by_id,
                    resolver=self._address_resolver,
                    full=False,
                )
                if resolved:
                    self._listener.register_client_handlers(
                        client,
                        resolved,
                        float(cfg.rate_limit_seconds),
                    )
            except Exception as exc:
                warning(f"账号「{account_id}」热接入后刷新监听失败：{exc}")
        info(f"账号「{account_id}」已热接入，现有任务未中断")
        return True, f"账号「{account_id}」已连接"

    async def _try_connect_account(
        self, acc: Account, cfg: AppConfig
    ) -> Optional[TelegramClient]:
        """老版串行连接单个账号；失败返回 None。"""
        client = TelegramClient(acc.session_path(), cfg.api_id, cfg.api_hash)
        try:
            info(f"Telegram：正在连接「{acc.id}」…")
            await asyncio.wait_for(client.connect(), timeout=45.0)
        except asyncio.TimeoutError:
            warning(f"连接超时 {acc.id}：45 秒内无响应（请检查网络/代理能否访问 Telegram）")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None
        except RPCError as exc:
            warning(f"连接失败 {acc.id}：{exc}")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None
        except Exception as exc:
            error(
                f"连接失败（非 RPC）{acc.id}：{exc}"
                "（若提示 database is locked，请关闭另一份本程序或占用该 .session 的其它工具）"
            )
            try:
                await client.disconnect()
            except Exception:
                pass
            return None
        if not await client.is_user_authorized():
            warning(f"账号未登录，跳过：{acc.id}")
            try:
                await client.disconnect()
            except Exception:
                pass
            return None
        info(f"已连接账号：{acc.id}")
        return client

    async def _reconnect_offline_async(
        self, cfg: AppConfig
    ) -> Tuple[int, int, int]:
        online = set(self._clients_by_id.keys())
        targets = [
            acc
            for acc in cfg.accounts
            if acc.enabled and acc.id not in online
        ]
        if not targets:
            info("没有需要重连的 Telegram 账号")
            return 0, 0, 0

        if not int(cfg.api_id) or not str(cfg.api_hash).strip():
            warning("未配置 api_id / api_hash，无法重连")
            return 0, len(targets), 0

        info(f"开始重连未连接账号：共 {len(targets)} 个…")
        ok = fail = 0
        newly: List[TelegramClient] = []
        for acc in targets:
            if not self._svc_running:
                break
            if acc.id in self._clients_by_id:
                continue
            client = await self._try_connect_account(acc, cfg)
            if client is None:
                fail += 1
                continue
            self._clients_by_id[acc.id] = client
            newly.append(client)
            ok += 1

        clients_by_id = dict(self._clients_by_id)
        self._scheduler.bind_telegram_clients(clients_by_id)
        if newly and self._listener.listen_enabled() and clients_by_id:
            try:
                primary = next(iter(clients_by_id.values()))
                resolved = await _resolve_watch_rules(
                    primary,
                    cfg,
                    clients_by_id,
                    resolver=self._address_resolver,
                    full=False,
                )
                if resolved:
                    rate = float(cfg.rate_limit_seconds)
                    for client in newly:
                        self._listener.register_client_handlers(
                            client, resolved, rate
                        )
            except Exception as exc:
                warning(f"重连后刷新监听规则失败：{exc}")
        info(f"重连未连接账号完成：成功 {ok}，失败 {fail}")
        return ok, fail, 0

    async def _async_run(self, cfg: AppConfig) -> None:
        """老版连接方式：串行 await connect()，全部连完后再启动监听/定时循环。"""
        self._loop = asyncio.get_running_loop()
        self._clients_by_id = {}
        self._listener._running = True  # noqa: SLF001
        self._scheduler._running = True  # noqa: SLF001

        accounts = [a for a in cfg.accounts if a.enabled]
        connected: List[Tuple[Account, TelegramClient]] = []

        if not int(cfg.api_id) or not str(cfg.api_hash).strip():
            warning("未配置 api_id / api_hash：无法连接 Telegram，定时任务将只能排队无法发送")
            self._scheduler.bind_telegram_clients({})
            try:
                await asyncio.gather(
                    self._listener.idle_forever(),
                    self._scheduler._async_main(),  # noqa: SLF001
                )
            finally:
                self._listener._running = False  # noqa: SLF001
                self._scheduler.unbind_telegram_clients()
                self._scheduler._running = False  # noqa: SLF001
                self._loop = None
                self._clients_by_id = {}
            return

        info(f"Telegram：准备依次连接 {len(accounts)} 个已启用账号…")
        self._clients_by_id = {}
        for acc in accounts:
            if not self._svc_running:
                break
            client = await self._try_connect_account(acc, cfg)
            if client is None:
                continue
            connected.append((acc, client))
            self._clients_by_id[acc.id] = client
            if len(self._clients_by_id) == 1 or len(self._clients_by_id) % 5 == 0:
                info(
                    f"Telegram：已连接 {len(self._clients_by_id)}/{len(accounts)} 个账号…"
                )

        clients_by_id: Dict[str, TelegramClient] = dict(self._clients_by_id)
        if not clients_by_id:
            error(
                "Telegram：没有任何账号连接成功，定时任务将不会发出消息。"
                "请在本软件完成各账号登录；并确认未同时打开第二份本程序、未用其它工具占用 sessions 目录下同名 .session。"
            )
        else:
            info(
                f"Telegram：连接阶段结束，成功 {len(clients_by_id)}/{len(accounts)} 个账号"
            )

        try:
            self._scheduler.bind_telegram_clients(clients_by_id)
            try:
                nj = len(load_jobs())
                n_run = sum(1 for x in load_jobs() if x.enabled and x.state == "running")
                n_steps = sum(x.item_count() for x in load_jobs())
                info(f"定时载入：文档任务 {nj} 个 / {n_steps} 步，运行中 {n_run} 个。")
            except Exception:
                pass

            if connected:
                primary = connected[0][1]
                await resolve_address_book_refs_with_owner_retry(
                    primary, cfg, clients_by_id, resolver=self._address_resolver, full=True
                )

            if self._listener.listen_enabled() and connected:
                resolved = await _resolve_watch_rules(
                    connected[0][1], cfg, clients_by_id, resolver=self._address_resolver, full=True
                )
                if resolved:
                    rate = float(cfg.rate_limit_seconds)
                    for _, client in connected:
                        self._listener.register_client_handlers(client, resolved, rate)
                else:
                    warning("没有可用的群组绑定，未注册监听事件（定时任务仍可用）")

            await asyncio.gather(
                self._listener.idle_forever(),
                self._scheduler._async_main(),  # noqa: SLF001
            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            error(f"Telegram 统一会话异常：{exc}")
        finally:
            # 含启动时连接 + 中途重连补上的客户端
            for client in list(self._clients_by_id.values()):
                try:
                    await client.disconnect()
                except Exception:
                    pass
            self._listener._running = False  # noqa: SLF001
            self._scheduler.unbind_telegram_clients()
            self._scheduler._running = False  # noqa: SLF001
            self._loop = None
            self._clients_by_id = {}
            self._address_resolver.clear()
            self._reconnect_busy = False
            info("Telegram 会话已断开")
