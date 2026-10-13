"""冒烟：自动入群 pause_reason、邀请码解析、等待中止。"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_WA = Path(__file__).resolve().parents[1]
if str(_WA) not in sys.path:
    sys.path.insert(0, str(_WA))
_ROOT = _WA.parent
_TG = _ROOT / "tg_multi_listener"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class TestJoinPauseReason(unittest.TestCase):
    def test_code_and_display(self) -> None:
        from i18n import init_i18n
        from i18n.pause_reason import (
            CODE_JOIN_GROUP_FAILED,
            display_pause_reason,
            normalize_pause_reason,
        )

        init_i18n("zh")
        self.assertEqual(normalize_pause_reason(CODE_JOIN_GROUP_FAILED), CODE_JOIN_GROUP_FAILED)
        self.assertEqual(
            normalize_pause_reason("发送账号入群失败，任务已暂停"),
            CODE_JOIN_GROUP_FAILED,
        )
        self.assertIn("入群失败", display_pause_reason(CODE_JOIN_GROUP_FAILED))


class TestWaInviteLookup(unittest.TestCase):
    def test_invite_code_from_link(self) -> None:
        from wa_jid import invite_code_from_link

        self.assertEqual(
            invite_code_from_link("https://chat.whatsapp.com/AbCdEf123"),
            "AbCdEf123",
        )
        self.assertIsNone(invite_code_from_link("120363@g.us"))

    def test_find_invite_via_invite_link_field(self) -> None:
        from config import AddressEntry, AppConfig, find_wa_invite_link_for_chat_ref
        from group_auto_join import find_invite_code_for_chat_ref
        from unittest.mock import patch

        cfg = AppConfig(
            address_book=[
                AddressEntry(
                    id="e1",
                    remark="g",
                    chat_ref="120363427704753362@g.us",
                    invite_link="https://chat.whatsapp.com/AbCdEf123",
                )
            ]
        )
        link = find_wa_invite_link_for_chat_ref(cfg, "120363427704753362@g.us")
        self.assertIn("AbCdEf123", link)
        with patch("config.load_config", return_value=cfg):
            code = find_invite_code_for_chat_ref("120363427704753362@g.us")
        self.assertEqual(code, "AbCdEf123")

    def test_address_entry_invite_field(self) -> None:
        from config import _address_entry_from_dict

        ent = _address_entry_from_dict(
            {
                "id": "a1",
                "remark": "r",
                "chat_ref": "120363@g.us",
                "invite_link": "https://chat.whatsapp.com/XxYy",
            }
        )
        self.assertIsNotNone(ent)
        assert ent is not None
        self.assertEqual(ent.invite_link, "https://chat.whatsapp.com/XxYy")


class TestTgInviteHash(unittest.TestCase):
    def test_hashes(self) -> None:
        from tg_multi_listener.group_auto_join import tg_invite_hash, tg_public_username

        self.assertEqual(tg_invite_hash("https://t.me/+AbCdEf"), "AbCdEf")
        self.assertEqual(tg_invite_hash("https://t.me/joinchat/XYZ99"), "XYZ99")
        self.assertEqual(tg_invite_hash("+OnlyHash"), "OnlyHash")
        self.assertIsNone(tg_invite_hash("@publicgroup"))
        self.assertEqual(tg_public_username("@hello"), "hello")
        self.assertEqual(tg_public_username("https://t.me/hello"), "hello")
        self.assertIsNone(tg_public_username("https://t.me/+AbCdEf"))
        self.assertIsNone(tg_public_username("-100123"))


class TestSleepAbortable(unittest.TestCase):
    def test_abort(self) -> None:
        from group_auto_join import AutoJoinAborted, sleep_abortable

        async def run() -> None:
            with self.assertRaises(AutoJoinAborted):
                await sleep_abortable(5.0, abort_check=lambda: True)

        asyncio.run(run())


class TestTgParseInviteAllowed(unittest.TestCase):
    def test_parse_invite(self) -> None:
        from tg_multi_listener.config import parse_chat_ref_input

        s = parse_chat_ref_input("https://t.me/+AbCdEfGh")
        self.assertIn("+AbCdEfGh", str(s))


class TestTgInvitePersistHelpers(unittest.TestCase):
    def test_find_invite_after_id(self) -> None:
        from tg_multi_listener.config import AddressEntry, AppConfig, find_invite_link_for_chat_ref

        cfg = AppConfig(
            api_id=0,
            api_hash="",
            address_book=[
                AddressEntry(
                    id="e1",
                    remark="g",
                    chat_ref="-1001234567890",
                    invite_link="https://t.me/+KeepMe",
                )
            ],
        )
        link = find_invite_link_for_chat_ref(cfg, -1001234567890)
        self.assertIn("+KeepMe", link)

    def test_address_entry_invite_field(self) -> None:
        from tg_multi_listener.config import _address_entry_from_dict

        ent = _address_entry_from_dict(
            {
                "id": "a1",
                "remark": "r",
                "chat_ref": "-1001",
                "invite_link": "https://t.me/+Xx",
            }
        )
        self.assertIsNotNone(ent)
        assert ent is not None
        self.assertEqual(ent.invite_link, "https://t.me/+Xx")


if __name__ == "__main__":
    unittest.main()
