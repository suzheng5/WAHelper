"""构建后：中文 exe 名、补丁 neonize DLL、说明文件。"""
from __future__ import annotations

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
OUT = os.path.join(DIST, os.environ.get("WA_COLLECT_NAME", "WAHelper"))
SRC = os.path.join(OUT, "WAHelper.exe")
DST_CN = os.path.join(OUT, "超群小帮手.exe")
DLL_NAME = "neonize-windows-amd64.dll"
LEGACY_EXE_NAMES = ("WhatsApp监听助手.exe",)
LICENSE_LOCAL_FILES = (
    "license_admin.json",
    "license_public.json",
    "license_records.txt",
    "license_ws.dat",
)


def _sync_license_public_config(out_dir: str) -> None:
    """从 license_admin.json 生成 license_public.json（分发包需含此文件）。"""
    admin_path = os.path.join(out_dir, "license_admin.json")
    public_path = os.path.join(out_dir, "license_public.json")
    raw_url = ""
    if os.path.isfile(admin_path):
        try:
            with open(admin_path, encoding="utf-8") as f:
                raw_url = str(json.load(f).get("raw_url") or "").strip()
        except (OSError, json.JSONDecodeError):
            pass
    if not raw_url:
        return
    try:
        ai_root = os.path.normpath(os.path.join(ROOT, ".."))
        if ai_root not in sys.path:
            sys.path.insert(0, ai_root)
        from license_gist import save_public_gist_raw_url

        save_public_gist_raw_url(out_dir, raw_url)
        print(f"已同步公开激活配置：{public_path}")
    except Exception as exc:
        print(f"同步 license_public.json 失败：{exc}")


def main() -> int:
    release_build = os.environ.get("WA_RELEASE_BUILD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if os.path.isfile(SRC):
        if os.path.isfile(DST_CN):
            os.remove(DST_CN)
        os.replace(SRC, DST_CN)
        print(f"已生成：{DST_CN}")
    elif os.path.isfile(DST_CN):
        print(f"已存在：{DST_CN}")
    else:
        print(f"未找到构建产物：{SRC}")
        return 1

    for legacy in LEGACY_EXE_NAMES:
        legacy_path = os.path.join(OUT, legacy)
        if os.path.isfile(legacy_path):
            os.remove(legacy_path)
            print(f"已移除旧版程序：{legacy_path}")

    official = os.path.join(
        os.path.dirname(ROOT), ".venv", "Lib", "site-packages", "neonize", DLL_NAME
    )
    # v3.0.17 实际运行验证过的 0.3.18 DLL；0.4.x 在首个 NewAClient
    # 初始化时会使整个 Windows 进程原生崩溃。
    stable = os.path.join(ROOT, DLL_NAME)
    dll_src = stable if os.path.isfile(stable) else official
    if os.path.isfile(dll_src):
        dest = os.path.join(OUT, "_internal", "neonize", DLL_NAME)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(dll_src, dest)
        label = "v3.0.17 稳定版" if dll_src == stable else "官方"
        print(f"已复制{label} neonize DLL 到：{dest}")

    for sub, rel in (("neonize", "download.py"), ("neonize", "_binder.py")):
        src = os.path.join(os.path.dirname(ROOT), ".venv", "Lib", "site-packages", sub, os.path.basename(rel))
        if not os.path.isfile(src):
            src = os.path.join(ROOT, sub, rel.replace("/", os.sep))
        if os.path.isfile(src):
            dest = os.path.join(OUT, "_internal", sub, os.path.basename(rel))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            print(f"已同步 neonize 补丁：{dest}")

    for name in ("整合版说明.txt", "定时任务导入说明与示例.txt", "请先看我.txt"):
        for src_dir in (os.path.join(ROOT, "docs"), ROOT):
            src = os.path.join(src_dir, name)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(OUT, name))
                print(f"已复制：{name}")
                break

    # 分发目录附带示例配置（非用户真实 config.json）
    for sub, names in (
        ("whatsapp", ("config.example.json",)),
        ("telegram", ("config.example.tg.json", "config.example.json")),
        ("", ("config.example.json",)),
    ):
        dest_dir = os.path.join(OUT, sub) if sub else OUT
        os.makedirs(dest_dir, exist_ok=True)
        for name in names:
            src = os.path.join(ROOT, name)
            if not os.path.isfile(src):
                continue
            dest = os.path.join(dest_dir, "config.example.json")
            if not os.path.isfile(dest):
                shutil.copy2(src, dest)
                print(f"已复制示例配置：{dest}")
            break

    if release_build:
        public_config = os.path.join(ROOT, "license_public.json")
        if os.path.isfile(public_config):
            shutil.copy2(public_config, os.path.join(OUT, "license_public.json"))
            print("已复制公开激活配置（不含管理密钥）")
    else:
        _restore_userdata_after_build(OUT)
        _install_license_manager(OUT)
        _restore_license_files(OUT)
        _sync_license_public_config(OUT)
        _restore_whatsapp_if_missing(OUT)
        _restore_whatsapp_schedule(OUT)
    _ensure_launcher_bat(OUT)
    if not release_build:
        _install_phone_query(OUT)
        _install_tg_phone_query(OUT)
    return 0


