from __future__ import annotations

import unittest

from mirsad.engines.chart_pattern_knowledge import analyze_candle_patterns


def candle(open_price: float, high: float, low: float, close: float) -> dict[str, float]:
    return {"open": open_price, "high": high, "low": low, "close": close}


def ids(result: dict) -> set[str]:
    return {item["pattern_id"] for item in result["detected"]}


class ChartPatternKnowledgeTests(unittest.TestCase):
    def test_doji_and_subtype_are_reported_as_rule_matches(self) -> None:
        history = [candle(100, 102, 98, 101) for _ in range(10)]
        result = analyze_candle_patterns(history + [candle(100, 101, 99, 100.01)])
        self.assertIn("doji", ids(result))
        self.assertTrue(all(
            item["interpretation"] == "RULE_MATCH_NOT_PROBABILITY"
            for item in result["detected"]
        ))

    def test_bullish_engulfing_requires_second_body_to_span_first(self) -> None:
        bars = [
            candle(106, 107, 105, 105),
            candle(105, 106, 104, 104),
            candle(104, 105, 103, 103),
            candle(103, 104, 102, 102),
            candle(103, 104, 98, 99),
            candle(98, 105, 97, 104),
        ]
        result = analyze_candle_patterns(bars)
        match = [x for x in result["detected"] if x["pattern_id"] == "bullish_engulfing"]
        self.assertTrue(match)
        self.assertEqual(match[-1]["start_index"], 4)
        self.assertEqual(match[-1]["end_index"], 5)
        self.assertEqual(match[-1]["context_required"], "DOWN")

    def test_bullish_harami_requires_second_body_inside_first(self) -> None:
        bars = [
            candle(106, 107, 105, 105),
            candle(105, 106, 104, 104),
            candle(104, 105, 103, 103),
            candle(103, 104, 102, 102),
            candle(103, 104, 98, 99),
            candle(100, 102.5, 99.5, 102),
        ]
        result = analyze_candle_patterns(bars)
        harami = [x for x in result["detected"] if x["pattern_id"] == "bullish_harami"]
        self.assertTrue(harami)
        engulfing = [x for x in result["detected"] if x["pattern_id"] == "bullish_engulfing"]
        self.assertFalse(engulfing)

    def test_hammer_requires_prior_decline_context(self) -> None:
        history = [
            candle(110 - index, 111 - index, 108.5 - index, 109 - index)
            for index in range(10)
        ]
        bars = history + [candle(100.0, 100.1, 95.0, 99.9)]
        result = analyze_candle_patterns(bars)
        hammer = [x for x in result["detected"] if x["pattern_id"] == "hammer"]
        self.assertTrue(hammer)
        self.assertEqual(hammer[-1]["context_match"], True)

    def test_piercing_line_requires_open_below_and_close_above_midpoint(self) -> None:
        bars = [
            candle(106, 107, 104, 105),
            candle(105, 106, 103, 104),
            candle(104, 105, 102, 103),
            candle(103, 104, 101, 102),
            candle(103, 104, 94, 95),
            candle(94, 102, 93, 101),
        ]
        result = analyze_candle_patterns(bars)
        self.assertIn("piercing_line", ids(result))

        false_positive = bars[:-1] + [candle(100, 102, 99, 101)]
        rejected = analyze_candle_patterns(false_positive)
        self.assertNotIn("piercing_line", ids(rejected))

    def test_dark_cloud_cover_requires_open_above_and_close_below_midpoint(self) -> None:
        bars = [
            candle(100, 102, 99, 101),
            candle(101, 103, 100, 102),
            candle(102, 104, 101, 103),
            candle(103, 105, 102, 104),
            candle(95, 106, 94, 104),
            candle(105, 106, 97, 98),
        ]
        result = analyze_candle_patterns(bars)
        self.assertIn("dark_cloud_cover", ids(result))

        false_positive = bars[:-1] + [candle(98, 100, 97, 99)]
        rejected = analyze_candle_patterns(false_positive)
        self.assertNotIn("dark_cloud_cover", ids(rejected))

    def test_current_open_candle_is_marked_forming(self) -> None:
        history = [candle(100, 102, 98, 101) for _ in range(10)]
        result = analyze_candle_patterns(
            history + [candle(100, 101, 99, 100.01)], last_candle_closed=False
        )
        doji = [x for x in result["detected"] if x["pattern_id"] == "doji"]
        self.assertTrue(doji)
        self.assertEqual(doji[-1]["confirmation_state"], "FORMING")
        self.assertTrue(doji[-1]["uses_unconfirmed_latest_candle"])


    def test_doji_uses_previous_ten_ranges_not_current_range(self) -> None:
        history = [candle(100, 110, 90, 100.2) for _ in range(10)]
        result = analyze_candle_patterns(history + [candle(100, 101, 99, 100.5)])
        self.assertIn("doji", ids(result))

    def test_doji_does_not_use_future_or_incomplete_history(self) -> None:
        short_history = [candle(100, 102, 98, 101) for _ in range(9)]
        result = analyze_candle_patterns(short_history + [candle(100, 101, 99, 100.01)])
        self.assertNotIn("doji", ids(result))

    def test_invalid_ohlc_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            analyze_candle_patterns([candle(100, 98, 99, 101)])


if __name__ == "__main__":
    unittest.main()
