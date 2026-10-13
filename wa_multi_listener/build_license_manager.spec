# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onefile：激活码管理（仅放本机 dist/WAHelper，不打进分发 zip）。"""
import os

import customtkinter

block_cipher = None

ROOT = os.path.dirname(os.path.abspath(SPEC))
AI_ROOT = os.path.normpath(os.path.join(ROOT, ".."))
DIST = os.path.normpath(os.path.join(ROOT, "dist"))
_ICON = r"C:\Users\USER\Pictures\icon.ico"

_ctk_path = os.path.dirname(customtkinter.__file__)
_gen_license = os.path.join(AI_ROOT, "gen_license.py")

a = Analysis(
    [_gen_license],
    pathex=[AI_ROOT],
    binaries=[],
    datas=[(_ctk_path, "customtkinter")],
    hiddenimports=["customtkinter", "license_gist"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="LicenseManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON if os.path.isfile(_ICON) else None,
    distpath=DIST,
)
