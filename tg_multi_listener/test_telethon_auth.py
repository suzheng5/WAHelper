"""登录验证码通道文案与类型判断。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace


class LoginCodeTypeTests(unittest.TestCase):
    def test_app_like_and_sms(self) -> None:
        from tg_multi_listener.telethon_auth import (
            describe_sent_via,
            is_app_like_sent,
            is_sms_sent,
        )

        app = SimpleNamespace(type=type("SentCodeTypeApp", (), {})())
        sms = SimpleNamespace(type=type("SentCodeTypeSms", (), {})())
        self.assertTrue(is_app_like_sent(app))
        self.assertFalse(is_sms_sent(app))
        self.assertTrue(is_sms_sent(sms))
        self.assertIn("Telegram", describe_sent_via(app))
        self.assertIn("短信", describe_sent_via(sms))


if __name__ == "__main__":
    unittest.main()
