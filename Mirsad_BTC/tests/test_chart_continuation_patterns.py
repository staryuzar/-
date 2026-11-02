from __future__ import annotations

import unittest

from mirsad.engines.chart_continuation_patterns import detect_classical_continuation_patterns


def base_bars(length: int, close: float = 110.0) -> list[dict[str, float]]:
    return [
        {"open": close, "high": close + 5.0, "low": close - 5.0, "close": close}
        for _ in range(length)
    ]


def pivot(index: int, price: float, kind: str) -> dict[str, float | int | str | bool]:
    return {
        "index": index, "price": price, "kind": kind,
        "confirmed": True, "confirmation_index": index + 2,
    }


def detect(
    highs: list[float],
    lows: list[float],
    *,
    high_indices: list[int] | None = None,
    low_indices: list[int] | None = None,
    length: int = 46,
    atr: float = 2.0,
    data: list[dict[str, float]] | None = None,
) -> list[dict]:
    high_indices = high_indices or [10, 20, 30]
    low_indices = low_indices or [15, 25, 35]
    bars = data or base_bars(length)
    high_pivots = [pivot(i, p, "high") for i, p in zip(high_indices, highs)]
    low_pivots = [pivot(i, p, "low") for i, p in zip(low_indices, lows)]
    return detect_classical_continuation_patterns(bars, high_pivots, low_pivots, atr=atr)


class ContinuationPatternTests(unittest.TestCase):
    def test_ascending_triangle_candidate(self) -> None:
        found = detect([120, 120, 120], [90, 95, 100])
        self.assertIn("ascending_triangle", [item["pattern_id"] for item in found])

    def test_descending_triangle_candidate(self) -> None:
        found = detect([130, 125, 120], [100, 100, 100])
        self.assertIn("descending_triangle", [item["pattern_id"] for item in found])

    def test_symmetrical_triangle_candidate(self) -> None:
        found = detect([130, 125, 120], [90, 95, 100])
        self.assertIn("symmetrical_triangle", [item["pattern_id"] for item in found])

    def test_rising_wedge_candidate(self) -> None:
        found = detect([110, 115, 120], [90, 100, 110])
        self.assertIn("rising_wedge", [item["pattern_id"] for item in found])

    def test_falling_wedge_candidate(self) -> None:
        found = detect([130, 120, 110], [90, 85, 80])
        self.assertIn("falling_wedge", [item["pattern_id"] for item in found])

    def test_rising_channel_candidate(self) -> None:
        data = base_bars(46, close=125.0)
        found = detect([120, 125, 130], [100, 105, 110], data=data)
        channel = [item for item in found if item["pattern_id"] == "rising_channel"]
        self.assertEqual(len(channel), 1)
        self.assertEqual(channel[0]["status"], "CANDIDATE")

    def test_breakout_is_only_confirmed_after_all_boundary_pivots(self) -> None:
        data = base_bars(46)
        data[40].update({"open": 125.0, "high": 132.0, "low": 119.0, "close": 130.0})
        found = detect([120, 120, 120], [90, 95, 100], data=data)
        triangle = next(item for item in found if item["pattern_id"] == "ascending_triangle")
        self.assertEqual(triangle["status"], "BREAKOUT_UP")
        self.assertEqual(triangle["breakout_index"], 40)
        self.assertEqual(triangle["formation_confirmed_at"], 37)

    def test_breakout_before_last_pivot_confirmation_is_ignored(self) -> None:
        data = base_bars(46)
        data[36].update({"open": 125.0, "high": 132.0, "low": 119.0, "close": 130.0})
        found = detect([120, 120, 120], [90, 95, 100], data=data)
        triangle = next(item for item in found if item["pattern_id"] == "ascending_triangle")
        self.assertEqual(triangle["status"], "CANDIDATE")
        self.assertIsNone(triangle["breakout_index"])

    def test_bull_flag_requires_a_large_prior_bullish_pole_and_shallow_pullback(self) -> None:
        data = base_bars(50, close=130.0)
        data[4]["low"] = 100.0
        data[18]["high"] = 140.0
        hi, lo = [24, 32, 40], [28, 36, 44]
        highs, lows = [138, 135, 132], [125, 122, 119]
        for i, p in zip(hi, highs): data[i]["high"] = float(p)
        for i, p in zip(lo, lows): data[i]["low"] = float(p)
        found = detect(highs, lows, high_indices=hi, low_indices=lo, length=50, data=data)
        self.assertIn("bull_flag", [item["pattern_id"] for item in found])

    def test_bear_flag_requires_a_large_prior_bearish_pole_and_shallow_rally(self) -> None:
        data = base_bars(50, close=118.0)
        data[4]["high"] = 150.0
        data[18]["low"] = 100.0
        hi, lo = [24, 32, 40], [28, 36, 44]
        highs, lows = [119, 122, 125], [110, 113, 116]
        for i, p in zip(hi, highs): data[i]["high"] = float(p)
        for i, p in zip(lo, lows): data[i]["low"] = float(p)
        found = detect(highs, lows, high_indices=hi, low_indices=lo, length=50, data=data)
        self.assertIn("bear_flag", [item["pattern_id"] for item in found])

    def test_bull_pennant_requires_impulse_before_symmetrical_convergence(self) -> None:
        data = base_bars(50, close=130.0)
        data[4]["low"] = 100.0
        data[18]["high"] = 140.0
        hi, lo = [24, 32, 40], [28, 36, 44]
        highs, lows = [138, 137, 136], [126, 127, 128]
        for i, p in zip(hi, highs): data[i]["high"] = float(p)
        for i, p in zip(lo, lows): data[i]["low"] = float(p)
        found = detect(highs, lows, high_indices=hi, low_indices=lo, length=50, data=data)
        self.assertIn("bull_pennant", [item["pattern_id"] for item in found])

    def test_no_classification_without_three_confirmed_pivots_per_boundary(self) -> None:
        bars = base_bars(40)
        found = detect_classical_continuation_patterns(
            bars, [pivot(10, 120, "high"), pivot(20, 119, "high")],
            [pivot(15, 90, "low"), pivot(25, 91, "low")], atr=2.0,
        )
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
