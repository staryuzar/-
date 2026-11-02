from __future__ import annotations

import unittest

from scripts.candlestick_pattern_benchmark import (
    CLASS_NAMES,
    _reference_class_id,
    aggregate,
)


class PatternBenchmarkReferenceTests(unittest.TestCase):
    def test_talib_pattern_names_map_to_the_eight_label_classes(self) -> None:
        cases = [
            ({"pattern": "CDLHAMMER", "side": "BULLISH"}, 0),
            ({"pattern": "CDLSHOOTINGSTAR", "side": "BEARISH"}, 1),
            ({"pattern": "CDLENGULFING", "side": "BULLISH"}, 2),
            ({"pattern": "CDLENGULFING", "side": "BEARISH"}, 3),
            ({"pattern": "CDLMORNINGSTAR", "side": "BULLISH"}, 4),
            ({"pattern": "CDLMORNINGDOJISTAR", "side": "BULLISH"}, 4),
            ({"pattern": "CDLEVENINGSTAR", "side": "BEARISH"}, 5),
            ({"pattern": "CDLEVENINGDOJISTAR", "side": "BEARISH"}, 5),
            ({"pattern": "CDLDOJI", "side": "NEUTRAL"}, 6),
            ({"pattern": "CDLHARAMI", "side": "BEARISH"}, 7),
            ({"pattern": "CDLHARAMICROSS", "side": "BULLISH"}, 7),
        ]
        for event, expected in cases:
            with self.subTest(event=event):
                self.assertEqual(_reference_class_id(event), expected)
        self.assertIsNone(_reference_class_id({"pattern": "CDLENGULFING", "side": "NEUTRAL"}))
        self.assertIsNone(_reference_class_id({"pattern": "CDLUNKNOWN", "side": "BULLISH"}))

    def test_visual_and_talib_reference_metrics_are_kept_separate(self) -> None:
        width = 1000
        x_margin = 0.8
        slot = width / (20 - 1 + 2 * x_margin)
        first_center = width * x_margin / (20 - 1 + 2 * x_margin)
        candle_15_center = first_center + 15 * slot

        result = aggregate([{
            "sample_index": 0,
            "sample_id": "SPY_TEST",
            "image_width": width,
            "image_height": 500,
            "status": "READY",
            "detected_bars": 20,
            "pattern_matches": {
                str(class_id): {
                    "tp": 0, "fp": 0, "fn": 1 if class_id == 0 else 0,
                    "predicted": 0, "ground_truth": 1 if class_id == 0 else 0,
                }
                for class_id in range(len(CLASS_NAMES))
            },
            "reference_pattern_matches": {
                str(class_id): {
                    "tp": 1 if class_id == 0 else 0,
                    "fp": 0,
                    "fn": 0,
                    "predicted": 1 if class_id == 0 else 0,
                    "ground_truth": 1 if class_id == 0 else 0,
                }
                for class_id in range(len(CLASS_NAMES))
            },
            "ground_truth": [{"class_id": 0, "cx": candle_15_center / width}],
            "predictions": [],
            "reference_predictions": [{"class_id": 0, "x_px": candle_15_center}],
            "reference_pattern_status": "READY",
        }])
        visual = result["per_class"]["Hammer"]
        reference = result["talib_reference_per_class"]["Hammer"]
        self.assertEqual(visual["tp"], 0)
        self.assertEqual(visual["fn"], 1)
        self.assertEqual(reference["tp"], 1)
        self.assertEqual(reference["fp"], 0)
        self.assertEqual(reference["fn"], 0)
        self.assertEqual(reference["f1"], 1.0)
        self.assertEqual(result["reference_status_counts"], {"READY": 1})


if __name__ == "__main__":
    unittest.main()