def _install_license_manager(out_dir: str) -> None:
    """激活码管理器仅放本机 dist/WAHelper，不进对外 zip。"""
    candidates = [
        os.path.join(DIST, "LicenseManager.exe"),
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
    src = ""
    for path in candidates:
        p = os.path.normpath(path)
        if os.path.isfile(p):
            src = p
            break
    if not src:
        print("未找到 LicenseManager.exe，跳过激活码管理器复制")
        return
    os.makedirs(out_dir, exist_ok=True)
    for name in ("LicenseManager.exe", "激活码管理.exe"):
        dst = os.path.join(out_dir, name)
        shutil.copy2(src, dst)
        print(f"已放入激活码管理：{dst}")


def _restore_license_files(out_dir: str) -> None:
    """恢复管理器配置、记录及本机主程序激活状态。"""
    preserve_root = os.path.join(ROOT, "userdata_preserve")
    for name in LICENSE_LOCAL_FILES:
        src = os.path.join(preserve_root, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(out_dir, name)
        shutil.copy2(src, dst)
        print(f"已恢复激活文件：{name}")


def _restore_userdata_after_build(out_dir: str) -> None:
    """PyInstaller 会清空 dist；从 userdata_preserve 恢复 telegram/whatsapp 用户数据。"""
    preserve_root = os.path.join(ROOT, "userdata_preserve")
    for sub in ("telegram", "whatsapp"):
        src = os.path.join(preserve_root, sub)
        dst = os.path.join(out_dir, sub)
        if not os.path.isdir(src):
            continue
        os.makedirs(dst, exist_ok=True)
        for name in ("config.json", "data", "sessions", "logs"):
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
        cfg = os.path.join(dst, "config.json")
        if os.path.isfile(cfg):
            print(f"已恢复用户数据：{sub}/（含 config.json）")


def _restore_whatsapp_if_missing(out_dir: str) -> None:
    """若打包后 whatsapp 目录为空/缺失，从 preserve 或备份恢复。"""
    wa = os.path.join(out_dir, "whatsapp")
    cfg = os.path.join(wa, "config.json")
    if os.path.isfile(cfg):
        try:
            with open(cfg, encoding="utf-8") as f:
                n = len(json.load(f).get("accounts") or [])
            if n > 0:
                return
        except (OSError, json.JSONDecodeError):
            pass
    script = os.path.join(ROOT, "scripts", "restore_wa_data.py")
    if os.path.isfile(script):
        import subprocess

        py = os.path.join(os.path.dirname(ROOT), ".venv", "Scripts", "python.exe")
        if not os.path.isfile(py):
            py = "python"
        subprocess.run([py, script], cwd=ROOT, check=False)


def _restore_whatsapp_schedule(out_dir: str) -> None:
    """用户备份可能保留旧主文件；从随数据保留的备份中恢复任务最多的一份。"""
    script = os.path.join(ROOT, "scripts", "restore_wa_schedule2.py")
    if not os.path.isfile(script):
        return
    import subprocess

    py = os.path.join(os.path.dirname(ROOT), ".venv", "Scripts", "python.exe")
    if not os.path.isfile(py):
        py = "python"
    subprocess.run([py, script], cwd=ROOT, check=False)


def _ensure_launcher_bat(out_dir: str) -> None:
    bat = os.path.join(out_dir, "启动.bat")
    content = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
taskkill /F /IM 超群小帮手.exe >nul 2>&1
taskkill /F /IM 发群小助手.exe >nul 2>&1
taskkill /F /IM WAHelper.exe >nul 2>&1
timeout /t 1 /nobreak >nul
if exist "%~dp0超群小帮手.exe" (
  start "" "%~dp0超群小帮手.exe"
) else if exist "%~dp0发群小助手.exe" (
  start "" "%~dp0发群小帮手.exe"
) else (
  start "" "%~dp0WAHelper.exe"
)
"""
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)
    print(f"已写入启动脚本：{bat}")


def _install_phone_query(out_dir: str) -> None:
    """安装无需启动主程序的一键 WS 手机号查询脚本。"""
    src = os.path.join(ROOT, "scripts", "query_wa_account_phones.py")
    if not os.path.isfile(src):
        return
    script_name = "查询WS账号手机号.py"
    shutil.copy2(src, os.path.join(out_dir, script_name))
    bat = os.path.join(out_dir, "查询WS账号手机号.bat")
    content = f"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHON=%~dp0..\\..\\..\\.venv\\Scripts\\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" "%~dp0{script_name}" --app-dir "%~dp0"
echo.
pause
"""
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)
    print(f"已安装手机号查询脚本：{bat}")


def _install_tg_phone_query(out_dir: str) -> None:
    """安装使用 session 快照联网查询 TG 手机号的一键脚本。"""
    src = os.path.join(ROOT, "scripts", "query_tg_account_phones.py")
    if not os.path.isfile(src):
        return
    script_name = "查询TG账号手机号.py"
    shutil.copy2(src, os.path.join(out_dir, script_name))
    bat = os.path.join(out_dir, "查询TG账号手机号.bat")
    content = f"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHON=%~dp0..\\..\\..\\.venv\\Scripts\\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" "%~dp0{script_name}" --app-dir "%~dp0"
echo.
pause
"""
    with open(bat, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(content)
    print(f"已安装 TG 手机号查询脚本：{bat}")


if __name__ == "__main__":
    raise SystemExit(main())
