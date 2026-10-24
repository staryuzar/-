"""Contract tests for the optional state-based re-entry lock after a losing close."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
EA = ROOT / "TV26_FiveTF_Arabic_CANDIDATE.mq5"
HARNESS = ROOT.parents[1] / ".github" / "scripts" / "tv26_strategy_cooldown_backtest.ps1"


class LossLatchOppositeConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA.read_text(encoding="utf-8")
        cls.harness = HARNESS.read_text(encoding="utf-8")
        trade_start = cls.source.index("void TradeIfAligned()")
        trade_end = cls.source.index("\nint OnInit()", trade_start)
        cls.trade = cls.source[trade_start:trade_end]
        handler_start = cls.source.index("void OnTradeTransaction(")
        handler_end = cls.source.index("\nvoid OnTick()", handler_start)
        cls.handler = cls.source[handler_start:handler_end]
        init_start = cls.source.index("int OnInit()")
        init_end = cls.source.index("\nvoid OnDeinit(", init_start)
        cls.init = cls.source[init_start:init_end]

    def test_feature_is_off_by_default_and_persisted_per_symbol_magic(self):
        self.assertIn(
            "input bool   InpRequireOppositeSignalAfterLossBeforeReentry = false;",
            self.source,
        )
        self.assertIn('g_lossLatchGV="TV26_LossDirection_"+_Symbol+"_"+IntegerToString((int)InpMagic);', self.init)
        self.assertIn("GlobalVariableCheck(g_lossLatchGV)", self.init)
        self.assertIn("GlobalVariableSet(g_lossLatchGV,(double)g_lossLatchSignal)", self.handler)

    def test_only_a_fully_closed_net_losing_position_arms_the_latch(self):
        self.assertIn("HistorySelectByPosition(positionId)", self.handler)
        self.assertIn("positionNet+=HistoryDealGetDouble(dealTicket,DEAL_PROFIT)", self.handler)
        self.assertIn("HistoryDealGetDouble(dealTicket,DEAL_SWAP)", self.handler)
        self.assertIn("HistoryDealGetDouble(dealTicket,DEAL_COMMISSION)", self.handler)
        self.assertIn("HistoryDealGetDouble(dealTicket,DEAL_FEE)", self.handler)
        self.assertIn("!positionStillOpen", self.handler)
        self.assertIn("positionNetReady && positionNet<0.0 && closedSignal!=0", self.handler)
        self.assertIn('TV26_LOSS_LATCH_ARMED;reason=NET_LOSS_ON_FULL_CLOSE', self.handler)
        self.assertIn("TV26_LOSS_LATCH_NOT_ARMED;reason=POSITION_NET_UNAVAILABLE", self.handler)

    def test_only_same_side_is_blocked_and_neutral_does_not_clear_loss_state(self):
        gate_start = self.trade.index("if(!hasTracked && InpRequireOppositeSignalAfterLossBeforeReentry")
        gate_end = self.trade.index("if(!hasTracked && InpCooldownBarsAfterExit", gate_start)
        block = self.trade[gate_start:gate_end]
        self.assertIn("sig==g_lossLatchSignal", block)
        self.assertIn("reason=SAME_DIRECTION_AFTER_LOSS_LATCH", block)
        self.assertNotIn("g_lossLatchSignal=0", block)
        neutral_end = self.trade.index("   ulong trackedTicket=0;")
        neutral_branch = self.trade[:neutral_end]
        self.assertIn("RememberSignal(0)", neutral_branch)
        self.assertNotIn("g_lossLatchSignal=0", neutral_branch)

    def test_latch_is_released_only_after_successful_opposite_order_acceptance(self):
        release_at = self.trade.index("TV26_LOSS_LATCH_RELEASED;reason=OPPOSITE_DIRECTION_ORDER_ACCEPTED")
        accepted_at = self.trade.index("TV26_ORDER_ACCEPTED;")
        self.assertLess(accepted_at, release_at)
        release_block = self.trade[release_at - 300:release_at + 650]
        self.assertIn("sig==-g_lossLatchSignal", release_block)
        self.assertIn("g_lossLatchSignal=0", release_block)
        self.assertIn("GlobalVariableSet(g_lossLatchGV,0.0)", release_block)

    def test_tester_harness_sets_verifies_and_counts_the_experiment(self):
        self.assertIn("TV26_TEST_REQUIRE_OPPOSITE_AFTER_LOSS", self.harness)
        self.assertIn("InpRequireOppositeSignalAfterLossBeforeReentry=$testOppositeAfterLossText", self.harness)
        self.assertIn("InpRequireOppositeSignalAfterLossBeforeReentry=' + [regex]::Escape($testOppositeAfterLossText)", self.harness)
        self.assertIn("blocked_same_direction_after_loss_latch", self.harness)
        self.assertIn("loss_latch_armed", self.harness)
        self.assertIn("loss_latch_released", self.harness)


if __name__ == "__main__":
    unittest.main()
