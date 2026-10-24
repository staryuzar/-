"""Regression tests for neutral consensus and same-direction re-entry state."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EA_PATH = ROOT / "TV26_FiveTF_Arabic_CANDIDATE.mq5"


class SignalLatchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA_PATH.read_text(encoding="utf-8")
        start = cls.source.index("void TradeIfAligned()")
        cls.trade_logic = cls.source[start:]
        neutral_start = cls.trade_logic.index("if(sig==0)")
        consensus_start = cls.trade_logic.index('Print("TV26_CONSENSUS;signal="', neutral_start)
        cls.neutral_branch = cls.trade_logic[neutral_start:consensus_start]

    def test_neutral_signal_does_not_clear_latch_while_position_is_open(self):
        branch = self.neutral_branch
        self.assertIn("bool neutralPositionOpen=FindOurPosition(neutralTicket,neutralSide);", branch)
        self.assertIn("if(neutralPositionOpen)", branch)
        self.assertIn("TV26_SIGNAL_LATCH_HELD;reason=NEUTRAL_WHILE_POSITION_OPEN", branch)
        self.assertIn("RememberSignal(0)", branch)

        open_branch = branch.index("if(neutralPositionOpen)")
        flat_else = branch.index("else", open_branch)
        reset = branch.index("RememberSignal(0)", flat_else)
        self.assertNotIn("RememberSignal(0)", branch[open_branch:flat_else])
        self.assertIn("TV26_SIGNAL_LATCH_RESET;reason=NEUTRAL_WHILE_FLAT", branch[flat_else:])

    def test_same_direction_entry_remains_blocked_until_latch_is_rearmed(self):
        logic = self.trade_logic
        self.assertIn("if(!hasTracked && sig==g_lastExecutedSignal)", logic)
        self.assertIn("reason=SAME_SIGNAL_LATCH", logic)
        # The neutral branch is the only path that re-arms the latch after the consensus becomes neutral while flat.
        self.assertIn("RememberSignal(0)", self.neutral_branch)

    def test_research_fix_is_diagnostic_and_does_not_add_global_cooldown(self):
        branch = self.neutral_branch
        self.assertIn("TV26_SIGNAL_LATCH_HELD", branch)
        self.assertIn("TV26_SIGNAL_LATCH_RESET", branch)
        self.assertIn("InpCooldownBarsAfterExit = 0", self.source)
        self.assertNotIn("RememberSignal(0); // Re-arm after the five-timeframe consensus is no longer strong.", branch)


if __name__ == "__main__":
    unittest.main()
