from __future__ import annotations

import unittest

from mirsad.engines.mt5_trend_analysis import analyze_mt5_native_trend


DURATIONS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def make_history(
    *,
    count: int = 121,
    directions: dict[str, str] | None = None,
    as_of_ms: int = 1_800_000_000_000,
    forming_spike: bool = False,
) -> dict:
    directions = directions or {timeframe: "up" for timeframe in DURATIONS}
    frames = {}
    for timeframe, duration in DURATIONS.items():
        direction = directions.get(timeframe, "up")
        bars = []
        first_open = as_of_ms - int((count - 1 + 0.25) * duration)
        for index in range(count):
            if direction == "up":
                close = 50_000.0 + index * 20.0
                open_price = close - 4.0
            elif direction == "down":
                close = 100_000.0 - index * 20.0
                open_price = close + 4.0
            else:
                close = 75_000.0
                open_price = close
            high = max(open_price, close) + 5.0
            low = min(open_price, close) - 5.0
            volume = 100.0 + (index % 7)
            if forming_spike and index == count - 1:
                close = 150_000.0
                open_price = 20_000.0
                high = 200_000.0
                low = 1_000.0
                volume = 1_000_000.0
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


class MT5NativeTrendAnalysisTests(unittest.TestCase):
    def test_all_up_frames_produce_bullish_multi_timeframe_direction(self) -> None:
        result = analyze_mt5_native_trend(make_history())
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BULLISH")
        self.assertGreater(result["trend_score"], 0.30)
        self.assertEqual(set(result["summary"]["eligible_timeframes"]), set(DURATIONS))
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BULLISH")
        self.assertFalse(result["decision_eligible"])
        self.assertFalse(result["safety"]["creates_orders"])

    def test_all_down_frames_produce_bearish_multi_timeframe_direction(self) -> None:
        directions = {timeframe: "down" for timeframe in DURATIONS}
        result = analyze_mt5_native_trend(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BEARISH")
        self.assertLess(result["trend_score"], -0.30)
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BEARISH")

    def test_flat_market_is_classified_as_neutral_and_ranging(self) -> None:
        directions = {timeframe: "flat" for timeframe in DURATIONS}
        result = analyze_mt5_native_trend(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "NEUTRAL")
        self.assertEqual(result["summary"]["market_regime"], "RANGING")
        self.assertLess(result["summary"]["average_adx14"], 18.0)

    def test_forming_bar_never_changes_direction_or_indicators(self) -> None:
        base = analyze_mt5_native_trend(make_history())
        spike = analyze_mt5_native_trend(make_history(forming_spike=True))
        self.assertEqual(base["direction"], spike["direction"])
        self.assertEqual(base["trend_score"], spike["trend_score"])
        for timeframe in DURATIONS:
            self.assertEqual(
                base["timeframes"][timeframe]["indicators"],
                spike["timeframes"][timeframe]["indicators"],
            )
            self.assertEqual(
                base["timeframes"][timeframe]["structure"],
                spike["timeframes"][timeframe]["structure"],
            )

    def test_short_term_and_higher_timeframe_directions_are_reported_separately(self) -> None:
        directions = {
            "1m": "down", "5m": "down", "15m": "down",
            "1h": "up", "4h": "up", "1d": "up",
        }
        result = analyze_mt5_native_trend(make_history(directions=directions))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["summary"]["short_term_direction"], "BEARISH")
        self.assertEqual(result["summary"]["higher_timeframe_direction"], "BULLISH")
        self.assertIn(result["summary"]["timeframe_alignment"], {
            "MIXED_TIMEFRAME_DIRECTIONS", "PARTIAL_OR_NEUTRAL_ALIGNMENT"
        })

    def test_insufficient_high_timeframe_history_does_not_claim_full_direction(self) -> None:
        history = make_history()
        # Both eligible slow-context alternatives are deliberately short;
        # 15m and 1h alone must not satisfy the higher-timeframe context gate.
        for timeframe in ("4h", "1d"):
            history["candles_by_tf"][timeframe] = history["candles_by_tf"][timeframe][-30:]
            for bar in history["candles_by_tf"][timeframe][:-1]:
                bar["closed"] = True
            history["candles_by_tf"][timeframe][-1]["closed"] = False
        result = analyze_mt5_native_trend(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "INSUFFICIENT_CONTEXT")
        self.assertIn("4h", result["timeframe_errors"])
        self.assertIn("1d", result["timeframe_errors"])

    def test_stale_timeframe_is_excluded_from_consensus(self) -> None:
        history = make_history()
        history["candles_by_tf"]["1h"] = [
            {**bar, "open_time_ms": bar["open_time_ms"] - 10 * DURATIONS["1h"]}
            for bar in history["candles_by_tf"]["1h"]
        ]
        result = analyze_mt5_native_trend(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])
        self.assertIn("1h", result["timeframe_errors"])

    def test_large_missing_interval_fraction_blocks_a_timeframe(self) -> None:
        history = make_history()
        bars = history["candles_by_tf"]["1h"]
        duration = DURATIONS["1h"]
        split = len(bars) // 2
        for bar in bars[:split]:
            bar["open_time_ms"] -= 10 * duration
        result = analyze_mt5_native_trend(history)
        self.assertEqual(result["timeframes"]["1h"]["status"], "PARTIAL")
        self.assertGreater(
            result["timeframes"]["1h"]["data_quality"]["gap_fraction"],
            0.03,
        )
        self.assertNotIn("1h", result["summary"]["eligible_timeframes"])

    def test_invalid_ohlc_fails_closed(self) -> None:
        history = make_history()
        history["candles_by_tf"]["15m"][10]["high"] = 1.0
        result = analyze_mt5_native_trend(history)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["timeframes"]["15m"]["status"], "INVALID")
        self.assertEqual(result["timeframes"]["15m"]["direction"], "UNKNOWN")

    def test_missing_candle_feed_blocks_analysis(self) -> None:
        result = analyze_mt5_native_trend({"status": "OFFLINE"})
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["direction"], "UNKNOWN")
        self.assertFalse(result["decision_eligible"])

    def test_native_copybuffer_comparison_is_diagnostic(self) -> None:
        history = make_history()
        first = analyze_mt5_native_trend(history)
        native_frames = {}
        for timeframe, report in first["timeframes"].items():
            indicators = report.get("indicators", {})
            last_open = history["candles_by_tf"][timeframe][-2]["open_time_ms"]
            values = {}
            for native_name, local_name in (
                ("ema20", "ema20"), ("ema50", "ema50"),
                ("rsi14", "rsi14"), ("atr14", "atr14"),
            ):
                values[native_name] = {
                    "status": "READY",
                    "closed": indicators.get(local_name),
                    "current": indicators.get(local_name),
                }
            native_frames[timeframe] = {
                "status": "READY",
                "closed_bar_time_utc_ms": last_open,
                "values": values,
            }
        native = {"status": "READY", "timeframes": native_frames}
        result = analyze_mt5_native_trend(history, native_indicators=native)
        self.assertEqual(result["native_indicator_parity"]["status"], "COMPARED")
        self.assertEqual(set(result["native_indicator_parity"]["compared_timeframes"]), set(DURATIONS))
        self.assertFalse(result["decision_eligible"])


if __name__ == "__main__":
    unittest.main()
