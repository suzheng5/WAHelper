# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir 打包：无控制台窗口，数据与 exe 同目录。"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

ROOT = os.path.dirname(os.path.abspath(SPEC))
PARENT = os.path.normpath(os.path.join(ROOT, ".."))
DIST = os.path.normpath(os.path.join(ROOT, "dist"))
_VENV_SITE = os.path.join(PARENT, ".venv", "Lib", "site-packages")
if os.path.isdir(_VENV_SITE) and _VENV_SITE not in sys.path:
    sys.path.insert(0, _VENV_SITE)

import neonize
from neonize.utils.platform import generated_name

EXE_NAME_ASCII = "WAHelper"
COLLECT_NAME = os.environ.get("WA_COLLECT_NAME", EXE_NAME_ASCII)
_ICON = r"C:\Users\lenovo\Pictures\icon.ico"


def _collect_wa_modules() -> list:
    names: list = []
    for fn in os.listdir(ROOT):
        if fn.endswith(".py") and fn != "main.py":
            names.append(os.path.splitext(fn)[0])
    for pkg in ("wa_ui", "qt_ui"):
        pkg_dir = os.path.join(ROOT, pkg)
        if not os.path.isdir(pkg_dir):
            continue
        names.append(pkg)
        for dirpath, _dirnames, filenames in os.walk(pkg_dir):
            for fn in filenames:
                if not fn.endswith(".py") or fn.startswith("__"):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), ROOT)
                mod = os.path.splitext(rel)[0].replace(os.sep, ".")
                names.append(mod)
    return names


def _collect_i18n() -> tuple[list, list]:
    """i18n 包与 locales 词典（v2.1+ 必须打进包）。"""
    imports: list = ["i18n"]
    datas: list = []
    i18n_dir = os.path.join(ROOT, "i18n")
    if os.path.isdir(i18n_dir):
        try:
            imports += collect_submodules("i18n")
        except Exception:
            imports += [
                "i18n.pause_reason",
                "i18n.job_card",
                "i18n.system_locale",
                "i18n.ui_locale_store",
                "i18n.ui_helpers",
            ]
        locales = os.path.join(i18n_dir, "locales")
        if os.path.isdir(locales):
            datas.append((locales, os.path.join("i18n", "locales")))
    return imports, datas


_main = os.path.join(ROOT, "main.py")
_datas = []
_binaries = []
_i18n_imports, _i18n_datas = _collect_i18n()
_datas += _i18n_datas
_hiddenimports = [
    "customtkinter",
    "PIL",
    "PIL._tkinter_finder",
    "segno",
    "phonenumbers",
    "magic",
    "linkpreview",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "shiboken6",
    "neonize",
    "neonize.aioze",
    "neonize.aioze.client",
    "neonize.aioze.events",
    "neonize._binder",
    "neonize.proto",
    "neonize.proto.Neonize_pb2",
    "neonize.utils",
    "neonize.utils.jid",
    "neonize.utils.message",
    "telethon",
    "telethon.crypto",
    "telethon.extensions",
    "certifi",
] + _collect_wa_modules() + _i18n_imports

try:
    _hiddenimports += collect_submodules("tg_multi_listener")
except Exception:
    _hiddenimports += [
        "tg_multi_listener",
        "tg_multi_listener.compat_config",
        "tg_multi_listener.config",
        "tg_multi_listener.ui.embed",
        "tg_multi_listener.ui.app",
        "tg_multi_listener.ui.theme",
        "tg_multi_listener.ui.login_dialog",
        "tg_multi_listener.listener",
        "tg_multi_listener.telethon_coordinator",
        "tg_multi_listener.telethon_auth",
        "tg_multi_listener.scheduler",
        "tg_multi_listener.schedule2_runner",
        "tg_multi_listener.schedule_txt_import",
        "tg_multi_listener.notifier",
        "tg_multi_listener.stats",
        "tg_multi_listener.group_owner",
        "tg_multi_listener.session_check",
        "tg_multi_listener.paths",
        "tg_multi_listener.logger_util",
    ]

