from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import mirsad.runtime as runtime


class RuntimeObserverFlowTests(unittest.TestCase):
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
                "venue_count": 2,
                "primary_venue": "OKX Spot",
                "venues": {
                    "OKX Spot": {"status": "LIVE", "candles_by_tf": {"1m": bars}},
                    "Second Spot": {"status": "LIVE", "candles_by_tf": {"1m": bars}},
                },
            }
            bridge_snapshot = {
                "engine": "engine_5_communication_bridge",
                "status": "CONNECTED",
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "account": {"server": "Headway-Demo"},
            }
            analysis = {
                "status": "READY",
                "decision_eligible": True,
                "calibration": {
                    "source": "reference_last_candle_ohlc",
                    "price_scale_valid": True,
                },
                "reference_calibration": {"status": "READY"},
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
            indicators_engine = Mock()
            indicators_engine.analyze.return_value = {"status": "READY"}
            decision_engine = Mock()
            decision_engine.analyze.return_value = {
                "status": "READY",
                "action": "WAIT",
                "command_ready": False,
            }

            with (
                patch.object(runtime, "MarketEngine", return_value=market_engine),
                patch.object(runtime, "MT5BridgeEngine", return_value=bridge_engine),
                patch.object(runtime, "IndicatorsEngine", return_value=indicators_engine),
                patch.object(runtime, "DecisionEngine", return_value=decision_engine),
                patch.object(runtime, "_inspect_mt5_chart_observer", return_value=observer),
                patch.object(runtime, "analyze_chart_image", return_value=analysis) as visual_analyzer,
                patch.object(runtime, "analyze_stored_multi_timeframe_structure", return_value={"status": "READY"}),
                patch.object(runtime, "save_market_snapshot"),
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
            self.assertEqual(report["decision"]["action"], "WAIT")
            self.assertEqual(report["command_publish"]["status"], "NOT_READY")
            bridge_engine.publish_decision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
