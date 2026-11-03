from __future__ import annotations

import unittest

from mirsad.engines.mt5_chart_geometry import (
    analyze_native_mt5_ohlc,
    native_geometry_visible_y_max,
    validate_mt5_chart_geometry,
    validate_mt5_geometry_overlay,
)


def make_bars(count: int = 12) -> list[dict]:
    result = []
    for index in range(count):
        base = 100.0 + index
        result.append({
            "time_server_ms": 1_700_000_000_000 + index * 60_000,
            "open": base,
            "high": base + 2.0,
            "low": base - 1.0,
            "close": base + 1.0,
            "is_closed": index < count - 1,
        })
    return result


def make_geometry(bars: list[dict]) -> dict:
    items = []
    for index, bar in enumerate(bars):
        x = 20 + index * 40
        base_y = 400 - index * 4
        items.append({
            "time_server_ms": bar["time_server_ms"],
            "is_closed": bar["is_closed"],
            "valid": True,
            "visible": True,
            "x_px": float(x),
            "x_alignment_error_px": 0,
            "open": {"x_px": x, "y_px": base_y + 2},
            "high": {"x_px": x, "y_px": base_y},
            "low": {"x_px": x, "y_px": base_y + 5},
            "close": {"x_px": x, "y_px": base_y + 1},
        })
    return {
        "schema": "MIR-MT5-CHART-GEOMETRY-1",
        "coordinate_source": "MQL5_CHART_TIME_PRICE_TO_XY",
        "coordinate_origin": "MAIN_CHART_WINDOW_TOP_LEFT",
        "source_width_px": 600,
        "source_height_px": 500,
        "image_width_px": 1200,
        "image_height_px": 1000,
        "provisional_x_scale_to_image": 2.0,
        "provisional_y_scale_to_image": 2.0,
        "bars_total": len(items),
        "bars_valid": len(items),
        "bars_visible": len(items),
        "bars": items,
    }


