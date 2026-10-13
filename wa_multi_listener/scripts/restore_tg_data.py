"""从 8/24 备份恢复 Telegram 配置到 dist/WAHelper。"""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(
    ROOT,
    "..",
    "backup",
    "backup_20260824_152026_pre_v3017_rollback",
    "WAHelper319",
    "telegram",
)
TARGET = os.path.join(ROOT, "dist", "WAHelper", "telegram")
PRESERVE = os.path.join(ROOT, "userdata_preserve", "telegram")
BACKUP = os.path.join(
    ROOT,
    "userdata_preserve",
    f"telegram_before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
)


def _strip_bom(path: str) -> None:
    if not os.path.isfile(path):
        return
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        open(path, "wb").write(raw[3:])


def _counts(cfg_path: str, sched_path: str) -> dict:
    out = {"config": cfg_path, "schedules": sched_path}
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f)
        accs = cfg.get("accounts") or []
        out["accounts"] = len(accs)
        out["enabled"] = sum(1 for a in accs if a.get("enabled", True))
        out["address_book"] = len(cfg.get("address_book") or [])
    if os.path.isfile(sched_path):
        with open(sched_path, encoding="utf-8") as f:
            data = json.load(f)
        out["schedules"] = len(data) if isinstance(data, list) else len(data.get("jobs") or [])
    sess = os.path.join(os.path.dirname(cfg_path), "sessions")
    if os.path.isdir(sess):
        out["session_files"] = len(
            [n for n in os.listdir(sess) if n.endswith(".session")]
        )
    return out


def _sync_tree(src: str, dst: str) -> None:
    os.makedirs(dst, exist_ok=True)
    for name in ("config.json", "data"):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d)
            shutil.copytree(s, d)
        elif os.path.isfile(s):
            shutil.copy2(s, d)
    src_sess = os.path.join(src, "sessions")
    dst_sess = os.path.join(dst, "sessions")
    if os.path.isdir(src_sess):
        if os.path.exists(dst_sess):
            shutil.rmtree(dst_sess)
        shutil.copytree(src_sess, dst_sess)


def main() -> int:
    src = os.path.normpath(SOURCE)
    if not os.path.isfile(os.path.join(src, "config.json")):
        print(f"SOURCE 不存在：{src}")
        return 1

    if os.path.isdir(TARGET):
        shutil.copytree(TARGET, BACKUP, dirs_exist_ok=True)
        print(f"已备份当前数据：{BACKUP}")

    # 使用备份中的 api 凭据（须与 .session 登录时一致，勿用 dist 里旧 api 覆盖）
    src_api: dict = {}
    try:
        with open(os.path.join(src, "config.json"), encoding="utf-8") as f:
            src_cfg = json.load(f)
        for k in ("api_id", "api_hash"):
            if src_cfg.get(k):
                src_api[k] = src_cfg[k]
    except (OSError, json.JSONDecodeError):
        pass

    _sync_tree(src, TARGET)
    cfg_path = os.path.join(TARGET, "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in src_api.items():
        cfg[k] = v
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    # 任务：在多个来源里选任务数最多的一份 schedules.json
    sched_name = os.path.join("data", "schedules.json")
    best_sched_src = ""
    best_sched_n = -1
    for root in (
        src,
        TARGET,
        os.path.join(ROOT, "userdata_preserve", "telegram"),
        os.path.join(ROOT, "userdata_preserve", "telegram", "telegram"),
        BACKUP,
    ):
        p = os.path.join(root, sched_name)
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8-sig") as f:
                data = json.load(f)
            n = len(data) if isinstance(data, list) else len(data.get("jobs") or [])
            if n > best_sched_n:
                best_sched_n = n
                best_sched_src = p
        except (OSError, json.JSONDecodeError):
            continue
    if best_sched_src:
        dst_sched = os.path.join(TARGET, sched_name)
        os.makedirs(os.path.dirname(dst_sched), exist_ok=True)
        shutil.copy2(best_sched_src, dst_sched)
        print(f"已选用任务数最多的 schedules（{best_sched_n} 条）：{best_sched_src}")

    for p in (
        cfg_path,
        os.path.join(TARGET, "data", "schedules.json"),
    ):
        _strip_bom(p)

    _sync_tree(TARGET, PRESERVE)
    for p in (
        os.path.join(PRESERVE, "config.json"),
        os.path.join(PRESERVE, "data", "schedules.json"),
    ):
        _strip_bom(p)

    nested = os.path.join(PRESERVE, "telegram")
    if os.path.isdir(nested) and not os.listdir(nested):
        os.rmdir(nested)

    result = {
        "source": _counts(
            os.path.join(src, "config.json"),
            os.path.join(src, "data", "schedules.json"),
        ),
        "target": _counts(
            cfg_path,
            os.path.join(TARGET, "data", "schedules.json"),
        ),
    }
    out = os.path.join(ROOT, "tg_verify.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
