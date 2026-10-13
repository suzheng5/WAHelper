"""恢复 dist/WAHelper 下的激活码管理器。"""
from __future__ import annotations

import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "WAHelper")
CANDIDATES = [
    os.path.join(ROOT, "dist", "LicenseManager.exe"),
    os.path.join(
        ROOT,
        "..",
        "backup",
        "backup_20260824_152026_pre_v3017_rollback",
        "WAHelper319",
        "LicenseManager.exe",
    ),
    os.path.join(
        ROOT,
        "..",
        "backup",
        "backup_20260824_152026_pre_v3017_rollback",
        "WAHelper319",
        "激活码管理.exe",
    ),
]
LICENSE_FILES = (
    "license_admin.json",
    "license_public.json",
    "license_records.txt",
    "license_ws.dat",
)


def main() -> int:
    src = next((os.path.normpath(p) for p in CANDIDATES if os.path.isfile(p)), "")
    if not src:
        print("未找到 LicenseManager 源文件")
        return 1
    os.makedirs(OUT, exist_ok=True)
    for name in ("LicenseManager.exe", "激活码管理.exe"):
        dst = os.path.join(OUT, name)
        shutil.copy2(src, dst)
        print(f"已复制：{dst} ({os.path.getsize(dst)} bytes)")
    preserve = os.path.join(ROOT, "userdata_preserve")
    for name in LICENSE_FILES:
        s = os.path.join(preserve, name)
        d = os.path.join(OUT, name)
        if os.path.isfile(s):
            shutil.copy2(s, d)
            print(f"已复制：{d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