class MT5ChartGeometryTests(unittest.TestCase):
    def test_valid_native_geometry_is_exposed_as_provisional_not_eligible(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        result = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        self.assertEqual(result["status"], "READY_FOR_PIXEL_ALIGNMENT")
        self.assertEqual(result["validated_bars"], len(bars))
        self.assertEqual(result["visible_bars"], len(bars))
        self.assertEqual(result["scale_x"], 2.0)
        self.assertEqual(result["scale_y"], 2.0)
        self.assertEqual(result["mapping_status"], "UNVERIFIED_PROVISIONAL_DIMENSION_RATIO")
        self.assertFalse(result["decision_eligible"])
        self.assertEqual(result["bars"][0]["x_image_px_provisional"], 40.0)

    def test_off_chart_invalid_points_are_skipped_without_poisoning_visible_geometry(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        geometry["bars"][0]["valid"] = False
        geometry["bars"][0]["visible"] = False
        geometry["bars"][0]["x_px"] = -1.0
        for field in ("open", "high", "low", "close"):
            geometry["bars"][0][field] = None
        geometry["bars_valid"] -= 1
        geometry["bars_visible"] -= 1
        result = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        self.assertEqual(result["status"], "READY_FOR_PIXEL_ALIGNMENT")
        self.assertEqual(result["validated_bars"], len(bars) - 1)
        self.assertEqual(result["visible_bars"], len(bars) - 1)
        self.assertFalse(result["bars"][0]["valid"])
        self.assertIsNone(result["bars"][0]["points_source_px"])

    def test_native_geometry_overlay_uses_fit_and_independent_image_holdout(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        validated = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        extracted = []
        for index, bar in enumerate(bars):
            item = geometry["bars"][index]
            extracted.append({
                "slot_index": index,
                "x_px": 1.1 * item["x_px"] + 5.0,
                "high_y_px": 1.5 * item["high"]["y_px"] + 7.0,
                "low_y_px": 1.5 * item["low"]["y_px"] + 7.0,
                "body_top_y_px": 1.5 * item["close"]["y_px"] + 7.0,
                "body_bottom_y_px": 1.5 * item["open"]["y_px"] + 7.0,
            })
        result = validate_mt5_geometry_overlay(
            validated,
            native_bars=bars,
            extracted_bars=extracted,
            visible_bars=len(bars),
            first_visible_bar_shift=len(bars) - 1,
        )
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["mapping_verified"])
        self.assertFalse(result["decision_eligible"])
        self.assertEqual(result["matched_candles"], len(bars))
        self.assertAlmostEqual(result["x_scale"], 1.1, places=6)
        self.assertAlmostEqual(result["x_offset"], 5.0, places=4)
        self.assertAlmostEqual(result["y_scale"], 1.5, places=6)
        self.assertAlmostEqual(result["y_offset"], 7.0, places=4)

    def test_native_geometry_overlay_rejects_bad_interleaved_holdout(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        validated = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        extracted = []
        for index, bar in enumerate(bars):
            item = geometry["bars"][index]
            extracted.append({
                "slot_index": index,
                "x_px": 1.1 * item["x_px"] + 5.0,
                "high_y_px": 1.5 * item["high"]["y_px"] + 7.0,
                "low_y_px": 1.5 * item["low"]["y_px"] + 7.0,
                "body_top_y_px": 1.5 * item["close"]["y_px"] + 7.0,
                "body_bottom_y_px": 1.5 * item["open"]["y_px"] + 7.0,
            })
        extracted[8]["high_y_px"] += 100.0
        result = validate_mt5_geometry_overlay(
            validated,
            native_bars=bars,
            extracted_bars=extracted,
            visible_bars=len(bars),
            first_visible_bar_shift=len(bars) - 1,
        )
        self.assertEqual(result["status"], "OVERLAY_HOLDOUT_FAILED")
        self.assertFalse(result["mapping_verified"])
        self.assertFalse(result["decision_eligible"])

    def test_geometry_must_match_exact_native_bar_timestamps(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        geometry["bars"][4]["time_server_ms"] += 60_000
        result = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        self.assertEqual(result["status"], "BAR_IDENTITY_MISMATCH")
        self.assertFalse(result["decision_eligible"])

    def test_geometry_requires_common_x_coordinate_for_ohlc_points(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        geometry["bars"][3]["close"]["x_px"] += 5
        result = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        self.assertEqual(result["status"], "X_ALIGNMENT_FAILED")

    def test_geometry_requires_correct_vertical_ohlc_order(self) -> None:
        bars = make_bars()
        geometry = make_geometry(bars)
        geometry["bars"][2]["high"]["y_px"] = 450
        result = validate_mt5_chart_geometry(
            geometry,
            bars=bars,
            chart={
                "source_width_px": 600,
                "source_main_window_height_px": 500,
                "visible_bars": len(bars),
            },
            image_width=1200,
            image_height=1000,
        )
        self.assertEqual(result["status"], "Y_ORDER_FAILED")

    def test_geometry_is_not_available_for_legacy_capture_manifests(self) -> None:
        result = validate_mt5_chart_geometry(
            None,
            bars=make_bars(),
            chart={"source_width_px": 600, "source_main_window_height_px": 500},
            image_width=1200,
            image_height=1000,
        )
        self.assertEqual(result["status"], "NOT_AVAILABLE")
        self.assertFalse(result["decision_eligible"])

    def test_native_ohlc_patterns_and_structure_use_closed_bars_only(self) -> None:
        bars = make_bars()
        result = analyze_native_mt5_ohlc(bars, symbol="BTCUSDT", timeframe="1m")
        self.assertEqual(result["source"], "MT5_COPYRATES")
        self.assertEqual(result["bar_count"], len(bars))
        self.assertEqual(result["closed_bar_count"], len(bars) - 1)
        self.assertEqual(result["forming_bar_count"], 1)
        self.assertEqual(
            result["structure"]["confirmed_bars"],
            len(bars) - 1,
        )
        self.assertFalse(result["decision_eligible"])
        self.assertTrue(all(
            item.get("confirmation_state") != "CONFIRMED"
            or item.get("end_index", -1) < len(bars) - 1
            for item in result["patterns"].get("detected", [])
        ))


if __name__ == "__main__":
    unittest.main()


class NativeGeometryExtentTests(unittest.TestCase):
    def test_native_geometry_visible_y_max_ignores_invalid_and_invisible_bars(self) -> None:
        geometry = {
            "bars": [
                {
                    "valid": True,
                    "visible": True,
                    "points_image_px_provisional": {
                        "open": {"x": 10, "y": 20},
                        "high": {"x": 10, "y": 12},
                        "low": {"x": 10, "y": 44},
                        "close": {"x": 10, "y": 30},
                    },
                },
                {
                    "valid": True,
                    "visible": False,
                    "points_image_px_provisional": {"low": {"x": 12, "y": 580}},
                },
                {
                    "valid": False,
                    "visible": True,
                    "points_image_px_provisional": {"low": {"x": 14, "y": 590}},
                },
            ]
        }
        self.assertEqual(native_geometry_visible_y_max(geometry), 44.0)
        self.assertIsNone(native_geometry_visible_y_max({"bars": []}))
