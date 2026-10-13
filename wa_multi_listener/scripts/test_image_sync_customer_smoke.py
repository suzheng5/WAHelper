"""冒烟：一键发图同步客户 — 全局分阶段顺序（无网络）。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import AddressEntry, AppConfig, Account  # noqa: E402
from one_click_image import (  # noqa: E402
    CUSTOMER_IMAGE_DELAY_SEC,
    CUSTOMER_TEXT_DELAY_SEC,
    bulk_send_images_and_resume,
    customer_pairs_for_job,
    send_image_for_job,
)
from schedule2_runner import Schedule2Job, Schedule2Row  # noqa: E402


def _row() -> Schedule2Row:
    return Schedule2Row(
        id="r1",
        original_account_id="acc1",
        send_as_account_id="acc1",
        content="",
        is_image_send=True,
    )


def _job(jid: str, entry_ids: list[str], chat: str = "120363000@g.us") -> Schedule2Job:
    return Schedule2Job(
        id=jid,
        enabled=True,
        chat_ids=[chat],
        interval_min_minutes=1.0,
        interval_max_minutes=2.0,
        source_path="t.txt",
        source_name="t.txt",
        rows=[_row()],
        chat_entry_ids=entry_ids,
        cursor=1,
        state="paused",
        pause_reason="await_image_send",
    )


def _cfg() -> AppConfig:
    return AppConfig(
        accounts=[Account(id="acc1", session_name="s1", enabled=True)],
        address_book=[
            AddressEntry(
                id="e1",
                remark="g1",
                chat_ref="120363000@g.us",
                watch_user="+8613800138000",
                listen_enabled=True,
                owner_account_id="acc1",
            ),
            AddressEntry(
                id="e2",
                remark="g2",
                chat_ref="120363001@g.us",
                watch_user="+8613800138001",
                listen_enabled=True,
                owner_account_id="acc1",
            ),
            AddressEntry(
                id="e3",
                remark="g3",
                chat_ref="120363002@g.us",
                watch_user="",
                listen_enabled=True,
                owner_account_id="acc1",
            ),
        ],
    )


def test_customer_pairs() -> None:
    cfg = _cfg()
    job = _job("j1", ["e1", "e3"])
    step = job.rows[0]
    accounts = {a.id: a for a in cfg.accounts}
    pairs = customer_pairs_for_job(job, cfg, step, accounts)
    assert pairs == [("8613800138000", "acc1")], pairs
    print("ok customer_pairs")


def test_group_only_no_sync_kwargs() -> None:
    cfg = _cfg()
    job = _job("j1", ["e3"], chat="120363002@g.us")

    async def run() -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name
        try:
            with patch(
                "one_click_image._send_paths_to_pairs",
                new=AsyncMock(return_value=(True, "", "acc1")),
            ):
                res = await send_image_for_job(
                    job=job,
                    cfg=cfg,
                    shared_clients={"acc1": object()},
                    account_locks={},
                    accounts={a.id: a for a in cfg.accounts},
                    image_paths=[path],
                )
            assert res.ok, res
        finally:
            os.unlink(path)

    asyncio.run(run())
    print("ok group_only")


def test_bulk_sync_global_phases() -> None:
    """全部群图 → 60s → 逐个客户图 → 30s → 逐个文字。"""
    cfg = _cfg()
    jobs = [
        _job("j1", ["e1"], chat="120363000@g.us"),
        _job("j2", ["e2"], chat="120363001@g.us"),
    ]
    calls: list[tuple] = []
    sleeps: list[float] = []

    async def fake_paths(**kwargs):
        pairs = tuple(p[0] for p in kwargs["pairs"])
        calls.append(("img", pairs))
        return True, "", "acc1"

    async def fake_text(**kwargs):
        pairs = tuple(p[0] for p in kwargs["pairs"])
        calls.append(("txt", pairs, kwargs["text"]))
        return True, ""

    async def fake_sleep(sec: float):
        sleeps.append(float(sec))

    resumed: list[str] = []

    async def run() -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name
        try:
            with (
                patch("one_click_image._send_paths_to_pairs", side_effect=fake_paths),
                patch("one_click_image._send_text_to_pairs", side_effect=fake_text),
                patch("one_click_image.asyncio.sleep", side_effect=fake_sleep),
            ):
                ok_n, fail_n, r_n = await bulk_send_images_and_resume(
                    jobs=jobs,
                    cfg=cfg,
                    shared_clients={"acc1": object()},
                    account_locks={},
                    image_paths=[path],
                    resume_job=lambda jid: resumed.append(jid) or True,
                    sync_to_customer=True,
                    customer_extra_text="hello cust",
                    gap_min=0.0,
                    gap_max=0.0,
                )
            assert (ok_n, fail_n, r_n) == (2, 0, 2), (ok_n, fail_n, r_n)
            # 群图两次（可一次一对多，当前实现按任务各发一次）
            assert calls[0][0] == "img" and "120363000@g.us" in calls[0][1]
            assert calls[1][0] == "img" and "120363001@g.us" in calls[1][1]
            # 再逐个客户图
            assert calls[2] == ("img", ("8613800138000",))
            assert calls[3] == ("img", ("8613800138001",))
            # 再逐个文字
            assert calls[4] == ("txt", ("8613800138000",), "hello cust")
            assert calls[5] == ("txt", ("8613800138001",), "hello cust")
            assert CUSTOMER_IMAGE_DELAY_SEC in sleeps
            assert CUSTOMER_TEXT_DELAY_SEC in sleeps
            # 60 秒出现在两张群图之后
            idx60 = sleeps.index(CUSTOMER_IMAGE_DELAY_SEC)
            idx30 = sleeps.index(CUSTOMER_TEXT_DELAY_SEC)
            assert idx60 < idx30
            assert set(resumed) == {"j1", "j2"}
        finally:
            os.unlink(path)

    asyncio.run(run())
    print("ok bulk_sync_global_phases")


def test_bulk_sync_no_extra_skips_text_wait() -> None:
    cfg = _cfg()
    jobs = [_job("j1", ["e1"])]
    text_calls: list[str] = []
    sleeps: list[float] = []

    async def fake_paths(**kwargs):
        return True, "", "acc1"

    async def fake_text(**kwargs):
        text_calls.append(kwargs["text"])
        return True, ""

    async def fake_sleep(sec: float):
        sleeps.append(float(sec))

    async def run() -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name
        try:
            with (
                patch("one_click_image._send_paths_to_pairs", side_effect=fake_paths),
                patch("one_click_image._send_text_to_pairs", side_effect=fake_text),
                patch("one_click_image.asyncio.sleep", side_effect=fake_sleep),
            ):
                ok_n, fail_n, _ = await bulk_send_images_and_resume(
                    jobs=jobs,
                    cfg=cfg,
                    shared_clients={"acc1": object()},
                    account_locks={},
                    image_paths=[path],
                    resume_job=lambda _jid: True,
                    sync_to_customer=True,
                    customer_extra_text="   ",
                    gap_min=0.0,
                    gap_max=0.0,
                )
            assert ok_n == 1 and fail_n == 0
            assert text_calls == []
            assert CUSTOMER_IMAGE_DELAY_SEC in sleeps
            assert CUSTOMER_TEXT_DELAY_SEC not in sleeps
        finally:
            os.unlink(path)

    asyncio.run(run())
    print("ok bulk_sync_no_extra")


def test_bulk_sync_no_customer() -> None:
    cfg = _cfg()
    jobs = [_job("j3", ["e3"], chat="120363002@g.us")]

    async def fake_paths(**kwargs):
        return True, "", "acc1"

    async def fake_sleep(_sec: float):
        return None

    async def run() -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name
        try:
            with (
                patch("one_click_image._send_paths_to_pairs", side_effect=fake_paths),
                patch("one_click_image.asyncio.sleep", side_effect=fake_sleep),
            ):
                ok_n, fail_n, r_n = await bulk_send_images_and_resume(
                    jobs=jobs,
                    cfg=cfg,
                    shared_clients={"acc1": object()},
                    account_locks={},
                    image_paths=[path],
                    resume_job=lambda _jid: True,
                    sync_to_customer=True,
                    gap_min=0.0,
                    gap_max=0.0,
                )
            assert (ok_n, fail_n, r_n) == (0, 1, 0)
        finally:
            os.unlink(path)

    asyncio.run(run())
    print("ok bulk_sync_no_customer")


if __name__ == "__main__":
    test_customer_pairs()
    test_group_only_no_sync_kwargs()
    test_bulk_sync_global_phases()
    test_bulk_sync_no_extra_skips_text_wait()
    test_bulk_sync_no_customer()
    print("ALL PASS")
