"""冒烟：WA 发图 TXT 解析、pause 叠加、按天归类。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_WA = Path(__file__).resolve().parents[1]
if str(_WA) not in sys.path:
    sys.path.insert(0, str(_WA))


class TestWaImageTxtParse(unittest.TestCase):
    def test_parse_image_send(self) -> None:
        from schedule_txt_import import import_doc_items

        text = """
[条目]
类型=发图
账号=女一
备注=海报
间隔=0
"""
        items, errs = import_doc_items(text, valid_accounts={"女一"})
        self.assertEqual(errs, [])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].is_image_send)
        self.assertEqual(items[0].account_id, "女一")
        self.assertEqual(items[0].reminder_note, "海报")
        self.assertEqual(items[0].content, "")

    def test_bang_image_head(self) -> None:
        from schedule_txt_import import import_doc_items

        text = """
[条目]
!发图!
账号=男二
说明=test
"""
        items, errs = import_doc_items(text, valid_accounts={"男二"})
        self.assertEqual(errs, [])
        self.assertTrue(items[0].is_image_send)


class TestWaImagePauseCompose(unittest.TestCase):
    def test_listen_keeps_await_image(self) -> None:
        from i18n.pause_reason import (
            CODE_AWAIT_IMAGE_LISTEN_HIT,
            CODE_AWAIT_IMAGE_SEND,
            CODE_LISTEN_HIT,
            compose_listen_pause_reason,
            is_await_image_send,
        )

        out = compose_listen_pause_reason(CODE_AWAIT_IMAGE_SEND, CODE_LISTEN_HIT)
        self.assertEqual(out, CODE_AWAIT_IMAGE_LISTEN_HIT)
        self.assertTrue(is_await_image_send(out))


class TestWaOneClickHelpers(unittest.TestCase):
    def test_group_by_day(self) -> None:
        from one_click_image import group_awaiting_by_day, is_job_awaiting_image
        from schedule2_runner import Schedule2Job, Schedule2Row

        rows = [
            Schedule2Row(
                id="r1",
                original_account_id="女一",
                send_as_account_id="女一",
                content="",
                is_image_send=True,
                reminder_note="n1",
            )
        ]
        j = Schedule2Job(
            id="j1",
            enabled=True,
            chat_ids=[],
            interval_min_minutes=5,
            interval_max_minutes=10,
            source_path="x",
            source_name="1.txt",
            rows=rows,
            cursor=1,
            state="paused",
            pause_reason="await_image_send",
            source_kind="folder",
            folder_day_index=0,
        )
        self.assertTrue(is_job_awaiting_image(j))
        groups = group_awaiting_by_day([j])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].day_1based, 1)


class TestS2RowRoundtrip(unittest.TestCase):
    def test_doc_to_row(self) -> None:
        from schedule_txt_import import import_doc_items
        from schedule2_runner import _doc_items_to_s2_rows

        items, _ = import_doc_items(
            "[条目]\n类型=发图\n账号=女一\n备注=x\n",
            valid_accounts={"女一"},
        )
        rows = _doc_items_to_s2_rows(items)
        self.assertTrue(rows[0].is_image_send)
        self.assertEqual(rows[0].reminder_note, "x")


if __name__ == "__main__":
    unittest.main()
