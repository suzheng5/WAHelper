"""v2.0.24 扩展冒烟：模块导入、调度器接口、TG 侧缓存。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestModuleImports(unittest.TestCase):
    def test_schedule2_runner_exports(self) -> None:
        from schedule2_runner import (
            Schedule2Runner,
            is_schedule2_job_send_allowed,
            load_schedule2_jobs,
            runner_loop_sleep_seconds,
        )

        self.assertTrue(callable(load_schedule2_jobs))
        self.assertTrue(callable(is_schedule2_job_send_allowed))
        self.assertIsNotNone(Schedule2Runner)
        self.assertEqual(runner_loop_sleep_seconds([], 0.0, step_count=lambda _: 0), 30.0)

    def test_watch_read_tracker(self) -> None:
        from watch_read_tracker import WaWatchReadTracker

        tr = WaWatchReadTracker()
        tr.mark_done("a", "b", "1")
        self.assertIn(("a", "b", "1"), tr._marked)

    def test_shell_version(self) -> None:
        from wa_ui.shell import APP_VERSION

        self.assertTrue(APP_VERSION.startswith("v2."))


class TestTgSchedulerImports(unittest.TestCase):
    def test_tg_scheduler_cache(self) -> None:
        import importlib

        parent = os.path.dirname(ROOT)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        mod = importlib.import_module("tg_multi_listener.scheduler")
        self.assertTrue(hasattr(mod, "load_jobs"))
        self.assertTrue(hasattr(mod, "is_doc_job_send_allowed"))


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestModuleImports, TestTgSchedulerImports):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
