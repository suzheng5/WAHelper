"""快速测试 Telegram session 是否能在当前 api 下连上（不启动 GUI）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TG_ROOT = os.path.join(ROOT, "dist", "WAHelper", "telegram")
sys.path.insert(0, os.path.join(ROOT, "..", "tg_multi_listener"))
sys.path.insert(0, os.path.join(ROOT, ".."))
os.environ["TG_HELPER_DATA_ROOT"] = TG_ROOT


async def main() -> int:
    from telethon import TelegramClient

    cfg_path = os.path.join(TG_ROOT, "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    api_id = int(cfg["api_id"])
    api_hash = str(cfg["api_hash"])
    accounts = [a for a in cfg.get("accounts", []) if a.get("enabled", True)]
    if not accounts:
        print("无已启用账号")
        return 1
    acc = accounts[0]
    sess = os.path.join(TG_ROOT, "sessions", f"{acc['session_name']}.session")
    print(f"api_id={api_id}")
    print(f"测试账号={acc['id']} session={sess}")
    if not os.path.isfile(sess):
        print("session 文件不存在")
        return 1
    client = TelegramClient(sess, api_id, api_hash)
    try:
        await asyncio.wait_for(client.connect(), timeout=45)
        ok = await client.is_user_authorized()
        me = await client.get_me() if ok else None
        print(f"connect=ok authorized={ok} user={getattr(me, 'username', None)}")
        return 0 if ok else 2
    except Exception as exc:
        print(f"连接失败: {exc}")
        return 3
    finally:
        await client.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
