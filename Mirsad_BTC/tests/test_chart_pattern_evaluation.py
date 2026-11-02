from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mirsad.engines.chart_pattern_evaluation import (
    evaluate_candle_pattern_detections,
    save_pattern_evaluation,
)
from mirsad.engines.visual_knowledge import seed_visual_knowledge
from mirsad.storage import connect


def rising_bars(count: int = 12) -> list[dict[str, float]]:
    closes = [100.0 + index * 2.0 for index in range(count)]
    return [
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
        for close in closes
    ]


class ChartPatternEvaluationTests(unittest.TestCase):
    def test_human_holdout_labels_measure_precision_and_fee_adjusted_outcomes(self) -> None:
        bars = rising_bars()
        detection = {
            "pattern_id": "hammer",
            "start_index": 0,
            "end_index": 0,
            "direction": "BULLISH",
        }
        evaluation = evaluate_candle_pattern_detections(
            bars,
            [detection],
            [detection],
            symbol="BTCUSDT",
            timeframe="5m",
            dataset_fingerprint="btc-human-holdout-v1",
            data_split="holdout",
            label_source="HUMAN_REVIEWED",
            manual_reviewed=True,
            horizons=(1, 2),
            fee_bps=5,
            slippage_bps=5,
            minimum_validation_samples=1,
        )
        pattern = evaluation["patterns"]["hammer"]
        self.assertEqual(pattern["true_positives"], 1)
        self.assertEqual(pattern["false_positives"], 0)
        self.assertEqual(pattern["false_negatives"], 0)
        self.assertEqual(pattern["precision"], 1.0)
        self.assertEqual(pattern["recall"], 1.0)
        self.assertEqual(pattern["f1"], 1.0)
        self.assertEqual(pattern["validation_status"], "VALIDATED")
        one_bar = pattern["horizon_metrics"]["1"]
        self.assertEqual(one_bar["sample_count"], 1)
        self.assertAlmostEqual(one_bar["mean_gross_return_pct"], 2.0, places=5)
        self.assertAlmostEqual(one_bar["round_trip_cost_pct"], 0.2, places=5)
        self.assertAlmostEqual(one_bar["mean_net_return_pct"], 1.8, places=5)
        self.assertEqual(
            evaluation["interpretation"].startswith("PATTERN_CLASSIFICATION_EVALUATION_ONLY"),
            True,
        )

    def test_matching_is_one_to_one_and_reports_false_positives_and_misses(self) -> None:
        bars = rising_bars()
        detections = [
            {"pattern_id": "hammer", "index": 1},
            {"pattern_id": "hammer", "index": 2},
        ]
        labels = [
            {"pattern_id": "hammer", "index": 1},
            {"pattern_id": "hammer", "index": 5},
        ]
        evaluation = evaluate_candle_pattern_detections(
            bars, detections, labels,
            symbol="BTCUSDT", timeframe="15m",
            dataset_fingerprint="btc-labelled-v2",
            data_split="validation",
            label_source="HUMAN", manual_reviewed=True,
            tolerance_bars=1, horizons=(1,),
        )
        pattern = evaluation["patterns"]["hammer"]
        self.assertEqual(pattern["true_positives"], 1)
        self.assertEqual(pattern["false_positives"], 1)
        self.assertEqual(pattern["false_negatives"], 1)
        self.assertEqual(pattern["precision"], 0.5)
        self.assertEqual(pattern["recall"], 0.5)
        self.assertEqual(pattern["validation_status"], "IN_PROGRESS")

    def test_machine_generated_labels_never_become_human_validated(self) -> None:
        bars = rising_bars()
        event = {"pattern_id": "hammer", "index": 0, "direction": "BULLISH"}
        evaluation = evaluate_candle_pattern_detections(
            bars, [event], [event],
            symbol="BTCUSDT", timeframe="1h",
            dataset_fingerprint="talib-generated-labels",
            data_split="holdout", label_source="TA-LIB",
            manual_reviewed=True, horizons=(1,), minimum_validation_samples=1,
        )
        self.assertEqual(
            evaluation["patterns"]["hammer"]["validation_status"],
            "UNVALIDATED",
        )

    def test_evaluation_is_stored_with_horizon_metrics_and_safe_schema_migration(self) -> None:
        bars = rising_bars()
        event = {"pattern_id": "hammer", "index": 0, "direction": "BULLISH"}
        evaluation = evaluate_candle_pattern_detections(
            bars, [event], [event],
            symbol="BTCUSDT", timeframe="1m",
            dataset_fingerprint="human-btc-set-a",
            data_split="holdout", label_source="HUMAN_REVIEWED",
            manual_reviewed=True, horizons=(1, 3),
            minimum_validation_samples=1,
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "visual.sqlite3"
            seed_visual_knowledge(str(path))
            stored = save_pattern_evaluation(
                evaluation, "hammer", primary_horizon_bars=1,
                db_path=str(path),
            )
            self.assertEqual(stored["status"], "STORED")
            self.assertEqual(stored["validation_status"], "VALIDATED")
            conn = connect(path)
            try:
                row = conn.execute(
                    "SELECT * FROM visual_pattern_evaluations WHERE pattern_id='hammer'"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row["primary_horizon_bars"], 1)
                self.assertEqual(row["data_split"], "holdout")
                self.assertEqual(row["label_source"], "HUMAN_REVIEWED")
                self.assertEqual(row["human_reviewed"], 1)
                self.assertIn('"3"', row["horizon_metrics_json"])
                self.assertAlmostEqual(row["fee_adjusted_expectancy_pct"], 1.86, places=4)
            finally:
                conn.close()

    def test_bad_events_and_invalid_ohlc_are_rejected(self) -> None:
        bars = rising_bars()
        with self.assertRaisesRegex(ValueError, "Unknown candle pattern"):
            evaluate_candle_pattern_detections(
                bars, [{"pattern_id": "fake", "index": 1}], [],
                symbol="BTCUSDT", timeframe="1m",
                dataset_fingerprint="set", data_split="test",
                label_source="HUMAN_REVIEWED",
            )
        with self.assertRaisesRegex(ValueError, "Inconsistent OHLC"):
            evaluate_candle_pattern_detections(
                [{"open": 101, "high": 99, "low": 100, "close": 102}],
                [], [], symbol="BTCUSDT", timeframe="1m",
                dataset_fingerprint="set", data_split="test",
                label_source="HUMAN_REVIEWED",
            )


if __name__ == "__main__":
    unittest.main()
