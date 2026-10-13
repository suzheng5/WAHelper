"""PyInstaller：为 Telethon/aiohttp 指定 CA 证书路径。"""
from __future__ import annotations

import os
import sys


def _configure_ssl_certs() -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except Exception:
        pass


_configure_ssl_certs()
