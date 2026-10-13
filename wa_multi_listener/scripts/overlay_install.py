"""覆盖升级：只替换程序文件，保留用户配置/任务/登录数据。"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

# 覆盖时必须保留（用户数据与激活状态）
PRESERVE_TOP_LEVEL = (
    "whatsapp",
    "telegram",
    "ui_locale.json",
    "license_ws.dat",
    "license_public.json",
    "config.json",
    "sessions",
    "data",
    "logs",
)

# 覆盖时必须替换（程序与内置资源）
REPLACE_TOP_LEVEL = (
    "超群小帮手.exe",
    "WAHelper.exe",
    "_internal",
    "neonize-windows-amd64.dll",
    "整合版说明.txt",
    "定时任务导入说明与示例.txt",
    "请先看我.txt",
)


def overlay_install(source: Path, target: Path, *, backup: bool = True) -> list[str]:
    """把 source 程序文件覆盖到 target，保留用户数据目录。"""
    source = source.resolve()
    target = target.resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"source missing: {source}")
    target.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []

    if backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_root = target.parent / f"{target.name}_backup_{stamp}"
        shutil.copytree(
            target,
            backup_root,
            ignore=shutil.ignore_patterns("_internal", "*.exe", "*.dll"),
            dirs_exist_ok=True,
        )
        # Also back up critical user data explicitly.
        for name in PRESERVE_TOP_LEVEL:
            src = target / name
            if src.exists():
                dest = backup_root / name
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
        actions.append(f"backup={backup_root}")

    for name in REPLACE_TOP_LEVEL:
        src = source / name
        if not src.exists():
            continue
        dest = target / name
        if dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
        actions.append(f"replaced={name}")

    # Example configs may be refreshed without touching user config.json.
    for rel in (
        Path("whatsapp") / "config.example.json",
        Path("telegram") / "config.example.json",
    ):
        src = source / rel
        if src.is_file():
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            actions.append(f"example={rel.as_posix()}")

    return actions


def verify_userdata_present(install_dir: Path) -> dict[str, bool]:
    root = install_dir.resolve()
    return {
        "whatsapp": (root / "whatsapp").exists() or (root / "config.json").exists(),
        "telegram": (root / "telegram").exists(),
        "ui_locale": (root / "ui_locale.json").exists(),
        "license": (root / "license_ws.dat").exists(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Overlay install preserving userdata")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()
    actions = overlay_install(args.source, args.target, backup=not args.no_backup)
    checks = verify_userdata_present(args.target)
    print("overlay actions:")
    for item in actions:
        print(" ", item)
    print("userdata checks:", checks)


if __name__ == "__main__":
    main()
