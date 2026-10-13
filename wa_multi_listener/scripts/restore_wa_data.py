"""对比并恢复 WhatsApp 数据到 dist/WAHelper。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from glob import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "dist", "WAHelper", "whatsapp")
PRESERVE = os.path.join(ROOT, "userdata_preserve", "whatsapp")
BACKUP = os.path.join(
    ROOT,
    "..",
    "backup",
    "backup_20260824_152026_pre_v3017_rollback",
    "WAHelper319",
    "whatsapp",
)


def _counts(path: str) -> dict:
    out = {"path": path, "exists": os.path.isdir(path)}
    if not out["exists"]:
        return out
    cfg = os.path.join(path, "config.json")
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            data = json.load(f)
        accs = data.get("accounts") or []
        out["accounts"] = len(accs)
        out["enabled"] = sum(1 for a in accs if a.get("enabled", True))
        ab = data.get("address_book")
        if isinstance(ab, list):
            out["address_book"] = len(ab)
    ab_path = os.path.join(path, "address_book.json")
    if os.path.isfile(ab_path):
        with open(ab_path, encoding="utf-8") as f:
            ab = json.load(f)
        out["address_book"] = len(ab) if isinstance(ab, list) else len(ab or {})
    sess = os.path.join(path, "sessions")
    if os.path.isdir(sess):
        out["sessions"] = len([n for n in os.listdir(sess) if n.endswith(".session")])
    for name in ("data/schedule2.json", "schedule2.json"):
        p = os.path.join(path, name.replace("/", os.sep))
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                jobs = json.load(f)
            out["schedule2"] = len(jobs) if isinstance(jobs, list) else len(jobs.get("jobs") or [])
            break
    out["score"] = sum(out.get(k, 0) for k in ("accounts", "address_book", "sessions", "schedule2"))
    return out


def _sync_tree(src: str, dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    for name in ("config.json", "address_book.json", "data", "sessions", "logs"):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if not os.path.exists(s):
            continue
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)


def main() -> int:
    sources: list[tuple[str, dict]] = []
    for label, path in (
        ("preserve", PRESERVE),
        ("backup", os.path.normpath(BACKUP)),
        ("dist", TARGET),
    ):
        c = _counts(os.path.normpath(path))
        c["label"] = label
        sources.append((label, c))
    for path in sorted(glob(os.path.join(ROOT, "userdata_preserve", "whatsapp_dist_before_*"))):
        c = _counts(path)
        c["label"] = os.path.basename(path)
        sources.append((c["label"], c))

    best = max((c for _, c in sources if c.get("exists")), key=lambda x: x.get("score", 0), default=None)
    if not best or best.get("score", 0) <= 0:
        print("未找到可恢复的 WhatsApp 数据")
        return 1

    src = best["path"]
    if os.path.isdir(TARGET):
        bak = os.path.join(
            ROOT,
            "userdata_preserve",
            f"whatsapp_dist_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        shutil.copytree(TARGET, bak, dirs_exist_ok=True)
        print(f"已备份当前 dist：{bak}")

    _sync_tree(src, TARGET)
    shutil.copytree(TARGET, PRESERVE, dirs_exist_ok=True)

    # schedule2：在 data 目录的多个 .bak 里选任务数最多的一份
    try:
        import subprocess

        py = os.path.join(os.path.dirname(ROOT), ".venv", "Scripts", "python.exe")
        if not os.path.isfile(py):
            py = "python"
        subprocess.run(
            [py, os.path.join(ROOT, "scripts", "restore_wa_schedule2.py")],
            cwd=ROOT,
            check=False,
        )
    except Exception:
        pass

    result = {
        "restored_from": best,
        "target": _counts(TARGET),
        "all_sources": [c for _, c in sources],
    }
    out = os.path.join(ROOT, "wa_restore_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
