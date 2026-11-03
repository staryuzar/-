from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from mirsad.engines.chart_ocr import (
    detect_price_axis_ticks,
    fit_price_axis,
    infer_plot_bottom_from_axis_ticks,
    parse_price_label,
)


class ChartOCRTests(unittest.TestCase):
    def test_parse_price_labels_with_separators_and_suffixes(self) -> None:
        self.assertEqual(parse_price_label("BTC 120,500.25"), 120500.25)
        self.assertEqual(parse_price_label("105.5K"), 105500.0)
        self.assertEqual(parse_price_label("1.25M"), 1250000.0)
        self.assertEqual(parse_price_label("90 000"), 90000.0)
        self.assertIsNone(parse_price_label("RSI 14"))
        self.assertIsNone(parse_price_label(""))
        self.assertIsNone(parse_price_label("RSI 14"))
        self.assertIsNone(parse_price_label("EMA 200"))

    def test_parse_price_label_normalizes_arabic_indic_digits(self) -> None:
        self.assertEqual(parse_price_label("١٢٠٬٠٠٠"), 120000.0)

    def test_parse_price_labels_with_european_and_arabic_decimal_separators(self) -> None:
        self.assertEqual(parse_price_label("92.500,25"), 92500.25)
        self.assertEqual(parse_price_label("92,500.25"), 92500.25)
        self.assertEqual(parse_price_label("1 234 567,89"), 1234567.89)
        self.assertEqual(parse_price_label("١٢٠٬٠٠٠٫٥٠"), 120000.50)
        self.assertEqual(parse_price_label("1.234.567,89"), 1234567.89)
        self.assertEqual(parse_price_label("1,234,567"), 1234567.0)
        self.assertEqual(parse_price_label("0.125"), 0.125)

    def test_parse_price_label_rejects_malformed_grouping_and_percent_axes(self) -> None:
        self.assertIsNone(parse_price_label("12,34,56"))
        self.assertIsNone(parse_price_label("50%"))
        self.assertIsNone(parse_price_label("1.23.45,6"))

    def test_linear_axis_is_fitted_from_four_consistent_ticks(self) -> None:
        ticks = [
            {"y_px": 30, "price": 120000, "score": 0.95},
            {"y_px": 110, "price": 100000, "score": 0.93},
            {"y_px": 190, "price": 80000, "score": 0.94},
            {"y_px": 270, "price": 60000, "score": 0.96},
        ]
        result = fit_price_axis(ticks, plot_top_px=10, plot_bottom_px=310, scale_type="linear")
        self.assertEqual(result["status"], "READY")
        self.assertAlmostEqual(result["price_top"], 125000.0, places=3)
        self.assertAlmostEqual(result["price_bottom"], 50000.0, places=3)
        self.assertGreaterEqual(result["confidence"], 0.95)

    def test_logarithmic_axis_is_fitted_in_log_price_space(self) -> None:
        ticks = [
            {"y_px": 20, "price": 100000, "score": 0.95},
            {"y_px": 90, "price": 50000, "score": 0.95},
            {"y_px": 160, "price": 25000, "score": 0.95},
            {"y_px": 230, "price": 12500, "score": 0.95},
        ]
        result = fit_price_axis(ticks, plot_top_px=10, plot_bottom_px=250, scale_type="logarithmic")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["scale_type"], "logarithmic")
        self.assertGreater(result["price_top"], result["price_bottom"])
        self.assertGreater(result["price_bottom"], 0)

    def test_axis_fit_rejects_three_or_fewer_labels(self) -> None:
        ticks = [
            {"y_px": 20, "price": 100, "score": 0.9},
            {"y_px": 80, "price": 90, "score": 0.9},
            {"y_px": 140, "price": 80, "score": 0.9},
        ]
        result = fit_price_axis(ticks, plot_top_px=0, plot_bottom_px=180)
        self.assertEqual(result["status"], "INSUFFICIENT_TICKS")

    def test_axis_fit_rejects_non_monotonic_tick_values(self) -> None:
        ticks = [
            {"y_px": 20, "price": 100, "score": 0.9},
            {"y_px": 60, "price": 150, "score": 0.9},
            {"y_px": 100, "price": 80, "score": 0.9},
            {"y_px": 140, "price": 180, "score": 0.9},
        ]
        result = fit_price_axis(ticks, plot_top_px=0, plot_bottom_px=180)
        self.assertNotEqual(result["status"], "READY")

    def test_axis_fit_rejects_invalid_price_scale(self) -> None:
        ticks = [
            {"y_px": 20, "price": 100, "score": 0.9},
            {"y_px": 60, "price": 90, "score": 0.9},
            {"y_px": 100, "price": 80, "score": 0.9},
            {"y_px": 140, "price": 70, "score": 0.9},
        ]
        result = fit_price_axis(ticks, plot_top_px=0, plot_bottom_px=180, scale_type="percent")
        self.assertEqual(result["status"], "INVALID_SCALE")

    def test_detect_price_axis_ticks_uses_ocr_boxes_and_confidence(self) -> None:
        class FakeOCR:
            def __call__(self, image):
                return SimpleNamespace(
                    txts=["120,000", "100,000", "80,000", "60,000", "noise"],
                    scores=[0.95, 0.90, 0.92, 0.88, 0.99],
                    boxes=np.asarray([
                        [[20, 20], [75, 20], [75, 32], [20, 32]],
                        [[20, 90], [75, 90], [75, 102], [20, 102]],
                        [[20, 160], [75, 160], [75, 172], [20, 172]],
                        [[20, 230], [75, 230], [75, 242], [20, 242]],
                        [[20, 260], [65, 260], [65, 272], [20, 272]],
                    ], dtype=float),
                )

        image = np.full((320, 500, 3), 255, dtype=np.uint8)
        with patch("mirsad.engines.chart_ocr._get_ocr_engine", return_value=FakeOCR()):
            result = detect_price_axis_ticks(image, plot_top_px=10, plot_bottom_px=310)
        self.assertEqual(result["status"], "TICKS_FOUND")
        self.assertEqual(len(result["ticks"]), 4)
        self.assertEqual(result["ticks"][0]["price"], 120000.0)
        self.assertGreater(result["candidate_plot_right_px"], 410)

    def test_empty_numpy_ocr_boxes_are_no_text_not_an_ocr_crash(self) -> None:
        class EmptyOCR:
            def __call__(self, image):
                return SimpleNamespace(
                    txts=(),
                    scores=(),
                    boxes=np.empty((0, 4, 2), dtype=np.float32),
                )

        image = np.full((320, 500, 3), 255, dtype=np.uint8)
        with patch("mirsad.engines.chart_ocr._get_ocr_engine", return_value=EmptyOCR()):
            result = detect_price_axis_ticks(image)
        self.assertEqual(result["status"], "NO_NUMERIC_TICKS")
        self.assertEqual(result["ticks"], [])

    def test_detect_price_axis_ticks_reports_unavailable_engine_without_crashing(self) -> None:
        image = np.full((320, 500, 3), 255, dtype=np.uint8)
        with patch(
            "mirsad.engines.chart_ocr._get_ocr_engine",
            side_effect=RuntimeError("missing OCR backend"),
        ):
            result = detect_price_axis_ticks(image)
        self.assertEqual(result["status"], "OCR_UNAVAILABLE")
        self.assertIn("missing OCR backend", result["reason"])


    def test_infer_plot_bottom_excludes_an_unlabelled_volume_overlay_band(self) -> None:
        ticks = [
            {
                "y_px": 60 + index * 20,
                "price": 120000 - index * 1000,
                "score": 0.95,
                "inlier": True,
            }
            for index in range(23)
        ]
        result = infer_plot_bottom_from_axis_ticks(
            ticks,
            plot_top_px=0,
            current_plot_bottom_px=595,
        )
        self.assertEqual(result["status"], "REFINED")
        self.assertEqual(result["tick_bottom_y_px"], 500.0)
        self.assertGreater(result["plot_bottom_px"], result["tick_bottom_y_px"])
        self.assertLess(result["plot_bottom_px"], 535)
        self.assertGreater(result["excluded_bottom_band_px"], 50)

    def test_infer_plot_bottom_uses_native_geometry_to_confirm_volume_band(self) -> None:
        ticks = [
            {"y_px": 30 + index * 32, "price": 120000 - index * 1000,
             "score": 0.95, "inlier": True}
            for index in range(17)
        ]
        result = infer_plot_bottom_from_axis_ticks(
            ticks, plot_top_px=0, current_plot_bottom_px=595,
            native_max_y_image_px=529.5,
        )
        self.assertEqual(result["status"], "REFINED")
        self.assertEqual(result["tick_bottom_y_px"], 542.0)
        self.assertEqual(result["plot_bottom_px"], 549)
        self.assertGreater(result["native_gap_px"], 64)

    def test_infer_plot_bottom_does_not_crop_when_native_candles_reach_image_bottom(self) -> None:
        ticks = [
            {"y_px": 30 + index * 32, "price": 120000 - index * 1000,
             "score": 0.95, "inlier": True}
            for index in range(17)
        ]
        result = infer_plot_bottom_from_axis_ticks(
            ticks, plot_top_px=0, current_plot_bottom_px=595,
            native_max_y_image_px=580,
        )
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertEqual(result["plot_bottom_px"], 595)

    def test_infer_plot_bottom_keeps_a_fully_labelled_plot_unchanged(self) -> None:
        ticks = [
            {
                "y_px": 60 + index * 20,
                "price": 120000 - index * 1000,
                "score": 0.95,
                "inlier": True,
            }
            for index in range(27)
        ]
        result = infer_plot_bottom_from_axis_ticks(
            ticks,
            plot_top_px=0,
            current_plot_bottom_px=595,
        )
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertEqual(result["plot_bottom_px"], 595)

    def test_infer_plot_bottom_ignores_outlier_ticks_and_requires_dense_coverage(self) -> None:
        ticks = [
            {"y_px": 60 + index * 20, "inlier": True}
            for index in range(5)
        ] + [
            {"y_px": 560, "inlier": False}
        ]
        result = infer_plot_bottom_from_axis_ticks(
            ticks,
            plot_top_px=0,
            current_plot_bottom_px=595,
        )
        self.assertEqual(result["status"], "UNCHANGED")
        self.assertEqual(result["plot_bottom_px"], 595)


if __name__ == "__main__":
    unittest.main()
