"""弹窗策略与 Win32 文件选择纯逻辑回归。"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wa_ui.file_picker_util import release_modal_grabs
from wa_ui.win_file_dialog import _build_filter_text, _paths_from_chunks
from wa_ui.window_policy import close_window, present_once


class _FakeWindow:
    def __init__(self) -> None:
        self.exists = True
        self.topmost: list[bool] = []
        self.lifted = 0
        self.belled = 0
        self.destroyed = 0
        self.released = 0
        self.after_callbacks = []
        self.current_grab = None

    def winfo_exists(self):
        return self.exists

    def winfo_toplevel(self):
        return self

    def deiconify(self):
        pass

    def transient(self, _owner):
        pass

    def attributes(self, _name, value):
        self.topmost.append(bool(value))

    def lift(self):
        self.lifted += 1

    def bell(self):
        self.belled += 1

    def after(self, _delay, callback):
        self.after_callbacks.append(callback)

    def grab_current(self):
        return self.current_grab

    def grab_release(self):
        self.released += 1

    def destroy(self):
        self.destroyed += 1
        self.exists = False


class DialogPolicyTests(unittest.TestCase):
    def test_modeless_popup_only_topmost_temporarily(self) -> None:
        win = _FakeWindow()
        present_once(win, parent=win, bell=True)
        self.assertEqual(win.topmost, [True])
        self.assertEqual(win.lifted, 1)
        self.assertEqual(win.belled, 1)
        self.assertEqual(len(win.after_callbacks), 1)
        win.after_callbacks[0]()
        self.assertEqual(win.topmost, [True, False])

    def test_close_only_changes_target_window(self) -> None:
        win = _FakeWindow()
        close_window(win)
        self.assertEqual(win.released, 1)
        self.assertEqual(win.destroyed, 1)

    def test_release_grab_does_not_touch_other_popups(self) -> None:
        root = _FakeWindow()
        grabbed = _FakeWindow()
        root.current_grab = grabbed
        release_modal_grabs(root)
        self.assertEqual(grabbed.released, 1)
        self.assertEqual(root.released, 1)

    def test_win_filter_conversion(self) -> None:
        value = _build_filter_text([("Images", "*.jpg *.png"), ("All", "*.*")])
        self.assertEqual(value, "Images\0*.jpg;*.png\0All\0*.*\0\0")

    def test_single_and_multi_unicode_paths(self) -> None:
        single = _paths_from_chunks([r"C:\图片\a 图.png"])
        self.assertEqual(single, [os.path.abspath(r"C:\图片\a 图.png")])
        multi = _paths_from_chunks([r"C:\图片", "一.png", "二.jpg"])
        self.assertEqual(
            multi,
            [
                os.path.abspath(r"C:\图片\一.png"),
                os.path.abspath(r"C:\图片\二.jpg"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
