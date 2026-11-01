from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from mirsad.engines.chart import analyze_chart_image


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
