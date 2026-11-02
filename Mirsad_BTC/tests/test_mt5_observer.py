from __future__ import annotations

import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from mirsad.engines.mt5_observer import MT5ChartObserverInbox
from mirsad.runtime import _inspect_mt5_chart_observer


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
            "published_at_utc_ms": captured + 100,
            "server_time_seconds": server_time_seconds,
            "server_utc_offset_seconds_at_capture": 0,
            "image_file": image_name,
            "image_width_px": 640,
            "image_height_px": 360,
            "image_size_bytes": image_path.stat().st_size,
            "forming_bar_included": True,
            "bars_time_basis": "MT5_SERVER_TIME",
            "bars_copied": len(bars),
            "bars": bars,
            "chart": {
                "symbol": "BTC",
                "timeframe": "M1",
                "digits": 2,
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
            self.assertEqual(result["bar_count"], 30)
            self.assertFalse(result["bars"][-1]["is_closed"])
            self.assertEqual(len(result["image_sha256"]), 64)

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

    def test_rejects_bar_time_after_broker_server_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            root, payload = self.make_capture(Path(directory), now_ms=now)
            payload["bars"][-1]["time_server_ms"] = (payload["server_time_seconds"] + 20) * 1000
            (root / f"capture_{payload['capture_id']}.json").write_text(json.dumps(payload), encoding="utf-8")

            result = MT5ChartObserverInbox(root).inspect_latest(now_ms=now + 500)

            self.assertEqual(result["status"], "BAR_TIME_IN_FUTURE")

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


if __name__ == "__main__":
    unittest.main()
