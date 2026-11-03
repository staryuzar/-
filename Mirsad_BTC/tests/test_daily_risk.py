from __future__ import annotations

import unittest

from mirsad.engines.daily_risk import evaluate_daily_risk


class DailyRiskBaselineTests(unittest.TestCase):
    def _account(self, equity: float = 1000.0, login: str = "12345") -> dict:
        return {
            "equity": equity,
            "login": login,
            "server": "Headway-Demo",
            "currency": "USD",
        }

    def test_first_valid_snapshot_initializes_utc_day_baseline(self) -> None:
        result = evaluate_daily_risk(
            self._account(), {}, max_daily_loss_fraction=0.02,
            now_ms=1_800_000_000_000,
        )
        report = result["report"]
        self.assertEqual(report["status"], "READY")
        self.assertFalse(report["locked"])
        self.assertEqual(report["starting_equity"], 1000.0)
        self.assertEqual(report["daily_loss_fraction"], 0.0)
        self.assertEqual(report["baseline_reset_reason"], "FIRST_VALID_EQUITY_SNAPSHOT")
        self.assertNotIn("login", result["state"])
        self.assertNotIn("server", result["state"])

    def test_daily_loss_limit_locks_new_entries_and_survives_restart(self) -> None:
        first = evaluate_daily_risk(
            self._account(), {}, max_daily_loss_fraction=0.02,
            now_ms=1_800_000_000_000,
        )
        second = evaluate_daily_risk(
            self._account(978.0), first["state"], max_daily_loss_fraction=0.02,
            now_ms=1_800_000_060_000,
        )
        report = second["report"]
        self.assertEqual(report["status"], "READY")
        self.assertTrue(report["locked"])
        self.assertTrue(report["new_entries_blocked"])
        self.assertEqual(report["starting_equity"], 1000.0)
        self.assertAlmostEqual(report["daily_loss_fraction"], 0.022)
        self.assertAlmostEqual(report["remaining_loss_cash"], 0.0)
        self.assertEqual(report["baseline_reset_reason"], None)

    def test_loss_below_limit_remains_unlocked_and_profit_does_not_count_as_loss(self) -> None:
        baseline = evaluate_daily_risk(
            self._account(), {}, max_daily_loss_fraction=0.02,
            now_ms=1_800_000_000_000,
        )
        loss = evaluate_daily_risk(
            self._account(990.0), baseline["state"],
            max_daily_loss_fraction=0.02, now_ms=1_800_000_060_000,
        )
        gain = evaluate_daily_risk(
            self._account(1030.0), baseline["state"],
            max_daily_loss_fraction=0.02, now_ms=1_800_000_060_000,
        )
        self.assertFalse(loss["report"]["locked"])
        self.assertAlmostEqual(loss["report"]["daily_loss_fraction"], 0.01)
        self.assertEqual(gain["report"]["daily_loss_cash"], 0.0)
        self.assertFalse(gain["report"]["locked"])

    def test_new_utc_day_and_account_change_reset_the_baseline(self) -> None:
        first = evaluate_daily_risk(
            self._account(), {}, max_daily_loss_fraction=0.02,
            now_ms=1_800_000_000_000,
        )
        new_day = evaluate_daily_risk(
            self._account(970.0), first["state"],
            max_daily_loss_fraction=0.02, now_ms=1_800_100_000_000,
        )
        other_account = evaluate_daily_risk(
            self._account(970.0, login="67890"), first["state"],
            max_daily_loss_fraction=0.02, now_ms=1_800_000_060_000,
        )
        self.assertEqual(new_day["report"]["baseline_reset_reason"], "NEW_UTC_DAY")
        self.assertEqual(new_day["report"]["starting_equity"], 970.0)
        self.assertEqual(other_account["report"]["baseline_reset_reason"], "ACCOUNT_CHANGED")
        self.assertEqual(other_account["report"]["starting_equity"], 970.0)

    def test_daily_loss_limit_can_be_disabled_for_development(self) -> None:
        previous_state = {"marker": "preserve-existing-baseline"}
        result = evaluate_daily_risk(
            None, previous_state, max_daily_loss_fraction=0.02,
            enabled=False, now_ms=1_800_000_000_000,
        )
        report = result["report"]
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["mode"], "DISABLED_FOR_DEVELOPMENT")
        self.assertFalse(report["enabled"])
        self.assertFalse(report["locked"])
        self.assertFalse(report["new_entries_blocked"])
        self.assertIsNone(report["max_daily_loss_fraction"])
        self.assertEqual(report["configured_max_daily_loss_fraction"], 0.02)
        self.assertFalse(report["decision_eligible"])
        self.assertEqual(result["state"], previous_state)

    def test_invalid_equity_identity_or_loss_limit_fails_closed(self) -> None:
        cases = [
            ({**self._account(), "equity": 0}, 0.02),
            ({**self._account(), "login": ""}, 0.02),
            ({"equity": 1000.0, "login": "123", "server": "Demo"}, 0.02),
            (self._account(), -0.01),
            (self._account(), 0.75),
        ]
        for account, cap in cases:
            with self.subTest(account=account, cap=cap):
                result = evaluate_daily_risk(
                    account, {}, max_daily_loss_fraction=cap,
                    now_ms=1_800_000_000_000,
                )
                self.assertNotEqual(result["report"]["status"], "READY")
                self.assertTrue(result["report"]["locked"])
                self.assertTrue(result["report"]["new_entries_blocked"])


if __name__ == "__main__":
    unittest.main()
