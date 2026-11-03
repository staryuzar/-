from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

from mirsad.engines.chart import (
    _patterns,
    _visible_slot_for_reference_offset,
    analyze_chart_image,
)
from mirsad.engines.chart_calibration import price_at_pixel, resolve_chart_calibration
from mirsad.engines.chart_image import load_chart_image
from mirsad.engines.chart_metrics import analyze_calibrated_bars
from mirsad.engines.chart_pattern_reference import analyze_talib_pattern_reference



class NativeSlotBoundsDiagnosticTests(unittest.TestCase):
    def test_native_slots_outside_ocr_bounds_are_measured_without_rewriting(self) -> None:
        slots = [
            {"slot_index": index, "x_px": value}
            for index, value in enumerate([10.0, 30.0, 50.0, 70.0, 90.0, 110.0, 130.0, 150.0])
        ]
        before = [dict(item) for item in slots]
        native_x = sorted(float(item["x_px"]) for item in slots)
        left, right, tolerance = 20.0, 110.0, 3.0
        left_outside = [x for x in native_x if x < left - tolerance]
        right_outside = [x for x in native_x if x > right + tolerance]
        inside = [
            x for x in native_x if left - tolerance <= x <= right + tolerance
        ]
        self.assertEqual(len(inside), 5)
        self.assertEqual(len(left_outside), 1)
        self.assertEqual(len(right_outside), 2)
        self.assertEqual(slots, before)


class VisibleReferenceSlotTests(unittest.TestCase):
    def test_native_offsets_map_to_visible_slots_without_chart_shift(self) -> None:
        self.assertEqual(_visible_slot_for_reference_offset(0, 93, 92), 92)
        self.assertEqual(_visible_slot_for_reference_offset(92, 93, 92), 0)
        self.assertIsNone(_visible_slot_for_reference_offset(93, 93, 92))

    def test_native_offsets_account_for_right_margin_from_chart_shift(self) -> None:
        self.assertEqual(_visible_slot_for_reference_offset(8, 93, 100), 92)
        self.assertEqual(_visible_slot_for_reference_offset(100, 93, 100), 0)
        self.assertIsNone(_visible_slot_for_reference_offset(7, 93, 100))
        self.assertIsNone(_visible_slot_for_reference_offset(101, 93, 100))


