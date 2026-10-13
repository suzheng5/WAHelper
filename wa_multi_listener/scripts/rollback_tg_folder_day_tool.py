"""TG 文件夹任务批量回退一天工具（独立 GUI，可分发）。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from typing import Any, Callable


APP_TITLE = "TG 任务回退一天"
PROCESS_NAMES = {"超群小帮手.exe", "WAHelper.exe"}


def resolve_tg_root(selected: Path) -> Path:
    for candidate in (selected / "telegram", selected):
        if (
            (candidate / "config.json").is_file()
            and (candidate / "data" / "schedules.json").is_file()
        ):
            return candidate
    raise RuntimeError("目录中没有找到 telegram\\config.json 和 telegram\\data\\schedules.json")


def running_main_programs() -> list[str]:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            encoding="mbcs",
            errors="replace",
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    wanted = {name.lower() for name in PROCESS_NAMES}
    found: set[str] = set()
    for line in output.splitlines():
        name = line.strip().strip('"').split('","', 1)[0]
        if name.lower() in wanted:
            found.add(name)
    return sorted(found)


def raw_candidates(tg_root: Path) -> list[dict[str, Any]]:
    schedule = tg_root / "data" / "schedules.json"
    jobs = json.loads(schedule.read_text(encoding="utf-8-sig"))
    if not isinstance(jobs, list):
        raise RuntimeError("schedules.json 格式错误")
    result: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        kind = str(job.get("source_kind") or "file").strip()
        files = [str(item) for item in (job.get("folder_files") or [])]
        folder_path = str(job.get("folder_path") or "").strip()
        if kind != "folder" and not (files and folder_path):
            continue
        index = int(job.get("folder_day_index") or 0)
        if index <= 0 or index >= len(files):
            continue
        result.append(
            {
                "id": str(job.get("id") or ""),
                "current_day": index + 1,
                "previous_day": index,
                "total": len(files),
                "current_file": str(job.get("source_name") or files[index]),
                "previous_file": files[index - 1],
                "cursor": int(job.get("cursor") or 0),
                "state": str(job.get("state") or ""),
            }
        )
    return result


def _ensure_package_path() -> None:
    if getattr(sys, "frozen", False):
        return
    ai_root = Path(__file__).resolve().parents[2]
    wa_root = Path(__file__).resolve().parents[1]
    for path in (ai_root, wa_root):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def rollback_all(
    tg_root: Path,
    notify: Callable[[str], None],
) -> tuple[int, int, Path, list[str]]:
    """回退全部候选任务；返回成功数、失败数、备份路径和失败摘要。"""
    running = running_main_programs()
    if running:
        raise RuntimeError("请先完全退出主程序：" + "、".join(running))

    _ensure_package_path()
    os.environ["TG_HELPER_DATA_ROOT"] = str(tg_root)

    from schedule_folder import resolve_folder_day_filename
    from tg_multi_listener.compat_config import load_config
    from tg_multi_listener.scheduler import (
        _reload_folder_day_items_tg,
        load_jobs,
        save_jobs,
    )

    schedule = tg_root / "data" / "schedules.json"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = schedule.with_name(f"schedules.json.bak_day_rollback_{stamp}")
    shutil.copy2(schedule, backup)
    notify(f"已备份：{backup.name}")

    jobs = load_jobs(force=True)
    cfg = load_config()
    changed = 0
    failed: list[str] = []

    for job in jobs:
        kind = str(getattr(job, "source_kind", "file") or "file").strip()
        files = list(getattr(job, "folder_files", None) or [])
        folder_path = str(getattr(job, "folder_path", "") or "").strip()
        if kind != "folder" and not (files and folder_path):
            continue
        index = int(getattr(job, "folder_day_index", 0) or 0)
        if index <= 0 or index >= len(files):
            continue

        previous_index = index - 1
        job_id = str(getattr(job, "id", "") or "")
        try:
            relative = resolve_folder_day_filename(folder_path, files[previous_index])
            ok, error = _reload_folder_day_items_tg(job, cfg, relative)
            if not ok:
                raise RuntimeError(error)
            job.folder_files[previous_index] = relative
            job.folder_day_index = previous_index
            job.cursor = 0
            job.enabled = True
            job.state = "paused"
            job.pause_reason = "startup_doc"
            job.next_send_ts = 0.0
            job.remaining_seconds = 0.0
            job.last_error = ""
            changed += 1
            notify(
                f"已回退 {job_id[:8]}：第 {index + 1} 天 → 第 {index} 天，"
                f"文件 {job.source_name}"
            )
        except Exception as exc:
            detail = f"{job_id[:8]}：{exc}"
            failed.append(detail)
            notify(f"跳过 {detail}")

    if changed:
        save_jobs(jobs)
    else:
        notify("没有任务成功回退，原配置未改动。")
    return changed, len(failed), backup, failed


class RollbackApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.path = StringVar()
        self.busy = BooleanVar(value=False)
        self._configure_window()
        self._build_ui()

    def _configure_window(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("900x650")
        self.root.minsize(760, 560)
        self.root.configure(bg="#0f1724")
        self.root.option_add("*Font", ("Microsoft YaHei UI", 10))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#0f1724")
        style.configure("Card.TFrame", background="#172235")
        style.configure(
            "Title.TLabel",
            background="#0f1724",
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 23, "bold"),
        )
        style.configure(
            "Sub.TLabel",
            background="#0f1724",
            foreground="#9fb0c4",
            font=("Microsoft YaHei UI", 10),
        )
        style.configure("Card.TLabel", background="#172235", foreground="#dce8f4")
        style.configure(
            "Accent.TButton",
            background="#22c7a8",
            foreground="#071511",
            borderwidth=0,
            padding=(18, 10),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map("Accent.TButton", background=[("active", "#38d8ba"), ("disabled", "#465365")])
        style.configure(
            "Muted.TButton",
            background="#26364d",
            foreground="#d6e2ee",
            borderwidth=0,
            padding=(13, 8),
        )
        style.configure(
            "Treeview",
            background="#111b2b",
            fieldbackground="#111b2b",
            foreground="#dbe7f3",
            rowheight=30,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background="#223149",
            foreground="#aebed0",
            borderwidth=0,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map("Treeview", background=[("selected", "#195d61")])

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=(30, 25))
        outer.pack(fill=BOTH, expand=True)

        ttk.Label(outer, text="把文件夹任务退回上一天", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="扫描全部 TG 文件夹任务，回退前自动备份，并从上一天 TXT 重新生成话术。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 18))

        card = ttk.Frame(outer, style="Card.TFrame", padding=15)
        card.pack(fill=X)
        ttk.Label(card, text="软件根目录", style="Card.TLabel").pack(anchor="w")
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(fill=X, pady=(8, 0))
        self.path_entry = ttk.Entry(row, textvariable=self.path)
        self.path_entry.pack(side=LEFT, fill=X, expand=True)
        self.choose_button = ttk.Button(
            row, text="选择文件夹", style="Muted.TButton", command=self.choose_folder
        )
        self.choose_button.pack(side=RIGHT, padx=(10, 0))

        note = ttk.Label(
            outer,
            text="回退后统一暂停并从上一天第 1 步开始；已经发出的错误日期消息不会自动撤回。",
            style="Sub.TLabel",
        )
        note.pack(anchor="w", pady=(12, 10))

        columns = ("task", "day", "current", "previous", "cursor", "state")
        self.tree = ttk.Treeview(outer, columns=columns, show="headings", selectmode="none")
        headings = {
            "task": "任务",
            "day": "回退",
            "current": "当前文件",
            "previous": "上一天文件",
            "cursor": "当前进度",
            "state": "状态",
        }
        widths = {"task": 90, "day": 105, "current": 180, "previous": 180, "cursor": 90, "state": 80}
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(key, width=widths[key], minwidth=60, anchor="center")
        self.tree.pack(fill=BOTH, expand=True)

        self.status = StringVar(value="请选择软件根目录。")
        ttk.Label(outer, textvariable=self.status, style="Sub.TLabel").pack(anchor="w", pady=(10, 8))

        actions = ttk.Frame(outer, style="Root.TFrame")
        actions.pack(fill=X)
        self.scan_button = ttk.Button(
            actions, text="重新扫描", style="Muted.TButton", command=self.scan
        )
        self.scan_button.pack(side=LEFT)
        self.rollback_button = ttk.Button(
            actions,
            text="回退全部候选任务",
            style="Accent.TButton",
            command=self.start_rollback,
            state="disabled",
        )
        self.rollback_button.pack(side=RIGHT)

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="选择软件根目录")
        if selected:
            self.path.set(selected)
            self.scan()

    def scan(self) -> None:
        try:
            tg_root = resolve_tg_root(Path(self.path.get().strip()))
            candidates = raw_candidates(tg_root)
        except Exception as exc:
            self._clear_tree()
            self.rollback_button.configure(state="disabled")
            self.status.set(str(exc))
            return
        self._clear_tree()
        for item in candidates:
            self.tree.insert(
                "",
                END,
                values=(
                    item["id"][:8],
                    f'{item["current_day"]} → {item["previous_day"]} / {item["total"]}',
                    item["current_file"],
                    item["previous_file"],
                    f'{item["cursor"]} 步',
                    item["state"] or "未知",
                ),
            )
        self.rollback_button.configure(state="normal" if candidates else "disabled")
        self.status.set(
            f"发现 {len(candidates)} 个可回退任务。"
            if candidates
            else "没有可回退任务（第 1 天任务不会显示）。"
        )

    def _clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.choose_button.configure(state=state)
        self.scan_button.configure(state=state)
        self.path_entry.configure(state=state)
        self.rollback_button.configure(state="disabled" if busy else state)

    def start_rollback(self) -> None:
        try:
            tg_root = resolve_tg_root(Path(self.path.get().strip()))
            count = len(raw_candidates(tg_root))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        if not count:
            messagebox.showinfo(APP_TITLE, "没有可回退任务。")
            return
        if running_main_programs():
            messagebox.showwarning(APP_TITLE, "请先完全退出“超群小帮手”，再执行回退。")
            return
        confirmed = messagebox.askyesno(
            APP_TITLE,
            f"将把 {count} 个文件夹任务全部回退一天。\n\n"
            "任务会暂停并从上一天第 1 步开始，操作前会自动备份 schedules.json。\n\n"
            "确定继续？",
            default="no",
        )
        if not confirmed:
            return
        self._set_busy(True)
        self.status.set("正在备份并回退，请勿启动主程序……")
        threading.Thread(target=self._rollback_worker, args=(tg_root,), daemon=True).start()

    def _rollback_worker(self, tg_root: Path) -> None:
        messages: list[str] = []
        try:
            changed, failed, backup, failures = rollback_all(tg_root, messages.append)
            self.root.after(
                0,
                lambda: self._rollback_done(changed, failed, backup, failures, messages),
            )
        except Exception as exc:
            traceback.print_exc()
            self.root.after(0, lambda: self._rollback_failed(f"{type(exc).__name__}: {exc}"))

    def _rollback_done(
        self,
        changed: int,
        failed: int,
        backup: Path,
        failures: list[str],
        messages: list[str],
    ) -> None:
        self._set_busy(False)
        self.scan()
        self.status.set(f"回退完成：成功 {changed}，失败 {failed}。备份：{backup.name}")
        detail = "\n".join(failures[:8])
        messagebox.showinfo(
            APP_TITLE,
            f"回退完成：成功 {changed} 个，失败 {failed} 个。\n\n备份文件：\n{backup}"
            + (f"\n\n失败摘要：\n{detail}" if detail else ""),
        )

    def _rollback_failed(self, error: str) -> None:
        self._set_busy(False)
        self.status.set("回退失败，原配置未写入。")
        messagebox.showerror(APP_TITLE, error)


def main() -> int:
    root = Tk()
    RollbackApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