for pkg in ("neonize", "phonenumbers", "google.protobuf", "telethon"):
    try:
        d, b, h = collect_all(pkg)
        if pkg == "neonize":
            # DLL 必须与 v3.0.17 的 0.3.18 Python binding 成套使用；
            # 移除 collect_all 自动加入的 wheel DLL，稍后只加入已验证稳定版。
            _dll_name = generated_name().lower()
            d = [row for row in d if os.path.basename(row[0]).lower() != _dll_name]
            b = [row for row in b if os.path.basename(row[0]).lower() != _dll_name]
        _datas += d
        _binaries += b
        _hiddenimports += h
    except Exception:
        pass

# 仅收集 Widgets 栈所需 DLL/插件，禁止 collect_dynamic_libs(PySide6) 全量拉取
# （全量会带上 QtWebEngine ~195MB、Multimedia、QML 等，打包与体积都会暴涨）
try:
    import glob as _glob

    import PySide6
    import shiboken6
    from PyInstaller.utils.hooks import collect_data_files

    _datas += collect_data_files(
        "PySide6",
        includes=[
            "plugins/platforms/qwindows.*",
            "plugins/styles/*",
            "plugins/imageformats/*",
            "plugins/iconengines/*",
            "plugins/tls/*",
            "translations/qtbase_*.qm",
            "translations/qt_*.qm",
        ],
    )
    _pyside_dir = os.path.dirname(PySide6.__file__)
    _shiboken_dir = os.path.dirname(shiboken6.__file__)
    _qt_dll_allow = {
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "Qt6Network.dll",
        "Qt6Svg.dll",
        "Qt6OpenGL.dll",
        "pyside6.abi3.dll",
        "opengl32sw.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_codecvt_ids.dll",
    }
    for _dll_name in _qt_dll_allow:
        _dll_path = os.path.join(_pyside_dir, _dll_name)
        if os.path.isfile(_dll_path):
            _binaries.append((_dll_path, "PySide6"))
    for _dll_path in _glob.glob(os.path.join(_shiboken_dir, "*.dll")):
        _binaries.append((_dll_path, "shiboken6"))
except Exception:
    pass

_neonize_root = os.path.dirname(neonize.__file__)
_stable_go_dll = os.path.join(ROOT, generated_name())
_go_dll = (
    _stable_go_dll
    if os.path.isfile(_stable_go_dll)
    else os.path.join(_neonize_root, generated_name())
)
if os.path.isfile(_go_dll):
    _binaries.append((_go_dll, "neonize"))
else:
    raise FileNotFoundError(f"未找到 neonize 动态库：{_go_dll}")

for _doc_name in ("定时任务导入说明与示例.txt", "整合版说明.txt"):
    _doc = os.path.join(ROOT, "docs", _doc_name)
    if os.path.isfile(_doc):
        _datas.append((_doc, "docs"))
for _cfg_name in ("config.example.json", "config.example.tg.json"):
    _cfg = os.path.join(ROOT, _cfg_name)
    if os.path.isfile(_cfg):
        _datas.append((_cfg, "."))

_rthook = os.path.join(ROOT, "hooks", "rthook_wa_path.py")
_rthook_qt = os.path.join(ROOT, "hooks", "rthook_qt_plugins.py")
_rthook_cert = os.path.join(ROOT, "hooks", "rthook_certifi.py")
_runtime_hooks = [p for p in (_rthook, _rthook_qt, _rthook_cert) if os.path.isfile(p)]

_excludes = [
    "ui",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtHttpServer",
    "PySide6.QtRemoteObjects",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "matplotlib",
    "scipy",
    "IPython",
    "notebook",
    # 环境里可能装了，但本应用不依赖；避免分析/拷贝拖慢打包
    "numpy",
    "pyarrow",
    "pandas",
    "sklearn",
    "torch",
    "tensorflow",
]

a = Analysis(
    [_main],
    pathex=[ROOT, PARENT],
    binaries=_binaries,
    datas=_datas,
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
    excludes=_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME_ASCII,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_ICON if os.path.isfile(_ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[
        "Qt6Core.dll",
        "Qt6Gui.dll",
        "Qt6Widgets.dll",
        "Qt6Network.dll",
        "qwindows.dll",
        "PySide6",
        "shiboken6",
    ],
    name=COLLECT_NAME,
    distpath=DIST,
)
