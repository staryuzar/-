from __future__ import annotations

import math
import unittest

from mirsad.engines.indicators import IndicatorsEngine, _atr, _rsi, _timeframe_trend


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

    def test_engine1_market_quote_without_engine2_candles_is_not_ready(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
