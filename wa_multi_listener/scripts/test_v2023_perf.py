"""v2.0.23 性能优化回归：缓存、自适应休眠、_marked 修剪、发送日志降级。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TG_ROOT = os.path.join(os.path.dirname(ROOT), "tg_multi_listener")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestJobFileCache(unittest.TestCase):
    def setUp(self) -> None:
        import job_file_cache as jfc

        jfc.invalidate_jobs_cache()
        self.jfc = jfc
        self.tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        self.tmp.write("[]")
        self.tmp.close()
        self.path = self.tmp.name
        self.read_count = 0

    def tearDown(self) -> None:
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self.jfc.invalidate_jobs_cache()

    def _read(self) -> list:
        self.read_count += 1
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_cache_avoids_repeated_disk_reads(self) -> None:
        a = self.jfc.load_jobs_cached(self.path, self._read)
        b = self.jfc.load_jobs_cached(self.path, self._read)
        self.assertEqual(a, b)
        self.assertEqual(self.read_count, 1)

    def test_force_reload(self) -> None:
        self.jfc.load_jobs_cached(self.path, self._read)
        self.jfc.load_jobs_cached(self.path, self._read, force=True)
        self.assertEqual(self.read_count, 2)

    def test_mtime_change_invalidates_cache(self) -> None:
        self.jfc.load_jobs_cached(self.path, self._read)
        time.sleep(0.05)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([{"x": 1}], f)
        self.jfc.load_jobs_cached(self.path, self._read)
        self.assertEqual(self.read_count, 2)

    def test_adaptive_sleep_imminent(self) -> None:
        now = 1000.0
        jobs = [SimpleNamespace(enabled=True, state="running", next_send_ts=now + 0.2, row_count=lambda: 3)]
        sec = self.jfc.runner_loop_sleep_seconds(jobs, now, step_count=lambda j: j.row_count())
        self.assertEqual(sec, 0.8)

    def test_adaptive_sleep_far_future(self) -> None:
        now = 1000.0
        jobs = [SimpleNamespace(enabled=True, state="running", next_send_ts=now + 600, row_count=lambda: 3)]
        sec = self.jfc.runner_loop_sleep_seconds(jobs, now, step_count=lambda j: j.row_count())
        self.assertEqual(sec, 30.0)

    def test_adaptive_sleep_needs_soon_when_next_zero(self) -> None:
        now = 1000.0
        jobs = [SimpleNamespace(enabled=True, state="running", next_send_ts=0.0, row_count=lambda: 3)]
        sec = self.jfc.runner_loop_sleep_seconds(jobs, now, step_count=lambda j: j.row_count())
        self.assertEqual(sec, 0.8)


class TestWatchReadTrackerMarked(unittest.TestCase):
    def test_marked_trimmed_to_max(self) -> None:
        from watch_read_tracker import WaWatchReadTracker, _MAX_MARKED

        tr = WaWatchReadTracker()
        for i in range(_MAX_MARKED + 50):
            tr.mark_done("acc", "chat", str(i))
        self.assertLessEqual(len(tr._marked), _MAX_MARKED)
        self.assertLessEqual(len(tr._marked_order), _MAX_MARKED)


class TestSchedule2JobCacheIntegration(unittest.TestCase):
    def setUp(self) -> None:
        import job_file_cache as jfc

        jfc.invalidate_jobs_cache()
        self._tmpdir = tempfile.mkdtemp()
        self.schedule_path = os.path.join(self._tmpdir, "schedule2.json")

    def tearDown(self) -> None:
        import job_file_cache as jfc
        import shutil

        jfc.invalidate_jobs_cache()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _sample_job_dict(self, *, state: str = "running", paused: bool = False) -> dict:
        return {
            "id": "jobtest01",
            "enabled": True,
            "chat_ids": ["120363@test"],
            "chat_entry_ids": [],
            "interval_min_minutes": 5,
            "interval_max_minutes": 10,
            "source_path": "x.txt",
            "source_name": "x.txt",
            "cursor": 0,
            "state": state,
            "pause_reason": "",
            "next_send_ts": time.time() + 3600,
            "rows": [
                {
                    "id": "r1",
                    "original_account_id": "a1",
                    "send_as_account_id": "a1",
                    "content": "hi",
                }
            ],
        }

    def test_send_allowed_reflects_disk_pause(self) -> None:
        with mock.patch("schedule2_runner.SCHEDULE2_FILE", self.schedule_path):
            import job_file_cache as jfc
            from schedule2_runner import (
                is_schedule2_job_send_allowed,
                load_schedule2_jobs,
                save_schedule2_jobs_patch,
            )
            from schedule2_runner import Schedule2Job, _job_from_dict

            jfc.invalidate_jobs_cache()
            with open(self.schedule_path, "w", encoding="utf-8") as f:
                json.dump([self._sample_job_dict()], f)

            self.assertTrue(is_schedule2_job_send_allowed("jobtest01"))

            paused = _job_from_dict(self._sample_job_dict(state="paused"))
            assert paused is not None
            paused.state = "paused"
            save_schedule2_jobs_patch([paused])

            self.assertFalse(is_schedule2_job_send_allowed("jobtest01"))
            jobs = load_schedule2_jobs()
            self.assertEqual(jobs[0].state, "paused")


class TestLogDowngrade(unittest.TestCase):
    def test_debug_not_in_memory_buffer(self) -> None:
        import logger_util as lu

        lu._memory.clear()
        before = len(lu.get_recent_lines(250))
        lu.debug("TEST_DEBUG_ONLY_v2023")
        after = len(lu.get_recent_lines(250))
        self.assertEqual(before, after)

    def test_info_still_in_memory_buffer(self) -> None:
        import logger_util as lu

        lu._memory.clear()
        lu.info("TEST_INFO_VISIBLE_v2023")
        lines = lu.get_recent_lines(10)
        self.assertTrue(any("TEST_INFO_VISIBLE_v2023" in ln for ln in lines))


class TestTgSchedulerCache(unittest.TestCase):
    def test_tg_job_cache_module_import(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "tg_job_file_cache",
            os.path.join(TG_ROOT, "job_file_cache.py"),
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.invalidate_jobs_cache()
        self.assertEqual(mod.runner_loop_sleep_seconds([], 0.0, step_count=lambda _: 0), 30.0)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        TestJobFileCache,
        TestWatchReadTrackerMarked,
        TestSchedule2JobCacheIntegration,
        TestLogDowngrade,
        TestTgSchedulerCache,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
