from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validate_mt5_direct_feed import validate
from mirsad.engines.mt5_native_indicators import REQUIRED_INDICATORS, TIMEFRAMES


def ready_market() -> dict:
    return {
        "status": "LIVE",
        "symbol": "BTCUSDT",
        "feed_health": {
            "broker_symbol": "BTC",
            "account_server": "Headway-Demo",
            "snapshot_age_seconds": 1.0,
        },
        "market_context": {
            "microstructure": {
                "status": "READY",
                "tick_count": 20,
                "quote_tick_count": 16,
                "reported_last_price_tick_count": 4,
                "reported_volume_update_count": 4,
            },
            "order_book": {"status": "NOT_AVAILABLE", "level_count": 0},
        },
    }


def ready_candles() -> dict:
    frames = {}
    for timeframe_index, timeframe in enumerate(TIMEFRAMES):
        bars = []
        for index in range(90):
            close = 90_000.0 + timeframe_index * 100.0 + index * 10.0
            bars.append({
                "open_time_ms": 1_798_000_000_000 - (89 - index) * 60_000,
                "open": close - 2.0,
                "high": close + 5.0,
                "low": close - 5.0,
                "close": close,
                "volume": 10.0,
                "closed": True,
            })
        frames[timeframe] = bars
    return {
        "status": "READY",
        "source": "MT5_CHART_OBSERVER",
        "captured_at_ms": 1_798_000_000_000,
        "broker_symbol": "BTC",
        "symbol": "BTCUSDT",
        "account_server": "Headway-Demo",
        "timeframes": {name: 120 for name in TIMEFRAMES},
        "closed_candles": {name: 119 for name in TIMEFRAMES},
        "candles_by_tf": frames,
    }


def ready_indicators() -> dict:
    frames = {}
    for timeframe in TIMEFRAMES:
        values = {
            name: {"status": "READY", "closed": 90_000.0, "current": 90_001.0}
            for name in REQUIRED_INDICATORS
        }
        frames[timeframe] = {"status": "READY", "values": values}
    return {
        "status": "READY",
        "source": "MT5_COPYBUFFER",
        "broker_symbol": "BTC",
        "account_server": "Headway-Demo",
        "ready_timeframe_count": 6,
        "timeframes": frames,
    }


