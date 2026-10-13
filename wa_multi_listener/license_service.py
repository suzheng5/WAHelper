"""WS 助手 / 超群小帮手激活校验（与 TelegramSender 共用机器指纹，Gist 按 product=ws 区分）。"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import ssl
import subprocess
import time
import urllib.request
from datetime import datetime
from typing import Optional, Tuple

from paths import app_root

LICENSE_FILE = "license_ws.dat"
PRODUCT = "ws"
PUBLIC_CONFIG_FILE = "license_public.json"
# WS 助手专用 Gist（勿与 TelegramSender 默认 Gist 混用）
DEFAULT_GIST_RAW_URL = (
    "https://gist.githubusercontent.com/suzheng6/4030cd2b3bdf2e10e2a9c47030880986/raw/licenses.json"
)
# 与 TelegramSender 共用机器指纹盐，管理员只需一份机器 ID
_MACHINE_SALT = "TgSenderLic2024"
_XOR_SALT = "WsHelperLic2026"


def get_machine_id() -> str:
    components: list[str] = []
    try:
        if platform.system() == "Windows":
            for cmd in (
                "wmic cpu get ProcessorId",
                "wmic baseboard get SerialNumber",
                "wmic diskdrive get SerialNumber",
            ):
                try:
                    output = (
                        subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL)
                        .decode()
                        .strip()
                    )
                    lines = [line.strip() for line in output.split("\n") if line.strip()]
                    if not lines:
                        continue
                    val = lines[-1]
                    if val in ("ProcessorId", "SerialNumber"):
                        continue
                    if val in ("To be filled by O.E.M.", ""):
                        continue
                    components.append(val)
                except Exception:
                    pass
    except Exception:
        pass
    components.append(platform.node())
    combined = "-".join(components)
    return hashlib.sha256((combined + _MACHINE_SALT).encode()).hexdigest()[:16].upper()


def _encode_license_data(data: dict) -> str:
    json_str = json.dumps(data)
    key = _XOR_SALT.encode()
    encoded = bytes([b ^ key[i % len(key)] for i, b in enumerate(json_str.encode())])
    return encoded.hex()


def _decode_license_data(encoded: str) -> Optional[dict]:
    try:
        data = bytes.fromhex(encoded)
        key = _XOR_SALT.encode()
        decoded = bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])
        return json.loads(decoded.decode())
    except Exception:
        return None


def _license_path() -> str:
    return os.path.join(app_root(), LICENSE_FILE)


def _save_local_license(code: str, machine_id: str, expires: str) -> None:
    data = {
        "code": code,
        "machine_id": machine_id,
        "expires": expires,
        "activated_at": datetime.now().isoformat(),
        "product": PRODUCT,
    }
    try:
        with open(_license_path(), "w", encoding="utf-8") as f:
            f.write(_encode_license_data(data))
    except OSError:
        pass


def _load_local_license() -> Optional[dict]:
    try:
        path = _license_path()
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return _decode_license_data(f.read().strip())
    except OSError:
        pass
    return None


def _normalize_gist_raw_url(url: str) -> str:
    u = (url or "").strip().split("?")[0]
    if "/raw/" not in u:
        return u
    prefix, rest = u.split("/raw/", 1)
    filename = rest.split("/")[-1] or "licenses.json"
    return f"{prefix}/raw/{filename}"


def _gist_raw_url() -> str:
    path = os.path.join(app_root(), PUBLIC_CONFIG_FILE)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            url = _normalize_gist_raw_url(str(data.get("raw_url") or ""))
            if url:
                return url
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return DEFAULT_GIST_RAW_URL


def _fetch_remote_licenses() -> Optional[dict]:
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        cache_bust_url = f"{_gist_raw_url()}?t={int(time.time())}"
        req = urllib.request.Request(
            cache_bust_url,
            headers={
                "User-Agent": "WsHelper",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=15, context=ctx) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _product_ok(info: dict) -> bool:
    p = (info.get("product") or "").strip().lower()
    return p in (PRODUCT, "whatsapp", "wa")


def _parse_expires(expires: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat((expires or "").replace("Z", ""))
    except Exception:
        return None


def check_license() -> Tuple[bool, str, Optional[str]]:
    machine_id = get_machine_id()
    local = _load_local_license()
    if not local:
        return False, "未激活", None

    if local.get("machine_id") != machine_id:
        return False, "激活码已绑定到其他设备", None

    expires_str = local.get("expires", "")
    expires_date = _parse_expires(expires_str)
    if not expires_date:
        return False, "激活数据损坏", None
    if datetime.now() > expires_date:
        return False, f"激活码已过期 ({expires_str[:10]})", expires_str[:10]

    code = local.get("code", "")
    remote = _fetch_remote_licenses()
    if remote is not None:
        license_info = remote.get(code)
        if license_info is None:
            # 远程无此码：保留本地有效激活（永久码可能未同步到 Gist）
            pass
        elif not _product_ok(license_info):
            return False, "激活码已失效（非 WS 助手激活码）", None
        else:
            remote_machine = license_info.get("machine")
            if remote_machine and remote_machine != machine_id:
                return False, "激活码已绑定到其他设备", None
            remote_expires = license_info.get("expires", "")
            remote_exp_date = _parse_expires(remote_expires)
            if remote_exp_date:
                if datetime.now() > remote_exp_date:
                    return False, f"激活码已过期 ({remote_expires[:10]})", remote_expires[:10]
                expires_str = remote_expires
                expires_date = remote_exp_date

    days_left = (expires_date - datetime.now()).days
    return True, f"已激活，剩余 {days_left} 天", expires_str[:10]


def activate(code: str) -> Tuple[bool, str]:
    code = (code or "").strip().upper()
    if not code:
        return False, "请输入激活码"

    machine_id = get_machine_id()
    remote = _fetch_remote_licenses()
    if not remote:
        return False, "无法连接激活服务器，请检查网络"

    license_info = remote.get(code)
    if not license_info:
        return False, "激活码不存在（请确认码是否正确，或联系管理员重新生成）"
    if not _product_ok(license_info):
        product = (license_info.get("product") or "").strip() or "未标注"
        return False, f"激活码无效（该码产品标识为 {product}，需要 WS 助手专用码）"

    bound_machine = license_info.get("machine")
    if bound_machine and bound_machine != machine_id:
        return False, f"此激活码已绑定到其他设备\n您的机器ID: {machine_id}"
    if not bound_machine:
        return False, f"激活码未绑定设备\n请将您的机器ID发送给管理员: {machine_id}"

    expires = license_info.get("expires", "")
    expires_date = _parse_expires(expires)
    if not expires_date:
        return False, "激活码数据格式错误"
    if datetime.now() > expires_date:
        return False, f"激活码已过期 ({expires[:10]})"

    _save_local_license(code, machine_id, expires)
    days_left = (expires_date - datetime.now()).days
    return True, f"激活成功！有效期至 {expires[:10]}（{days_left} 天）"


def get_license_info() -> dict:
    machine_id = get_machine_id()
    local = _load_local_license()
    info = {
        "machine_id": machine_id,
        "activated": False,
        "code": None,
        "expires": None,
        "days_left": 0,
    }
    if not local:
        return info
    info["code"] = (local.get("code", "") or "")[:8] + "****"
    info["expires"] = (local.get("expires", "") or "")[:10]
    expires_date = _parse_expires(local.get("expires", ""))
    if expires_date:
        info["days_left"] = max(0, (expires_date - datetime.now()).days)
        info["activated"] = datetime.now() < expires_date
    return info
