from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mirsad.runtime import _analyze_mt5_observer_chart


def fixture_capture(root: Path) -> tuple[dict, dict, dict]:
    image_path = root / "observer.png"
    Image.new("RGB", (640, 360), (20, 25, 35)).save(image_path, format="PNG")
    bars = []
    for index in range(30):
        base = 90_000.0 + index
        bars.append({
            "time_server_ms": 1_700_000_000_000 + index * 60_000,
            "open": base, "high": base + 20, "low": base - 20, "close": base + 5,
            "is_closed": index < 29,
        })
    observer = {
        "status": "READY_FOR_ENGINE_2_VALIDATION",
        "capture_id": "capture-1",
        "image_path": str(image_path),
        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "age_seconds": 1.0,
        "capture_data_skew_ms": 50,
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
    market = {
        "symbol": "BTCUSDT",
        "status": "LIVE",
        "primary_venue": "OKX Spot",
        "venues": {"OKX Spot": {"status": "LIVE", "candles_by_tf": {"1m": [{}]}}},
    }
    bridge = {
        "status": "CONNECTED",
        "symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
    }
    return observer, market, bridge


class MT5ObserverEngine2IntegrationTests(unittest.TestCase):
    def test_valid_capture_is_passed_to_engine2_with_native_forming_bar_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            expected_analysis = {
                "status": "READY",
                "decision_eligible": True,
                "calibration": {"source": "reference_multi_candle_ohlc"},
                "reference_multi_calibration": {"status": "READY"},
                "reference_axis_validation": {"status": "READY"},
                "reference_ohlc_override_applied": True,
            }
            with patch("mirsad.runtime.analyze_chart_image", return_value=expected_analysis) as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)

            self.assertTrue(result["decision_eligible"])
            self.assertEqual(result["source"], "MT5_OBSERVER")
            self.assertEqual(result["observer_capture"]["native_bar_count"], 30)
            args, kwargs = analyzer.call_args
            self.assertEqual(args[0], Path(observer["image_path"]))
            self.assertEqual(args[1]["symbol"], "BTCUSDT")
            self.assertEqual(args[1]["timeframe"], "1m")
            self.assertFalse(args[1]["last_candle_closed"])
            self.assertTrue(args[1]["auto_axis_ocr"])
            self.assertEqual(args[1]["reference_last_candle_ohlc"]["close"], observer["bars"][-1]["close"])
            self.assertEqual(kwargs["expected_symbol"], "BTCUSDT")
            self.assertEqual(args[1]["expected_candle_count"], 30)
            self.assertTrue(args[1]["require_multi_reference_validation"])
            self.assertGreaterEqual(len(args[1]["reference_candle_candidates"]), 8)

    def test_flat_forming_bar_uses_previous_closed_mt5_candle_as_visual_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            flat_price = float(observer["bars"][-1]["close"])
            observer["bars"][-1].update({
                "open": flat_price, "high": flat_price,
                "low": flat_price, "close": flat_price,
            })
            expected_analysis = {
                "status": "READY",
                "decision_eligible": True,
                "calibration": {"source": "reference_multi_candle_ohlc"},
                "reference_multi_calibration": {"status": "READY"},
                "reference_axis_validation": {"status": "READY"},
                "reference_ohlc_override_applied": True,
                "reference_anchor": {"status": "READY", "offset_from_right": 1},
            }
            with patch("mirsad.runtime.analyze_chart_image", return_value=expected_analysis) as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)

            self.assertTrue(result["decision_eligible"])
            self.assertFalse(result["observer_capture"]["forming_bar_used_as_reference"])
            self.assertEqual(result["observer_capture"]["reference_anchor"]["offset_from_right"], 1)
            metadata = analyzer.call_args.args[1]
            self.assertEqual(metadata["reference_candle_candidates"][0]["offset_from_right"], 1)
            self.assertTrue(metadata["reference_candle_candidates"][0]["closed"])
            self.assertEqual(
                metadata["reference_last_candle_ohlc"]["close"],
                observer["bars"][-2]["close"],
            )
            self.assertFalse(metadata["last_candle_closed"])

    def test_changed_image_after_inbox_validation_is_rejected_by_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            Image.new("RGB", (640, 360), (220, 20, 20)).save(observer["image_path"], format="PNG")
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertFalse(result["decision_eligible"])
            self.assertEqual(result["status"], "OBSERVER_IMAGE_CHANGED")

    def test_capture_with_small_source_viewport_never_reaches_visual_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            observer["visual_calibration_eligible"] = False
            observer["chart"]["source_dimensions_usable"] = False
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertFalse(result["decision_eligible"])
            self.assertEqual(result["status"], "OBSERVER_VIEWPORT_UNSUITABLE")

    def test_capture_with_unsynchronized_image_and_ohlc_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            observer["capture_data_skew_ms"] = 2_001
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertEqual(result["status"], "OBSERVER_CAPTURE_NOT_SYNCHRONIZED")

    def test_capture_scrolled_away_from_latest_candles_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            observer["chart"]["first_visible_bar_shift"] = 100
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertFalse(result["decision_eligible"])
            self.assertEqual(result["status"], "OBSERVER_NOT_AT_LIVE_EDGE")

    def test_capture_without_autoscroll_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            observer["chart"]["chart_autoscroll"] = False
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertEqual(result["status"], "OBSERVER_NOT_AT_LIVE_EDGE")

    def test_wrong_broker_to_market_symbol_mapping_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            bridge["market_symbol"] = "ETHUSDT"
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertFalse(result["decision_eligible"])

    def test_stale_engine1_quote_does_not_block_valid_engine2_image_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            market["status"] = "STALE"
            market["venues"]["OKX Spot"]["status"] = "STALE"
            expected_analysis = {
                "status": "READY",
                "decision_eligible": True,
                "calibration": {"source": "reference_multi_candle_ohlc"},
                "reference_multi_calibration": {"status": "READY"},
                "reference_axis_validation": {"status": "READY"},
                "reference_ohlc_override_applied": True,
                "reference_anchor": {"status": "READY", "offset_from_right": 0},
            }
            with patch("mirsad.runtime.analyze_chart_image", return_value=expected_analysis) as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)

            analyzer.assert_called_once()
            self.assertEqual(result["status"], "READY")
            self.assertTrue(result["decision_eligible"])
            self.assertFalse(
                result["observer_capture"]["engine_1_quote_freshness_required_for_visual_analysis"]
            )

    def test_wrong_broker_server_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            bridge["account"]["server"] = "Other-Demo"
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertFalse(result["decision_eligible"])

    def test_forming_bar_is_required_and_old_bar_cannot_be_used_as_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            observer["bars"][-1]["is_closed"] = True
            with patch("mirsad.runtime.analyze_chart_image") as analyzer:
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            analyzer.assert_not_called()
            self.assertEqual(result["status"], "OBSERVER_BAR_STATE_INVALID")

    def test_failed_reference_candle_geometry_keeps_engine2_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observer, market, bridge = fixture_capture(Path(directory))
            expected_analysis = {
                "status": "READY",
                "decision_eligible": True,
                "calibration": {"source": "ocr"},
                "reference_multi_calibration": {"status": "NOT_REQUESTED"},
                "reference_ohlc_override_applied": False,
            }
            with patch("mirsad.runtime.analyze_chart_image", return_value=expected_analysis):
                result = _analyze_mt5_observer_chart(observer, market, bridge)
            self.assertFalse(result["decision_eligible"])
            self.assertEqual(result["status"], "OBSERVER_REFERENCE_NOT_VERIFIED")
            self.assertEqual(result["observer_reference_status"], "NOT_REQUESTED")

    def test_missing_capture_allows_existing_manual_chart_fallback(self) -> None:
        result = _analyze_mt5_observer_chart({"status": "WAITING_FOR_CAPTURE"}, {}, {})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
