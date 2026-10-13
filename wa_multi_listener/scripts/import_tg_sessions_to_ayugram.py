"""将本软件中的 Telethon session 批量导入同一个 AyuGram tdata。

用户只需选择软件根目录与 AyuGram 根目录。程序会使用 session 快照进行转换，
转换全部成功后才替换 AyuGram/tdata，并始终保留带时间戳的完整备份。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import traceback
import types
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _install_tgcrypto_fallback() -> None:
    """Python 3.12 没有 TgCrypto wheel，以 PyCryptodome 提供兼容的 AES-IGE。"""
    try:
        import tgcrypto  # noqa: F401

        return
    except ImportError:
        pass

    from Crypto.Cipher import AES

    def xor(left: bytes, right: bytes) -> bytes:
        return bytes(a ^ b for a, b in zip(left, right))

    def encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
        src, aes_key, aes_iv = bytes(data), bytes(key), bytes(iv)
        if len(src) % 16 or len(aes_key) != 32 or len(aes_iv) != 32:
            raise ValueError("AES-IGE 参数长度无效")
        cipher = AES.new(aes_key, AES.MODE_ECB)
        previous_cipher, previous_plain = aes_iv[:16], aes_iv[16:]
        output = bytearray()
        for offset in range(0, len(src), 16):
            plain = src[offset : offset + 16]
            encrypted = xor(cipher.encrypt(xor(plain, previous_cipher)), previous_plain)
            output.extend(encrypted)
            previous_plain, previous_cipher = plain, encrypted
        return bytes(output)

    def decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
        src, aes_key, aes_iv = bytes(data), bytes(key), bytes(iv)
        if len(src) % 16 or len(aes_key) != 32 or len(aes_iv) != 32:
            raise ValueError("AES-IGE 参数长度无效")
        cipher = AES.new(aes_key, AES.MODE_ECB)
        previous_cipher, previous_plain = aes_iv[:16], aes_iv[16:]
        output = bytearray()
        for offset in range(0, len(src), 16):
            encrypted = src[offset : offset + 16]
            plain = xor(cipher.decrypt(xor(encrypted, previous_plain)), previous_cipher)
            output.extend(plain)
            previous_plain, previous_cipher = plain, encrypted
        return bytes(output)

    module = types.ModuleType("tgcrypto")
    module.ige256_encrypt = encrypt  # type: ignore[attr-defined]
    module.ige256_decrypt = decrypt  # type: ignore[attr-defined]
    sys.modules["tgcrypto"] = module


_install_tgcrypto_fallback()

from opentele.api import APIData, UseCurrentSession  # noqa: E402
from opentele.td import Account, TDesktop  # noqa: E402
from PyQt5.QtCore import QThread, Qt, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QFont  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from telethon import TelegramClient  # noqa: E402


APP_TITLE = "TG 账号迁移到 AyuGram"
PROCESS_NAMES = {"AyuGram.exe", "超群小帮手.exe", "WAHelper.exe"}


def _api_data_equal(left: APIData, right: object) -> bool:
    """修复 opentele 1.15.1：APIData.copy() 更换随机 pid，导致多账号递归。"""
    if not isinstance(right, APIData):
        return False
    fields = (
        "api_id",
        "api_hash",
        "device_model",
        "system_version",
        "app_version",
        "lang_code",
        "system_lang_code",
        "lang_pack",
    )
    return all(getattr(left, name, None) == getattr(right, name, None) for name in fields)


APIData.__eq__ = _api_data_equal  # type: ignore[method-assign]


@dataclass
class ImportResult:
    session: str
    account_name: str
    user_id: int = 0
    phone: str = ""
    display_name: str = ""
    status: str = ""


def resolve_telegram_dir(root: Path) -> Path:
    candidates = (root / "telegram", root)
    for candidate in candidates:
        if (candidate / "config.json").is_file() and (candidate / "sessions").is_dir():
            return candidate
    raise RuntimeError("所选目录中没有找到 telegram/config.json 和 telegram/sessions")


def validate_ayugram_root(root: Path) -> None:
    if not (root / "AyuGram.exe").is_file():
        raise RuntimeError("所选目录中没有找到 AyuGram.exe")


def running_target_processes() -> list[str]:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        raw = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            encoding="mbcs",
            errors="replace",
            creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: set[str] = set()
    for line in raw.splitlines():
        name = line.strip().strip('"').split('","', 1)[0]
        if name.lower() in {item.lower() for item in PROCESS_NAMES}:
            found.add(name)
    return sorted(found)


def clone_session(source: Path, target: Path) -> None:
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(
            f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=10
        )
        target_connection = sqlite3.connect(target, timeout=10)
        source_connection.backup(target_connection)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()


def account_display_name(user: Any) -> str:
    return " ".join(
        value
        for value in (
            str(getattr(user, "first_name", "") or "").strip(),
            str(getattr(user, "last_name", "") or "").strip(),
        )
        if value
    )


def copy_ayugram_preferences(old_tdata: Path, new_tdata: Path) -> None:
    """保留 AyuGram 自身偏好和反撤回数据库，不复制旧认证与缓存。"""
    for name in ("ayu_settings.json", "ayudata.db"):
        source = old_tdata / name
        if source.is_file():
            shutil.copy2(source, new_tdata / name)


async def import_accounts(
    software_root: Path,
    ayugram_root: Path,
    notify: Callable[[str], None],
    progress: Callable[[int, int], None],
) -> tuple[list[ImportResult], Path | None]:
    telegram_dir = resolve_telegram_dir(software_root)
    validate_ayugram_root(ayugram_root)
    config = json.loads((telegram_dir / "config.json").read_text(encoding="utf-8-sig"))
    api_id = int(config.get("api_id") or 0)
    api_hash = str(config.get("api_hash") or "").strip()
    if api_id <= 0 or not api_hash:
        raise RuntimeError("Telegram 配置缺少 api_id 或 api_hash")

    configured: dict[str, str] = {}
    for account in config.get("accounts") or []:
        session_name = str(account.get("session_name") or account.get("id") or "").strip()
        if session_name:
            configured[session_name] = str(account.get("id") or session_name).strip()

    session_files = sorted(
        (telegram_dir / "sessions").glob("*.session"),
        key=lambda path: (path.stem not in configured, configured.get(path.stem, path.stem)),
    )
    if not session_files:
        raise RuntimeError("没有找到任何 .session 登录文件")

    notify(f"发现 {len(session_files)} 个 session，开始验证并转换……")
    results: list[ImportResult] = []
    seen_user_ids: set[int] = set()
    clients: list[TelegramClient] = []
    temp_root = Path(tempfile.mkdtemp(prefix="ayugram-import-"))
    stage_tdata = temp_root / "tdata"
    stage_tdata.mkdir(parents=True)

    # opentele 的 3 账号限制只是客户端默认常量；AyuGram 可读取更多账号索引。
    TDesktop.kMaxAccounts = max(100, len(session_files) + 5)
    desktop: TDesktop | None = None
    desktop_api = APIData(
        api_id=api_id,
        api_hash=api_hash,
        device_model="AyuGram Desktop",
        system_version="Windows",
        app_version="6.2",
        lang_code="zh-hans",
        system_lang_code="zh-hans",
        lang_pack="tdesktop",
    )

    try:
        total = len(session_files)
        for index, source in enumerate(session_files, start=1):
            account_name = configured.get(source.stem, f"历史会话：{source.stem}")
            result = ImportResult(session=source.stem, account_name=account_name)
            progress(index - 1, total)
            notify(f"[{index}/{total}] 正在验证：{account_name}")

            cloned_base = temp_root / "sessions" / f"account_{index:03d}"
            cloned_base.parent.mkdir(parents=True, exist_ok=True)
            try:
                clone_session(source, cloned_base.with_suffix(".session"))
                client = TelegramClient(
                    str(cloned_base),
                    api_id,
                    api_hash,
                    connection_retries=1,
                    request_retries=1,
                    timeout=15,
                )
                clients.append(client)
                await asyncio.wait_for(client.connect(), timeout=25)
                if not await asyncio.wait_for(client.is_user_authorized(), timeout=15):
                    result.status = "跳过：session 已失效或未登录"
                    results.append(result)
                    notify(f"[{index}/{total}] {account_name}：{result.status}")
                    continue

                user = await asyncio.wait_for(client.get_me(), timeout=20)
                user_id = int(getattr(user, "id", 0) or 0)
                if user_id <= 0:
                    raise RuntimeError("无法取得 Telegram 用户 ID")
                result.user_id = user_id
                result.phone = str(getattr(user, "phone", "") or "").strip()
                result.display_name = account_display_name(user)
                if user_id in seen_user_ids:
                    result.status = "跳过：同一账号的重复 session"
                    results.append(result)
                    notify(f"[{index}/{total}] {account_name}：{result.status}")
                    continue

                if desktop is None:
                    desktop = await asyncio.wait_for(
                        TDesktop.FromTelethon(
                            client,
                            flag=UseCurrentSession,
                            api=desktop_api,
                        ),
                        timeout=45,
                    )
                else:
                    await asyncio.wait_for(
                        Account.FromTelethon(
                            client,
                            flag=UseCurrentSession,
                            api=desktop_api,
                            owner=desktop,
                        ),
                        timeout=45,
                    )
                seen_user_ids.add(user_id)
                result.status = "已导入"
                results.append(result)
                notify(
                    f"[{index}/{total}] 已导入：{account_name}"
                    + (f"（+{result.phone}）" if result.phone else "")
                )
            except asyncio.TimeoutError:
                result.status = "失败：连接或转换超时"
                results.append(result)
                notify(f"[{index}/{total}] {account_name}：{result.status}")
            except Exception as exc:
                result.status = f"失败：{type(exc).__name__}: {exc}"
                results.append(result)
                notify(f"[{index}/{total}] {account_name}：{result.status}")
            finally:
                if clients:
                    client = clients[-1]
                    try:
                        await client.disconnect()
                    except Exception:
                        pass
                    try:
                        client.session.close()
                    except Exception:
                        pass
            progress(index, total)

        imported = sum(result.status == "已导入" for result in results)
        if imported == 0 or desktop is None:
            raise RuntimeError("没有可导入的有效账号，AyuGram 数据未修改")

        notify(f"正在生成包含 {imported} 个账号的统一 tdata……")
        desktop.SaveTData(str(stage_tdata))
        if not (stage_tdata / "key_datas").is_file():
            raise RuntimeError("转换器没有生成有效的 key_datas")

        old_tdata = ayugram_root / "tdata"
        if old_tdata.is_dir():
            copy_ayugram_preferences(old_tdata, stage_tdata)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup: Path | None = None
        if old_tdata.exists():
            backup = ayugram_root / f"tdata_backup_{stamp}"
            old_tdata.rename(backup)
        try:
            shutil.move(str(stage_tdata), str(old_tdata))
        except Exception:
            if backup is not None and backup.exists() and not old_tdata.exists():
                backup.rename(old_tdata)
            raise

        report = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "software_root": str(software_root),
            "ayugram_root": str(ayugram_root),
            "backup": str(backup) if backup else "",
            "session_count": len(session_files),
            "imported_count": imported,
            "results": [asdict(result) for result in results],
        }
        (ayugram_root / "AyuGram账号导入报告.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return results, backup
    finally:
        for client in clients:
            try:
                await client.disconnect()
            except Exception:
                pass
            try:
                client.session.close()
            except Exception:
                pass
        shutil.rmtree(temp_root, ignore_errors=True)


class ImportWorker(QThread):
    log = pyqtSignal(str)
    step = pyqtSignal(int, int)
    succeeded = pyqtSignal(int, int, str)
    failed = pyqtSignal(str)

    def __init__(self, software_root: Path, ayugram_root: Path) -> None:
        super().__init__()
        self.software_root = software_root
        self.ayugram_root = ayugram_root

    def run(self) -> None:
        try:
            results, backup = asyncio.run(
                import_accounts(
                    self.software_root,
                    self.ayugram_root,
                    self.log.emit,
                    self.step.emit,
                )
            )
            imported = sum(result.status == "已导入" for result in results)
            self.succeeded.emit(imported, len(results), str(backup or "无原 tdata"))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker: ImportWorker | None = None
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(760, 590)
        self.resize(820, 640)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(16)

        title = QLabel("把已登录账号搬进 AyuGram")
        title.setObjectName("title")
        subtitle = QLabel("只选两个文件夹。程序会验证全部 session、去重、备份并生成一个统一 tdata。")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.software_edit = self._path_card(
            layout,
            "本软件根目录",
            "目录内应包含 telegram\\config.json，例如 dist\\WAHelper",
            self._choose_software,
        )
        self.ayugram_edit = self._path_card(
            layout,
            "AyuGram 根目录",
            "目录内应包含 AyuGram.exe，例如 D:\\AyuGram",
            self._choose_ayugram,
        )

        safety = QLabel("安全策略  ·  原 session 只读快照  ·  完成后才替换  ·  原 tdata 自动备份")
        safety.setObjectName("safety")
        layout.addWidget(safety)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("运行过程会显示在这里……")
        layout.addWidget(self.log_view, 1)

        buttons = QHBoxLayout()
        self.open_report_button = QPushButton("打开导入报告")
        self.open_report_button.setObjectName("secondary")
        self.open_report_button.clicked.connect(self._open_report)
        self.open_report_button.setEnabled(False)
        buttons.addWidget(self.open_report_button)
        buttons.addStretch()
        self.start_button = QPushButton("开始导入全部账号")
        self.start_button.clicked.connect(self._start)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #101827; color: #E9F0F7; }
            QLabel#title { font-size: 27px; font-weight: 700; color: #FFFFFF; }
            QLabel#subtitle { font-size: 13px; color: #9FB0C4; }
            QLabel#cardTitle { font-size: 14px; font-weight: 650; color: #EAF7FF; }
            QLabel#hint { font-size: 11px; color: #7F91A7; }
            QLabel#safety {
                background: #132A31; color: #73D8C8; border: 1px solid #22505A;
                border-radius: 8px; padding: 9px 12px;
            }
            QFrame#pathCard {
                background: #172235; border: 1px solid #26364D; border-radius: 12px;
            }
            QLineEdit {
                background: #0D1522; border: 1px solid #31445F; border-radius: 7px;
                padding: 9px 11px; color: #E9F0F7; selection-background-color: #18A58F;
            }
            QTextEdit {
                background: #0B121D; border: 1px solid #26364D; border-radius: 10px;
                padding: 10px; color: #BFD0E2; font-family: Consolas, "Microsoft YaHei UI";
            }
            QPushButton {
                background: #1FC7A8; color: #071511; border: none; border-radius: 8px;
                padding: 10px 18px; font-weight: 700;
            }
            QPushButton:hover { background: #35D8BA; }
            QPushButton:disabled { background: #344255; color: #7D8A9B; }
            QPushButton#secondary {
                background: #22324A; color: #C9D8E8; border: 1px solid #354A68;
            }
            QProgressBar {
                background: #0D1522; border: 1px solid #26364D; border-radius: 6px;
                height: 12px; color: transparent;
            }
            QProgressBar::chunk { background: #1FC7A8; border-radius: 5px; }
            """
        )

    def _path_card(
        self,
        parent: QVBoxLayout,
        title_text: str,
        hint_text: str,
        choose: Callable[[], None],
    ) -> QLineEdit:
        card = QFrame()
        card.setObjectName("pathCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 13, 16, 14)
        card_layout.setSpacing(7)
        title = QLabel(title_text)
        title.setObjectName("cardTitle")
        hint = QLabel(hint_text)
        hint.setObjectName("hint")
        row = QHBoxLayout()
        edit = QLineEdit()
        button = QPushButton("选择文件夹")
        button.setObjectName("secondary")
        button.clicked.connect(choose)
        row.addWidget(edit, 1)
        row.addWidget(button)
        card_layout.addWidget(title)
        card_layout.addWidget(hint)
        card_layout.addLayout(row)
        parent.addWidget(card)
        return edit

    def _choose_software(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择本软件根目录")
        if path:
            self.software_edit.setText(path)

    def _choose_ayugram(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 AyuGram 根目录")
        if path:
            self.ayugram_edit.setText(path)

    def _set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.software_edit.setEnabled(not busy)
        self.ayugram_edit.setEnabled(not busy)

    def _start(self) -> None:
        software_root = Path(self.software_edit.text().strip())
        ayugram_root = Path(self.ayugram_edit.text().strip())
        try:
            resolve_telegram_dir(software_root)
            validate_ayugram_root(ayugram_root)
        except Exception as exc:
            QMessageBox.warning(self, APP_TITLE, str(exc))
            return

        running = running_target_processes()
        if running:
            QMessageBox.warning(
                self,
                APP_TITLE,
                "请先完全退出以下程序后再导入：\n\n" + "\n".join(running),
            )
            return

        answer = QMessageBox.question(
            self,
            APP_TITLE,
            "即将验证并导入全部 session。\n\n"
            "AyuGram 现有 tdata 会先完整备份，再替换为统一账号数据。\n"
            "转换期间请勿启动本软件或 AyuGram。\n\n继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.log_view.clear()
        self.progress.setValue(0)
        self.open_report_button.setEnabled(False)
        self._set_busy(True)
        self.worker = ImportWorker(software_root.resolve(), ayugram_root.resolve())
        self.worker.log.connect(self.log_view.append)
        self.worker.step.connect(self._on_step)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.start()

    def _on_step(self, current: int, total: int) -> None:
        self.progress.setValue(round(current * 100 / max(1, total)))

    def _on_success(self, imported: int, total: int, backup: str) -> None:
        self._set_busy(False)
        self.progress.setValue(100)
        self.open_report_button.setEnabled(True)
        message = (
            f"导入完成：{imported} 个账号已写入 AyuGram。\n"
            f"共检查 {total} 个 session。\n\n原 tdata 备份：\n{backup}"
        )
        self.log_view.append("\n" + message.replace("\n", "<br>"))
        QMessageBox.information(self, APP_TITLE, message)

    def _on_failure(self, message: str) -> None:
        self._set_busy(False)
        self.log_view.append(f"\n导入失败：{message}")
        QMessageBox.critical(
            self,
            APP_TITLE,
            "导入未完成，原 AyuGram 数据未被替换。\n\n" + message,
        )

    def _open_report(self) -> None:
        root = Path(self.ayugram_edit.text().strip())
        report = root / "AyuGram账号导入报告.json"
        if report.is_file():
            os.startfile(report)  # type: ignore[attr-defined]


def main() -> int:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "WAHelper.AyuGramImporter"
            )
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
