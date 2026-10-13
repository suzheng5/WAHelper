"""点赞账号池：主号/女→爱心，男→拇指；切换主号后仍可匹配。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestReactionPick(unittest.TestCase):
    def test_emoji_rules(self) -> None:
        from schedule_reactions import reaction_emoji_for_account

        self.assertEqual(reaction_emoji_for_account("主侧", is_main=True), "❤️")
        self.assertEqual(reaction_emoji_for_account("女三", is_main=False), "❤️")
        self.assertEqual(reaction_emoji_for_account("男侧1", is_main=False), "👍")
        # 主号槽即使简称带「男」仍点爱心
        self.assertEqual(reaction_emoji_for_account("男二", is_main=True), "❤️")

    def test_pool_after_owner_switch(self) -> None:
        import random

        from schedule_reactions import pick_reaction_accounts

        avail = {"批超A", "女一", "女助手", "男二", "路人"}
        random.seed(42)
        all_ids: set[str] = set()
        for _ in range(30):
            picked = pick_reaction_accounts(
                sender_account_id="女一",
                main_account_id="批超A",
                available_account_ids=avail,
            )
            ids = {a for _, a in picked}
            self.assertTrue(ids)
            self.assertNotIn("女一", ids)
            self.assertNotIn("路人", ids)
            all_ids |= ids
        self.assertIn("批超A", all_ids)
        self.assertTrue({"女助手", "男二"} & all_ids)

    def test_empty_when_no_match(self) -> None:
        from schedule_reactions import pick_reaction_accounts

        out = pick_reaction_accounts(
            sender_account_id="a",
            main_account_id="",
            available_account_ids={"客服1", "客服2"},
        )
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