class ChartEngineTests(unittest.TestCase):
    WIDTH = 500
    HEIGHT = 320
    META = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "price_top": 120000.0,
        "price_bottom": 80000.0,
        "plot_left_px": 0,
        "plot_right_px": WIDTH,
        "plot_top_px": 10,
        "plot_bottom_px": 310,
        "last_candle_closed": True,
    }

    def _write_chart(
        self,
        path: Path,
        *,
        direction: str = "up",
        colour: str = "GREEN",
        count: int = 24,
    ) -> None:
        image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
        bgr = (0, 200, 0) if colour == "GREEN" else (0, 0, 220)

        for index in range(count):
            if direction == "up":
                close_y = int(210 - index * 5)
            elif direction == "down":
                close_y = int(80 + index * 5)
            else:
                close_y = 140

            # Green candles close above their open; red candles close below it.
            open_y = close_y + 8 if colour == "GREEN" else close_y - 8
            high_y = min(open_y, close_y) - 5
            low_y = max(open_y, close_y) + 5
            x = 12 + index * 20

            cv2.line(image, (x, high_y), (x, low_y), bgr, 1)
            cv2.rectangle(
                image,
                (x - 2, min(open_y, close_y)),
                (x + 2, max(open_y, close_y)),
                bgr,
                thickness=-1,
            )

        self.assertTrue(cv2.imwrite(str(path), image))

    def _analyze(self, *, direction="up", colour="GREEN", metadata=None, expected="BTCUSDT", count=24):
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "synthetic_chart.png"
            self._write_chart(image_path, direction=direction, colour=colour, count=count)
            meta = dict(self.META)
            if metadata:
                meta.update(metadata)
            return analyze_chart_image(image_path, meta, expected_symbol=expected)

    @staticmethod
    def _pattern_bar(
        colour: str,
        top: int,
        bottom: int,
        shape: str = "normal",
        high: int | None = None,
        low: int | None = None,
    ) -> dict:
        return {
            "colour": colour,
            "shape": shape,
            "high_y_px": top - 3 if high is None else high,
            "low_y_px": bottom + 3 if low is None else low,
            "body_top_y_px": top,
            "body_bottom_y_px": bottom,
        }

    def test_axisless_chart_reports_pixel_bias_without_decision_eligibility(self) -> None:
        result = self._analyze(metadata={"price_top": None, "price_bottom": None})
        self.assertFalse(result["calibration"]["price_scale_valid"])
        self.assertFalse(result["decision_eligible"])
        pixel = result["pixel_visual_evidence"]
        self.assertEqual(pixel["status"], "READY")
        self.assertEqual(pixel["direction"], "BULLISH")
        self.assertFalse(pixel["decision_eligible"])
        self.assertEqual(pixel["method"], "scale_free_pixel_close_trend")

    def test_detected_candles_without_price_axis_are_not_misreported_as_low_detection(self) -> None:
        result = self._analyze(metadata={"price_top": None, "price_bottom": None})
        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(result["status"], "DETECTED_UNCALIBRATED")
        self.assertFalse(result["decision_eligible"])

    def test_sparse_chart_keeps_low_detection_status(self) -> None:
        result = self._analyze(count=3)
        self.assertEqual(result["status"], "LOW_DETECTION")
        self.assertLess(result["detected_bar_count"], 5)

    def test_calibrated_chart_below_minimum_history_has_distinct_status(self) -> None:
        result = self._analyze(count=10)
        self.assertEqual(result["status"], "INSUFFICIENT_CALIBRATED_CANDLES")
        self.assertFalse(result["decision_eligible"])

    def test_doji_uses_previous_ten_candle_ranges(self) -> None:
        bars = [
            self._pattern_bar("GREEN", 100, 105, high=98, low=112)
            for _ in range(10)
        ]
        bars.append(self._pattern_bar("GREEN", 100, 101, high=98, low=112))
        patterns = _patterns(bars)
        self.assertEqual(
            len([x for x in patterns if x["pattern"] == "doji_candidate" and x["index"] == 10]),
            1,
        )

    def test_unclosed_latest_pattern_is_marked_forming(self) -> None:
        bars = [
            self._pattern_bar("GREEN", 100, 105, high=98, low=112)
            for _ in range(10)
        ]
        bars.append(self._pattern_bar("GREEN", 100, 101, high=98, low=112))
        patterns = _patterns(bars, last_candle_closed=False)
        latest_doji = [
            item for item in patterns
            if item["pattern"] == "doji_candidate" and item["index"] == len(bars) - 1
        ]
        self.assertEqual(len(latest_doji), 1)
        self.assertEqual(latest_doji[0]["confirmation_state"], "FORMING")
        self.assertTrue(latest_doji[0]["uses_unconfirmed_latest_candle"])

    def test_hammer_requires_short_body_long_lower_shadow_and_prior_low_context(self) -> None:
        bars = [
            self._pattern_bar("RED", 100, 105, high=98, low=110)
            for _ in range(10)
        ]
        bars.append(self._pattern_bar("GREEN", 108, 110, high=107, low=125))
        patterns = _patterns(bars)
        self.assertEqual(
            len([x for x in patterns if x["pattern"] == "hammer_candidate" and x["index"] == 10]),
            1,
        )

    def test_shooting_star_requires_real_body_gap_up(self) -> None:
        bars = [
            self._pattern_bar("GREEN", 100, 105, high=98, low=110)
            for _ in range(10)
        ]
        bars.append(self._pattern_bar("RED", 80, 82, high=65, low=83))
        patterns = _patterns(bars)
        self.assertEqual(
            len([x for x in patterns if x["pattern"] == "shooting_star_candidate" and x["index"] == 10]),
            1,
        )

    def test_shooting_star_without_gap_up_is_not_emitted(self) -> None:
        bars = [
            self._pattern_bar("GREEN", 100, 105, high=98, low=110)
            for _ in range(10)
        ]
        bars.append(self._pattern_bar("RED", 101, 103, high=86, low=104))
        patterns = _patterns(bars)
        self.assertEqual(
            len([x for x in patterns if x["pattern"] == "shooting_star_candidate" and x["index"] == 10]),
            0,
        )

    def test_harami_requires_long_first_body_and_short_contained_second_body(self) -> None:
        bars = [
            self._pattern_bar("RED", 100, 105, high=98, low=110)
            for _ in range(10)
        ]
        bars.extend([
            self._pattern_bar("RED", 100, 120, high=98, low=122),
            self._pattern_bar("GREEN", 105, 108, high=104, low=109),
        ])
        patterns = _patterns(bars)
        harami = [x for x in patterns if x["pattern"] == "harami_candidate"]
        self.assertEqual(len(harami), 1)
        self.assertEqual(harami[0]["start_index"], 10)
        self.assertEqual(harami[0]["index"], 11)

    def test_morning_star_requires_long_first_body_gap_down_and_penetration(self) -> None:
        bars = [
            self._pattern_bar("GREEN", 100, 105, high=98, low=110)
            for _ in range(10)
        ]
        bars.extend([
            self._pattern_bar("RED", 100, 120, high=98, low=122),
            self._pattern_bar("RED", 123, 126, high=121, low=128),
            self._pattern_bar("GREEN", 101, 114, high=99, low=116),
        ])
        patterns = _patterns(bars)
        stars = [x for x in patterns if x["pattern"] == "morning_star_candidate"]
        self.assertEqual(len(stars), 1)
        self.assertEqual(stars[0]["start_index"], 10)
        self.assertEqual(stars[0]["index"], 12)

    def test_evening_star_requires_long_first_body_gap_up_and_penetration(self) -> None:
        bars = [
            self._pattern_bar("GREEN", 100, 105, high=98, low=110)
            for _ in range(10)
        ]
        bars.extend([
            self._pattern_bar("GREEN", 100, 120, high=98, low=122),
            self._pattern_bar("GREEN", 94, 97, high=92, low=99),
            self._pattern_bar("RED", 110, 124, high=108, low=126),
        ])
        patterns = _patterns(bars)
        stars = [x for x in patterns if x["pattern"] == "evening_star_candidate"]
        self.assertEqual(len(stars), 1)
        self.assertEqual(stars[0]["start_index"], 10)
        self.assertEqual(stars[0]["index"], 12)

    def test_reference_candle_ohlc_calibrates_axisless_benchmark_chart(self) -> None:
        result = self._analyze(metadata={
            "price_top": None,
            "price_bottom": None,
            "reference_last_candle_ohlc": {
                "open": 119.7,
                "high": 121.0,
                "low": 119.2,
                "close": 120.5,
            },
        })
        self.assertEqual(result["reference_calibration"]["status"], "READY")
        self.assertEqual(result["calibration"]["source"], "reference_last_candle_ohlc")
        self.assertTrue(result["calibration"]["price_scale_valid"])
        self.assertGreaterEqual(result["calibrated_bar_count"], 20)
        self.assertTrue(result["decision_eligible"])
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["reference_ohlc_override_applied"])
        self.assertAlmostEqual(result["bars"][-1]["open"], 119.7, places=4)
        self.assertAlmostEqual(result["bars"][-1]["high"], 121.0, places=4)
        self.assertAlmostEqual(result["bars"][-1]["low"], 119.2, places=4)
        self.assertAlmostEqual(result["bars"][-1]["close"], 120.5, places=4)

    def test_flat_forming_candle_falls_back_to_exact_previous_visible_slot(self) -> None:
        # The last native MT5 bar is forming but flat. The previous completed
        # candle is used only as the axis anchor and must map to image slot 22.
        result = self._analyze(metadata={
            "price_top": None,
            "price_bottom": None,
            "expected_candle_count": 24,
            "last_candle_closed": False,
            "reference_candle_candidates": [
                {
                    "offset_from_right": 0,
                    "ohlc": {
                        "open": 108_000.0, "high": 108_000.0,
                        "low": 108_000.0, "close": 108_000.0,
                    },
                },
                {
                    "offset_from_right": 1,
                    "time_server_ms": 1_700_000_000_000,
                    "closed": True,
                    "ohlc": {
                        "open": 106_933.333333,
                        "high": 108_666.666667,
                        "low": 106_266.666667,
                        "close": 108_000.0,
                    },
                },
            ],
        })
        self.assertEqual(result["reference_calibration"]["status"], "READY")
        self.assertTrue(result["reference_ohlc_override_applied"])
        self.assertTrue(result["quality_gates"]["native_reference_candle_verified"])
        self.assertTrue(result["decision_eligible"])
        self.assertFalse(result["last_candle_closed"])
        self.assertEqual(result["reference_anchor"]["status"], "READY")
        self.assertEqual(result["reference_anchor"]["offset_from_right"], 1)
        self.assertIn(result["reference_anchor"]["slot_index"], (None, 22))
        self.assertEqual(result["reference_anchor"]["bar_index"], result["calibrated_bar_count"] - 2)
        self.assertAlmostEqual(result["bars"][-2]["open"], 106_933.333333, places=3)
        self.assertEqual(result["bars"][-1]["candle_state"], "FORMING_OR_UNVERIFIED")

    def test_multi_reference_loop_collects_all_exact_slots_after_first_anchor(self) -> None:
        def price_at(y: int) -> float:
            return 120000.0 - ((y - 10) / 300.0) * 40000.0

        candidates = [{
            "offset_from_right": 0,
            "closed": False,
            "ohlc": {
                "open": 108000.0, "high": 108000.0,
                "low": 108000.0, "close": 108000.0,
            },
        }]
        for offset in range(1, 24):
            index = 23 - offset
            close_y = 210 - index * 5
            open_y = close_y + 8
            high_y = close_y - 5
            low_y = open_y + 5
            candidates.append({
                "offset_from_right": offset,
                "closed": True,
                "time_server_ms": 1_700_000_000_000 - offset * 60_000,
                "ohlc": {
                    "open": price_at(open_y),
                    "high": price_at(high_y),
                    "low": price_at(low_y),
                    "close": price_at(close_y),
                },
            })

        result = self._analyze(metadata={
            "price_top": None,
            "price_bottom": None,
            "expected_candle_count": 24,
            "first_visible_bar_shift": 23,
            "last_candle_closed": False,
            "require_multi_reference_validation": True,
            "reference_candle_candidates": candidates,
        })

        self.assertEqual(result["reference_slot_diagnostics"]["exact_slot_match_count"], 23)
        self.assertEqual(result["reference_multi_calibration"]["status"], "READY")
        self.assertGreaterEqual(result["reference_multi_calibration"]["matched_candles"], 8)
        self.assertTrue(result["quality_gates"]["native_reference_candle_verified"])
        self.assertTrue(result["decision_eligible"])

    def test_reference_candidate_is_rejected_when_its_exact_visual_slot_is_missing(self) -> None:
        result = self._analyze(metadata={
            "price_top": None,
            "price_bottom": None,
            "expected_candle_count": 30,
            "reference_candle_candidates": [{
                "offset_from_right": 0,
                "ohlc": {
                    "open": 119.7, "high": 121.0,
                    "low": 119.2, "close": 120.5,
                },
            }],
        })
        # Thirty expected slots but only twenty-four synthetic candle objects; it must never
        # silently attach another candle's OHLC to a different pixel candle.
        self.assertFalse(result["reference_ohlc_override_applied"])
        self.assertNotEqual(result["reference_anchor"]["status"], "READY")
        self.assertFalse(result["quality_gates"]["native_reference_candle_verified"])
        self.assertFalse(result["decision_eligible"])

    def test_native_reference_candle_is_checked_against_an_already_valid_manual_axis(self) -> None:
        result = self._analyze(metadata={
            "reference_last_candle_ohlc": {
                "open": 107600.0,
                "high": 109333.333333,
                "low": 106933.333333,
                "close": 108666.666667,
            },
        })
        self.assertEqual(result["calibration"]["source"], "manual")
        self.assertEqual(result["reference_calibration"]["status"], "READY")
        self.assertEqual(result["reference_axis_validation"]["status"], "READY")
        self.assertTrue(result["reference_ohlc_override_applied"])
        self.assertTrue(result["quality_gates"]["native_reference_candle_verified"])
        self.assertTrue(result["decision_eligible"])

    def test_live_native_anchor_replaces_an_inconsistent_ocr_axis_only_when_explicitly_enabled(self) -> None:
        ticks = [
            {"y_px": 30, "price": 120000.0, "score": 0.95},
            {"y_px": 110, "price": 100000.0, "score": 0.95},
            {"y_px": 190, "price": 80000.0, "score": 0.95},
            {"y_px": 270, "price": 60000.0, "score": 0.95},
        ]
        reference = {
            "open": 107600.0,
            "high": 109333.333333,
            "low": 106933.333333,
            "close": 108666.666667,
        }
        with patch(
            "mirsad.engines.chart.detect_price_axis_ticks",
            return_value={"status": "TICKS_FOUND", "ticks": ticks, "candidate_plot_right_px": None},
        ):
            result = self._analyze(metadata={
                "price_top": 0.0,
                "price_bottom": 0.0,
                "auto_axis_ocr": True,
                "allow_reference_anchor_override": True,
                "expected_candle_count": 24,
                "reference_last_candle_ohlc": reference,
            })
        self.assertEqual(result["axis_ocr"]["fit"]["status"], "READY")
        self.assertEqual(result["calibration"]["source"], "reference_last_candle_ohlc")
        self.assertEqual(result["reference_calibration"]["status"], "READY")
        self.assertEqual(result["reference_axis_validation"]["status"], "READY")
        self.assertEqual(
            result["reference_axis_validation"]["method"],
            "native_ohlc_anchor_replaced_inconsistent_ocr",
        )
        self.assertEqual(
            result["reference_axis_validation"]["ocr_axis_validation"]["status"],
            "REFERENCE_AXIS_MISMATCH",
        )
        self.assertTrue(result["reference_ohlc_override_applied"])
        self.assertTrue(result["decision_eligible"])

    def test_native_reference_mismatch_blocks_an_otherwise_valid_manual_axis(self) -> None:
        result = self._analyze(metadata={
            "reference_last_candle_ohlc": {
                "open": 109100.0,
                "high": 110833.333333,
                "low": 108433.333333,
                "close": 110166.666667,
            },
        })
        self.assertTrue(result["calibration"]["price_scale_valid"])
        self.assertEqual(result["reference_axis_validation"]["status"], "REFERENCE_AXIS_MISMATCH")
        self.assertFalse(result["reference_ohlc_override_applied"])
        self.assertFalse(result["quality_gates"]["native_reference_candle_verified"])
        self.assertFalse(result["decision_eligible"])

    def test_reference_body_pixels_must_agree_with_wick_scale_fit(self) -> None:
        result = self._analyze(metadata={
            "price_top": None,
            "price_bottom": None,
            "reference_last_candle_ohlc": {
                "open": 120.8,
                "high": 121.0,
                "low": 119.2,
                "close": 120.9,
            },
        })
        self.assertEqual(
            result["reference_calibration"]["status"],
            "REFERENCE_FIT_REJECTED",
        )
        self.assertFalse(result["calibration"]["price_scale_valid"])
        self.assertFalse(result["decision_eligible"])

    def test_reference_candle_colour_conflict_blocks_anchor_calibration(self) -> None:
        result = self._analyze(metadata={
            "price_top": None,
            "price_bottom": None,
            "reference_last_candle_ohlc": {
                "open": 120.5,
                "high": 121.0,
                "low": 119.2,
                "close": 119.7,
            },
        })
        self.assertEqual(
            result["reference_calibration"]["status"],
            "REFERENCE_DIRECTION_MISMATCH",
        )
        self.assertFalse(result["calibration"]["price_scale_valid"])
        self.assertFalse(result["decision_eligible"])

    def test_calibrated_chart_detects_bars_and_returns_consistent_ohlc(self) -> None:
        result = self._analyze(direction="up", colour="GREEN")
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["decision_eligible"])
        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(result["calibrated_bar_count"], result["detected_bar_count"])
        first = result["bars"][0]
        self.assertLess(first["open"], first["close"])
        self.assertGreaterEqual(first["high"], max(first["open"], first["close"]))
        self.assertLessEqual(first["low"], min(first["open"], first["close"]))

    def test_virtual_positive_scale_is_valid_for_normalized_chart_images(self) -> None:
        result = self._analyze(
            direction="up",
            colour="GREEN",
            metadata={"price_top": 2.0, "price_bottom": 1.0},
        )
        self.assertTrue(result["calibration"]["price_scale_valid"])
        self.assertTrue(result["decision_eligible"])
        self.assertEqual(result["calibrated_bar_count"], result["detected_bar_count"])
        self.assertEqual(result["visual_bias"], "BULLISH")

    def test_high_resolution_wide_candles_are_not_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "wide_candles.png"
            width, height = 1000, self.HEIGHT
            image = np.full((height, width, 3), 255, dtype=np.uint8)
            for index in range(24):
                close_y = 210 - index * 4
                open_y = close_y + 8
                x = 20 + index * 40
                cv2.line(image, (x, close_y - 5), (x, open_y + 5), (0, 200, 0), 1)
                cv2.rectangle(image, (x - 9, close_y), (x + 9, open_y), (0, 200, 0), -1)
            self.assertTrue(cv2.imwrite(str(path), image))
            metadata = dict(self.META)
            metadata["plot_right_px"] = width
            result = analyze_chart_image(path, metadata, expected_symbol="BTCUSDT")

        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(result["visual_bias"], "BULLISH")
        self.assertTrue(result["decision_eligible"])
        self.assertEqual(result["extraction_diagnostics"]["maximum_bar_width"], 20)

    def test_known_candle_count_allows_fixed_slot_widths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixed_slot_chart.png"
            width, height = 640, self.HEIGHT
            image = np.full((height, width, 3), 255, dtype=np.uint8)
            for index in range(20):
                close_y = 210 - index * 6
                open_y = close_y + 8
                x = 24 + index * 31
                cv2.line(image, (x, close_y - 5), (x, open_y + 5), (0, 200, 0), 1)
                cv2.rectangle(image, (x - 9, close_y), (x + 9, open_y), (0, 200, 0), -1)
            self.assertTrue(cv2.imwrite(str(path), image))
            metadata = dict(self.META)
            metadata.update({
                "plot_right_px": width,
                "expected_candle_count": 20,
            })
            result = analyze_chart_image(path, metadata, expected_symbol="BTCUSDT")

        self.assertGreaterEqual(result["detected_bar_count"], 18)
        self.assertEqual(result["visual_bias"], "BULLISH")
        self.assertEqual(result["extraction_diagnostics"]["maximum_bar_width"], 34)

    def test_horizontal_indicator_line_does_not_merge_all_candles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "chart_with_moving_average.png"
            self._write_chart(path, direction="up", colour="GREEN", count=24)
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            cv2.line(image, (0, 50), (self.WIDTH - 1, 50), (0, 200, 0), thickness=2)
            self.assertTrue(cv2.imwrite(str(path), image))
            result = analyze_chart_image(path, self.META, expected_symbol="BTCUSDT")

        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(
            result["visual_bias"],
            "BULLISH",
            msg=repr({
                "bars": result["detected_bar_count"],
                "bias": result["visual_bias"],
                "score": result["analysis_score"],
                "confidence": result["analysis_confidence"],
                "trend": result["visual_trend"],
                "diagnostics": result["extraction_diagnostics"],
            }),
        )
        self.assertGreater(result["visual_trend"]["net_change"], 0)
        self.assertTrue(result["decision_eligible"])
        diagnostics = result["extraction_diagnostics"]
        self.assertGreater(diagnostics["raw_active_columns"], diagnostics["active_columns"])
        self.assertGreater(diagnostics["indicator_pixels_suppressed"], 0)
        self.assertGreaterEqual(diagnostics["vertical_kernel_height"], 3)

    def test_diagonal_moving_average_overlays_do_not_merge_fixed_slot_candles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "chart_with_diagonal_moving_averages.png"
            self._write_chart(path, direction="up", colour="GREEN", count=24)
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            cv2.line(
                image, (0, 42), (self.WIDTH - 1, 104),
                (0, 190, 0), thickness=2, lineType=cv2.LINE_AA,
            )
            cv2.line(
                image, (0, 280), (self.WIDTH - 1, 220),
                (0, 0, 210), thickness=2, lineType=cv2.LINE_AA,
            )
            self.assertTrue(cv2.imwrite(str(path), image))
            metadata = dict(self.META)
            metadata["expected_candle_count"] = 24
            result = analyze_chart_image(path, metadata, expected_symbol="BTCUSDT")
        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(result["visual_bias"], "BULLISH")
        component_filter = result["extraction_diagnostics"]["component_filter"]
        self.assertGreater(component_filter["raw_components"], 0)
        self.assertGreater(component_filter["retained_components"], 0)

    def test_visual_bias_uses_price_progression_not_green_candle_count(self) -> None:
        result = self._analyze(direction="down", colour="GREEN")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["visual_bias"], "BEARISH")
        self.assertGreater(result["visual_trend"]["falling_close_steps"], 0)
        self.assertLess(result["visual_trend"]["net_change"], 0)  # Pixel y rises as price falls, so price decreases.

    def test_red_candles_with_rising_closes_are_not_labelled_bearish(self) -> None:
        result = self._analyze(direction="up", colour="RED")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["visual_bias"], "BULLISH")

    def test_flat_calibrated_closes_remain_neutral_even_with_green_bodies(self) -> None:
        result = self._analyze(direction="flat", colour="GREEN")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["visual_bias"], "NEUTRAL")

    def test_analyzer_returns_trend_structure_support_and_confidence(self) -> None:
        result = self._analyze(direction="up", colour="GREEN")
        self.assertIn("analysis_score", result)
        self.assertGreater(result["analysis_score"], 0.3)
        self.assertGreaterEqual(result["analysis_confidence"], 0.55)
        self.assertIn("support", result["market_structure"])
        self.assertIn("resistance", result["market_structure"])
        self.assertIn("trend", result["analysis_components"])

    def test_chart_exposes_talib_reference_separate_from_visual_patterns(self) -> None:
        result = self._analyze()
        reference = result["reference_patterns"]
        self.assertEqual(reference["status"], "READY")
        self.assertEqual(reference["source"], "TA-Lib")
        self.assertGreaterEqual(reference["pattern_definition_count"], 50)
        self.assertIn("pattern_candidates", result)
        self.assertIn("events", reference)
        self.assertIn("not probabilities", reference["interpretation"])
        self.assertIn("never add both outputs", reference["interpretation"])

    def test_open_latest_candle_is_visible_but_excluded_from_confirmed_analysis(self) -> None:
        result = self._analyze(metadata={"last_candle_closed": False})
        self.assertEqual(
            result["confirmed_bar_count"],
            result["calibrated_bar_count"] - 1,
        )
        self.assertEqual(result["visual_trend"]["sample_bars"], result["confirmed_bar_count"])
        self.assertFalse(result["last_candle_closed"])
        self.assertEqual(result["latest_candle_state"], "FORMING_OR_UNVERIFIED")
        self.assertEqual(result["bars"][-1]["candle_state"], "FORMING_OR_UNVERIFIED")

    def test_unverified_latest_candle_cannot_satisfy_minimum_closed_bar_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "twenty_bar_chart.png"
            self._write_chart(path, count=20)
            metadata = dict(self.META)
            metadata["last_candle_closed"] = False
            result = analyze_chart_image(path, metadata, expected_symbol="BTCUSDT")
        self.assertEqual(result["calibrated_bar_count"], 20)
        self.assertEqual(result["confirmed_bar_count"], 19)
        self.assertFalse(result["decision_eligible"])
        self.assertFalse(result["quality_gates"]["minimum_candle_count"])

    def test_insufficient_calibrated_history_returns_neutral_without_crashing(self) -> None:
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "colour_purity": 1.0}
            for _ in range(5)
        ]
        result = analyze_calibrated_bars(bars, top_price=110.0, bottom_price=90.0)
        self.assertEqual(result["visual_bias"], "NEUTRAL")
        self.assertEqual(result["analysis_score"], 0.0)
        self.assertEqual(result["analysis_confidence"], 0.0)
        self.assertEqual(result["visual_trend"]["direction"], "NEUTRAL")

    def test_flat_calibrated_history_returns_neutral_bias(self) -> None:
        bars = [
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
             "x_px": i * 10, "colour_purity": 0.99}
            for i in range(12)
        ]
        result = analyze_calibrated_bars(bars, top_price=110.0, bottom_price=90.0)
        self.assertEqual(result["visual_bias"], "NEUTRAL")
        self.assertEqual(result["visual_trend"]["direction"], "NEUTRAL")
        self.assertEqual(result["visual_trend"]["score"], 0.0)

    def test_minimum_move_and_directional_consistency_suppress_noise(self) -> None:
        closes = [100.0, 100.03, 99.99, 100.02, 100.01, 100.04, 100.02, 100.05]
        bars = [
            {"open": close, "high": close + 0.5, "low": close - 0.5,
             "close": close, "x_px": i * 10, "colour_purity": 1.0}
            for i, close in enumerate(closes)
        ]
        result = analyze_calibrated_bars(bars, top_price=110.0, bottom_price=90.0)
        self.assertEqual(result["visual_trend"]["direction"], "NEUTRAL")
        self.assertFalse(result["visual_trend"]["minimum_move_met"])
        self.assertEqual(result["visual_trend"]["score"], 0.0)

    def test_trend_metrics_include_short_medium_and_long_windows(self) -> None:
        result = self._analyze(direction="up", colour="GREEN")
        windows = result["visual_trend"]["windows"]
        self.assertEqual(set(windows), {"short_6", "medium_12", "long_30"})
        self.assertEqual(windows["long_30"]["direction"], "BULLISH")

    def test_market_structure_reports_pivot_indices_and_watch_zones(self) -> None:
        closes = [
            100, 102, 104, 106, 103, 101,
            108, 112, 116, 120, 116, 112,
            124, 128, 132, 136, 132, 128,
            140, 144, 148, 152, 148, 144,
            156, 160, 164, 160, 156, 154,
        ]
        bars = []
        for index, close in enumerate(closes):
            bars.append({
                "open": float(close),
                "high": float(close) + 0.5,
                "low": float(close) - 0.5,
                "close": float(close),
                "x_px": index * 10,
                "colour_purity": 0.99,
            })
        result = analyze_calibrated_bars(bars, top_price=120.0, bottom_price=90.0)
        structure = result["market_structure"]
        self.assertEqual(result["visual_bias"], "BULLISH")
        self.assertTrue(structure["swing_highs"])
        self.assertTrue(structure["swing_lows"])
        self.assertTrue(all(0 <= p["index"] < len(bars) for p in structure["swing_highs"]))
        self.assertTrue(all(0 <= p["index"] < len(bars) for p in structure["swing_lows"]))
        for pivot in structure["swing_highs"] + structure["swing_lows"]:
            self.assertTrue(pivot["confirmed"])
            self.assertEqual(pivot["confirmation_index"], pivot["index"] + 2)
            self.assertEqual(pivot["confirmation_delay_bars"], 2)
            self.assertEqual(
                pivot["confirmation_x_px"],
                bars[pivot["confirmation_index"]]["x_px"],
            )
        self.assertTrue(structure["support_zones"])
        self.assertTrue(structure["resistance_zones"])
        self.assertIsNotNone(structure["entry_zone"])
        self.assertIsNotNone(structure["exit_zone"])
        self.assertEqual(structure["entry_zone"]["status"], "OBSERVATION_ONLY")

    @staticmethod
    def _structure_bars(closes, *, last_high=None, last_low=None):
        bars = []
        for index, close in enumerate(closes):
            high = float(close) + 0.5
            low = float(close) - 0.5
            if index == len(closes) - 1:
                if last_high is not None:
                    high = float(last_high)
                if last_low is not None:
                    low = float(last_low)
            bars.append({
                "open": float(close),
                "high": high,
                "low": low,
                "close": float(close),
                "x_px": index * 10,
                "colour_purity": 0.99,
            })
        return bars

    def test_confirmed_swing_break_emits_bullish_bos_on_close(self) -> None:
        closes = [
            100, 102, 104, 106, 104, 102,
            108, 112, 116, 120, 116, 112,
            124, 128, 132, 136, 132, 128,
            140, 144, 148, 152, 148, 144, 150, 154,
        ]
        result = analyze_calibrated_bars(
            self._structure_bars(closes), top_price=180.0, bottom_price=90.0
        )
        events = result["market_structure"]["structure_events"]
        self.assertTrue(any(event["event"] == "BOS_BULLISH" for event in events))
        self.assertTrue(all(event["confirmation_index"] == len(closes) - 1 for event in events))

    def test_break_against_bullish_structure_emits_bearish_choch(self) -> None:
        closes = [
            100, 102, 104, 106, 104, 102,
            108, 112, 116, 120, 116, 112,
            124, 128, 132, 136, 132, 128,
            140, 144, 148, 152, 148, 143, 146, 147, 140,
        ]
        result = analyze_calibrated_bars(
            self._structure_bars(closes), top_price=180.0, bottom_price=90.0
        )
        structure = result["market_structure"]
        self.assertEqual(structure["prior_structure_direction"], "BULLISH")
        self.assertTrue(any(event["event"] == "CHOCH_BEARISH" for event in structure["structure_events"]))

    def test_wick_through_confirmed_swing_is_liquidity_sweep_not_bos(self) -> None:
        closes = [
            100, 102, 104, 106, 104, 102,
            108, 112, 116, 120, 116, 112,
            124, 128, 132, 136, 132, 128,
            140, 144, 148, 152, 148, 144, 150, 149,
        ]
        bars = self._structure_bars(closes, last_high=155.0)
        result = analyze_calibrated_bars(bars, top_price=180.0, bottom_price=90.0)
        structure = result["market_structure"]
        self.assertFalse(any(
            event["event"] == "BOS_BULLISH"
            for event in structure["structure_events"]
        ))
        self.assertTrue(any(
            event["event"] == "HIGH_LIQUIDITY_SWEEP"
            and event["side"] == "BEARISH_REJECTION"
            for event in structure["liquidity_sweeps"]
        ))

    def test_ocr_axis_calibration_is_used_only_when_manual_axis_is_missing(self) -> None:
        ticks = [
            {"y_px": 30, "price": 120000.0, "score": 0.95},
            {"y_px": 110, "price": 100000.0, "score": 0.95},
            {"y_px": 190, "price": 80000.0, "score": 0.95},
            {"y_px": 270, "price": 60000.0, "score": 0.95},
        ]
        with patch(
            "mirsad.engines.chart.detect_price_axis_ticks",
            return_value={"status": "TICKS_FOUND", "ticks": ticks, "candidate_plot_right_px": None},
        ):
            result = self._analyze(
                metadata={"price_top": 0.0, "price_bottom": 0.0, "auto_axis_ocr": True}
            )
        self.assertEqual(result["calibration"]["source"], "ocr")
        self.assertTrue(result["calibration"]["price_scale_valid"])
        self.assertTrue(result["decision_eligible"])
        self.assertEqual(result["axis_ocr"]["fit"]["status"], "READY")

    def test_manual_axis_values_take_precedence_over_ocr(self) -> None:
        with patch("mirsad.engines.chart.detect_price_axis_ticks") as mocked_ocr:
            result = self._analyze(metadata={"auto_axis_ocr": True})
        mocked_ocr.assert_not_called()
        self.assertEqual(result["calibration"]["source"], "manual")

    def test_logarithmic_axis_uses_geometric_midpoint(self) -> None:
        calibration = {
            "price_scale_valid": True,
            "price_scale_type": "logarithmic",
            "price_top": 1000.0,
            "price_bottom": 100.0,
            "plot_top_px": 0,
            "plot_bottom_px": 100,
        }
        midpoint = price_at_pixel(50, calibration)
        self.assertAlmostEqual(midpoint, 316.227766, places=5)

    def test_linear_axis_midpoint_is_arithmetic(self) -> None:
        calibration = {
            "price_scale_valid": True,
            "price_scale_type": "linear",
            "price_top": 1000.0,
            "price_bottom": 100.0,
            "plot_top_px": 0,
            "plot_bottom_px": 100,
        }
        self.assertAlmostEqual(price_at_pixel(50, calibration), 550.0)

    def test_unsupported_axis_scale_blocks_analysis(self) -> None:
        result = self._analyze(metadata={"price_scale_type": "square_root"})
        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(result["decision_eligible"])

    def test_expected_candle_count_outside_safe_range_is_rejected(self) -> None:
        result = self._analyze(metadata={"expected_candle_count": 501})
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("expected_candle_count", result["error"])

    def test_image_pixel_limit_is_checked_before_opencv_decode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "large_dimensions.png"
            image = np.full((64, 64, 3), 255, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(path), image))
            with patch("mirsad.engines.chart_image.MAX_IMAGE_PIXELS", 1000):
                decoded, error = load_chart_image(path)
        self.assertIsNone(decoded)
        self.assertIn("pixel safety limit", error)

    def test_image_file_size_limit_is_checked_before_decode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "oversized.png"
            path.write_bytes(b"123456")
            with patch("mirsad.engines.chart_image.MAX_IMAGE_BYTES", 5):
                image, error = load_chart_image(path)
        self.assertIsNone(image)
        self.assertIn("exceeds", error)

    def test_logarithmic_calibration_metadata_is_validated(self) -> None:
        calibration = resolve_chart_calibration(
            {
                "plot_left_px": 0, "plot_top_px": 0,
                "plot_right_px": 500, "plot_bottom_px": 320,
                "price_top": 1000.0, "price_bottom": 100.0,
                "price_scale_type": "logarithmic",
            },
            image_width=500,
            image_height=320,
        )
        self.assertTrue(calibration["price_scale_valid"])
        self.assertEqual(calibration["price_scale_type"], "logarithmic")

    def test_image_crop_bounds_outside_image_return_controlled_error(self) -> None:
        result = self._analyze(metadata={"plot_left_px": 700, "plot_right_px": 800})
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("Invalid chart crop metadata", result["error"])

    def test_non_finite_price_axis_is_not_accepted(self) -> None:
        result = self._analyze(metadata={"price_top": float("inf")})
        self.assertFalse(result["decision_eligible"])
        self.assertFalse(result["calibration"]["price_scale_valid"])

    def test_blue_orange_palette_extracts_directional_candles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "blue_orange.png"
            image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
            bullish_bgr = (220, 90, 20)
            for index in range(24):
                close_y = 210 - index * 5
                open_y = close_y + 8
                x = 12 + index * 20
                cv2.line(image, (x, close_y - 5), (x, open_y + 5), bullish_bgr, 1)
                cv2.rectangle(image, (x - 2, close_y), (x + 2, open_y), bullish_bgr, -1)
            self.assertTrue(cv2.imwrite(str(path), image))
            meta = dict(self.META)
            meta["palette_mode"] = "blue_orange"
            result = analyze_chart_image(path, meta, expected_symbol="BTCUSDT")
        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(result["visual_bias"], "BULLISH")
        self.assertTrue(result["decision_eligible"])

    def test_auto_palette_detects_teal_and_magenta_candles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "teal_magenta.png"
            image = np.full((self.HEIGHT, self.WIDTH, 3), 245, dtype=np.uint8)
            bullish_bgr = (170, 130, 0)
            for index in range(24):
                close_y = 210 - index * 5
                open_y = close_y + 8
                x = 12 + index * 20
                cv2.line(image, (x, close_y - 5), (x, open_y + 5), bullish_bgr, 1)
                cv2.rectangle(image, (x - 2, close_y), (x + 2, open_y), bullish_bgr, -1)
            self.assertTrue(cv2.imwrite(str(path), image))
            result = analyze_chart_image(path, self.META, expected_symbol="BTCUSDT")
        self.assertGreaterEqual(result["detected_bar_count"], 20)
        self.assertEqual(result["visual_bias"], "BULLISH")

    def test_last_bar_must_be_near_the_right_side_of_price_plot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "left_only.png"
            image = np.full((self.HEIGHT, self.WIDTH, 3), 255, dtype=np.uint8)
            for index in range(12):
                close_y = 210 - index * 5
                open_y = close_y + 8
                x = 12 + index * 18
                cv2.line(image, (x, close_y - 5), (x, open_y + 5), (0, 200, 0), 1)
                cv2.rectangle(image, (x - 2, close_y), (x + 2, open_y), (0, 200, 0), -1)
            self.assertTrue(cv2.imwrite(str(path), image))
            result = analyze_chart_image(path, self.META, expected_symbol="BTCUSDT")
        self.assertFalse(result["decision_eligible"])
        self.assertLess(result["last_bar_x_ratio"], 0.68)

    def test_symbol_mismatch_blocks_decision_eligibility(self) -> None:
        result = self._analyze(expected="ETHUSDT")
        self.assertFalse(result["decision_eligible"])
        self.assertFalse(result["calibration"]["symbol_matches"])

    def test_invalid_price_scale_blocks_decision_eligibility(self) -> None:
        result = self._analyze(metadata={"price_top": 80000.0, "price_bottom": 120000.0})
        self.assertFalse(result["decision_eligible"])
        self.assertFalse(result["calibration"]["price_scale_valid"])

    def test_unreadable_image_returns_error_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            invalid = Path(temp) / "not_an_image.png"
            invalid.write_text("not an image", encoding="utf-8")
            result = analyze_chart_image(invalid, self.META, expected_symbol="BTCUSDT")
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("could not be read", result["error"])


if __name__ == "__main__":
    unittest.main()
