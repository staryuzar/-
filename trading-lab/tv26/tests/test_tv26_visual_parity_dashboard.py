from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "TradingView_Visual_Parity_5TF.pine"


class TV26VisualParityDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = DASHBOARD.read_text(encoding="utf-8")
        cls.code = "\n".join(
            line for line in cls.source.splitlines()
            if not line.lstrip().startswith("//")
        )

    def test_dashboard_uses_versioned_technical_rating_library(self) -> None:
        self.assertIn("import TradingView/TechnicalRating/3 as tvRating", self.code)
        self.assertIn("tvRating.calcRatingAll()", self.code)

    def test_dashboard_reads_all_five_timeframes(self) -> None:
        requests = re.findall(r"request\.security\(", self.code)
        self.assertEqual(len(requests), 5)
        for timeframe in ('"1"', '"5"', '"15"', '"30"', '"60"'):
            self.assertIn(f"syminfo.tickerid, {timeframe}", self.code)

    def test_dashboard_displays_all_twenty_six_components(self) -> None:
        self.assertIn('"SMA 10", "SMA 20", "SMA 30", "SMA 50", "SMA 100", "SMA 200"', self.code)
        self.assertIn('"EMA 10", "EMA 20", "EMA 30", "EMA 50", "EMA 100", "EMA 200"', self.code)
        self.assertIn('"Bulls/Bears Power 13", "Ultimate Oscillator"', self.code)
        self.assertIn("for componentIndex = 0 to array.size(componentNames) - 1", self.code)
        self.assertIn("f_packedVoteText(array.get(packs, tfIndex), componentIndex)", self.code)

    def test_dashboard_uses_confirmed_closed_bar_values(self) -> None:
        self.assertIn("packedVotes[1]", self.code)
        self.assertIn("libTotal[1]", self.code)
        self.assertIn("time[1]", self.code)
        self.assertIn("open[1]", self.code)
        self.assertIn("high[1]", self.code)
        self.assertIn("low[1]", self.code)
        self.assertIn("close[1]", self.code)
        self.assertIn("OHLC (فتح/أعلى/أدنى/إغلاق)", self.code)
        self.assertIn("lookahead=barmerge.lookahead_on", self.code)

    def test_dashboard_has_no_chart_data_export_plots_or_csv_flow(self) -> None:
        plot_calls = re.findall(r"(?m)^\s*plot(?:shape|char|bar|candle|arrow)?\s*\(", self.code)
        self.assertEqual(plot_calls, [])
        self.assertNotIn("TV26_AllTF.csv", self.code)
        self.assertNotIn("file_download", self.code.lower())
        self.assertIn("var table t = table.new(position.top_right, 6, 34", self.code)

    def test_macd_vote_matches_official_technical_rating_v3(self) -> None:
        # TradingView's TechnicalRating v3 votes on MACD line vs signal only;
        # histogram sign is not an additional condition.
        self.assertIn(
            "float rMacd = f_calcRating(macdSignal, macdLine > macdSignal, macdLine < macdSignal)",
            self.code,
        )
        self.assertNotIn("macdHist > 0", self.code)
        self.assertNotIn("macdHist < 0", self.code)

    def test_dashboard_exposes_formula_vs_library_deltas(self) -> None:
        self.assertIn("formulaTotalM1", self.code)
        self.assertIn("formulaMaM1", self.code)
        self.assertIn("formulaOscM1", self.code)
        self.assertIn("dTotal", self.code)
        self.assertIn("dMa", self.code)
        self.assertIn("dOsc", self.code)


if __name__ == "__main__":
    unittest.main()
