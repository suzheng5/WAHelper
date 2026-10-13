"""通过现有 Telegram session 查询当前及历史登录账号的手机号。"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from telethon import TelegramClient


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else ROOT / "dist" / "WAHelper"
)


def _clone_session(source: Path, target: Path) -> None:
    """用 SQLite backup 得到一致快照，避免查询过程占用原 session。"""
    src: sqlite3.Connection | None = None
    dst: sqlite3.Connection | None = None
    try:
        src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
        dst = sqlite3.connect(target)
        src.backup(dst)
        return
    except sqlite3.Error:
        pass
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()
    shutil.copy2(source, target)


def _name(user: Any) -> str:
    return " ".join(
        x for x in (str(getattr(user, "first_name", "") or "").strip(),
                    str(getattr(user, "last_name", "") or "").strip()) if x
    )


async def _query_one(
    row: dict[str, str],
    *,
    api_id: int,
    api_hash: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, str]:
    source = Path(row.pop("_session_path"))
    configured_phone = row["手机号码"]
    if not source.is_file():
        row["状态"] = "session 文件不存在"
        return row

    async with semaphore:
        with tempfile.TemporaryDirectory(prefix="tg-phone-query-") as temp_dir:
            base = Path(temp_dir) / "account"
            cloned = base.with_suffix(".session")
            try:
                _clone_session(source, cloned)
            except OSError as exc:
                row["状态"] = f"无法读取 session：{exc}"
                return row

            client = TelegramClient(
                str(base),
                api_id,
                api_hash,
                connection_retries=1,
                request_retries=1,
                timeout=12,
            )
            try:
                await asyncio.wait_for(client.connect(), timeout=20)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=12):
                    row["状态"] = "未登录或 session 已失效"
                    return row
                user = await asyncio.wait_for(client.get_me(), timeout=15)
                if user is None:
                    row["状态"] = "无法取得账号资料"
                    return row
                phone = str(getattr(user, "phone", "") or "").strip()
                row["手机号码"] = f"+{phone}" if phone else configured_phone
                username = str(getattr(user, "username", "") or "").strip()
                row["用户名"] = f"@{username}" if username else ""
                row["姓名"] = _name(user)
                row["Telegram用户ID"] = str(getattr(user, "id", "") or "")
                row["状态"] = "查询成功" if phone else "已登录，但账号未公开手机号"
                return row
            except asyncio.TimeoutError:
                row["状态"] = "连接超时"
                return row
            except Exception as exc:
                row["状态"] = f"查询失败：{type(exc).__name__}"
                return row
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass
                try:
                    client.session.close()
                except Exception:
                    pass


def _load_accounts(app_dir: Path) -> tuple[int, str, list[dict[str, str]]]:
    tg_dir = app_dir / "telegram"
    config = json.loads((tg_dir / "config.json").read_text(encoding="utf-8-sig"))
    api_id = int(config.get("api_id") or 0)
    api_hash = str(config.get("api_hash") or "").strip()
    sessions_dir = tg_dir / "sessions"

    configured: dict[str, dict[str, Any]] = {}
    for account in config.get("accounts") or []:
        session = str(account.get("session_name") or account.get("id") or "").strip()
        if session:
            configured[session] = account

    session_names = set(configured)
    session_names.update(path.stem for path in sessions_dir.glob("*.session"))
    rows: list[dict[str, str]] = []
    for session in sorted(session_names):
        account = configured.get(session) or {}
        phone = str(account.get("phone") or "").strip()
        if phone and not phone.startswith("+"):
            phone = f"+{phone}"
        rows.append(
            {
                "账号名称": str(account.get("id") or f"历史会话：{session}"),
                "手机号码": phone,
                "用户名": "",
                "姓名": "",
                "Telegram用户ID": "",
                "当前账号": "是" if session in configured else "否",
                "已启用": "是" if account.get("enabled", False) else "否",
                "状态": "待查询",
                "_session_path": str(sessions_dir / f"{session}.session"),
            }
        )
    return api_id, api_hash, rows


async def _run(app_dir: Path, limit: int, concurrency: int) -> list[dict[str, str]]:
    api_id, api_hash, rows = _load_accounts(app_dir)
    if api_id <= 0 or not api_hash:
        raise RuntimeError("Telegram config.json 缺少 api_id 或 api_hash")
    if limit > 0:
        rows = rows[:limit]
    semaphore = asyncio.Semaphore(max(1, concurrency))
    total = len(rows)

    async def run_index(index: int, row: dict[str, str]) -> dict[str, str]:
        print(f"[{index}/{total}] 正在查询：{row['账号名称']}")
        result = await _query_one(
            row, api_id=api_id, api_hash=api_hash, semaphore=semaphore
        )
        print(f"[{index}/{total}] {result['账号名称']}：{result['状态']}")
        return result

    return list(
        await asyncio.gather(
            *(run_index(i, row) for i, row in enumerate(rows, start=1))
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="查询 TG 已登录账号手机号")
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=0, help="仅测试前 N 个会话")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--no-pause", action="store_true", help="完成后不等待回车")
    args = parser.parse_args()

    app_dir = args.app_dir.resolve()
    try:
        rows = asyncio.run(_run(app_dir, args.limit, args.concurrency))
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"查询失败：{exc}")
        return 1

    output = args.output or app_dir / "TG已登录账号手机号.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "账号名称",
        "手机号码",
        "用户名",
        "姓名",
        "Telegram用户ID",
        "当前账号",
        "已启用",
        "状态",
    )
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    success = sum(row["状态"].startswith(("查询成功", "已登录")) for row in rows)
    print(f"\n查询完成：{success}/{len(rows)} 个会话仍有效")
    print(f"结果已保存：{output}")
    if getattr(sys, "frozen", False) and not args.no_pause:
        try:
            input("\n按回车键退出…")
        except EOFError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
