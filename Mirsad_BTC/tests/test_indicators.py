from __future__ import annotations

import math
import unittest

from mirsad.engines.indicators import (
    INDICATOR_SIGNAL_GROUP_WEIGHTS, IndicatorsEngine, _adx, _atr,
    _ema_series, _macd, _rsi, _stochastic, _timeframe_trend,
)


def make_chart_candles(count: int = 90, direction: str = "up", include_forming: bool = False) -> dict:
    frames = {}
    for timeframe in ("1m", "5m", "15m", "1h", "4h", "1d"):
        candles = []
        for index in range(count):
            close = 100.0 + (index * 0.5 if direction == "up" else -index * 0.5 if direction == "down" else 0.0)
            candles.append({
                "open_time_ms": index * 60_000,
                "open": close - 0.1, "high": close + 1.0,
                "low": close - 1.0, "close": close,
                "volume": 1.0, "closed": True,
            })
        if include_forming:
            candles.append({
                "open_time_ms": count * 60_000, "open": 100.0,
                "high": 10_000.0, "low": 1.0, "close": 9_000.0,
                "volume": 1.0, "closed": False,
            })
        frames[timeframe] = candles
    return {
        "status": "READY",
        "source": "MT5_CHART_OBSERVER",
        "captured_at_ms": 1_700_000_000_000,
        "candles_by_tf": frames,
    }


