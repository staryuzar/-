"""Contract tests for targeted cooldown after profitable same-direction exits."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "TV26_FiveTF_Arabic_CANDIDATE.mq5"
HARNESS = ROOT.parents[1] / ".github" / "scripts" / "tv26_strategy_cooldown_backtest.ps1"


class PostProfitSameDirectionCooldownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA.read_text(encoding="utf-8")
        cls.harness = HARNESS.read_text(encoding="utf-8")
        start = cls.source.index("void TradeIfAligned()")
        end = cls.source.index("\nint OnInit()", start)
        cls.trade = cls.source[start:end]
        handler_start = cls.source.index("void OnTradeTransaction(")
        handler_end = cls.source.index("\nvoid OnTick()", handler_start)
        cls.handler = cls.source[handler_start:handler_end]
        cls.init_start = cls.source.index("int OnInit()")
        cls.init_end = cls.source.index("\nvoid OnDeinit(", cls.init_start)
        cls.init = cls.source[cls.init_start:cls.init_end]

    def test_new_parameter_defaults_off_and_is_bounded(self):
        self.assertIn("input int    InpSameDirectionCooldownAfterProfitBars = 0;", self.source)
        self.assertIn("InpSameDirectionCooldownAfterProfitBars<0", self.init)
        self.assertIn("InpSameDirectionCooldownAfterProfitBars>720", self.init)

    def test_only_a_net_profitable_exit_sets_the_profit_state(self):
        self.assertIn("DEAL_PROFIT", self.handler)
        self.assertIn("DEAL_SWAP", self.handler)
        self.assertIn("DEAL_COMMISSION", self.handler)
        self.assertIn("DEAL_FEE", self.handler)
        self.assertIn("HistoryDealGetInteger(trans.deal,DEAL_POSITION_ID)", self.handler)
        self.assertIn("HistorySelectByPosition(positionId)", self.handler)
        self.assertIn("positionNet+=HistoryDealGetDouble(dealTicket,DEAL_PROFIT)", self.handler)
        self.assertIn("g_lastExitWasProfit=(positionNetReady && positionNet>0.0);", self.handler)
        self.assertNotIn("g_lastExitWasProfit=(exitDealNet>0.0);", self.handler)
        self.assertIn("g_lastExitSignal=closedSignal;", self.handler)
        self.assertIn("if(closeTime>=g_lastExitTime)", self.handler)

    def test_exit_direction_is_reconstructed_from_closing_deal_type(self):
        self.assertIn("if(exitDealType==DEAL_TYPE_BUY) closedSignal=-1;", self.handler)
        self.assertIn("else if(exitDealType==DEAL_TYPE_SELL) closedSignal=1;", self.handler)

    def test_gate_only_blocks_same_direction_after_profitable_exit(self):
        gate = self.trade.index("reason=POST_PROFIT_SAME_DIRECTION_COOLDOWN")
        global_cooldown = self.trade.index("reason=POST_EXIT_COOLDOWN")
        demo_guard = self.trade.index("reason=NOT_DEMO_ACCOUNT")
        gate_start = self.trade.index("if(!hasTracked && InpSameDirectionCooldownAfterProfitBars>0")
        gate_end = self.trade.index("if(InpDemoOnly && AccountInfoInteger", gate_start)
        self.assertLess(global_cooldown, gate)
        self.assertLess(gate, demo_guard)
        block = self.trade[gate_start:gate_end]
        self.assertIn("g_lastExitWasProfit", block)
        self.assertIn("g_lastExitSignal==sig", block)
        self.assertIn("g_lastExitNet", block)
        self.assertIn("InpSameDirectionCooldownAfterProfitBars*PeriodSeconds(PERIOD_M1)", block)
        self.assertNotIn("RememberSignal(0)", block)

    def test_existing_global_cooldown_remains_a_separate_optional_guard(self):
        self.assertIn("InpCooldownBarsAfterExit = 0;", self.source)
        self.assertIn("reason=POST_EXIT_COOLDOWN", self.trade)
        self.assertIn("reason=POST_PROFIT_SAME_DIRECTION_COOLDOWN", self.trade)

    def test_tester_harness_writes_verifies_and_counts_the_new_input(self):
        self.assertIn("TV26_TEST_PROFIT_REENTRY_COOLDOWN_BARS", self.harness)
        self.assertIn("$testProfitReentryBars -lt 0 -or $testProfitReentryBars -gt 720", self.harness)
        self.assertIn("InpSameDirectionCooldownAfterProfitBars=$testProfitReentryBars", self.harness)
        self.assertIn("'(?is)InpSameDirectionCooldownAfterProfitBars=' + [regex]::Escape($testProfitReentryText)", self.harness)
        self.assertIn("blocked_post_profit_same_direction_cooldown", self.harness)
        self.assertIn("same-direction post-profit cooldown=$testProfitReentryBars M1 bars", self.harness)


if __name__ == "__main__":
    unittest.main()
