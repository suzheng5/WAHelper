"""Windows 打包：构建 dist/WAHelper；分发 zip 不含登录与配置。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PRESERVE = ROOT / "userdata_preserve"
COLLECT_NAME = os.environ.get("WA_COLLECT_NAME", "WAHelper")
OUT = DIST / COLLECT_NAME
VENV_PY = ROOT.parent / ".venv" / "Scripts" / "python.exe"
PYINSTALLER = ROOT.parent / ".venv" / "Scripts" / "pyinstaller.exe"
APP_ZIP_BASENAME = "超群小帮手"
VERSION_PY = ROOT / "app_version.py"

PLATFORM_DIRS = ("whatsapp", "telegram")
LEGACY_FLAT_USER = ("config.json", "sessions", "data", "logs")
USERDATA_SUBDIRS = frozenset({"sessions", "data", "logs", "userdata_preserve"})
USERDATA_FILES = frozenset({"config.json"})
LICENSE_LOCAL_FILES = (
    "license_admin.json",
    "license_public.json",
    "license_records.txt",
    "license_ws.dat",
)
# 界面偏好（列宽等）：本机目录保留，不打进对外分发 zip
UI_PREF_FILES = (
    "ui_column_widths.json",
    "ui_locale.json",
)
# 仅本机目录保留、不打进对外分发 zip
RELEASE_EXCLUDE_FILES = frozenset({
    "LicenseManager.exe",
    "激活码管理.exe",
    "license_admin.json",
    "license_records.txt",
    "license.dat",
    "license_ws.dat",
    "ui_column_widths.json",
})


def read_app_version() -> str:
    text = VERSION_PY.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        raise RuntimeError(f"未在 {VERSION_PY} 中找到 APP_VERSION")
    return m.group(1).strip()


def distribution_zip_name(*, include_userdata: bool = False) -> str:
    ver = read_app_version()
    if include_userdata:
        return f"{APP_ZIP_BASENAME}_{ver}_本机完整.zip"
    return f"{APP_ZIP_BASENAME}_{ver}.zip"


def _copy_file_newer(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        return
    if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
        return
    shutil.copy2(src, dst)


def _merge_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_file():
        _copy_file_newer(src, dst)
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        s, d = item, dst / item.name
        if item.is_dir():
            _merge_tree(s, d)
        else:
            _copy_file_newer(s, d)


def _backup_schedule2() -> None:
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for p in (
        PRESERVE / "whatsapp" / "data" / "schedule2.json",
        OUT / "whatsapp" / "data" / "schedule2.json",
        OUT / "data" / "schedule2.json",
    ):
        if p.is_file():
            shutil.copy2(p, p.with_name(f"schedule2.json.bak_{stamp}"))
            print(f"已备份定时任务：{p.with_name(f'schedule2.json.bak_{stamp}')}")


def _pull_from_dist_root(src_root: Path) -> None:
    if not src_root.is_dir():
        return
    for sub in PLATFORM_DIRS:
        _merge_tree(src_root / sub, PRESERVE / sub)
    wa_dest = PRESERVE / "whatsapp"
    for name in LEGACY_FLAT_USER:
        _merge_tree(src_root / name, wa_dest / name)
    for name in LICENSE_LOCAL_FILES:
        _copy_file_newer(src_root / name, PRESERVE / name)
    for name in UI_PREF_FILES:
        _copy_file_newer(src_root / name, PRESERVE / name)
    print(f"已收拢用户数据：{src_root} → {PRESERVE}")


def pull_userdata_into_preserve() -> None:
    PRESERVE.mkdir(parents=True, exist_ok=True)
    _backup_schedule2()
    for name in ("WAHelper", "WAHelper_build"):
        _pull_from_dist_root(DIST / name)


def restore_userdata_to_out() -> None:
    if not PRESERVE.is_dir():
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for sub in PLATFORM_DIRS:
        src = PRESERVE / sub
        if src.exists():
            _merge_tree(src, OUT / sub)
            print(f"已恢复用户数据：{sub} → {OUT}")
    legacy_data = PRESERVE / "data"
    if legacy_data.is_dir() and not (PRESERVE / "whatsapp" / "data").exists():
        _merge_tree(legacy_data, OUT / "whatsapp" / "data")
    for name in LICENSE_LOCAL_FILES:
        src = PRESERVE / name
        if src.is_file():
            _copy_file_newer(src, OUT / name)
            print(f"已恢复激活相关文件：{name} → {OUT}")
    for name in UI_PREF_FILES:
        src = PRESERVE / name
        if src.is_file():
            _copy_file_newer(src, OUT / name)
            print(f"已恢复界面偏好：{name} → {OUT}")
    _sync_license_public_config(OUT)


def _is_userdata_in_release(rel: Path) -> bool:
    """判断是否为用户登录/配置/业务数据（不应打进对外分发 zip）。"""
    parts = rel.parts
    if not parts:
        return False
    name = rel.name
    if name in RELEASE_EXCLUDE_FILES:
        return True
    if name in USERDATA_FILES:
        return True
    # 本机备份/临时文件不进分发包
    low = name.lower()
    if low.endswith(".bak") or ".bak_" in low or name.startswith("schedule2.json.bak"):
        return True
    if parts[0] in USERDATA_SUBDIRS:
        return True
    if len(parts) >= 2 and parts[0] in PLATFORM_DIRS:
        if parts[1] in USERDATA_SUBDIRS:
            return True
        if parts[1] == "config.json":
            return True
    if len(parts) >= 3 and parts[0] in PLATFORM_DIRS and parts[2] in USERDATA_SUBDIRS:
        return True
    if name in ("WAHelper.exe", "WhatsApp监听助手.exe"):
        return True
    if "sessions" in parts and (low.endswith(".db") or low.endswith(".session")):
        return True
    return False


def make_zip(*, include_userdata: bool, zip_name: str) -> Path:
    zip_path = DIST / zip_name
    if zip_path.is_file():
        zip_path.unlink()
    skipped = 0
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in OUT.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(OUT)
            if not include_userdata and _is_userdata_in_release(rel):
                skipped += 1
                continue
            zf.write(f, arcname=str(rel))
    mb = zip_path.stat().st_size / (1024 * 1024)
    label = "含本机登录/配置" if include_userdata else "不含登录/配置（可对外分发）"
    print(f"已生成压缩包：{zip_path}（约 {mb:.1f} MB，{label}，跳过 {skipped} 个用户文件）")
    return zip_path


def _sync_license_public_config(out_dir: Path) -> None:
    """从 license_admin.json 生成 license_public.json（分发 zip 需包含后者）。"""
    admin_path = out_dir / "license_admin.json"
    if not admin_path.is_file():
        return
    try:
        ai_root = ROOT.parent
        if str(ai_root) not in sys.path:
            sys.path.insert(0, str(ai_root))
        from license_gist import save_public_gist_raw_url

        raw_url = json.loads(admin_path.read_text(encoding="utf-8")).get("raw_url", "")
        if raw_url:
            save_public_gist_raw_url(str(out_dir), str(raw_url))
            print(f"已同步公开激活配置：{out_dir / 'license_public.json'}")
    except Exception as exc:
        print(f"同步 license_public.json 失败：{exc}")


def run_pyinstaller_license_manager() -> int:
    spec = ROOT / "build_license_manager.spec"
    if not spec.is_file():
        print(f"未找到注册机 spec：{spec}")
        return 1
    cmd = [str(PYINSTALLER), str(spec), "--noconfirm", "--clean"]
    print("正在打包激活码管理（注册机）…")
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def install_license_manager_to_out() -> None:
    """将注册机 exe 放入本机运行目录；分发 zip 会排除。"""
    src = DIST / "LicenseManager.exe"
    if not src.is_file():
        print(f"未找到注册机构建产物：{src}")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("LicenseManager.exe", "激活码管理.exe"):
        dst = OUT / name
        shutil.copy2(src, dst)
        print(f"已放入本机目录（不进 zip）：{dst}")


def run_pyinstaller() -> int:
    env = os.environ.copy()
    env["WA_COLLECT_NAME"] = COLLECT_NAME
    cmd = [
        str(PYINSTALLER),
        str(ROOT / "build_windows.spec"),
        "--noconfirm",
        "--clean",
    ]
    print("正在运行 PyInstaller…")
    return subprocess.run(cmd, cwd=str(ROOT), env=env).returncode


def run_finalize() -> int:
    env = os.environ.copy()
    env["WA_COLLECT_NAME"] = COLLECT_NAME
    return subprocess.run(
        [str(VENV_PY), str(ROOT / "scripts" / "finalize_dist.py")],
        cwd=str(ROOT),
        env=env,
    ).returncode


def main() -> int:
    if not PYINSTALLER.is_file():
        print(f"未找到 pyinstaller：{PYINSTALLER}")
        return 1

    t0 = time.perf_counter()
    timings: list[tuple[str, float]] = []

    def _stage(name: str, fn):
        started = time.perf_counter()
        print(f"\n>>> [{name}] 开始…")
        result = fn()
        elapsed = time.perf_counter() - started
        timings.append((name, elapsed))
        print(f"<<< [{name}] 结束，耗时 {elapsed:.1f}s")
        return result

    _stage("pull_userdata", pull_userdata_into_preserve)

    if _stage("pyinstaller_main", run_pyinstaller) != 0:
        return 1

    if _stage("finalize", run_finalize) != 0:
        return 1

    _stage("restore_userdata", restore_userdata_to_out)

    if _stage("pyinstaller_license", run_pyinstaller_license_manager) != 0:
        return 1
    _stage("install_license", install_license_manager_to_out)

    def _clean_build() -> None:
        build_dir = ROOT / "build"
        if build_dir.is_dir():
            shutil.rmtree(build_dir, ignore_errors=True)

    _stage("clean_build", _clean_build)

    # ---------- 产物 ②：对外分发包（无依赖环境，解压即用；不含登录/配置/注册机）----------
    dist_zip = distribution_zip_name(include_userdata=False)
    ascii_zip = f"WAHelper_{read_app_version()}.zip"

    def _zip_release() -> Path:
        path = make_zip(include_userdata=False, zip_name=dist_zip)
        # 同步一份 ASCII 文件名，便于网盘/GitHub 下载
        ascii_path = DIST / ascii_zip
        if ascii_path.is_file():
            ascii_path.unlink()
        shutil.copy2(path, ascii_path)
        print(f"已同步 ASCII 分发包：{ascii_path}")
        return path

    _stage("zip_release", _zip_release)
    # 可选：本机完整备份 zip（含登录），默认不生成以节省时间；需要时设 WA_ZIP_WITH_USERDATA=1
    if os.environ.get("WA_ZIP_WITH_USERDATA", "").strip() in ("1", "true", "yes"):
        _stage(
            "zip_userdata",
            lambda: make_zip(
                include_userdata=True,
                zip_name=distribution_zip_name(include_userdata=True),
            ),
        )

    total = time.perf_counter() - t0
    print(f"\n完成。总耗时 {total:.1f}s")
    print("各阶段耗时：")
    for name, elapsed in timings:
        pct = (elapsed / total * 100) if total else 0
        print(f"  {name:22s} {elapsed:7.1f}s  ({pct:5.1f}%)")
    print("\n========== 打包产物（两项） ==========")
    print(f"① 本机运行目录（已覆盖程序文件，保留你的登录/配置）：\n   {OUT}")
    print(f"   启动：{OUT / '超群小帮手.exe'}")
    print(f"   注册机（仅本机，不进分发包）：{OUT / '激活码管理.exe'}")
    print(f"② 对外分发包（无 Python/依赖，解压即用，无登录数据）：\n   {DIST / dist_zip}")
    print(f"   ASCII 同内容：{DIST / ascii_zip}")
    print(f"用户数据备份目录：{PRESERVE}")
    print(
        "若还要覆盖到其它安装目录："
        f"{VENV_PY.name} scripts/overlay_install.py "
        f"--source {OUT} --target <旧安装目录>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
