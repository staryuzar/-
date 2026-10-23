import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from compare_tv26_csv import COMPONENTS


PINE_VOTE_VARIABLES = [
    "rSma10", "rSma20", "rSma30", "rSma50", "rSma100", "rSma200",
    "rEma10", "rEma20", "rEma30", "rEma50", "rEma100", "rEma200",
    "rHull9", "rVwma20", "rIchimoku",
    "rRsi", "rStoch", "rCci", "rAdx", "rAo", "rMomentum", "rMacd",
    "rStochRsi", "rWilliams", "rBullBear", "rUo",
]
OUTPUT_FIELDS = (
    "packed", "total", "ma", "osc", "formula_total", "formula_ma",
    "formula_osc", "bar_open_time", "open", "high", "low", "close",
)
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1")


class TV26AllTFPineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "TradingView_Parity_AllTF_Export.pine").read_text(encoding="utf-8")

    def test_plot_and_request_limits_are_respected(self):
        plot_count = len(re.findall(r"(?m)^\s*plot\(", self.source))
        request_count = len(re.findall(r"request\.security\(syminfo\.tickerid", self.source))
        self.assertEqual(plot_count, 60, "One combined export must stay at 60 plots, below TradingView's 64 plot-count limit.")
        self.assertEqual(request_count, 5, "Exactly one request.security tuple is expected per target timeframe.")

    def test_all_60_columns_are_exported(self):
        self.assertEqual(len(COMPONENTS), 26)
        for tf in TIMEFRAMES:
            for field in OUTPUT_FIELDS:
                self.assertIn(f'"TV26.{tf}.{field}"', self.source, f"Missing export column for {tf}.{field}")

    def test_packed_vote_order_matches_mt5_component_order(self):
        packed_fn = self.source.split("f_all_tf_payload() =>", 1)[1]
        vote_array = packed_fn.split("array<float> votes = array.from(", 1)[1].split(")", 1)[0]
        actual = re.findall(r"\br[A-Za-z0-9]+\b", vote_array)
        self.assertEqual(actual, PINE_VOTE_VARIABLES)
        self.assertEqual(list(COMPONENTS.keys()), [
            "SMA10", "SMA20", "SMA30", "SMA50", "SMA100", "SMA200",
            "EMA10", "EMA20", "EMA30", "EMA50", "EMA100", "EMA200",
            "HMA9", "VWMA20", "Ichimoku",
            "RSI14", "Stochastic", "CCI20", "ADX", "AO", "Momentum10", "MACD",
            "StochRSI", "WilliamsR", "BullBearPower", "UltimateOscillator",
        ])

    def test_missing_vote_uses_reserved_base4_digit(self):
        self.assertIn("float digit = na(v) ? 3.0 : v + 1.0", self.source)
        self.assertIn('out.append("" if digit == 3 else str(digit - 1))',
                      (ROOT / "split_tv26_alltf_export.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
