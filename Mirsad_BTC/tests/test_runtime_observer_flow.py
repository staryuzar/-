from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import mirsad.runtime as runtime


def make_engine2_multiframe_history(as_of_ms: int) -> dict:
    durations = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
    }
    frames = {}
    for timeframe, duration in durations.items():
        candles = []
        for index in range(90):
            wave = (0, 20, 40, 20, 0, -20, -40, -20)[index % 8]
            close = 90_000.0 + index * 5.0 + wave
            candles.append({
                "open_time_ms": as_of_ms - (89 - index) * duration,
                "open": close - 2.0, "high": close + 5.0,
                "low": close - 5.0, "close": close,
                "volume": 10.0, "closed": index < 89,
            })
        frames[timeframe] = candles
    return {
        "engine": "engine_2_chart_candles",
        "source": "MT5_CHART_OBSERVER",
        "status": "READY",
        "captured_at_ms": as_of_ms,
        "candles_by_tf": frames,
        "timeframes": {key: len(rows) for key, rows in frames.items()},
    }

class RuntimeObserverFlowTests(unittest.TestCase):
    def test_engine2_multi_timeframe_structure_uses_only_native_engine2_history(self) -> None:
        now_ms = int(time.time() * 1000)
        history = make_engine2_multiframe_history(now_ms)
        result = runtime._analyze_engine2_multi_timeframe_structure(history)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["source"], "MT5_CHART_OBSERVER")
        self.assertEqual(result["ownership"], "engine_2_native_candles_only")
        self.assertEqual(result["as_of_ms"], now_ms)
        self.assertEqual(set(result["available_timeframes"]), set(history["candles_by_tf"]))
        self.assertGreaterEqual(len(result["eligible_timeframes"]), 2)
        for frame in result["timeframe_reports"].values():
            self.assertLessEqual(frame["last_close_time_ms"], now_ms)

    def test_engine2_multi_timeframe_structure_refuses_unvalidated_history(self) -> None:
        result = runtime._analyze_engine2_multi_timeframe_structure({"status": "STALE"})
        self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(result["source"], "MT5_CHART_OBSERVER")
        self.assertEqual(result["available_timeframes"], [])
    def test_collect_once_feeds_eligible_observer_chart_into_engine4_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "observer.png"
            Image.new("RGB", (640, 360), (15, 20, 30)).save(image_path, format="PNG")
            image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()

            bars = []
            for index in range(30):
                base = 90_000.0 + index
                bars.append({
                    "time_server_ms": 1_700_000_000_000 + index * 60_000,
                    "open": base, "high": base + 20, "low": base - 20,
                    "close": base + 5, "is_closed": index < 29,
                })

            observer = {
                "status": "READY_FOR_ENGINE_2_VALIDATION",
                "capture_id": "runtime-flow-capture",
                "image_path": str(image_path),
                "image_sha256": image_hash,
                "age_seconds": 1.0,
                "capture_data_skew_ms": 0,
                "newest_bar_after_server_clock": False,
                "visual_calibration_eligible": True,
                "rates_status": "AVAILABLE",
                "rates_error_code": 0,
                "bar_count": len(bars),
                "bars": bars,
                "account": {"server": "Headway-Demo"},
                "chart": {
                    "symbol": "BTC",
                    "timeframe": "1m",
                    "source_dimensions_usable": True,
                    "source_width_px": 1400,
                    "source_main_window_height_px": 800,
                    "chart_autoscroll": True,
                    "windows_total": 1,
                    "visible_bars": 30,
                    "first_visible_bar_shift": 29,
                    "price_min": 89_000.0,
                    "price_max": 91_000.0,
                    "price_scale_type": "linear",
                },
            }

            now_ms = int(time.time() * 1000)
            market = {
                "symbol": "BTCUSDT",
                "price": 90_100.0,
                "captured_at_ms": now_ms,
                "status": "LIVE",
                "source": "MT5_TERMINAL",
                "venue_count": 1,
                "primary_venue": "MT5 Broker",
                "feed_health": {"terminal_connected": True, "quote_fresh": True},
                "market_context": {"microstructure": {"status": "NOT_AVAILABLE"}},
                "venues": {
                    "MT5 Broker": {"status": "LIVE", "price": 90_100.0},
                },
            }
            bridge_snapshot = {
                "engine": "engine_5_communication_bridge",
                "status": "CONNECTED",
                "terminal_connected": True,
                "execution_enabled": False,
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "account": {"server": "Headway-Demo"},
            }
            analysis = {
                "status": "READY",
                "decision_eligible": True,
                "calibration": {
                    "source": "reference_multi_candle_ohlc",
                    "price_scale_valid": True,
                },
                "reference_multi_calibration": {"status": "READY"},
                "reference_axis_validation": {"status": "READY"},
                "reference_ohlc_override_applied": True,
                "visual_bias": "NEUTRAL",
                "analysis_score": 0.0,
                "analysis_confidence": 0.86,
                "quality_gates": {"native_reference_candle_verified": True},
                "detected_bar_count": 30,
                "confirmed_bar_count": 29,
            }

            market_engine = Mock()
            market_engine.collect.return_value = market
            bridge_engine = Mock()
            bridge_engine.inspect.return_value = bridge_snapshot
            bridge_engine.publish_decision = Mock()
            candle_history = {
                "engine": "engine_2_chart_candles",
                "source": "MT5_CHART_OBSERVER",
                "status": "READY",
                "candles_by_tf": {"1m": bars},
                "timeframes": {"1m": len(bars)},
                "closed_candles": {"1m": len(bars) - 1},
            }
            candle_history_engine = Mock()
            candle_history_engine.collect.return_value = candle_history
            indicators_engine = Mock()
            indicators_engine.analyze.return_value = {"status": "READY"}
            decision_engine = Mock()
            decision_engine.analyze.return_value = {
                "status": "READY",
                "action": "WAIT",
                "command_ready": False,
            }

            intelligence_engine = Mock()
            intelligence_engine.collect.return_value = {
                "engine": "engine_1_market_intelligence", "status": "READY",
                "direction": "NEUTRAL", "directional_score": 0.0,
                "confidence": 0.8, "evidence_coverage": 0.8,
                "economic_calendar": {"status": "EMPTY", "high_impact_window_active": False, "events": []},
            }

            with (
                patch.object(runtime, "MT5MarketDataEngine", return_value=market_engine),
                patch.object(runtime, "MarketIntelligenceEngine", return_value=intelligence_engine),
                patch.object(runtime, "MT5ChartCandleHistory", return_value=candle_history_engine),
                patch.object(runtime, "MT5BridgeEngine", return_value=bridge_engine),
                patch.object(runtime, "IndicatorsEngine", return_value=indicators_engine),
                patch.object(runtime, "DecisionEngine", return_value=decision_engine),
                patch.object(runtime, "_inspect_mt5_chart_observer", return_value=observer),
                patch.object(runtime, "analyze_chart_image", return_value=analysis) as visual_analyzer,
                patch.object(runtime, "save_market_snapshot"),
                patch.object(runtime, "save_market_intelligence_snapshot"),
                patch.object(runtime, "write_json_atomic"),
                patch.object(runtime, "ENABLE_ORDER_PUBLISH", False),
            ):
                report = runtime.collect_once()

            self.assertEqual(visual_analyzer.call_count, 1)
            self.assertEqual(report["chart"]["source"], "MT5_OBSERVER")
            self.assertTrue(report["chart"]["decision_eligible"])
            self.assertEqual(report["chart"]["observer_capture"]["capture_id"], "runtime-flow-capture")
            decision_engine.analyze.assert_called_once()
            passed_chart = decision_engine.analyze.call_args.args[1]
            self.assertEqual(passed_chart["source"], "MT5_OBSERVER")
            self.assertTrue(passed_chart["decision_eligible"])
            self.assertEqual(report["market_intelligence"]["status"], "READY")
            self.assertTrue(report["readiness"]["engine_1_market_intelligence"])
            intelligence_engine.collect.assert_called_once_with()
            self.assertIs(
                decision_engine.analyze.call_args.kwargs["market_intelligence"],
                report["market_intelligence"],
            )
            self.assertEqual(report["decision"]["action"], "WAIT")
            self.assertEqual(report["command_publish"]["status"], "NOT_READY")
            self.assertTrue(report["execution_controls"]["terminal_connected"])
            self.assertIs(report["execution_controls"]["expert_execution_enabled"], False)
            self.assertEqual(report["execution_controls"]["expert_execution_telemetry"], "REPORTED_DISABLED")
            candle_history_engine.collect.assert_called_once_with(
                bridge=bridge_snapshot, market=market
            )
            indicators_engine.analyze.assert_called_once_with(candle_history)
            self.assertEqual(report["engine_2_candles"]["status"], "READY")
            self.assertTrue(report["readiness"]["engine_2_visual_chart"])
            self.assertTrue(report["readiness"]["engine_2_candles"])
            self.assertEqual(report["engine_2_multi_timeframe_structure"]["source"], "NATIVE_MT5_OHLC")
            self.assertEqual(report["chart"]["engine_2_multi_timeframe_structure"]["source"], "NATIVE_MT5_OHLC")
            bridge_engine.publish_decision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
