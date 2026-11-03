from __future__ import annotations

import unittest

from mirsad.engines.chart_calibration import calibrate_from_reference_candles


def price_at(y: float, *, top: float = 120000.0, bottom: float = 80000.0) -> float:
    return top - ((y - 10.0) / 300.0) * (top - bottom)


def make_pairs(count: int = 24) -> list[dict]:
    pairs = []
    for slot in range(count):
        high_y = 35.0 + slot * 7.0
        low_y = high_y + 8.0
        body_top = high_y + 2.0
        body_bottom = high_y + 6.0
        pairs.append({
            "slot_index": slot,
            "closed": True,
            "bar": {
                "slot_index": slot,
                "x_px": 20.0 + slot * 40.0,
                "high_y_px": high_y,
                "low_y_px": low_y,
                "body_top_y_px": body_top,
                "body_bottom_y_px": body_bottom,
            },
            "ohlc": {
                "open": price_at(body_bottom),
                "high": price_at(high_y),
                "low": price_at(low_y),
                "close": price_at(body_top),
            },
        })
    return pairs


class MultiReferenceCalibrationTests(unittest.TestCase):
    def calibrate(self, pairs: list[dict]) -> dict:
        return calibrate_from_reference_candles(
            pairs,
            image_width=1000,
            image_height=400,
            plot_left_px=0,
            plot_top_px=10,
            plot_right_px=1000,
            plot_bottom_px=310,
            scale_type="linear",
        )

    def test_multi_candle_fit_passes_independent_interleaved_holdout(self) -> None:
        result = self.calibrate(make_pairs())
        self.assertEqual(result["status"], "READY", msg=repr(result))
        self.assertEqual(result["matched_candles"], 24)
        self.assertEqual(result["fit_candles"], 18)
        self.assertEqual(result["validation_candles"], 6)
        self.assertEqual(result["validation_passed_candles"], 6)
        self.assertGreaterEqual(result["validation_x_coverage"], 0.25)
        self.assertAlmostEqual(result["calibration"]["price_top"], 120000.0, places=3)
        self.assertAlmostEqual(result["calibration"]["price_bottom"], 80000.0, places=3)

    def test_multiple_bad_holdout_candles_block_calibration(self) -> None:
        pairs = make_pairs()
        for index in (0, 4):
            for field in ("open", "high", "low", "close"):
                pairs[index]["ohlc"][field] += 1500.0
        result = self.calibrate(pairs)
        self.assertEqual(result["status"], "REFERENCE_HOLDOUT_VALIDATION_FAILED")
        self.assertFalse(result.get("calibration"))

    def test_forming_candles_are_never_used_as_reference_points(self) -> None:
        pairs = make_pairs()
        for pair in pairs[-6:]:
            pair["closed"] = False
        result = self.calibrate(pairs)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["matched_candles"], 18)
        self.assertEqual(result["fit_candles"], 13)
        self.assertEqual(result["validation_candles"], 5)

    def test_reference_pairs_must_cover_the_chart_horizontally(self) -> None:
        pairs = make_pairs()
        for index, pair in enumerate(pairs):
            pair["bar"]["x_px"] = 100.0 + index * 5.0
        result = self.calibrate(pairs)
        self.assertEqual(result["status"], "REFERENCE_SPATIAL_COVERAGE_LOW")
        self.assertEqual(result["matched_candles"], 24)
        self.assertEqual(result["fit_candles"], 18)
        self.assertEqual(result["validation_candles"], 6)
        self.assertEqual(result["fit_x_coverage"], 0.11)


if __name__ == "__main__":
    unittest.main()
