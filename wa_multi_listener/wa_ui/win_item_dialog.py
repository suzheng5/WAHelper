"""Windows Vista+ IFileOpenDialog：统一文件、多选图片与文件夹选择。"""
from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import wintypes
from typing import Optional, Sequence, Tuple


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class COMDLG_FILTERSPEC(ctypes.Structure):
    _fields_ = [
        ("pszName", wintypes.LPCWSTR),
        ("pszSpec", wintypes.LPCWSTR),
    ]


def _guid(value: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _failed(hr: int) -> bool:
    return ctypes.c_long(hr).value < 0


def _method(
    interface: ctypes.c_void_p,
    index: int,
    restype: object,
    *argtypes: object,
):
    vtable = ctypes.cast(
        interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    prototype = ctypes.WINFUNCTYPE(
        restype, ctypes.c_void_p, *argtypes
    )
    return prototype(vtable[index])


def _release(interface: ctypes.c_void_p) -> None:
    if not interface.value:
        return
    try:
        _method(interface, 2, ctypes.c_ulong)(interface)
    except Exception:
        pass


def _item_path(item: ctypes.c_void_p) -> tuple[str, int]:
    SIGDN_FILESYSPATH = 0x80058000
    pointer = ctypes.c_void_p()
    get_display_name = _method(
        item,
        5,
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_void_p),
    )
    hr = int(get_display_name(item, SIGDN_FILESYSPATH, ctypes.byref(pointer)))
    if _failed(hr) or not pointer.value:
        return "", hr & 0xFFFFFFFF
    try:
        return os.path.abspath(ctypes.wstring_at(pointer.value)), 0
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def pick_items(
    *,
    title: str = "",
    initialdir: str = "",
    filetypes: Optional[Sequence[Tuple[str, str]]] = None,
    owner_hwnd: int = 0,
    multi: bool = False,
    folders: bool = False,
) -> tuple[list[str], int]:
    """返回 (绝对路径列表, HRESULT)；取消时 HRESULT 为 0。"""
    if sys.platform != "win32":
        return [], 0

    CLSID_FILE_OPEN_DIALOG = _guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
    IID_FILE_OPEN_DIALOG = _guid("D57C7288-D4AD-4768-BE02-9D969532D960")
    IID_SHELL_ITEM = _guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")
    CLSCTX_INPROC_SERVER = 0x1
    COINIT_APARTMENTTHREADED = 0x2
    RPC_E_CHANGED_MODE = 0x80010106
    ERROR_CANCELLED_HR = 0x800704C7
    FOS_PICKFOLDERS = 0x00000020
    FOS_FORCEFILESYSTEM = 0x00000040
    FOS_ALLOWMULTISELECT = 0x00000200
    FOS_PATHMUSTEXIST = 0x00000800
    FOS_FILEMUSTEXIST = 0x00001000
    FOS_NOCHANGEDIR = 0x00000008

    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    init_hr = int(ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED))
    init_code = init_hr & 0xFFFFFFFF
    if _failed(init_hr) and init_code != RPC_E_CHANGED_MODE:
        return [], init_code
    uninitialize = init_hr in (0, 1)

    dialog = ctypes.c_void_p()
    folder_item = ctypes.c_void_p()
    result_item = ctypes.c_void_p()
    result_array = ctypes.c_void_p()
    try:
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ole32.CoCreateInstance.restype = ctypes.c_long
        hr = int(
            ole32.CoCreateInstance(
                ctypes.byref(CLSID_FILE_OPEN_DIALOG),
                None,
                CLSCTX_INPROC_SERVER,
                ctypes.byref(IID_FILE_OPEN_DIALOG),
                ctypes.byref(dialog),
            )
        )
        if _failed(hr) or not dialog.value:
            return [], hr & 0xFFFFFFFF

        options = wintypes.DWORD()
        hr = int(
            _method(
                dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD)
            )(dialog, ctypes.byref(options))
        )
        if _failed(hr):
            return [], hr & 0xFFFFFFFF
        flags = (
            options.value
            | FOS_FORCEFILESYSTEM
            | FOS_PATHMUSTEXIST
            | FOS_NOCHANGEDIR
        )
        flags |= FOS_PICKFOLDERS if folders else FOS_FILEMUSTEXIST
        if multi:
            flags |= FOS_ALLOWMULTISELECT
        hr = int(
            _method(dialog, 9, ctypes.c_long, wintypes.DWORD)(
                dialog, flags
            )
        )
        if _failed(hr):
            return [], hr & 0xFFFFFFFF

        if title:
            _method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)(
                dialog, str(title)
            )

        filter_buffers: list[ctypes.Array] = []
        pairs = list(filetypes or [])
        if pairs and not folders:
            specs = (COMDLG_FILTERSPEC * len(pairs))()
            for index, (label, pattern) in enumerate(pairs):
                name_buf = ctypes.create_unicode_buffer(str(label or "Files"))
                spec_buf = ctypes.create_unicode_buffer(
                    (pattern or "*.*").replace(" ", ";")
                )
                filter_buffers.extend((name_buf, spec_buf))
                specs[index].pszName = ctypes.cast(
                    name_buf, wintypes.LPCWSTR
                )
                specs[index].pszSpec = ctypes.cast(
                    spec_buf, wintypes.LPCWSTR
                )
            hr = int(
                _method(
                    dialog,
                    4,
                    ctypes.c_long,
                    ctypes.c_uint,
                    ctypes.POINTER(COMDLG_FILTERSPEC),
                )(dialog, len(pairs), specs)
            )
            if _failed(hr):
                return [], hr & 0xFFFFFFFF

        start = (initialdir or "").strip()
        if start and os.path.isdir(start):
            shell32 = ctypes.windll.shell32
            shell32.SHCreateItemFromParsingName.argtypes = [
                wintypes.LPCWSTR,
                ctypes.c_void_p,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            ]
            shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
            folder_hr = int(
                shell32.SHCreateItemFromParsingName(
                    start,
                    None,
                    ctypes.byref(IID_SHELL_ITEM),
                    ctypes.byref(folder_item),
                )
            )
            if not _failed(folder_hr) and folder_item.value:
                _method(dialog, 12, ctypes.c_long, ctypes.c_void_p)(
                    dialog, folder_item
                )

        show = _method(dialog, 3, ctypes.c_long, wintypes.HWND)
        hr = int(show(dialog, int(owner_hwnd or 0)))
        if _failed(hr) and owner_hwnd:
            hr = int(show(dialog, 0))
        if _failed(hr):
            code = hr & 0xFFFFFFFF
            return [], 0 if code == ERROR_CANCELLED_HR else code

        paths: list[str] = []
        if multi:
            hr = int(
                _method(
                    dialog,
                    27,
                    ctypes.c_long,
                    ctypes.POINTER(ctypes.c_void_p),
                )(dialog, ctypes.byref(result_array))
            )
            if _failed(hr) or not result_array.value:
                return [], hr & 0xFFFFFFFF
            count = wintypes.DWORD()
            hr = int(
                _method(
                    result_array,
                    7,
                    ctypes.c_long,
                    ctypes.POINTER(wintypes.DWORD),
                )(result_array, ctypes.byref(count))
            )
            if _failed(hr):
                return [], hr & 0xFFFFFFFF
            get_item_at = _method(
                result_array,
                8,
                ctypes.c_long,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.c_void_p),
            )
            for index in range(count.value):
                item = ctypes.c_void_p()
                try:
                    hr = int(
                        get_item_at(
                            result_array, index, ctypes.byref(item)
                        )
                    )
                    if _failed(hr) or not item.value:
                        return [], hr & 0xFFFFFFFF
                    path, error = _item_path(item)
                    if error:
                        return [], error
                    paths.append(path)
                finally:
                    _release(item)
        else:
            hr = int(
                _method(
                    dialog,
                    20,
                    ctypes.c_long,
                    ctypes.POINTER(ctypes.c_void_p),
                )(dialog, ctypes.byref(result_item))
            )
            if _failed(hr) or not result_item.value:
                return [], hr & 0xFFFFFFFF
            path, error = _item_path(result_item)
            if error:
                return [], error
            paths.append(path)
        return paths, 0
    finally:
        _release(result_array)
        _release(result_item)
        _release(folder_item)
        _release(dialog)
        if uninitialize:
            ole32.CoUninitialize()
