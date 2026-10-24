"""Contract tests for the optional strategy-only M1/M5 oscillator gate."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "TV26_FiveTF_Arabic_CANDIDATE.mq5"
HARNESS = ROOT.parents[1] / ".github" / "scripts" / "tv26_strategy_cooldown_backtest.ps1"


class M1M5OscillatorGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA.read_text(encoding="utf-8")
        cls.harness = HARNESS.read_text(encoding="utf-8")
        start = cls.source.index("void TradeIfAligned()")
        end = cls.source.index("\nint OnInit()", start)
        cls.trade = cls.source[start:end]
        aligned_start = cls.source.index("int AlignedSignal()")
        aligned_end = cls.source.index("\nstring DetailSignal(", aligned_start)
        cls.aligned = cls.source[aligned_start:aligned_end]

    def test_gate_defaults_to_disabled_and_has_range_validation(self):
        self.assertIn(
            "input double InpMinM1M5DirectionalOscillatorRating = 0.00;",
            self.source,
        )
        self.assertIn(
            "if(InpMinM1M5DirectionalOscillatorRating<0.0 || InpMinM1M5DirectionalOscillatorRating>1.0)",
            self.source,
        )

    def test_gate_only_blocks_strategy_entries_and_keeps_tv_rating_classification(self):
        self.assertIn("InpMinM1M5DirectionalOscillatorRating>0.0", self.trade)
        self.assertIn("double m1DirectionalOsc=(double)sig*g_oscRating[0];", self.trade)
        self.assertIn("double m5DirectionalOsc=(double)sig*g_oscRating[1];", self.trade)
        self.assertIn("if(!m1OscPass || !m5OscPass)", self.trade)
        self.assertIn("reason=M1_M5_OSCILLATOR_GATE", self.trade)
        self.assertIn(";M1_directional=", self.trade)
        self.assertIn(";M5_directional=", self.trade)
        self.assertIn("InpMinM1M5DirectionalOscillatorRating", self.trade)
        self.assertNotIn("InpMinM1M5DirectionalOscillatorRating", self.aligned)
        self.assertIn("if(g_rating[t]<=STRONG) allStrongBuy=false;", self.aligned)
        self.assertIn("if(g_rating[t]>=-STRONG) allStrongSell=false;", self.aligned)

    def test_gate_only_runs_for_a_new_entry_after_latch_and_cooldown_checks(self):
        disabled = self.trade.index("reason=TRADING_DISABLED")
        foreign_position = self.trade.index("HasForeignNettingPosition()")
        breakout = self.trade.index("reason=M1_CLOSE_BREAKOUT_NOT_CONFIRMED")
        same_side = self.trade.index("reason=POSITION_ALREADY_SAME_SIDE")
        latch = self.trade.index("reason=SAME_SIGNAL_LATCH")
        cooldown = self.trade.index("reason=POST_EXIT_COOLDOWN")
        gate = self.trade.index("reason=M1_M5_OSCILLATOR_GATE")
        demo_guard = self.trade.index("reason=NOT_DEMO_ACCOUNT")
        self.assertLess(disabled, gate)
        self.assertLess(foreign_position, gate)
        self.assertLess(breakout, gate)
        self.assertLess(same_side, gate)
        self.assertLess(latch, gate)
        self.assertLess(cooldown, gate)
        self.assertLess(gate, demo_guard)
        gate_start = self.trade.index("if(InpMinM1M5DirectionalOscillatorRating>0.0)")
        gate_end = self.trade.index("if(InpDemoOnly && AccountInfoInteger", gate_start)
        self.assertNotIn("RememberSignal(0)", self.trade[gate_start:gate_end])

    def test_tester_harness_applies_and_audits_requested_gate_value(self):
        self.assertIn("TV26_TEST_MIN_M1M5_OSCILLATOR_RATING", self.harness)
        self.assertIn("must be between 0 and 1", self.harness)
        self.assertIn("$testM1M5Osc -lt 0 -or $testM1M5Osc -gt 1.0", self.harness)
        self.assertIn(
            "InpMinM1M5DirectionalOscillatorRating=$testM1M5OscText",
            self.harness,
        )
        self.assertIn(
            "'(?is)InpMinM1M5DirectionalOscillatorRating=' + [regex]::Escape($testM1M5OscText)",
            self.harness,
        )
        self.assertIn("blocked_m1_m5_oscillator_gate", self.harness)
        self.assertIn("minimum M1/M5 directional oscillator rating=$testM1M5OscText", self.harness)


if __name__ == "__main__":
    unittest.main()
