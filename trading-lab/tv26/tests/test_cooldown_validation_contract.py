"""Regression checks for the TV26 post-exit cooldown experiment wiring."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github" / "scripts" / "tv26_strategy_cooldown_backtest.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "tv26-strategy-cooldown-validation.yml"
REPORT = ROOT / "trading-lab" / "tv26" / "TV26_10DAY_STRATEGY_DIAGNOSIS_2026-10-24_AR.md"


class CooldownValidationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.report = REPORT.read_text(encoding="utf-8")

    def test_cooldown_parameter_is_bounded_and_applied_to_tester_set(self):
        self.assertIn("TV26_TEST_COOLDOWN_BARS", self.script)
        self.assertIn("$testCooldownBars -lt 0 -or $testCooldownBars -gt 720", self.script)
        self.assertIn("InpCooldownBarsAfterExit=$testCooldownBars", self.script)
        self.assertIn("InpCooldownBarsAfterExit=' + [regex]::Escape($testCooldownText)", self.script)

    def test_mt5_report_must_confirm_requested_cooldown_input(self):
        self.assertIn("expectedInputs", self.script)
        self.assertIn("blocked_post_exit_cooldown", self.script)
        self.assertIn("reason=POST_EXIT_COOLDOWN", self.script)

    def test_experiment_uses_same_dates_and_real_tick_model(self):
        self.assertIn('TV26_TEST_FROM: "2026.10.14"', self.workflow)
        self.assertIn('TV26_TEST_TO: "2026.10.24"', self.workflow)
        self.assertIn('TV26_TEST_MODEL: "4"', self.workflow)
        self.assertIn('TV26_TEST_RISK_PERCENT: "1.00"', self.workflow)
        self.assertIn('TV26_TEST_STOP_ATR: "2.00"', self.workflow)
        self.assertIn('TV26_TEST_TARGET_ATR: "3.00"', self.workflow)
        self.assertIn("TV26_TEST_REQUIRE_M1_BREAKOUT: \"true\"", self.workflow)

    def test_only_five_and_ten_closed_m1_bars_are_compared(self):
        self.assertIn("cooldown: [5, 10]", self.workflow)
        self.assertIn("tv26_strategy_cooldown_backtest.ps1", self.workflow)
        self.assertIn("InpDemoOnly=true", self.script)
        self.assertIn("InpTesterOnly=true", self.script)
        self.assertIn("No live orders are permitted by the tester-only guard.", self.script)

    def test_prior_matrix_report_does_not_claim_profitability(self):
        self.assertIn("لا توجد نسخة مثبتة الربحية حتى الآن", self.report)
        self.assertIn("TradingView", self.report)
        self.assertIn("لا اعتماد للتداول الحقيقي", self.report)


if __name__ == "__main__":
    unittest.main()
