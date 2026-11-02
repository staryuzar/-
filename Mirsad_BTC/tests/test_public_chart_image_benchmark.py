from __future__ import annotations

import unittest

from scripts.run_public_chart_image_benchmark import _bar_direction, _crop_box


class PublicChartImageBenchmarkTests(unittest.TestCase):
    def test_crop_box_uses_normalized_coordinates(self) -> None:
        self.assertEqual(_crop_box(1000, 500, [0.1, 0.2, 0.9, 0.8]), (100, 100, 900, 400))

    def test_crop_box_rejects_out_of_bounds_and_tiny_regions(self) -> None:
        with self.assertRaises(ValueError):
            _crop_box(1000, 500, [0.8, 0.2, 0.1, 0.9])
        with self.assertRaises(ValueError):
            _crop_box(100, 100, [0.0, 0.0, 0.5, 0.5])

    def test_last_bar_direction_uses_calibrated_ohlc_when_available(self) -> None:
        self.assertEqual(_bar_direction({"open": 10.0, "close": 11.0, "colour": "RED"}), "BULLISH")
        self.assertEqual(_bar_direction({"open": 11.0, "close": 10.0, "colour": "GREEN"}), "BEARISH")
        self.assertEqual(_bar_direction({"open": 10.0, "close": 10.0}), "DOJI")

    def test_last_bar_direction_falls_back_to_detected_palette(self) -> None:
        self.assertEqual(_bar_direction({"colour": "GREEN"}), "BULLISH")
        self.assertEqual(_bar_direction({"colour": "ORANGE"}), "BEARISH")
        self.assertIsNone(_bar_direction({}))


if __name__ == "__main__":
    unittest.main()
