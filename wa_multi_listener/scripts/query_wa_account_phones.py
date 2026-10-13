"""只读查询 WhatsApp 当前及历史登录会话对应的手机号。"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APP_DIR = ROOT / "dist" / "WAHelper"


def _phone_from_jid(value: object) -> str:
    text = str(value or "").strip()
    user = text.split("@", 1)[0].split(":", 1)[0]
    digits = re.sub(r"\D", "", user)
    return f"+{digits}" if len(digits) >= 7 else ""


def _read_devices(db_path: Path) -> list[tuple[str, str, str]]:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=2.0) as con:
            rows = con.execute(
                "SELECT jid, push_name, business_name FROM whatsmeow_device"
            ).fetchall()
    except (OSError, sqlite3.Error):
        return []
    result: list[tuple[str, str, str]] = []
    for jid, push_name, business_name in rows:
        phone = _phone_from_jid(jid)
        if phone:
            result.append(
                (phone, str(push_name or "").strip(), str(business_name or "").strip())
            )
    return result


def query(app_dir: Path) -> list[dict[str, str]]:
    wa_dir = app_dir / "whatsapp"
    sessions_dir = wa_dir / "sessions"
    config_path = wa_dir / "config.json"

    accounts: list[dict] = []
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8-sig"))
            accounts = list(data.get("accounts") or [])
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    labels_by_session: dict[str, list[str]] = defaultdict(list)
    enabled_by_session: dict[str, bool] = {}
    for account in accounts:
        session = str(account.get("session_name") or "").strip()
        label = str(account.get("id") or "").strip()
        if session and label:
            labels_by_session[session].append(label)
            enabled_by_session[session] = bool(account.get("enabled", True))

    by_phone: dict[str, dict[str, object]] = {}
    for db_path in sorted(sessions_dir.glob("*.db")):
        session = db_path.stem
        labels = labels_by_session.get(session) or ["历史会话"]
        for phone, push_name, business_name in _read_devices(db_path):
            row = by_phone.setdefault(
                phone,
                {
                    "phone": phone,
                    "accounts": set(),
                    "push_names": set(),
                    "business_names": set(),
                    "sessions": set(),
                    "current": False,
                    "enabled": False,
                },
            )
            row["accounts"].update(labels)  # type: ignore[union-attr]
            if push_name:
                row["push_names"].add(push_name)  # type: ignore[union-attr]
            if business_name:
                row["business_names"].add(business_name)  # type: ignore[union-attr]
            row["sessions"].add(db_path.name)  # type: ignore[union-attr]
            if session in labels_by_session:
                row["current"] = True
                row["enabled"] = bool(enabled_by_session.get(session))

    output: list[dict[str, str]] = []
    for phone in sorted(by_phone):
        row = by_phone[phone]
        output.append(
            {
                "账号名称": "、".join(sorted(row["accounts"])),  # type: ignore[arg-type]
                "手机号码": phone,
                "当前账号": "是" if row["current"] else "否",
                "已启用": "是" if row["enabled"] else "否",
                "WhatsApp名称": "、".join(sorted(row["push_names"])),  # type: ignore[arg-type]
                "商业名称": "、".join(sorted(row["business_names"])),  # type: ignore[arg-type]
                "会话文件数": str(len(row["sessions"])),  # type: ignore[arg-type]
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="查询 WS 已登录账号手机号")
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    app_dir = args.app_dir.resolve()
    rows = query(app_dir)
    output = args.output or app_dir / "WS已登录账号手机号.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "账号名称",
        "手机号码",
        "当前账号",
        "已启用",
        "WhatsApp名称",
        "商业名称",
        "会话文件数",
    )
    with output.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"查询完成：共找到 {len(rows)} 个已登录手机号")
    for row in rows:
        print(f"{row['账号名称']:<20} {row['手机号码']}")
    print(f"\n结果已保存：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
