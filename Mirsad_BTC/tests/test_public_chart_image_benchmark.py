from __future__ import annotations

import unittest

from scripts.run_public_chart_image_benchmark import _bar_direction, _crop_box, _ohlc_comparison


class PublicChartImageBenchmarkTests(unittest.TestCase):
    def test_crop_box_uses_normalized_coordinates(self) -> None:
        self.assertEqual(_crop_box(1000, 500, [0.1, 0.2, 0.9, 0.8]), (100, 100, 900, 400))\n        self.assertEqual(\n            _crop_box(1000, 500, [0.1, 0.2, 0.9, 0.8], preserve_right_axis=True),\n            (100, 100, 1000, 400),\n        )

    def test_crop_box_rejects_out_of_bounds_and_tiny_regions(self) -> None:
        with self.assertRaises(ValueError):
            _crop_box(1000, 500, [0.8, 0.2, 0.1, 0.9])
        with self.assertRaises(ValueError):
            _crop_box(100, 100, [0.0, 0.0, 0.5, 0.5])

    def test_last_bar_direction_uses_calibrated_ohlc_when_available(self) -> None:
        self.assertEqual(_bar_direction({"open": 10.0, "close": 11.0, "colour": "RED"}), "BULLISH")
        self.assertEqual(_bar_direction({"open": 11.0, "close": 10.0, "colour": "GREEN"}), "BEARISH")
        self.assertEqual(_bar_direction({"open": 10.0, "close": 10.0}), "DOJI")

    def test_ohlc_comparison_reports_per_field_calibration_error(self) -> None:\n        result = _ohlc_comparison(\n            {\"open\": 100.0, \"high\": 103.0, \"low\": 98.0, \"close\": 102.0},\n            {\"open\": 100.0, \"high\": 102.0, \"low\": 98.0, \"close\": 102.0},\n        )\n        self.assertEqual(result[\"absolute_error_pct_by_field\"][\"high\"], 0.9804)\n        self.assertTrue(result[\"within_3pct_tolerance\"])\n\n    def test_last_bar_direction_falls_back_to_detected_palette(self) -> None:
        self.assertEqual(_bar_direction({"colour": "GREEN"}), "BULLISH")
        self.assertEqual(_bar_direction({"colour": "ORANGE"}), "BEARISH")
        self.assertIsNone(_bar_direction({}))


if __name__ == "__main__":
    unittest.main()
