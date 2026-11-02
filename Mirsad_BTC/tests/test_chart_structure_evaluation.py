from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mirsad.engines.chart_structure_evaluation import (
    analyze_and_evaluate_stored_market_structures,
    evaluate_stored_structure_events,
    evaluate_structure_events,
    scan_historical_structure_events,
    persist_structure_evaluations,
)
from mirsad.engines.visual_knowledge import visual_knowledge_summary
from mirsad.storage import CANDLE_INTERVAL_MS, connect


def make_bars(length: int) -> list[dict[str, float | int | bool]]:
    interval = CANDLE_INTERVAL_MS["1h"]
    start = (1_700_000_000_000 // interval) * interval
    bars: list[dict[str, float | int | bool]] = []
    for index in range(length):
        base = 100.0 + index
        bars.append({
            "open_time_ms": start + index * interval,
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base + 0.5,
            "closed": True,
        })
    return bars


def reversal_event(
    pattern_id: str = "double_bottom",
    direction: str = "BULLISH",
    confirmation_index: int = 2,
) -> dict[str, int | str]:
    return {
        "pattern_id": pattern_id,
        "direction": direction,
        "status": "CONFIRMED",
        "formation_confirmed_at": confirmation_index - 1,
        "confirmation_index": confirmation_index,
    }


class StructureEventEvaluationTests(unittest.TestCase):
    def evaluate(self, bars, events, **kwargs):
        interval = CANDLE_INTERVAL_MS["1h"]
        split_start_ms = kwargs.pop("split_start_ms", int(bars[0]["open_time_ms"]))
        split_end_ms = kwargs.pop(
            "split_end_ms", int(bars[-1]["open_time_ms"]) + interval
        )
        embargo_bars = kwargs.pop("embargo_bars", 0)
        data_split = kwargs.pop("data_split", "test")
        dataset_id = kwargs.pop("dataset_id", "fixture-v1")
        return evaluate_structure_events(
            bars,
            events,
            symbol="BTCUSDT",
            venue="Binance Spot",
            timeframe="1h",
            data_split=data_split,
            dataset_id=dataset_id,
            split_start_ms=split_start_ms,
            split_end_ms=split_end_ms,
            embargo_bars=embargo_bars,
            **kwargs,
        )

    def test_historical_scan_emits_double_bottom_on_its_confirmation_bar_only(self) -> None:
        closes = [
            96.0, 94.0, 92.0, 93.0, 95.0, 91.0, 94.0, 97.0,
            100.0, 103.0, 104.0, 102.0, 99.0, 96.0, 94.0, 91.2,
            94.0, 97.0, 112.0, 110.0, 108.0, 106.0,
        ]
        interval = CANDLE_INTERVAL_MS["1h"]
        start = (1_700_000_000_000 // interval) * interval
        bars = [
            {
                "open_time_ms": start + index * interval,
                "open": close,
                "high": close + 0.25,
                "low": close - 0.25,
                "close": close,
                "closed": True,
            }
            for index, close in enumerate(closes)
        ]

        full_events, summary = scan_historical_structure_events(
            bars,
            timeframe="1h",
        )
        prefix_events, _ = scan_historical_structure_events(
            bars[:19],
            timeframe="1h",
        )
        full_double_bottoms = [
            event for event in full_events if event["pattern_id"] == "double_bottom"
        ]
        prefix_double_bottoms = [
            event for event in prefix_events if event["pattern_id"] == "double_bottom"
        ]
        self.assertTrue(full_double_bottoms)
        self.assertEqual(full_double_bottoms[0]["status"], "CONFIRMED")
        self.assertEqual(full_double_bottoms[0]["confirmation_index"], 18)
        self.assertEqual(full_double_bottoms[0]["event_index"], 18)
        self.assertEqual(
            full_double_bottoms[0]["event_open_time_ms"],
            prefix_double_bottoms[0]["event_open_time_ms"],
        )
        self.assertEqual(summary["lookahead_policy"], "closed_prefix_replay")
        self.assertEqual(summary["future_bars_used_for_event_detection"], 0)

    def test_stored_evaluation_uses_only_selected_venue_and_as_of_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "stored-market.sqlite3")
            interval = CANDLE_INTERVAL_MS["1h"]
            start = (1_700_000_000_000 // interval) * interval
            conn = connect(db_path)
            try:
                for venue, offset in (("Binance Spot", 0.0), ("OKX Spot", 500.0)):
                    conn.executemany(
                        """INSERT INTO candles
                           (venue,symbol,interval,open_time_ms,open,high,low,close,volume,is_closed)
                           VALUES(?,?,?,?,?,?,?,?,?,1)""",
                        [
                            (
                                venue, "BTCUSDT", "1h", start + index * interval,
                                100.0 + offset + index,
                                101.0 + offset + index,
                                99.0 + offset + index,
                                100.5 + offset + index,
                                1.0,
                            )
                            for index in range(12)
                        ],
                    )
            finally:
                conn.close()

            result = evaluate_stored_structure_events(
                [reversal_event()],
                symbol="BTCUSDT",
                venue="Binance Spot",
                timeframe="1h",
                as_of_ms=start + 10 * interval,
                data_split="test",
                dataset_id="stored-fixture-v1",
                split_start_ms=start,
                split_end_ms=start + 10 * interval,
                horizons=(1,),
                db_path=db_path,
            )
            self.assertEqual(result["storage_source"], "engine_1_stored_closed_candles")
            self.assertEqual(result["venue"], "Binance Spot")
            self.assertEqual(result["stored_bar_count"], 10)
            self.assertEqual(result["bar_count"], 10)

    def test_end_to_end_stored_market_scan_uses_engine_two_and_keeps_empty_results_honest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "engine-two-study.sqlite3")
            bars = make_bars(20)
            conn = connect(db_path)
            try:
                conn.executemany(
                    """INSERT INTO candles
                       (venue,symbol,interval,open_time_ms,open,high,low,close,volume,is_closed)
                       VALUES(?,?,?,?,?,?,?,?,?,1)""",
                    [
                        (
                            "Binance Spot", "BTCUSDT", "1h", int(bar["open_time_ms"]),
                            float(bar["open"]), float(bar["high"]), float(bar["low"]),
                            float(bar["close"]), 1.0,
                        )
                        for bar in bars
                    ],
                )
            finally:
                conn.close()

            result = analyze_and_evaluate_stored_market_structures(
                symbol="BTCUSDT",
                venue="Binance Spot",
                timeframe="1h",
                as_of_ms=int(bars[-1]["open_time_ms"]) + CANDLE_INTERVAL_MS["1h"],
                data_split="test",
                dataset_id="engine-two-fixture-v1",
                split_start_ms=int(bars[0]["open_time_ms"]),
                split_end_ms=int(bars[-1]["open_time_ms"]) + CANDLE_INTERVAL_MS["1h"],
                horizons=(1, 3),
                db_path=db_path,
            )
            self.assertIn(result["structure_analysis_status"], {"READY", "PARTIAL"})
            self.assertEqual(len(result["detected_structure_events"]), 0)
            self.assertEqual(result["evaluation"]["bar_count"], 20)
            self.assertEqual(result["evaluation"]["empirical_status"], "UNVALIDATED")

    def test_stored_evaluation_rejects_insufficient_history(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "empty-market.sqlite3")
            with self.assertRaisesRegex(ValueError, "Insufficient stored closed candles"):
                evaluate_stored_structure_events(
                    [],
                    symbol="BTCUSDT",
                    venue="Binance Spot",
                    timeframe="1h",
                    as_of_ms=1_700_000_000_000,
                    data_split="test",
                    dataset_id="empty-fixture",
                    db_path=db_path,
                )

    def test_entry_uses_next_open_and_costs_are_round_trip(self) -> None:
        bars = make_bars(20)
        result = self.evaluate(
            bars,
            [reversal_event()],
            horizons=(1, 3, 5),
            fee_bps_per_side=10.0,
            slippage_bps_per_side=5.0,
        )
        horizon = result["results_by_pattern"]["double_bottom"]["horizons"]["1"]
        expected_gross = ((103.5 / 103.0) - 1.0) * 100.0
        self.assertEqual(result["entry_rule"], "next_closed_candle_open_after_signal_confirmation")
        self.assertEqual(result["round_trip_cost_pct"], 0.30)
        self.assertAlmostEqual(horizon["mean_return_pct"], expected_gross, places=6)
        self.assertAlmostEqual(
            horizon["fee_adjusted_expectancy_pct"], expected_gross - 0.30, places=6
        )
        self.assertEqual(horizon["sample_count"], 1)

    def test_directional_comparison_uses_non_event_bars_as_unconditional_baseline(self) -> None:
        result = self.evaluate(
            make_bars(20),
            [reversal_event()],
            horizons=(1,),
            fee_bps_per_side=10.0,
            slippage_bps_per_side=5.0,
        )
        comparison = result["results_by_pattern"]["double_bottom"][
            "directional_comparisons"
        ]["BULLISH"]["horizons"]["1"]
        self.assertEqual(comparison["event"]["sample_count"], 1)
        self.assertEqual(
            comparison["unconditional_non_event_baseline"]["sample_count"], 16
        )
        self.assertIsNotNone(comparison["excess_mean_return_pct"])
        self.assertIsNotNone(comparison["excess_mean_net_return_pct"])
        self.assertEqual(
            result["baseline_policy"],
            "same_split_direction_adjusted_non_event_bars",
        )
        self.assertEqual(
            result["baseline_event_overlap_policy"],
            "purge_windows_overlapping_confirmed_event_windows_per_horizon",
        )
        self.assertTrue(result["baseline_overlapping_windows_possible"])
        self.assertFalse(result["baseline_is_statistical_test"])

    def test_bearish_return_and_excursions_are_direction_adjusted(self) -> None:
        result = self.evaluate(
            make_bars(20),
            [reversal_event("double_top", "BEARISH")],
            horizons=(1,),
        )
        horizon = result["results_by_pattern"]["double_top"]["horizons"]["1"]
        self.assertLess(horizon["mean_return_pct"], 0)
        self.assertLess(horizon["mean_mae_pct"], 0)
        self.assertGreater(horizon["mean_mfe_pct"], 0)

    def test_candidate_is_skipped_and_short_horizons_have_independent_counts(self) -> None:
        bars = make_bars(6)
        events = [
            {
                "pattern_id": "bull_flag",
                "status": "CANDIDATE",
                "formation_confirmed_at": 2,
            },
            reversal_event(confirmation_index=4),
        ]
        result = self.evaluate(bars, events, horizons=(1, 3, 5))
        pattern = result["results_by_pattern"]["double_bottom"]["horizons"]
        self.assertEqual(result["counts"]["candidate_events_skipped"], 1)
        self.assertEqual(pattern["1"]["sample_count"], 1)
        self.assertEqual(pattern["3"]["sample_count"], 0)
        self.assertEqual(pattern["5"]["sample_count"], 0)

    def test_unclosed_bars_are_rejected(self) -> None:
        bars = make_bars(10)
        bars[5]["closed"] = False
        with self.assertRaisesRegex(ValueError, "not explicitly marked closed"):
            self.evaluate(bars, [reversal_event()], horizons=(1,))

    def test_missing_candle_interval_is_rejected_not_bridged(self) -> None:
        bars = make_bars(10)
        bars[5]["open_time_ms"] = int(bars[5]["open_time_ms"]) + 1
        with self.assertRaisesRegex(ValueError, "contiguous"):
            self.evaluate(bars, [reversal_event()], horizons=(1,))

    def test_event_cannot_precede_formation_confirmation(self) -> None:
        event = reversal_event()
        event["formation_confirmed_at"] = event["confirmation_index"]
        with self.assertRaisesRegex(ValueError, "after all formation pivots"):
            self.evaluate(make_bars(10), [event], horizons=(1,))

    def test_weekly_split_boundaries_use_monday_utc_anchor(self) -> None:
        interval = CANDLE_INTERVAL_MS["1w"]
        monday_anchor = 4 * CANDLE_INTERVAL_MS["1d"]
        start = monday_anchor + (
            (1_700_000_000_000 - monday_anchor) // interval
        ) * interval
        bars = [
            {
                "open_time_ms": start + index * interval,
                "open": 100.0 + index,
                "high": 101.0 + index,
                "low": 99.0 + index,
                "close": 100.5 + index,
                "closed": True,
            }
            for index in range(10)
        ]
        result = evaluate_structure_events(
            bars,
            [],
            symbol="BTCUSDT",
            venue="Binance Spot",
            timeframe="1w",
            data_split="test",
            dataset_id="weekly-monday-fixture",
            split_start_ms=start,
            split_end_ms=start + 10 * interval,
            horizons=(1,),
        )
        self.assertEqual(result["bar_interval_ms"], interval)
        self.assertEqual(result["results_by_pattern"], {})

    def test_event_outside_split_is_skipped(self) -> None:
        bars = make_bars(20)
        split_start = int(bars[0]["open_time_ms"])
        split_end = split_start + 10 * CANDLE_INTERVAL_MS["1h"]
        result = self.evaluate(
            bars,
            [reversal_event(confirmation_index=12)],
            split_start_ms=split_start,
            split_end_ms=split_end,
            horizons=(1,),
        )
        self.assertEqual(result["counts"]["events_outside_split_skipped"], 1)
        self.assertEqual(result["results_by_pattern"], {})

    def test_horizon_that_crosses_split_end_is_purged(self) -> None:
        bars = make_bars(20)
        split_start = int(bars[0]["open_time_ms"])
        split_end = split_start + 6 * CANDLE_INTERVAL_MS["1h"]
        result = self.evaluate(
            bars,
            [reversal_event(confirmation_index=4)],
            split_start_ms=split_start,
            split_end_ms=split_end,
            horizons=(1, 3),
        )
        horizons = result["results_by_pattern"]["double_bottom"]["horizons"]
        self.assertEqual(horizons["1"]["sample_count"], 1)
        self.assertEqual(horizons["3"]["sample_count"], 0)
        self.assertEqual(result["counts"]["incomplete_horizon_samples_by_horizon"]["3"], 1)

    def test_split_start_embargo_excludes_early_events(self) -> None:
        bars = make_bars(20)
        interval = CANDLE_INTERVAL_MS["1h"]
        split_start = int(bars[2]["open_time_ms"])
        split_end = int(bars[-1]["open_time_ms"]) + interval
        result = self.evaluate(
            bars,
            [
                reversal_event(confirmation_index=3),
                reversal_event(confirmation_index=5),
            ],
            split_start_ms=split_start,
            split_end_ms=split_end,
            embargo_bars=2,
            horizons=(1,),
        )
        self.assertEqual(result["counts"]["events_embargoed_at_split_start"], 1)
        self.assertEqual(result["results_by_pattern"]["double_bottom"]["horizons"]["1"]["sample_count"], 1)

    def test_split_bounds_must_align_to_candle_interval(self) -> None:
        bars = make_bars(10)
        with self.assertRaisesRegex(ValueError, "align to the selected candle interval"):
            self.evaluate(
                bars,
                [reversal_event()],
                split_start_ms=int(bars[0]["open_time_ms"]) + 1,
                horizons=(1,),
            )

    def test_empty_split_window_is_registered_and_blocks_later_overlap(self) -> None:
        bars = make_bars(20)
        interval = CANDLE_INTERVAL_MS["1h"]
        start = int(bars[0]["open_time_ms"])
        split_end = start + 10 * interval
        full_end = int(bars[-1]["open_time_ms"]) + interval
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "empty-split-registry.sqlite3")
            empty_train = self.evaluate(
                bars,
                [],
                data_split="train",
                dataset_id="dataset-with-empty-train",
                split_start_ms=start,
                split_end_ms=split_end,
            )
            self.assertEqual(
                persist_structure_evaluations(empty_train, db_path=db_path),
                0,
            )
            conn = connect(db_path)
            try:
                registered = conn.execute(
                    """SELECT data_split,split_start_ms,split_end_ms
                       FROM visual_structure_evaluation_splits"""
                ).fetchall()
                self.assertEqual(len(registered), 1)
                self.assertEqual(registered[0]["data_split"], "train")
                evaluation_rows = conn.execute(
                    "SELECT COUNT(*) FROM visual_structure_evaluations"
                ).fetchone()[0]
                self.assertEqual(evaluation_rows, 0)
            finally:
                conn.close()

            overlapping_validation = self.evaluate(
                bars,
                [],
                data_split="validation",
                dataset_id="dataset-with-empty-train",
                split_start_ms=start + 5 * interval,
                split_end_ms=full_end,
            )
            with self.assertRaisesRegex(ValueError, "overlaps previously registered train window"):
                persist_structure_evaluations(
                    overlapping_validation,
                    db_path=db_path,
                )

    def test_train_validation_test_windows_must_be_chronological(self) -> None:
        bars = make_bars(20)
        interval = CANDLE_INTERVAL_MS["1h"]
        start = int(bars[0]["open_time_ms"])
        split_point = start + 10 * interval
        end = int(bars[-1]["open_time_ms"]) + interval
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "chronological-splits.sqlite3")
            later_test = self.evaluate(
                bars,
                [reversal_event(confirmation_index=2)],
                data_split="test",
                split_start_ms=start,
                split_end_ms=split_point,
                horizons=(1,),
            )
            self.assertEqual(
                persist_structure_evaluations(later_test, primary_horizon_bars=1, db_path=db_path),
                1,
            )
            earlier_validation = self.evaluate(
                bars,
                [reversal_event(confirmation_index=12)],
                data_split="validation",
                split_start_ms=split_point,
                split_end_ms=end,
                horizons=(1,),
            )
            with self.assertRaisesRegex(ValueError, "validation must end before test begins"):
                persist_structure_evaluations(
                    earlier_validation,
                    primary_horizon_bars=1,
                    db_path=db_path,
                )

    def test_one_dataset_id_requires_the_same_ohlc_fingerprint_across_splits(self) -> None:
        bars = make_bars(20)
        interval = CANDLE_INTERVAL_MS["1h"]
        start = int(bars[0]["open_time_ms"])
        split_point = start + 10 * interval
        end = int(bars[-1]["open_time_ms"]) + interval
        dataset_id = "immutable-cross-split-dataset"
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "immutable-cross-split.sqlite3")
            train = self.evaluate(
                bars,
                [reversal_event(confirmation_index=2)],
                data_split="train",
                dataset_id=dataset_id,
                split_start_ms=start,
                split_end_ms=split_point,
                horizons=(1,),
            )
            self.assertEqual(
                persist_structure_evaluations(
                    train, primary_horizon_bars=1, db_path=db_path
                ),
                1,
            )

            # A later split cannot silently use a revised candle series under
            # the same dataset_id, even when its own time window is disjoint.
            revised_bars = make_bars(20)
            revised_bars[-1]["close"] = float(revised_bars[-1]["close"]) + 0.25
            validation = self.evaluate(
                revised_bars,
                [reversal_event(confirmation_index=12)],
                data_split="validation",
                dataset_id=dataset_id,
                split_start_ms=split_point,
                split_end_ms=end,
                horizons=(1,),
            )
            with self.assertRaisesRegex(
                ValueError, "same immutable OHLC fingerprint"
            ):
                persist_structure_evaluations(
                    validation, primary_horizon_bars=1, db_path=db_path
                )

            conn = connect(db_path)
            try:
                registered = conn.execute(
                    """SELECT data_split,dataset_fingerprint
                       FROM visual_structure_evaluation_splits
                       WHERE dataset_id=?""",
                    (dataset_id,),
                ).fetchall()
                self.assertEqual(len(registered), 1)
                self.assertEqual(registered[0]["data_split"], "train")
            finally:
                conn.close()

    def test_fee_and_slippage_assumptions_must_be_paired(self) -> None:
        with self.assertRaisesRegex(ValueError, "both be supplied"):
            self.evaluate(
                make_bars(10),
                [reversal_event()],
                horizons=(1,),
                fee_bps_per_side=8.0,
            )

    def test_persistence_is_idempotent_and_never_auto_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "structure-evaluation.sqlite3")
            result = self.evaluate(
                make_bars(20),
                [reversal_event()],
                horizons=(1, 3, 5),
                fee_bps_per_side=8.0,
                slippage_bps_per_side=4.0,
            )
            first = persist_structure_evaluations(
                result, primary_horizon_bars=1, db_path=db_path, calculated_at_ms=1234
            )
            second = persist_structure_evaluations(
                result, primary_horizon_bars=1, db_path=db_path, calculated_at_ms=1235
            )
            self.assertEqual(first, 1)
            self.assertEqual(second, 1)

            conn = connect(db_path)
            try:
                rows = conn.execute(
                    """SELECT structure_id,sample_count,validation_status,human_reviewed,
                              fee_adjusted_expectancy_pct,data_split,dataset_id,
                              split_start_ms,split_end_ms,embargo_bars,horizon_metrics_json
                       FROM visual_structure_evaluations"""
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["structure_id"], "double_bottom")
                self.assertEqual(rows[0]["sample_count"], 1)
                self.assertEqual(rows[0]["validation_status"], "IN_PROGRESS")
                self.assertEqual(rows[0]["human_reviewed"], 0)
                self.assertEqual(rows[0]["data_split"], "test")
                self.assertEqual(rows[0]["dataset_id"], "fixture-v1")
                self.assertEqual(rows[0]["split_start_ms"], int(make_bars(20)[0]["open_time_ms"]))
                self.assertEqual(
                    rows[0]["split_end_ms"],
                    int(make_bars(20)[-1]["open_time_ms"]) + CANDLE_INTERVAL_MS["1h"],
                )
                self.assertEqual(rows[0]["embargo_bars"], 0)
                self.assertIsNotNone(rows[0]["fee_adjusted_expectancy_pct"])
                stored_metrics = json.loads(rows[0]["horizon_metrics_json"])
                self.assertIn("directional_comparisons", stored_metrics)
                self.assertIsNotNone(
                    stored_metrics["directional_comparisons"]["BULLISH"]["horizons"]["1"][
                        "excess_mean_return_pct"
                    ]
                )
                summary = visual_knowledge_summary(db_path)
                self.assertEqual(summary["evaluation_split_windows"], 1)
                self.assertEqual(
                    summary["recent_evaluation_split_windows"][0]["data_split"],
                    "test",
                )
            finally:
                conn.close()

            overlapping_train = self.evaluate(
                make_bars(20),
                [reversal_event()],
                data_split="train",
            )
            with self.assertRaisesRegex(ValueError, "overlaps previously stored test window"):
                persist_structure_evaluations(
                    overlapping_train,
                    primary_horizon_bars=1,
                    db_path=db_path,
                    calculated_at_ms=1236,
                )


if __name__ == "__main__":
    unittest.main()
