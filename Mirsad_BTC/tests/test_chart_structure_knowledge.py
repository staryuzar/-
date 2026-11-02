from __future__ import annotations

import unittest

from mirsad.engines.chart_structure_knowledge import analyze_chart_structure_knowledge


def make_bars(closes: list[float]) -> list[dict[str, float]]:
    return [
        {
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        }
        for close in closes
    ]


class ChartStructureKnowledgeTests(unittest.TestCase):
    def test_internal_swing_and_external_scales_report_confirmed_pivots(self) -> None:
        closes = [
            100, 102, 104, 106, 103, 101,
            108, 112, 116, 120, 116, 112,
            124, 128, 132, 136, 132, 128,
            140, 144, 148, 152, 148, 144,
            150, 154,
        ]
        result = analyze_chart_structure_knowledge(make_bars(closes))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(set(result["scales"]), {"internal", "swing", "external"})
        swing = result["scales"]["swing"]
        self.assertTrue(swing["swing_highs"])
        self.assertTrue(swing["swing_lows"])
        for pivot in swing["swing_highs"] + swing["swing_lows"]:
            self.assertTrue(pivot["confirmed"])
            self.assertEqual(pivot["confirmation_index"], pivot["index"] + 2)

    def test_latest_unclosed_candle_is_excluded_from_structure(self) -> None:
        bars = make_bars([100, 102, 104, 106, 103, 101, 108, 112, 116, 120])
        result = analyze_chart_structure_knowledge(bars, last_candle_closed=False)
        self.assertEqual(result["confirmed_bars"], len(bars) - 1)

    def test_gap_is_detected_as_price_imbalance_not_institutional_evidence(self) -> None:
        bars = [
            {"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 102, "high": 104, "low": 101.5, "close": 103},
            {"open": 106, "high": 108, "low": 105, "close": 107},
            {"open": 109, "high": 111, "low": 108, "close": 110},
            {"open": 112, "high": 114, "low": 111, "close": 113},
            {"open": 115, "high": 117, "low": 114, "close": 116},
            {"open": 118, "high": 120, "low": 117, "close": 119},
            {"open": 121, "high": 123, "low": 120, "close": 122},
        ]
        result = analyze_chart_structure_knowledge(bars)
        bullish_gaps = [x for x in result["fair_value_gaps"] if x["structure_id"] == "bullish_fvg"]
        self.assertTrue(bullish_gaps)
        self.assertEqual(bullish_gaps[0]["status"], "UNMITIGATED_AT_SAMPLE_END")

    def test_insufficient_history_does_not_infer_structure(self) -> None:
        result = analyze_chart_structure_knowledge(make_bars([100, 101, 102, 103, 102]))
        self.assertEqual(result["status"], "INSUFFICIENT")
        self.assertEqual(result["bos_choch_events"], [])

    def test_invalid_ohlc_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Inconsistent OHLC"):
            analyze_chart_structure_knowledge([
                {"open": 101, "high": 99, "low": 100, "close": 102}
            ])


if __name__ == "__main__":
    unittest.main()
