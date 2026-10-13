"""WA：重新读取文件夹/单文件当前 TXT 话术。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestReloadFolderScripts(unittest.TestCase):
    def test_reload_picks_up_edited_txt(self) -> None:
        from config import AppConfig
        from schedule2_runner import Schedule2Job, Schedule2Row, reload_schedule2_folder_scripts

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "1.txt").write_text(
                "[条目]\n账号=女一\n消息=旧话术\n间隔=1\n",
                encoding="utf-8",
            )
            (p / "2.txt").write_text(
                "[条目]\n账号=女一\n消息=第二天\n间隔=1\n",
                encoding="utf-8",
            )
            job = Schedule2Job(
                id="j1",
                enabled=True,
                chat_ids=["g"],
                interval_min_minutes=1,
                interval_max_minutes=1,
                source_path=str(p / "1.txt"),
                source_name="1.txt",
                rows=[
                    Schedule2Row(
                        id="r1",
                        original_account_id="女一",
                        send_as_account_id="女一",
                        content="旧话术",
                        delay_after_minutes=1.0,
                    )
                ],
                cursor=0,
                state="paused",
                source_kind="folder",
                folder_path=str(p),
                folder_files=["1.txt", "2.txt"],
                folder_day_index=0,
            )
            (p / "1.txt").write_text(
                "[条目]\n账号=女一\n消息=新话术已改\n间隔=1\n",
                encoding="utf-8",
            )
            cfg = AppConfig(accounts=[], address_book=[])
            ok, err = reload_schedule2_folder_scripts(job, cfg)
            self.assertTrue(ok, err)
            self.assertIn("新话术已改", job.rows[0].content)
            self.assertEqual(job.folder_day_index, 0)

    def test_reload_single_file_keeps_cursor(self) -> None:
        from config import AppConfig
        from schedule2_runner import (
            Schedule2Job,
            Schedule2Row,
            reload_schedule2_job_scripts,
        )

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.txt"
            p.write_text(
                "[条目]\n账号=女一\n消息=旧1\n间隔=1\n"
                "[条目]\n账号=女一\n消息=旧2\n间隔=1\n"
                "[条目]\n账号=女一\n消息=旧3\n间隔=1\n",
                encoding="utf-8",
            )
            job = Schedule2Job(
                id="j2",
                enabled=True,
                chat_ids=["g"],
                interval_min_minutes=1,
                interval_max_minutes=1,
                source_path=str(p),
                source_name="a.txt",
                rows=[
                    Schedule2Row(
                        id="r1",
                        original_account_id="女一",
                        send_as_account_id="女一",
                        content="旧1",
                        delay_after_minutes=1.0,
                    ),
                    Schedule2Row(
                        id="r2",
                        original_account_id="女一",
                        send_as_account_id="女一",
                        content="旧2",
                        delay_after_minutes=1.0,
                    ),
                    Schedule2Row(
                        id="r3",
                        original_account_id="女一",
                        send_as_account_id="女一",
                        content="旧3",
                        delay_after_minutes=1.0,
                    ),
                ],
                cursor=2,
                state="running",
                source_kind="file",
            )
            p.write_text(
                "[条目]\n账号=女一\n消息=新1\n间隔=1\n"
                "[条目]\n账号=女一\n消息=新2已改\n间隔=1\n"
                "[条目]\n账号=女一\n消息=新3\n间隔=1\n",
                encoding="utf-8",
            )
            cfg = AppConfig(accounts=[], address_book=[])
            ok, err = reload_schedule2_job_scripts(job, cfg)
            self.assertTrue(ok, err)
            self.assertIn("新2已改", job.rows[1].content)
            self.assertEqual(job.cursor, 2)
            self.assertEqual(job.state, "running")


if __name__ == "__main__":
    unittest.main(verbosity=2)
