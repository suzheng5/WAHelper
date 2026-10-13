"""冒烟：发图 TXT 解析、listen 仍归 await_image、按天归类。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARENT = os.path.dirname(ROOT)
for p in (ROOT, PARENT, os.path.join(PARENT, "wa_multi_listener")):
    if p not in sys.path:
        sys.path.insert(0, p)


class TestImageSendTxt(unittest.TestCase):
    def test_parse_image_step(self) -> None:
        from tg_multi_listener.schedule_txt_import import import_doc_items

        text = """
[条目]
类型=发图
账号=主号
备注=第三天发活动海报
间隔=0
"""
        items, errs = import_doc_items(text, valid_accounts={"acc1"}, require_per_item_interval=False)
        self.assertEqual(errs, [])
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].is_image_send)
        self.assertEqual(items[0].original_label(), "主号")
        self.assertIn("活动海报", items[0].reminder_note)

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

    def test_card_colors_and_sort(self) -> None:
        from i18n.pause_reason import CODE_AWAIT_IMAGE_LISTEN_HIT, CODE_AWAIT_IMAGE_SEND
        from wa_ui.taskmgr_tile_theme import (
            taskmgr_display_sort_tier,
            taskmgr_job_bucket,
        )

        self.assertEqual(
            taskmgr_job_bucket(running=False, enabled=True, pause_reason=CODE_AWAIT_IMAGE_SEND),
            "other_pause",
        )
        self.assertEqual(
            taskmgr_job_bucket(running=False, enabled=True, pause_reason=CODE_AWAIT_IMAGE_LISTEN_HIT),
            "stage_listen_pause",
        )
        self.assertEqual(
            taskmgr_display_sort_tier(running=False, enabled=True, pause_reason=CODE_AWAIT_IMAGE_SEND),
            1,
        )
        self.assertEqual(
            taskmgr_display_sort_tier(
                running=False, enabled=True, pause_reason=CODE_AWAIT_IMAGE_LISTEN_HIT
            ),
            0,
        )

    def test_group_by_day(self) -> None:
        from types import SimpleNamespace

        from tg_multi_listener.one_click_image import group_awaiting_by_day, notes_for_awaiting_jobs
        from tg_multi_listener.scheduler import DocMessage, ScheduledJob

        step = DocMessage(
            account_id="主号",
            content="",
            is_image_send=True,
            original_account_id="主号",
            send_as_account_id="主号",
            reminder_note="n",
        )
        j1 = ScheduledJob(
            id="a",
            enabled=True,
            chat_ids=[],
            interval_min_minutes=1,
            interval_max_minutes=1,
            source_path="x",
            source_name="x",
            items=[step, DocMessage(account_id="主号", content="hi")],
            cursor=1,
            state="paused",
            pause_reason="await_image_send",
            source_kind="folder",
            folder_day_index=2,
        )
        j2 = ScheduledJob(
            id="b",
            enabled=True,
            chat_ids=[],
            interval_min_minutes=1,
            interval_max_minutes=1,
            source_path="y",
            source_name="y",
            items=[step, DocMessage(account_id="主号", content="hi")],
            cursor=1,
            state="paused",
            pause_reason="await_image_send",
            source_kind="folder",
            folder_day_index=2,
        )
        groups = group_awaiting_by_day([j1, j2])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].day_1based, 3)
        self.assertEqual(len(groups[0].jobs), 2)
        self.assertEqual(notes_for_awaiting_jobs(groups[0].jobs), "n")


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestImageSendTxt)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
