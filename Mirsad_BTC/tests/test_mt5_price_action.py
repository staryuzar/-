from __future__ import annotations

import unittest

from mirsad.engines.mt5_price_action import analyze_mt5_native_price_action, _summarize_latest_pattern_alignment


DURATIONS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
WAVE = (0, 10, 20, 10, 0, -10, -20, -10)


def make_history(
    *,
    count: int = 121,
    directions: dict[str, str] | None = None,
    as_of_ms: int = 1_800_000_000_000,
    forming_spike: bool = False,
) -> dict:
    directions = directions or {name: "up" for name in DURATIONS}
    frames = {}
    for timeframe, duration in DURATIONS.items():
        direction = directions.get(timeframe, "up")
        drift = 1.25 if direction == "up" else -1.25 if direction == "down" else 0.0
        bars = []
        first_open = as_of_ms - int((count - 0.5) * duration)
        for index in range(count):
            close = 50_000.0 + index * drift + WAVE[index % len(WAVE)]
            open_price = close - (2.0 if direction == "up" else -2.0 if direction == "down" else 0.0)
            high = max(open_price, close) + 3.0
            low = min(open_price, close) - 3.0
            volume = 100.0 + (index % 9)
            if forming_spike and index == count - 1:
                open_price, close, high, low, volume = 20_000.0, 150_000.0, 200_000.0, 1_000.0, 1_000_000.0
            bars.append({
                "open_time_ms": first_open + index * duration,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "closed": index < count - 1,
            })
        frames[timeframe] = bars
    return {
        "status": "READY",
        "source": "MT5_CHART_OBSERVER",
        "symbol": "BTCUSDT",
        "broker_symbol": "BTC",
        "account_server": "Headway-Demo",
        "captured_at_ms": as_of_ms,
        "candles_by_tf": frames,
    }


class LatestCandlePatternAlignmentTests(unittest.TestCase):
    def test_mixed_patterns_within_one_timeframe_are_not_misclassified_as_no_pattern(self) -> None:
        alignment, bullish, bearish, mixed = _summarize_latest_pattern_alignment({
            "1m": "MIXED",
            "5m": "NONE",
        })
        self.assertEqual(alignment, "MIXED_CANDLE_PATTERN_EVIDENCE")
        self.assertEqual(bullish, [])
        self.assertEqual(bearish, [])
        self.assertEqual(mixed, ["1m"])

    def test_opposing_timeframe_patterns_are_mixed(self) -> None:
        alignment, bullish, bearish, mixed = _summarize_latest_pattern_alignment({
            "1m": "BULLISH",
            "5m": "BEARISH",
            "15m": "NONE",
        })
        self.assertEqual(alignment, "MIXED_CANDLE_PATTERN_EVIDENCE")
        self.assertEqual(bullish, ["1m"])
        self.assertEqual(bearish, ["5m"])
        self.assertEqual(mixed, [])