class IndicatorsEngineTests(unittest.TestCase):
    def test_returns_all_required_indicators_from_engine2_completed_ohlc(self) -> None:
        result = IndicatorsEngine().analyze(make_chart_candles())
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["source"], "engine_2_chart_candles")
        self.assertIsNotNone(result["values"]["ema20_1m"])
        self.assertIsNotNone(result["values"]["ema50_1m"])
        self.assertIsNotNone(result["values"]["rsi14_1m"])
        self.assertGreater(result["values"]["atr14_5m"], 0)
        self.assertEqual(result["timeframes"]["15m"]["status"], "READY")
        self.assertEqual(result["last_closed_candle_time_ms"], 89 * 60_000)

    def test_forming_candle_is_excluded_from_indicator_history(self) -> None:
        base = IndicatorsEngine().analyze(make_chart_candles())
        with_forming = IndicatorsEngine().analyze(make_chart_candles(include_forming=True))
        self.assertEqual(base["values"], with_forming["values"])
        self.assertEqual(base["timeframes"], with_forming["timeframes"])

    def test_insufficient_closed_history_blocks_indicator_engine(self) -> None:
        result = IndicatorsEngine().analyze(make_chart_candles(count=49))
        self.assertEqual(result["status"], "NOT_READY")
        self.assertIn("1m", result["missing_timeframes"])
        self.assertIn("5m", result["missing_timeframes"])

    def test_flat_series_has_neutral_rsi(self) -> None:
        self.assertEqual(_rsi([100.0] * 30), 50.0)

    def test_monotonic_rise_has_maximum_rsi(self) -> None:
        self.assertEqual(_rsi([float(i + 1) for i in range(30)]), 100.0)

    def test_timeframe_trend_uses_only_closed_candles(self) -> None:
        candles = make_chart_candles(include_forming=True)["candles_by_tf"]["1m"]
        result = _timeframe_trend(candles)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["closed_candles"], 90)

    def test_atr_includes_gap_from_previous_close(self) -> None:
        candles = []
        for index in range(16):
            close = 100.0 if index < 15 else 110.0
            candles.append({"high": close + 1, "low": close - 1, "close": close})
        value = _atr(candles, period=14)
        self.assertIsNotNone(value)
        self.assertGreater(value, 2.0)

    def test_mt5_atr_uses_simple_moving_average_of_true_range(self) -> None:
        candles = [
            {"high": 101.0, "low": 99.0, "close": 100.0},
            {"high": 103.0, "low": 101.0, "close": 102.0},
            {"high": 101.0, "low": 99.0, "close": 100.0},
            {"high": 105.0, "low": 103.0, "close": 104.0},
            {"high": 104.0, "low": 102.0, "close": 103.0},
        ]
        self.assertAlmostEqual(_atr(candles, period=3), (3.0 + 5.0 + 2.0) / 3.0)

    def test_mt5_macd_signal_is_simple_average_of_macd_line(self) -> None:
        closes = [100.0 + index * 0.7 + (index % 4) * 0.2 for index in range(80)]
        main, signal, osma = _macd(closes, fast=12, slow=26, signal=9)
        fast = _ema_series(closes, 12)
        slow = _ema_series(closes, 26)
        macd_values = [
            fast_value - slow_value
            for fast_value, slow_value in zip(fast, slow)
            if fast_value is not None and slow_value is not None
        ]
        expected_signal = sum(macd_values[-9:]) / 9
        self.assertAlmostEqual(signal, expected_signal)
        self.assertAlmostEqual(osma, main - signal)

    def test_stochastic_matches_mt5_slowing_and_signal_smoothing(self) -> None:
        closes = [10.0, 90.0, 30.0, 70.0, 50.0, 80.0, 20.0, 60.0, 40.0, 100.0, 0.0]
        candles = [
            {"high": 100.0, "low": 0.0, "close": close}
            for close in closes
        ]
        slow_k, slow_d = _stochastic(candles, k_period=5, d_period=3, slowing=3)
        self.assertAlmostEqual(slow_k, 46.6666666667, places=8)
        self.assertAlmostEqual(slow_d, 51.1111111111, places=8)

    def test_stochastic_slows_by_summing_range_weighted_components(self) -> None:
        candles = [
            {"high": 10.0, "low": 0.0, "close": 5.0},
            {"high": 12.0, "low": 1.0, "close": 9.0},
            {"high": 11.0, "low": 2.0, "close": 8.0},
            {"high": 15.0, "low": 3.0, "close": 10.0},
            {"high": 14.0, "low": 4.0, "close": 13.0},
            {"high": 16.0, "low": 2.0, "close": 12.0},
            {"high": 18.0, "low": 5.0, "close": 16.0},
            {"high": 17.0, "low": 6.0, "close": 8.0},
            {"high": 20.0, "low": 7.0, "close": 19.0},
        ]
        raw_numerators = []
        raw_ranges = []
        for end in range(5, len(candles) + 1):
            window = candles[end - 5:end]
            lowest = min(row["low"] for row in window)
            highest = max(row["high"] for row in window)
            raw_numerators.append(candles[end - 1]["close"] - lowest)
            raw_ranges.append(highest - lowest)
        slow_k_values = [
            100.0 * sum(raw_numerators[i - 2:i + 1]) / sum(raw_ranges[i - 2:i + 1])
            for i in range(2, len(raw_numerators))
        ]
        expected_k = slow_k_values[-1]
        expected_d = sum(slow_k_values[-3:]) / 3.0
        actual_k, actual_d = _stochastic(candles, k_period=5, d_period=3, slowing=3)
        self.assertAlmostEqual(actual_k, expected_k, places=8)
        self.assertAlmostEqual(actual_d, expected_d, places=8)

    def test_adx_uses_initial_dx_and_wilder_smoothing_window(self) -> None:
        candles = []
        for index in range(28):
            close = 100.0 + index
            candles.append({
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
            })
        adx, plus_di, minus_di = _adx(candles, period=14)
        self.assertAlmostEqual(adx, 100.0, places=8)
        self.assertGreater(plus_di, 0.0)
        self.assertEqual(minus_di, 0.0)
        self.assertEqual(_adx(candles[:-1], period=14), (None, None, None))

    def test_full_twenty_indicator_catalog_is_calculated_for_each_timeframe(self) -> None:
        result = IndicatorsEngine().analyze(make_chart_candles(count=90))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["indicator_catalog"]), 20)
        self.assertEqual(set(result["indicators_by_timeframe"]), {"1m", "5m", "15m", "1h", "4h", "1d"})
        for timeframe, indicators in result["indicators_by_timeframe"].items():
            self.assertEqual(len(indicators), 20, timeframe)
            for name, value in indicators.items():
                self.assertIsNotNone(value, f"{timeframe}.{name}")
                self.assertTrue(math.isfinite(value), f"{timeframe}.{name}")

    def test_forming_bar_is_excluded_from_every_technical_indicator(self) -> None:
        base = IndicatorsEngine().analyze(make_chart_candles(count=90))
        with_forming = IndicatorsEngine().analyze(make_chart_candles(count=90, include_forming=True))
        self.assertEqual(base["indicators_by_timeframe"], with_forming["indicators_by_timeframe"])

    def test_higher_timeframe_short_history_is_reported_without_faking_values(self) -> None:
        candles = make_chart_candles(count=90)
        candles["candles_by_tf"]["1d"] = candles["candles_by_tf"]["1d"][:24]
        result = IndicatorsEngine().analyze(candles)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["timeframes"]["1d"]["status"], "INSUFFICIENT")
        self.assertIsNone(result["indicators_by_timeframe"]["1d"]["ema50"])

    def test_engine5_broker_quote_without_engine2_candles_is_not_ready(self) -> None:
        result = IndicatorsEngine().analyze({
            "status": "LIVE",
            "source": "MT5_TERMINAL",
            "price": 90_000,
            "market_context": {"microstructure": {"status": "READY"}},
        })
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["values"], {})

    def test_missing_engine2_candle_source_returns_not_ready(self) -> None:
        result = IndicatorsEngine().analyze({"status": "OFFLINE", "candles_by_tf": {}})
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["values"], {})


    def test_composite_signal_uses_five_distinct_indicator_families(self) -> None:
        result = IndicatorsEngine().analyze(make_chart_candles(direction="up"))
        self.assertEqual(result["status"], "READY")
        self.assertAlmostEqual(sum(INDICATOR_SIGNAL_GROUP_WEIGHTS.values()), 1.0)
        self.assertGreater(result["signal_score"], 0.25)
        self.assertAlmostEqual(result["signal_quality"], 1.0)
        self.assertIn("tick_volume", result["signal_volume_basis"])
        self.assertIn("not consolidated executed-trade volume", result["signal_volume_basis"])
        groups = result["signal_components_by_timeframe"]["1m"]["groups"]
        self.assertEqual(set(groups), {
            "trend", "momentum", "directional_strength", "oscillator", "volume_flow",
        })
        self.assertTrue(all(group["effective_weight"] > 0 for group in groups.values()))

    def test_composite_signal_is_bearish_for_a_sustained_falling_series(self) -> None:
        result = IndicatorsEngine().analyze(make_chart_candles(direction="down"))
        self.assertEqual(result["status"], "READY")
        self.assertLess(result["signal_score"], -0.25)

    def test_positive_atr_does_not_create_a_directional_signal_in_a_flat_market(self) -> None:
        result = IndicatorsEngine().analyze(make_chart_candles(direction="flat"))
        self.assertEqual(result["status"], "READY")
        self.assertGreater(result["values"]["atr14_5m"], 0)
        self.assertAlmostEqual(result["signal_score"], 0.0, places=8)

    def test_missing_tick_volume_does_not_fake_volume_flow_confirmation(self) -> None:
        candles = make_chart_candles(direction="up")
        for timeframe in candles["candles_by_tf"]:
            for bar in candles["candles_by_tf"][timeframe]:
                bar["volume"] = 0.0
        result = IndicatorsEngine().analyze(candles)
        self.assertEqual(result["status"], "READY")
        flow = result["signal_components_by_timeframe"]["1m"]["groups"]["volume_flow"]
        self.assertEqual(flow["coverage"], 0.0)
        self.assertIsNone(result["indicators_by_timeframe"]["1m"]["mfi14"])
        self.assertIsNone(result["indicators_by_timeframe"]["1m"]["obv"])

    def test_insufficient_higher_timeframe_is_not_a_directional_vote(self) -> None:
        candles = make_chart_candles(count=90)
        candles["candles_by_tf"]["1d"] = candles["candles_by_tf"]["1d"][:24]
        result = IndicatorsEngine().analyze(candles)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["timeframes"]["1d"]["status"], "INSUFFICIENT")
        self.assertEqual(result["signal_components_by_timeframe"]["1d"]["status"], "NOT_READY")
        self.assertIsNone(result["signal_components_by_timeframe"]["1d"]["score"])


if __name__ == "__main__":
    unittest.main()
