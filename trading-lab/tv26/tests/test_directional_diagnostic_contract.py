"""Static safeguards for the isolated TV26 direction-asymmetry diagnostic."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
EA = ROOT / "trading-lab" / "tv26" / "TV26_FiveTF_Arabic_CANDIDATE.mq5"
SCRIPT = ROOT / ".github" / "scripts" / "tv26_strategy_cooldown_backtest.ps1"


class DirectionalDiagnosticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ea = EA.read_text(encoding="utf-8")
        cls.script = SCRIPT.read_text(encoding="utf-8")

    def test_default_keeps_both_directions_enabled(self):
        self.assertIn("input bool   InpAllowBuyEntries        = true;", self.ea)

    def test_sell_only_mode_is_blocked_outside_strategy_tester(self):
        self.assertIn("if(!InpAllowBuyEntries && !MQLInfoInteger(MQL_TESTER))", self.ea)
        self.assertIn("return INIT_PARAMETERS_INCORRECT;", self.ea)

    def test_buy_only_block_is_logged_not_silenced(self):
        self.assertIn("if(sig>0 && !InpAllowBuyEntries)", self.ea)
        self.assertIn("reason=BUY_DIRECTION_DISABLED", self.ea)
        self.assertIn("blocked_buy_direction_diagnostic", self.script)

    def test_test_parameter_flows_into_mt5_set_and_is_verified(self):
        self.assertIn("$testAllowBuyText = [string]$env:TV26_TEST_ALLOW_BUY", self.script)
        self.assertIn("InpAllowBuyEntries=$testAllowBuyText", self.script)
        self.assertIn("'(?is)InpAllowBuyEntries=' + [regex]::Escape($testAllowBuyText)", self.script)
        self.assertIn("allow buy entries=$testAllowBuyText", self.script)

    def test_core_risk_guard_is_unchanged(self):
        self.assertIn("InpRiskPercent>2.0", self.ea)
        self.assertIn("if(lots<=0)", self.ea)
        self.assertIn("reason=MIN_VOLUME_RISK_CAP", self.ea)
        self.assertIn("InpTesterOnly=true", self.script)
        self.assertIn("InpDemoOnly=true", self.script)


if __name__ == "__main__":
    unittest.main()