class MT5NativePriceActionTests(unittest.TestCase):
    def test_higher_highs_and_higher_lows_produce_bullish_structure(self) -> None:
        result = analyze_mt5_native_price_action(make_history())
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BULLISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BULLISH")
        self.assertEqual(set(result["summary"]["eligible_timeframes"]), set(DURATIONS))
        for timeframe in DURATIONS:
            structure = result["timeframes"][timeframe]["structure"]["swing"]
            self.assertGreaterEqual(len(structure["swing_highs"]), 2)
            self.assertGreaterEqual(len(structure["swing_lows"]), 2)
            self.assertTrue(structure["higher_highs"])
            self.assertTrue(structure["higher_lows"])

    def test_lower_highs_and_lower_lows_produce_bearish_structure(self) -> None:
        directions = {name: "down" for name in DURATIONS}
        result = analyze_mt5_native_price_action(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BEARISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BEARISH")

    def test_conflicting_timeframes_are_reported_as_mixed(self) -> None:
        directions = {
            "1m": "down", "5m": "down", "15m": "down",
            "1h": "up", "4h": "up", "1d": "up",
        }
        result = analyze_mt5_native_price_action(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "MIXED_TIMEFRAME_DIRECTIONS")
        self.assertEqual(result["summary"]["short_term_direction"], "BEARISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BULLISH")

    def test_forming_candle_spike_does_not_change_price_action_result(self) -> None:
        normal = analyze_mt5_native_price_action(make_history())
        spike = analyze_mt5_native_price_action(make_history(forming_spike=True))
        self.assertEqual(normal["direction"], spike["direction"])
        self.assertEqual(normal["structure_score"], spike["structure_score"])
        for timeframe in DURATIONS:
            self.assertEqual(
                normal["timeframes"][timeframe]["structure"],
                spike["timeframes"][timeframe]["structure"],
            )
            self.assertEqual(
                normal["timeframes"][timeframe]["candle_analysis"],
                spike["timeframes"][timeframe]["candle_analysis"],
            )
            self.assertEqual(
                spike["timeframes"][timeframe]["forming_candle"]["state"],
                "FORMING_NOT_USED_FOR_DIRECTION",
            )

    def test_swings_are_only_published_after_right_side_confirmation(self) -> None:
        result = analyze_mt5_native_price_action(make_history())
        pivots = (
            result["timeframes"]["1h"]["structure"]["swing"]["swing_highs"]
            + result["timeframes"]["1h"]["structure"]["swing"]["swing_lows"]
        )
        self.assertTrue(pivots)
        for pivot in pivots:
            self.assertTrue(pivot["confirmed"])
            self.assertLessEqual(
                pivot["confirmation_time_utc_ms"],
                result["timeframes"]["1h"]["last_closed_bar_open_time_ms"],
            )

    def test_insufficient_higher_timeframes_blocks_final_direction(self) -> None:
        history = make_history()
        for timeframe in ("4h", "1d"):
            history["candles_by_tf"][timeframe] = history["candles_by_tf"][timeframe][-18:]
            for bar in history["candles_by_tf"][timeframe][:-1]:
                bar["closed"] = True
            history["candles_by_tf"][timeframe][-1]["closed"] = False
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "INSUFFICIENT_CONTEXT")

    def test_large_missing_intervals_make_timeframe_ineligible(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["1h"]
        split = len(bars) // 2
        for bar in bars[:split]:
            bar["open_time_ms"] -= 10 * DURATIONS["1h"]
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["timeframes"]["1h"]["status"], "PARTIAL")
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])

    def test_one_missing_candle_blocks_timeframe_consensus(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["1h"]
        bars[60:] = bars[61:]
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["timeframes"]["1h"]["status"], "PARTIAL")
        self.assertEqual(result["timeframes"]["1h"]["data_quality"]["gap_count"], 1)
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])

    def test_forming_candle_must_immediately_follow_latest_closed_candle(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["15m"]
        bars[-1]["open_time_ms"] += DURATIONS["15m"]
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["timeframes"]["15m"]["status"], "INVALID_SEQUENCE")
        self.assertNotIn("15m", result["summary"]["eligible_timeframes"])

    def test_stale_timeframe_is_not_used_for_consensus(self) -> None:
        history = make_history()
        history["candles_by_tf"]["1h"] = [
            {**bar, "open_time_ms": bar["open_time_ms"] - 10 * DURATIONS["1h"]}
            for bar in history["candles_by_tf"]["1h"]
        ]
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["timeframes"]["1h"]["status"], "STALE")
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])

    def test_timeframe_needs_confirmed_swing_evidence_before_eligibility(self) -> None:
        history = make_history()
        for bars in history["candles_by_tf"].values():
            for index, bar in enumerate(bars[:-1]):
                price = 50_000.0 + index * 4.0
                bar.update({
                    "open": price + 1.0,
                    "high": price + 3.0,
                    "low": price,
                    "close": price + 2.0,
                    "closed": True,
                })
            bars[-1]["closed"] = False

        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "INSUFFICIENT_CONTEXT")
        self.assertEqual(result["summary"]["eligible_timeframes"], [])
        for report in result["timeframes"].values():
            self.assertEqual(report["data_quality"]["status"], "READY")
            self.assertEqual(report["structure"]["status"], "PARTIAL")
            self.assertEqual(report["status"], "PARTIAL")
            self.assertEqual(
                report["readiness"]["confirmed_swing_structure"], "PARTIAL"
            )

    def test_invalid_ohlc_fails_closed(self) -> None:
        history = make_history()
        history["candles_by_tf"]["15m"][10]["high"] = 1.0
        result = analyze_mt5_native_price_action(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["timeframes"]["15m"]["status"], "INVALID")
        self.assertEqual(result["timeframes"]["15m"]["direction"], "MIXED_OR_UNKNOWN")

    def test_candle_patterns_are_reported_with_timestamps_and_context(self) -> None:
        history = make_history()
        result = analyze_mt5_native_price_action(history)
        report = result["timeframes"]["1m"]["candle_analysis"]
        self.assertIn("latest_closed_candle", report)
        self.assertIn("latest_candle_patterns", report)
        for pattern in report["recent_patterns"]:
            self.assertIn("start_time_utc_ms", pattern)
            self.assertIn("end_time_utc_ms", pattern)
            self.assertEqual(pattern["interpretation"], "RULE_MATCH_NOT_PROBABILITY")

    def test_engine2_does_not_calculate_or_depend_on_technical_indicators(self) -> None:
        import inspect
        from mirsad.engines import mt5_price_action

        signature = inspect.signature(mt5_price_action.analyze_mt5_native_price_action)
        self.assertEqual(list(signature.parameters), ["candle_history"])
        result = analyze_mt5_native_price_action(make_history())
        self.assertFalse(result["safety"]["calculates_indicators"])
        for frame in result["timeframes"].values():
            self.assertNotIn("indicators", frame)

    def test_missing_candle_source_blocks_analysis(self) -> None:
        result = analyze_mt5_native_price_action({"status": "OFFLINE"})
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["direction"], "UNKNOWN")
        self.assertFalse(result["decision_eligible"])


if __name__ == "__main__":
    unittest.main()
