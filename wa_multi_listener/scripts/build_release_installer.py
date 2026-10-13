"""构建完全脱敏的 Windows 分发目录、ZIP 和 Inno Setup 安装程序。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
RELEASE_DIR = DIST / "WAHelper_release"
VENV = ROOT.parent / ".venv"
PYINSTALLER = VENV / "Scripts" / "pyinstaller.exe"
PYTHON = VENV / "Scripts" / "python.exe"
ICON = Path(r"C:\Users\lenovo\Pictures\icon.ico")
LANGUAGE_FILE = ROOT / "scripts" / "installer" / "ChineseSimplified.isl"
APP_ID = "{{4E2CFA0A-B86C-48A8-AC3D-72E347E01231}"

FORBIDDEN_ROOT_FILES = {
    "licensemanager.exe",
    "激活码管理.exe",
    "license_admin.json",
    "license_records.txt",
    "license_ws.dat",
    "license.dat",
    "ui_column_widths.json",
    "tg_verify.json",
    "wa_restore_result.json",
}
FORBIDDEN_ANYWHERE_FILES = {
    "address_book.json",
    "ui_locale.json",
    "tg已登录账号手机号.csv",
    "ws已登录账号手机号.csv",
}
TEXT_EXTENSIONS = {".json", ".txt", ".py", ".bat", ".ini", ".cfg", ".yaml", ".yml"}
TOKEN_PATTERN = re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}")


def version() -> str:
    text = (ROOT / "app_version.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise RuntimeError("app_version.py 中没有 APP_VERSION")
    return match.group(1)


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("\n>", subprocess.list2cmdline(command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def build_release_directory() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    env["WA_COLLECT_NAME"] = RELEASE_DIR.name
    env["WA_RELEASE_BUILD"] = "1"
    _run(
        [str(PYINSTALLER), str(ROOT / "build_windows.spec"), "--noconfirm", "--clean"],
        env=env,
    )
    _run([str(PYTHON), str(ROOT / "scripts" / "finalize_dist.py")], env=env)


def _sensitive_values() -> set[bytes]:
    values: set[bytes] = set()

    admin = ROOT / "userdata_preserve" / "license_admin.json"
    if admin.is_file():
        try:
            token = str(json.loads(admin.read_text(encoding="utf-8")).get("token") or "")
            if len(token) >= 20:
                values.add(token.encode())
        except (OSError, json.JSONDecodeError):
            pass

    for platform_name in ("telegram", "whatsapp"):
        config = ROOT / "userdata_preserve" / platform_name / "config.json"
        if not config.is_file():
            continue
        try:
            payload = json.loads(config.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        api_hash = str(payload.get("api_hash") or "").strip()
        if len(api_hash) >= 20:
            values.add(api_hash.encode())
        for account in payload.get("accounts") or []:
            session = str(account.get("session_name") or "").strip()
            phone = re.sub(r"\D", "", str(account.get("phone") or ""))
            if len(session) >= 12:
                values.add(session.encode("utf-8"))
            if len(phone) >= 10:
                values.add(phone.encode())
    return values


def audit_release_directory(directory: Path = RELEASE_DIR) -> None:
    if not directory.is_dir():
        raise RuntimeError(f"分发目录不存在：{directory}")

    violations: list[str] = []
    sensitive = _sensitive_values()
    files = [path for path in directory.rglob("*") if path.is_file()]
    for path in files:
        rel = path.relative_to(directory)
        parts = tuple(part.lower() for part in rel.parts)
        name = rel.name.lower()

        if len(parts) == 1 and name in FORBIDDEN_ROOT_FILES:
            violations.append(f"禁止的本机文件：{rel}")
        if name in FORBIDDEN_ANYWHERE_FILES:
            violations.append(f"禁止的用户数据或偏好文件：{rel}")
        if name == "config.json":
            violations.append(f"真实配置文件：{rel}")
        if name.endswith((".session", ".session-journal", ".db", ".db-wal", ".db-shm")):
            violations.append(f"账号会话文件：{rel}")
        if name.endswith(".log") or ".bak_" in name or name.endswith(".bak"):
            violations.append(f"日志或备份文件：{rel}")
        if len(parts) >= 2 and parts[0] in ("telegram", "whatsapp"):
            if parts[1] in ("sessions", "data", "logs", "userdata_preserve"):
                violations.append(f"平台用户数据：{rel}")

        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            continue
        if TOKEN_PATTERN.search(raw):
            violations.append(f"疑似 GitHub 令牌：{rel}")
        for value in sensitive:
            if value and value in raw:
                violations.append(f"匹配本机账号/密钥指纹：{rel}")
                break

    required = (
        directory / "超群小帮手.exe",
        directory / "_internal",
        directory / "license_public.json",
    )
    for path in required:
        if not path.exists():
            violations.append(f"缺少分发必需文件：{path.name}")

    if violations:
        raise RuntimeError("脱敏审计失败：\n- " + "\n- ".join(sorted(set(violations))))
    print(f"脱敏审计通过：{len(files)} 个文件，无配置、账号、session、任务、日志或管理密钥")


def make_zip() -> Path:
    output = DIST / f"WAHelper_{version()}_portable.zip"
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in RELEASE_DIR.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(RELEASE_DIR))
    print(f"已生成便携版：{output}")
    return output


def find_iscc() -> Path:
    candidates = (
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise RuntimeError("未找到 Inno Setup 6，请先安装 JRSoftware.InnoSetup")


def make_installer() -> Path:
    ver = version()
    numeric_version = ver.removeprefix("v")
    build_dir = ROOT / "build" / "installer"
    build_dir.mkdir(parents=True, exist_ok=True)
    iss = build_dir / "WAHelper.iss"
    output_name = f"WAHelper_{ver}_Setup"
    source = str(RELEASE_DIR).replace("\\", "\\\\")
    icon = str(ICON).replace("\\", "\\\\")
    language = str(LANGUAGE_FILE).replace("\\", "\\\\")
    output_dir = str(DIST).replace("\\", "\\\\")
    iss.write_text(
        f"""#define MyAppName "超群小帮手"
#define MyAppVersion "{numeric_version}"
#define MyAppExeName "超群小帮手.exe"

[Setup]
AppId={APP_ID}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher=WAHelper
DefaultDirName={{localappdata}}\\Programs\\WAHelper
DefaultGroupName={{#MyAppName}}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={output_dir}
OutputBaseFilename={output_name}
SetupIconFile={icon}
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "{language}"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："

[Files]
Source: "{source}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{autoprograms}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{autodesktop}}\\{{#MyAppName}}"; Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "启动 {{#MyAppName}}"; Flags: nowait postinstall skipifsilent
""",
        encoding="utf-8-sig",
    )
    _run([str(find_iscc()), str(iss)])
    installer = DIST / f"{output_name}.exe"
    if not installer.is_file():
        raise RuntimeError(f"安装程序未生成：{installer}")
    print(f"已生成安装程序：{installer}")
    return installer


def main() -> int:
    if not ICON.is_file():
        raise RuntimeError(f"图标不存在：{ICON}")
    if not LANGUAGE_FILE.is_file():
        raise RuntimeError(f"安装程序语言文件不存在：{LANGUAGE_FILE}")
    if not PYINSTALLER.is_file() or not PYTHON.is_file():
        raise RuntimeError("构建环境不完整")
    build_release_directory()
    audit_release_directory()
    make_zip()
    make_installer()
    print("\n分发构建完成。当前个人运行目录 dist\\WAHelper 未被修改。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\n构建失败：{exc}", file=sys.stderr)
        raise
