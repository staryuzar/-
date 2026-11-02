from __future__ import annotations

import unittest

from scripts.run_public_chart_image_benchmark import (
    _bar_direction,
    _crop_box,
    _failed_quality_gates,
    _ohlc_comparison,
    _trend_window_snapshot,
)


class PublicChartImageBenchmarkTests(unittest.TestCase):
    def test_crop_box_uses_normalized_coordinates(self) -> None:
        self.assertEqual(
            _crop_box(1000, 500, [0.1, 0.2, 0.9, 0.8]),
            (100, 100, 900, 400),
        )
        self.assertEqual(
            _crop_box(
                1000,
                500,
                [0.1, 0.2, 0.9, 0.8],
                preserve_right_axis=True,
            ),
            (100, 100, 1000, 400),
        )

    def test_crop_box_rejects_out_of_bounds_and_tiny_regions(self) -> None:
        with self.assertRaises(ValueError):
            _crop_box(1000, 500, [0.8, 0.2, 0.1, 0.9])
        with self.assertRaises(ValueError):
            _crop_box(100, 100, [0.0, 0.0, 0.5, 0.5])

    def test_last_bar_direction_uses_calibrated_ohlc_when_available(self) -> None:
        self.assertEqual(
            _bar_direction({"open": 10.0, "close": 11.0, "colour": "RED"}),
            "BULLISH",
        )
        self.assertEqual(
            _bar_direction({"open": 11.0, "close": 10.0, "colour": "GREEN"}),
            "BEARISH",
        )
        self.assertEqual(_bar_direction({"open": 10.0, "close": 10.0}), "DOJI")

    def test_ohlc_comparison_reports_per_field_calibration_error(self) -> None:
        result = _ohlc_comparison(
            {"open": 100.0, "high": 103.0, "low": 98.0, "close": 102.0},
            {"open": 100.0, "high": 102.0, "low": 98.0, "close": 102.0},
        )
        self.assertEqual(result["absolute_error_pct_by_field"]["high"], 0.9804)
        self.assertTrue(result["within_3pct_tolerance"])

    def test_trend_snapshot_preserves_mixed_time_horizons(self) -> None:
        snapshot = _trend_window_snapshot({
            "windows": {
                "short_6": {"status": "READY", "sample_bars": 6, "direction": "BEARISH", "score": -0.4},
                "medium_12": {"status": "READY", "sample_bars": 12, "direction": "BULLISH", "score": 0.3},
                "long_30": {"status": "READY", "sample_bars": 30, "direction": "BULLISH", "score": 0.2},
            }
        })
        self.assertEqual(snapshot["short_6"]["direction"], "BEARISH")
        self.assertEqual(snapshot["medium_12"]["direction"], "BULLISH")
        self.assertEqual(snapshot["long_30"]["direction"], "BULLISH")

    def test_failed_quality_gates_are_reported_without_promoting_chart(self) -> None:
        self.assertEqual(
            _failed_quality_gates({
                "price_axis_calibrated": True,
                "minimum_candle_count": False,
                "latest_candle_near_right_edge": False,
            }),
            ["latest_candle_near_right_edge", "minimum_candle_count"],
        )

    def test_last_bar_direction_falls_back_to_detected_palette(self) -> None:
        self.assertEqual(_bar_direction({"colour": "GREEN"}), "BULLISH")
        self.assertEqual(_bar_direction({"colour": "ORANGE"}), "BEARISH")
        self.assertIsNone(_bar_direction({}))


if __name__ == "__main__":
    unittest.main()
