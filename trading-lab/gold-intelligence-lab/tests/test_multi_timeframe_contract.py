"""Contracts for five-timeframe consensus summary."""
import unittest
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from goldlab.multi_timeframe import TIMEFRAMES, summarize_timeframe_consensus

def item(category, eligible=True, ready=True, score=0.7):
    return {"analysis": {"ratings": {"overall_category_ar": category, "overall": score},
        "readiness": {"complete": ready},
        "current_market_review": {"eligible": eligible, "reason_ar": "test"}}}

class MultiTimeframeContracts(unittest.TestCase):
    def test_missing_frames_block_summary(self):
        result = summarize_timeframe_consensus({"M1": item("شراء قوي")})
        self.assertEqual(result["status"], "BLOCKED_OR_INCOMPLETE")
        self.assertEqual(result["missing_timeframes"], ["M5", "M15", "M30", "H1"])
    def test_five_strong_buy_frames(self):
        result = summarize_timeframe_consensus({tf: item("شراء قوي") for tf in TIMEFRAMES})
        self.assertEqual(result["status"], "STRONG_BUY_ALL_FIVE")
    def test_five_strong_sell_frames(self):
        result = summarize_timeframe_consensus({tf: item("بيع قوي", score=-0.8) for tf in TIMEFRAMES})
        self.assertEqual(result["status"], "STRONG_SELL_ALL_FIVE")
    def test_bad_quality_blocks_summary(self):
        reports = {tf: item("شراء قوي") for tf in TIMEFRAMES}
        reports["M1"] = item("شراء قوي", eligible=False)
        result = summarize_timeframe_consensus(reports)
        self.assertEqual(result["status"], "BLOCKED_OR_INCOMPLETE")
        self.assertIn("M1", result["blocked_timeframes"])
    def test_four_of_five_is_partial(self):
        reports = {tf: item("شراء") for tf in TIMEFRAMES}
        reports["H1"] = item("بيع", score=-0.3)
        self.assertEqual(summarize_timeframe_consensus(reports)["status"], "PARTIAL_BULLISH_ALIGNMENT")
    def test_mixed_frames(self):
        cats = ["شراء", "شراء قوي", "حياد", "بيع", "بيع قوي"]
        reports = {tf: item(cat) for tf, cat in zip(TIMEFRAMES, cats)}
        self.assertEqual(summarize_timeframe_consensus(reports)["status"], "MIXED_TIMEFRAMES")
    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            summarize_timeframe_consensus([])
if __name__ == "__main__":
    unittest.main()
