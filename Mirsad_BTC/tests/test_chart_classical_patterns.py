from __future__ import annotations

import unittest

from mirsad.engines.chart_classical_patterns import detect_classical_reversal_patterns


def bars(length: int, close: float = 105.0) -> list[dict[str, float]]:
    return [
        {"open": close, "high": close + 0.25, "low": close - 0.25, "close": close}
        for _ in range(length)
    ]


def pivot(index: int, price: float, kind: str) -> dict[str, float | int | str | bool]:
    return {
        "index": index, "price": price, "kind": kind,
        "confirmed": True, "confirmation_index": index + 2,
    }


class ClassicalReversalPatternTests(unittest.TestCase):
    def test_double_top_requires_close_beyond_neckline_after_pivot_confirmation(self) -> None:
        data = bars(22)
        data[18]["close"] = 98.9
        result = detect_classical_reversal_patterns(
            data, [pivot(5, 110.0, "high"), pivot(15, 109.8, "high")],
            [pivot(10, 100.0, "low")], range_reference=2.0,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pattern_id"], "double_top")
        self.assertEqual(result[0]["status"], "CONFIRMED")
        self.assertEqual(result[0]["formation_confirmed_at"], 17)
        self.assertEqual(result[0]["confirmation_index"], 18)
        self.assertEqual(result[0]["empirical_status"], "UNVALIDATED")

    def test_double_top_break_before_pattern_exists_is_ignored(self) -> None:
        data = bars(24)
        data[16]["close"] = 95.0
        data[18]["close"] = 105.0
        data[19]["close"] = 105.0
        result = detect_classical_reversal_patterns(
            data, [pivot(5, 110.0, "high"), pivot(15, 109.8, "high")],
            [pivot(10, 100.0, "low")], range_reference=2.0,
        )
        self.assertEqual(result[0]["status"], "CANDIDATE")
        self.assertIsNone(result[0]["confirmation_index"])

    def test_double_top_can_be_invalidated_by_close_above_pattern_high(self) -> None:
        data = bars(22)
        data[18]["close"] = 112.0
        result = detect_classical_reversal_patterns(
            data, [pivot(5, 110.0, "high"), pivot(15, 109.8, "high")],
            [pivot(10, 100.0, "low")], range_reference=2.0,
        )
        self.assertEqual(result[0]["status"], "INVALIDATED")
        self.assertEqual(result[0]["invalidation_index"], 18)

    def test_confirmed_double_top_is_invalidated_by_a_later_completed_close(self) -> None:
        data = bars(24)
        data[18]["close"] = 98.9
        data[20]["close"] = 112.0
        result = detect_classical_reversal_patterns(
            data, [pivot(5, 110.0, "high"), pivot(15, 109.8, "high")],
            [pivot(10, 100.0, "low")], range_reference=2.0,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "INVALIDATED_AFTER_CONFIRMATION")
        self.assertEqual(result[0]["confirmation_index"], 18)
        self.assertEqual(result[0]["invalidation_index"], 20)
        self.assertTrue(result[0]["ever_confirmed"])
        self.assertFalse(result[0]["active_at_sample_end"])

    def test_head_and_shoulders_uses_sloped_neckline_and_closed_break(self) -> None:
        data = bars(25)
        data[23]["close"] = 98.0
        highs = [pivot(5, 110.0, "high"), pivot(12, 120.0, "high"), pivot(20, 110.5, "high")]
        lows = [pivot(8, 100.0, "low"), pivot(16, 101.0, "low")]
        result = detect_classical_reversal_patterns(data, highs, lows, range_reference=2.0)
        hs = [item for item in result if item["pattern_id"] == "head_and_shoulders"]
        self.assertEqual(len(hs), 1)
        self.assertEqual(hs[0]["status"], "CONFIRMED")
        self.assertEqual(hs[0]["formation_confirmed_at"], 22)
        self.assertEqual(hs[0]["confirmation_index"], 23)
        self.assertGreater(hs[0]["neckline_slope_per_bar"], 0)

    def test_double_bottom_requires_bullish_close_above_neckline(self) -> None:
        data = bars(22, close=95.0)
        data[18]["close"] = 101.1
        result = detect_classical_reversal_patterns(
            data, [pivot(10, 100.0, "high")],
            [pivot(5, 90.0, "low"), pivot(15, 90.2, "low")], range_reference=2.0,
        )
        self.assertEqual(result[0]["pattern_id"], "double_bottom")
        self.assertEqual(result[0]["status"], "CONFIRMED")

    def test_inverse_head_and_shoulders_is_reported_as_bullish_structure(self) -> None:
        data = bars(25, close=85.0)
        data[23]["close"] = 92.0
        lows = [pivot(5, 80.0, "low"), pivot(12, 70.0, "low"), pivot(20, 80.5, "low")]
        highs = [pivot(8, 90.0, "high"), pivot(16, 89.0, "high")]
        result = detect_classical_reversal_patterns(data, highs, lows, range_reference=2.0)
        inverse = [item for item in result if item["pattern_id"] == "inverse_head_and_shoulders"]
        self.assertEqual(len(inverse), 1)
        self.assertEqual(inverse[0]["direction"], "BULLISH")
        self.assertEqual(inverse[0]["status"], "CONFIRMED")

    def test_small_history_returns_no_patterns(self) -> None:
        self.assertEqual(detect_classical_reversal_patterns(bars(9), [], [], range_reference=1.0), [])


if __name__ == "__main__":
    unittest.main()
