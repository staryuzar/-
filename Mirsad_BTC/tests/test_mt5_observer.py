from __future__ import annotations

import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mirsad.engines.mt5_observer import MT5ChartObserverInbox, recent_reference_candle_candidates
from mirsad.runtime import _inspect_mt5_chart_observer


class MT5ReferenceCandleCandidateTests(unittest.TestCase):
    def test_skips_flat_forming_bar_and_returns_recent_closed_candle(self) -> None:
        bars = [
            {
                "time_server_ms": 1_000 + index * 60_000,
                "open": 100.0 + index,
                "high": 102.0 + index,
                "low": 99.0 + index,
                "close": 101.0 + index,
                "is_closed": index < 3,
            }
            for index in range(3)
        ]
        bars.append({
            "time_server_ms": 181_000,
            "open": 103.0, "high": 103.0, "low": 103.0, "close": 103.0,
            "is_closed": False,
        })
        candidates = recent_reference_candle_candidates(bars)
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["offset_from_right"], 1)
        self.assertTrue(candidates[0]["closed"])
        self.assertEqual(candidates[0]["time_server_ms"], 121_000)
        self.assertGreater(
            candidates[0]["ohlc"]["high"] - candidates[0]["ohlc"]["low"], 0
        )

    def test_no_flat_or_invalid_candle_is_used_as_reference(self) -> None:
        bars = [{
            "time_server_ms": 1_000,
            "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
            "is_closed": False,
        }]
        self.assertEqual(recent_reference_candle_candidates(bars), [])


