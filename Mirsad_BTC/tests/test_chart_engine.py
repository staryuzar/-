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

    def test_visual_bias_uses_price_progression_not_green_candle_count(self) -> None:
        result = self._analyze(direction="down", colour="GREEN")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["visual_bias"], "BEARISH")
        self.assertGreater(result["visual_trend"]["falling_close_steps"], 0)
        self.assertGreater(result["visual_trend"]["net_change"], 0)  # Pixel y rises as price falls.

    def test_red_candles_with_rising_closes_are_not_labelled_bearish(self) -> None:
        result = self._analyze(direction="up", colour="RED")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["visual_bias"], "BULLISH")

    def test_flat_calibrated_closes_remain_neutral_even_with_green_bodies(self) -> None:
        result = self._analyze(direction="flat", colour="GREEN")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["visual_bias"], "NEUTRAL")

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
