"""只读加载现有 WA/TG 任务并转换为统一展示记录。"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class TaskRecord:
    task_id: str
    platform: str
    title: str
    target: str
    source_name: str
    status: str
    cursor: int
    total: int
    note: str = ""

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.task_id,
                self.platform,
                self.title,
                self.target,
                self.source_name,
                self.status,
                self.note,
            )
        ).casefold()


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("jobs", "items", "tasks"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _address_names(config_path: Path) -> dict[str, str]:
    payload = _read_json(config_path, {})
    rows = payload.get("address_book", []) if isinstance(payload, dict) else []
    result: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        entry_id = str(row.get("id") or "").strip()
        label = str(
            row.get("remark")
            or row.get("name")
            or row.get("chat_title")
            or row.get("chat_id")
            or row.get("jid")
            or ""
        ).strip()
        if entry_id and label:
            result[entry_id] = label
    return result


def _status_of(job: dict[str, Any]) -> str:
    if not bool(job.get("enabled", True)):
        return "stopped"
    state = str(job.get("state") or "running").casefold()
    reason = str(job.get("pause_reason") or "").casefold()
    if state in {"stopped", "finished", "done", "disabled"}:
        return "stopped"
    if "listen" in reason or "监听" in reason:
        return "listen"
    if state in {"paused", "pause", "waiting"} or reason:
        return "paused"
    return "running"


def _target_of(job: dict[str, Any], names: dict[str, str]) -> str:
    entry_ids = [str(value) for value in job.get("chat_entry_ids", []) if str(value)]
    chat_ids = [str(value) for value in job.get("chat_ids", []) if str(value)]
    labels = [names.get(value, value) for value in entry_ids] or chat_ids
    if not labels:
        return ""
    first = labels[0]
    return first if len(labels) == 1 else f"{first} +{len(labels) - 1}"


def _records_from(
    jobs: Iterable[dict[str, Any]], *, platform: str, names: dict[str, str]
) -> list[TaskRecord]:
    result: list[TaskRecord] = []
    for index, job in enumerate(jobs, start=1):
        rows = job.get("rows")
        if not isinstance(rows, list):
            rows = job.get("items")
        if not isinstance(rows, list):
            rows = job.get("messages")
        total = len(rows) if isinstance(rows, list) else int(job.get("total") or 0)
        cursor = max(0, int(job.get("cursor") or 0))
        source_name = str(
            job.get("source_name")
            or Path(str(job.get("source_path") or "")).name
            or f"Task {index}"
        )
        note = str(job.get("pause_reason") or job.get("last_error") or "").strip()
        result.append(
            TaskRecord(
                task_id=str(job.get("id") or f"{platform.lower()}-{index}"),
                platform=platform,
                title=source_name,
                target=_target_of(job, names),
                source_name=source_name,
                status=_status_of(job),
                cursor=min(cursor, total) if total else cursor,
                total=total,
                note=note,
            )
        )
    return result


def load_task_records(data_root: Path) -> list[TaskRecord]:
    """读取数据目录；兼容安装版根目录和项目开发目录。"""
    root = Path(data_root).expanduser().resolve()
    wa_root = root / "whatsapp" if (root / "whatsapp").exists() else root
    if (root / "telegram").exists():
        tg_root = root / "telegram"
    elif root.name.casefold() == "whatsapp" and (root.parent / "telegram").exists():
        tg_root = root.parent / "telegram"
    else:
        tg_root = root.parent / "tg_multi_listener"

    wa_jobs = _items(_read_json(wa_root / "data" / "schedule2.json", []))
    tg_jobs = _items(_read_json(tg_root / "data" / "schedules.json", []))
    wa_names = _address_names(wa_root / "config.json")
    tg_names = _address_names(tg_root / "config.json")

    records = _records_from(wa_jobs, platform="WA", names=wa_names)
    records.extend(_records_from(tg_jobs, platform="TG", names=tg_names))
    return records


def make_stress_records(records: list[TaskRecord], count: int) -> list[TaskRecord]:
    """复制只读记录用于滚动压力测试；没有真实数据时生成占位任务。"""
    target = max(0, int(count))
    seed = records or [
        TaskRecord("demo", "WA", "演示任务", "演示群", "demo.txt", "running", 3, 20)
    ]
    return [
        replace(
            seed[index % len(seed)],
            task_id=f"{seed[index % len(seed)].task_id}-{index + 1}",
            title=f"{seed[index % len(seed)].title} #{index + 1}",
        )
        for index in range(target)
    ]
