"""成员检测：客户端候选顺序与归属离线回退（不连网）。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
for p in (str(ROOT), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_wa_clients_order_and_offline_fallback() -> None:
    from watch_membership_audit import _clients_for_entry, audit_address_book_watch_users

    c1, c2, c3 = object(), object(), object()
    clients = {"a": c1, "b": c2, "c": c3}
    ordered = _clients_for_entry(clients, c1, "b")
    assert ordered[0] is c2 and ordered[1] is c1 and c3 in ordered

    # 归属离线：仍应包含其它在线账号
    ordered2 = _clients_for_entry(clients, c1, "missing")
    assert c1 in ordered2 and c2 in ordered2 and c3 in ordered2

    async def _run() -> None:
        cfg = SimpleNamespace(
            address_book=[
                SimpleNamespace(
                    id="e1",
                    remark="g1",
                    chat_ref="",
                    invite_link="",
                    watch_user="8613800138000",
                    listen_enabled=True,
                    owner_account_id="offline_owner",
                )
            ]
        )
        # 无真实 WA client 时只验证不会因 owner 离线直接 OFFLINE 短路到空结果前：
        # clients 非空但解析会失败 → ERROR，而不是 OFFLINE early-exit
        class Dummy:
            pass

        out = await audit_address_book_watch_users(cfg, {"a": Dummy()})  # type: ignore[arg-type]
        assert out["e1"].status.value == "error"
        assert "未在线" in (out["e1"].detail or "") or "群" in (out["e1"].detail or "")

    asyncio.run(_run())
    print("wa audit client fallback ok")


def test_tg_clients_order() -> None:
    # 避免加载 telethon：直接 exec 模块内辅助函数不可行，改为导入后测
    # 若环境无 telethon 则跳过
    try:
        from tg_multi_listener.watch_membership_audit import _clients_for_entry
    except Exception as exc:
        print("skip tg:", exc)
        return
    c1, c2, c3 = object(), object(), object()
    clients = {"a": c1, "b": c2, "c": c3}
    ordered = _clients_for_entry(clients, c1, "c")  # type: ignore[arg-type]
    assert ordered[0] is c3 and ordered[1] is c1 and c2 in ordered
    ordered2 = _clients_for_entry(clients, c1, "gone")  # type: ignore[arg-type]
    assert ordered2[0] is c1 and len(ordered2) == 3
    print("tg audit client order ok")


if __name__ == "__main__":
    test_wa_clients_order_and_offline_fallback()
    test_tg_clients_order()
    print("all ok")