class MT5ChartObserverInboxTests(unittest.TestCase):
    def make_capture(self, root: Path, *, now_ms: int | None = None):
        captured = int(time.time() * 1000) if now_ms is None else now_ms
        observer_root = root / "MirsadBTC" / "observer"
        images = observer_root / "images"
        images.mkdir(parents=True, exist_ok=True)

        capture_id = "1700000000000_987654321_1"
        image_name = f"o_{capture_id}.png"
        image_path = images / image_name
        Image.new("RGB", (640, 360), (22, 28, 38)).save(image_path, format="PNG")

        server_time_seconds = captured // 1000
        server_time_ms = server_time_seconds * 1000
        bars = []
        start = server_time_ms - 30 * 60_000
        for index in range(30):
            base = 90_000.0 + index * 10.0
            bars.append({
                "time_server_ms": start + index * 60_000,
                "open": base,
                "high": base + 25,
                "low": base - 15,
                "close": base + 5,
                "tick_volume": 100 + index,
                "real_volume": 0,
                "spread_points": 20,
                "is_closed": index < 29,
            })

        payload = {
            "schema": "MIR-CHART-OBSERVATION-1",
            "capture_id": capture_id,
            "capture_at_utc_ms": captured,
            "rates_snapshot_at_utc_ms": captured - 50,
            "published_at_utc_ms": captured + 100,
            "server_time_seconds": server_time_seconds,
            "server_utc_offset_seconds_at_capture": 0,
            "image_file": image_name,
            "image_width_px": 640,
            "image_height_px": 360,
            "image_size_bytes": image_path.stat().st_size,
            "account": {
                "terminal_connected": True,
                "server": "Example-Broker-Server",
                "trade_mode": 0,
                "trade_mode_label": "DEMO",
            },
            "forming_bar_included": True,
            "bars_time_basis": "MT5_SERVER_TIME",
            "bars_copied": len(bars),
            "rates_status": "AVAILABLE",
            "rates_error_code": 0,
            "bars": bars,
            "chart": {
                "symbol": "BTC",
                "timeframe": "M1",
                "digits": 2,
                "source_width_px": 1400,
                "source_main_window_height_px": 800,
                "source_dimensions_usable": True,
                "source_dimensions_status": "USABLE",
                "windows_total": 1,
                "price_min": 89_000.0,
                "price_max": 92_000.0,
                "plot_bounds_status": "NOT_CALIBRATED_FROM_PIXELS",
            },
        }
        manifest = observer_root / f"capture_{capture_id}.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        return observer_root, payload

    def test_reads_valid_image_and_native_rates_without_authorizing_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, _ = self.make_capture(Path(directory), now_ms=now)

            result = MT5ChartObserverInbox(root, max_age_seconds=120).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertFalse(result["decision_eligible"])
            self.assertEqual(result["chart"]["symbol"], "BTC")
            self.assertEqual(result["chart"]["timeframe"], "1m")
            self.assertEqual(result["account"]["server"], "Example-Broker-Server")
            self.assertEqual(result["account"]["trade_mode_label"], "DEMO")
            self.assertTrue(result["account"]["terminal_connected"])
            self.assertEqual(result["bar_count"], 30)
            self.assertEqual(result["capture_data_skew_ms"], 50)
            self.assertFalse(result["bars"][-1]["is_closed"])
            self.assertEqual(len(result["image_sha256"]), 64)

    def test_upscaled_png_does_not_override_small_source_chart_viewport(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            image_path = root / "images" / payload["image_file"]
            # Simulate a 1600x900 screenshot generated from a 606x260
            # native MT5 chart viewport.
            Image.new("RGB", (1600, 900), (22, 28, 38)).save(image_path, format="PNG")
            payload["image_width_px"] = 1600
            payload["image_height_px"] = 900
            payload["image_size_bytes"] = image_path.stat().st_size
            payload["chart"]["source_width_px"] = 606
            payload["chart"]["source_main_window_height_px"] = 260
            # Even stale or incorrect producer flags cannot bypass this gate.
            payload["chart"]["source_dimensions_usable"] = True
            payload["chart"]["source_dimensions_status"] = "USABLE"
            (root / f"capture_{payload['capture_id']}.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertFalse(result["visual_calibration_eligible"])
            self.assertEqual(
                result["visual_calibration_status"],
                "BELOW_VISUAL_CALIBRATION_THRESHOLD",
            )
            self.assertFalse(result["chart"]["source_dimensions_usable"])

    def test_accepts_capture_when_source_viewport_is_small_but_marks_calibration_unusable(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["chart"]["source_width_px"] = 0
            payload["chart"]["source_main_window_height_px"] = 0
            payload["chart"]["source_dimensions_usable"] = False
            payload["chart"]["source_dimensions_status"] = "BELOW_VISUAL_CALIBRATION_THRESHOLD"
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root, max_age_seconds=120).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertFalse(result["decision_eligible"])
            self.assertFalse(result["visual_calibration_eligible"])
            self.assertEqual(
                result["visual_calibration_status"],
                "BELOW_VISUAL_CALIBRATION_THRESHOLD",
            )
            self.assertEqual(result["chart"]["source_width_px"], 0)

    def test_rejects_stale_capture_instead_of_falling_back(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, _ = self.make_capture(Path(directory), now_ms=now - 300_000)

            result = MT5ChartObserverInbox(root, max_age_seconds=60).inspect_latest(now_ms=now)

            self.assertEqual(result["status"], "STALE")
            self.assertFalse(result["decision_eligible"])

    def test_rejects_path_traversal_image_name(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["image_file"] = "../outside.png"
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "INVALID_IMAGE_PATH")

    def test_rejects_windows_path_traversal_image_name(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["image_file"] = r"..\\outside.png"
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "INVALID_IMAGE_PATH")

    def test_records_large_skew_without_rejecting_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["rates_snapshot_at_utc_ms"] = now - 10_000
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertEqual(result["capture_data_skew_ms"], 10_000)
            self.assertFalse(result["decision_eligible"])

    def test_accepts_m2_timeframe_without_blocking_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["chart"]["timeframe"] = "M2"
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertEqual(result["chart"]["source_timeframe"], "M2")
            self.assertEqual(result["chart"]["timeframe"], "m2")
            self.assertFalse(result["decision_eligible"])

    def test_accepts_more_than_500_bars_without_capture_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            bars = payload["bars"]
            # The formerly forming bar becomes closed once a newer bar exists.
            bars[-1]["is_closed"] = True
            last_time = bars[-1]["time_server_ms"]
            for index in range(30, 601):
                base = 90_000.0 + index * 10.0
                bars.append({
                    "time_server_ms": last_time + (index - 29) * 60_000,
                    "open": base,
                    "high": base + 25,
                    "low": base - 15,
                    "close": base + 5,
                    "tick_volume": 100 + index,
                    "real_volume": 0,
                    "spread_points": 20,
                    "is_closed": index < 600,
                })
            payload["bars_copied"] = len(bars)
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertEqual(result["bar_count"], 601)
            self.assertFalse(result["decision_eligible"])

    def test_accepts_empty_history_and_keeps_chart_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["bars"] = []
            payload["bars_copied"] = 0
            payload["rates_status"] = "UNAVAILABLE"
            payload["rates_error_code"] = 4401
            payload["forming_bar_included"] = False
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertEqual(result["bar_count"], 0)
            self.assertEqual(result["rates_status"], "UNAVAILABLE")
            self.assertFalse(result["decision_eligible"])

    def test_accepts_broker_server_clock_with_utc_plus_two_offset(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["server_time_seconds"] += 7200
            payload["server_utc_offset_seconds_at_capture"] = 7200
            for bar in payload["bars"]:
                bar["time_server_ms"] += 7_200_000
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertEqual(result["bars_time_basis"], "MT5_SERVER_TIME")
            self.assertFalse(result["decision_eligible"])

    def test_records_bar_time_after_broker_server_clock_without_blocking_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["bars"][-1]["time_server_ms"] = (payload["server_time_seconds"] + 20) * 1000
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "READY_FOR_ENGINE_2_VALIDATION")
            self.assertTrue(result["newest_bar_after_server_clock"])
            self.assertFalse(result["decision_eligible"])

    def test_rejects_missing_server_time(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            del payload["server_time_seconds"]
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "INVALID_SERVER_TIME")

    def test_rejects_image_size_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["image_size_bytes"] += 4
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "IMAGE_SIZE_MISMATCH")

    def test_rejects_non_monotonic_bar_times(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["bars"][4]["time_server_ms"] = payload["bars"][3]["time_server_ms"]
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "INVALID_OHLC_SNAPSHOT")

    def test_rejects_inconsistent_ohlc(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["bars"][8]["high"] = payload["bars"][8]["low"] - 1
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "INVALID_OHLC_SNAPSHOT")

    def test_rejects_wrong_manifest_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["schema"] = "MIR1"
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "SCHEMA_MISMATCH")

    def test_waits_when_no_capture_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            result = MT5ChartObserverInbox(Path(directory) / "empty").inspect_latest()

            self.assertEqual(result["status"], "WAITING_FOR_CAPTURE")
            self.assertFalse(result["decision_eligible"])

    def test_runtime_reports_observer_not_configured_without_changing_decision(self):
        with patch("mirsad.runtime.MT5_COMMON_FILES", ""):
            result = _inspect_mt5_chart_observer()

        self.assertEqual(result["status"], "NOT_CONFIGURED")
        self.assertFalse(result["decision_eligible"])

    def test_runtime_reads_observer_inbox_from_configured_common_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("mirsad.runtime.MT5_COMMON_FILES", directory):
                result = _inspect_mt5_chart_observer()

        self.assertEqual(result["status"], "WAITING_FOR_CAPTURE")
        self.assertFalse(result["decision_eligible"])


class MT5ObserverScreenshotAlignmentTests(unittest.TestCase):
    def test_capture_preserves_viewport_used_for_native_pixel_geometry(self) -> None:
        source = Path(__file__).resolve().parents[1] / "mt5" / "Mirsad_ChartObserver.mq5"
        content = source.read_text(encoding="utf-8")
        self.assertIn(r'\"screenshot_alignment\":\"ALIGN_LEFT\"', content)
        self.assertIn("screenshot_width, screenshot_height, ALIGN_LEFT", content)
        self.assertNotIn("screenshot_width, screenshot_height, ALIGN_RIGHT", content)
        capture_body = content.split("bool BeginCapture()", 1)[1].split("bool TryFinalizePendingCapture()", 1)[0]
        navigation_call = "g_last_capture_navigation_ok = SynchronizeLatestChartViewport();"
        self.assertIn(navigation_call, capture_body)
        self.assertLess(capture_body.index(navigation_call), capture_body.index("CHART_FIRST_VISIBLE_BAR"))
        self.assertIn(r'\"chart_navigated_to_end\"', content)



if __name__ == "__main__":
    unittest.main()
