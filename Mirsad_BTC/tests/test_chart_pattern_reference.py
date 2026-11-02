from __future__ import annotations

import unittest

import numpy as np
import talib

from mirsad.engines.chart_pattern_reference import (
    _pattern_signal_arrays,
    analyze_talib_pattern_reference,
)


def to_bars(open_, high, low, close):
    return [
        {
            "x_px": index,
            "open": float(open_[index]),
            "high": float(high[index]),
            "low": float(low[index]),
            "close": float(close[index]),
        }
        for index in range(len(close))
    ]


def deterministic_ohlc(count: int = 100, seed: int = 17):
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0.0, 0.8, count))
    open_ = close + rng.normal(0.0, 0.45, count)
    spread_high = rng.uniform(0.08, 0.65, count)
    spread_low = rng.uniform(0.08, 0.65, count)
    high = np.maximum(open_, close) + spread_high
    low = np.minimum(open_, close) - spread_low
    return to_bars(open_, high, low, close)


class ChartPatternReferenceTests(unittest.TestCase):
    def test_reference_scans_large_talib_pattern_catalog(self) -> None:
        result = analyze_talib_pattern_reference(
            deterministic_ohlc(), last_candle_closed=True
        )
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["source"], "TA-Lib")
        self.assertGreaterEqual(result["pattern_definition_count"], 50)
        self.assertIn("not probabilities", result["interpretation"])
        self.assertIn("events", result)

    def test_open_latest_candle_is_never_reported_as_completed(self) -> None:
        count = 35
        open_ = np.full(count, 100.0)
        close = np.full(count, 100.02)
        high = np.full(count, 101.0)
        low = np.full(count, 99.0)
        close[-1] = 100.01
        bars = to_bars(open_, high, low, close)
        result = analyze_talib_pattern_reference(
            bars, last_candle_closed=False, event_window=5
        )
        latest_events = [event for event in result["events"] if event["bar_index"] == count - 1]
        self.assertTrue(latest_events)
        self.assertTrue(all(event["state"] == "FORMING" for event in latest_events))
        self.assertGreaterEqual(result["forming_count"], len(latest_events))

    def test_closed_latest_candle_can_be_reported_completed(self) -> None:
        count = 35
        open_ = np.full(count, 100.0)
        close = np.full(count, 100.02)
        high = np.full(count, 101.0)
        low = np.full(count, 99.0)
        close[-1] = 100.01
        bars = to_bars(open_, high, low, close)
        result = analyze_talib_pattern_reference(
            bars, last_candle_closed=True, event_window=5
        )
        latest_events = [event for event in result["events"] if event["bar_index"] == count - 1]
        self.assertTrue(latest_events)
        self.assertTrue(all(event["state"] == "COMPLETED" for event in latest_events))

    def test_bullish_engulfing_is_invalidated_by_a_later_close_below_formation_low(self) -> None:
        bars = [
            {"x_px": 0, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5},
            {"x_px": 1, "open": 12.0, "high": 12.5, "low": 9.5, "close": 10.0},
            {"x_px": 2, "open": 9.0, "high": 13.5, "low": 8.5, "close": 13.0},
            {"x_px": 3, "open": 8.5, "high": 9.0, "low": 7.5, "close": 8.0},
        ]
        events = talib.CDLENGULFING(
            np.asarray([bar["open"] for bar in bars], dtype=float),
            np.asarray([bar["high"] for bar in bars], dtype=float),
            np.asarray([bar["low"] for bar in bars], dtype=float),
            np.asarray([bar["close"] for bar in bars], dtype=float),
        )
        self.assertGreater(int(events[2]), 0)
        result = analyze_talib_pattern_reference(bars, last_candle_closed=True)
        engulfing = [
            event for event in result["events"]
            if event["pattern"] == "CDLENGULFING" and event["bar_index"] == 2
        ]
        self.assertEqual(len(engulfing), 1)
        self.assertEqual(engulfing[0]["side"], "BULLISH")
        self.assertEqual(engulfing[0]["state"], "INVALIDATED")
        self.assertEqual(engulfing[0]["invalidation_rule"], "close_below_formation_low")
        self.assertEqual(engulfing[0]["x_px"], 2.0)
        self.assertEqual(engulfing[0]["formation_center_x_px"], 1.5)

    def test_scan_is_point_in_time_and_does_not_use_future_bars(self) -> None:
        bars = deterministic_ohlc(count=90, seed=23)
        full, error = _pattern_signal_arrays(bars)
        self.assertIsNone(error)
        self.assertGreaterEqual(len(full), 50)

        for cut in (35, 50, 70):
            prefix, prefix_error = _pattern_signal_arrays(bars[:cut + 1])
            self.assertIsNone(prefix_error)
            self.assertEqual(set(full), set(prefix))
            for name in full:
                self.assertEqual(
                    int(full[name][cut]),
                    int(prefix[name][cut]),
                    msg=f"Look-ahead mismatch in {name} at bar {cut}",
                )

    def test_invalid_ohlc_is_rejected_before_calling_talib(self) -> None:
        bars = deterministic_ohlc(count=30)
        bars[5]["high"] = bars[5]["low"] - 1.0
        with self.assertRaisesRegex(ValueError, "Invalid calibrated OHLC"):
            analyze_talib_pattern_reference(bars)

    def test_empty_history_reports_insufficient_data(self) -> None:
        result = analyze_talib_pattern_reference([])
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")
        self.assertEqual(result["events"], [])


if __name__ == "__main__":
    unittest.main()
