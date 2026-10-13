"""v2.1.0 i18n 冒烟：词典、pause_reason、job 卡片、系统语言检测。"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestI18nCore(unittest.TestCase):
    def test_locale_files(self) -> None:
        for lang in ("zh", "en"):
            path = os.path.join(ROOT, "i18n", "locales", f"{lang}.json")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("nav.dash", data)
            self.assertIn("pause_reason.listen_hit", data)
            self.assertIn("job_card.running", data)

    def test_pause_reason_en(self) -> None:
        from i18n import init_i18n
        from i18n.pause_reason import display_pause_reason, normalize_pause_reason
        from i18n.job_card import format_job_status_label

        init_i18n("en")
        self.assertEqual(normalize_pause_reason("监听命中目标用户，自动暂停"), "listen_hit")
        self.assertIn("Listen", display_pause_reason("listen_hit"))
        label = format_job_status_label(
            enabled=True, state="paused", pause_reason="监听命中目标用户，自动暂停"
        )
        self.assertIn("Paused", label)

    def test_system_locale(self) -> None:
        from i18n.system_locale import detect_system_language

        lang = detect_system_language()
        self.assertIn(lang, ("zh", "en"))

    def test_ui_helpers(self) -> None:
        from i18n import init_i18n
        from i18n.ui_helpers import combo_label_for_lang, lang_from_combo_label

        init_i18n("en")
        en_lbl = combo_label_for_lang("en")
        self.assertEqual(lang_from_combo_label(en_lbl), "en")


class TestVersion(unittest.TestCase):
    def test_app_version(self) -> None:
        from wa_ui.shell import APP_VERSION

        self.assertTrue(APP_VERSION.startswith("v2."))


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestI18nCore, TestVersion):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