class DirectFeedValidatorTests(unittest.TestCase):
    def test_direct_feed_passes_without_any_image_capture_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "scripts.validate_mt5_direct_feed.MT5MarketDataEngine.collect",
                    return_value=ready_market(),
                ),
                patch(
                    "scripts.validate_mt5_direct_feed.MT5ChartCandleHistory.collect",
                    return_value=ready_candles(),
                ),
                patch(
                    "scripts.validate_mt5_direct_feed.MT5NativeIndicatorHistory.collect",
                    return_value=ready_indicators(),
                ),
            ):
                result = validate(
                    Path(directory),
                    market_symbol="BTCUSDT",
                    broker_symbol="BTC",
                    expected_server="Headway-Demo",
                )

        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["engine2"]["status"], "READY")
        self.assertEqual(result["engine3"]["status"], "READY")
        self.assertFalse(result["image_capture_enabled"])
        self.assertFalse(result["decision_eligible"])
        self.assertEqual(result["candles"]["timeframes"]["1m"], 120)
        self.assertEqual(result["native_indicators"]["ready_timeframe_count"], 6)
        self.assertEqual(result["engine3"]["calculated_status"], "READY")
        self.assertIsNotNone(result["engine3"]["signal_score"])
        self.assertGreaterEqual(result["engine3"]["signal_quality"], 0.60)
        self.assertEqual(set(result["engine3"]["signal_components_by_timeframe"]), set(TIMEFRAMES))
        self.assertEqual(result["engine3"]["status"], "READY")
        self.assertFalse(result["safety"]["trading_api_used"])

    def test_direct_feed_rejects_any_timeframe_below_engine2_closed_bar_minimum(self) -> None:
        candles = ready_candles()
        candles["closed_candles"]["1d"] = 23
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "scripts.validate_mt5_direct_feed.MT5MarketDataEngine.collect",
                    return_value=ready_market(),
                ),
                patch(
                    "scripts.validate_mt5_direct_feed.MT5ChartCandleHistory.collect",
                    return_value=candles,
                ),
                patch(
                    "scripts.validate_mt5_direct_feed.MT5NativeIndicatorHistory.collect",
                    return_value=ready_indicators(),
                ),
            ):
                result = validate(
                    Path(directory),
                    market_symbol="BTCUSDT",
                    broker_symbol="BTC",
                    expected_server="Headway-Demo",
                )
        self.assertEqual(result["engine2"]["status"], "FAILED")
        self.assertTrue(any("1d has 23 closed bars" in item for item in result["engine2"]["failures"]))

    def test_optional_higher_timeframe_indicator_gaps_do_not_block_engine3(self) -> None:
        indicators = ready_indicators()
        for timeframe in ("1h", "4h", "1d"):
            for name in REQUIRED_INDICATORS:
                indicators["timeframes"][timeframe]["values"][name] = {
                    "status": "UNAVAILABLE", "closed": None, "current": None
                }
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("scripts.validate_mt5_direct_feed.MT5MarketDataEngine.collect", return_value=ready_market()),
                patch("scripts.validate_mt5_direct_feed.MT5ChartCandleHistory.collect", return_value=ready_candles()),
                patch("scripts.validate_mt5_direct_feed.MT5NativeIndicatorHistory.collect", return_value=indicators),
            ):
                result = validate(Path(directory), market_symbol="BTCUSDT",
                    broker_symbol="BTC", expected_server="Headway-Demo")
        self.assertEqual(result["engine3"]["status"], "READY")
        self.assertEqual(result["native_indicators"]["optional_timeframe_missing_core_values"]["1h"], list(REQUIRED_INDICATORS))

    def test_missing_core_indicator_on_required_timeframe_keeps_engine3_partial(self) -> None:
        indicators = ready_indicators()
        indicators["timeframes"]["5m"]["values"]["rsi14"]["status"] = "WARMING_UP"
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("scripts.validate_mt5_direct_feed.MT5MarketDataEngine.collect", return_value=ready_market()),
                patch("scripts.validate_mt5_direct_feed.MT5ChartCandleHistory.collect", return_value=ready_candles()),
                patch("scripts.validate_mt5_direct_feed.MT5NativeIndicatorHistory.collect", return_value=indicators),
            ):
                result = validate(Path(directory), market_symbol="BTCUSDT",
                    broker_symbol="BTC", expected_server="Headway-Demo")
        self.assertEqual(result["engine2"]["status"], "READY")
        self.assertEqual(result["engine3"]["status"], "PARTIAL")
        self.assertTrue(any("5m missing core values rsi14" in item for item in result["engine3"]["warnings"]))

    def test_engine2_feed_remains_ready_when_native_indicators_are_partial(self) -> None:
        partial = ready_indicators()
        partial["status"] = "PARTIAL"
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch(
                    "scripts.validate_mt5_direct_feed.MT5MarketDataEngine.collect",
                    return_value=ready_market(),
                ),
                patch(
                    "scripts.validate_mt5_direct_feed.MT5ChartCandleHistory.collect",
                    return_value=ready_candles(),
                ),
                patch(
                    "scripts.validate_mt5_direct_feed.MT5NativeIndicatorHistory.collect",
                    return_value=partial,
                ),
            ):
                result = validate(
                    Path(directory),
                    market_symbol="BTCUSDT",
                    broker_symbol="BTC",
                    expected_server="Headway-Demo",
                )
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["engine2"]["status"], "READY")
        self.assertEqual(result["engine3"]["status"], "PARTIAL")
        self.assertFalse(result["engine2"]["failures"])
        self.assertTrue(any("native indicator feed" in item for item in result["engine3"]["warnings"]))


    def test_direct_feed_is_partial_when_native_buffers_ready_but_composite_signal_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch("scripts.validate_mt5_direct_feed.MT5MarketDataEngine.collect", return_value=ready_market()),
                patch("scripts.validate_mt5_direct_feed.MT5ChartCandleHistory.collect", return_value=ready_candles()),
                patch("scripts.validate_mt5_direct_feed.MT5NativeIndicatorHistory.collect", return_value=ready_indicators()),
                patch("scripts.validate_mt5_direct_feed.IndicatorsEngine.analyze", return_value={
                    "status": "NOT_READY", "reason": "test quality gate",
                    "signal_score": None, "signal_quality": 0.0,
                }),
            ):
                result = validate(Path(directory), market_symbol="BTCUSDT",
                    broker_symbol="BTC", expected_server="Headway-Demo")
        self.assertEqual(result["engine2"]["status"], "READY")
        self.assertEqual(result["engine3"]["native_status"], "READY")
        self.assertEqual(result["engine3"]["calculated_status"], "NOT_READY")
        self.assertEqual(result["engine3"]["status"], "PARTIAL")
        self.assertTrue(any("calculated Engine 3 signal" in item for item in result["engine3"]["warnings"]))


if __name__ == "__main__":
    unittest.main()
