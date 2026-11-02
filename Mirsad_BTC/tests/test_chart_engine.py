from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

from mirsad.engines.chart import _patterns, analyze_chart_image
from mirsad.engines.chart_calibration import price_at_pixel, resolve_chart_calibration
from mirsad.engines.chart_image import load_chart_image
from mirsad.engines.chart_metrics import analyze_calibrated_bars


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

    def _analyze(self, *, direction="up", colour="GREEN", metadata=None, expected="BTCUSDT"):
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "synthetic_chart.png"
            self._write_chart(image_path, direction=direction, colour=colour)
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
        self.assertTrue(structure["support_zones"])
        self.assertTrue(structure["resistance_zones"])
        self.assertIsNotNone(structure["entry_zone"])
        self.assertIsNotNone(structure["exit_zone"])
        self.assertEqual(structure["entry_zone"]["status"], "OBSERVATION_ONLY")

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
