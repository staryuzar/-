from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mirsad.engines.chart_structure_evaluation import (
    analyze_and_evaluate_stored_market_structures,
    evaluate_stored_structure_events,
    evaluate_structure_events,
    persist_structure_evaluations,
)
from mirsad.storage import CANDLE_INTERVAL_MS, connect


def make_bars(length: int) -> list[dict[str, float | int | bool]]:
    interval = CANDLE_INTERVAL_MS["1h"]
    start = 1_700_000_000_000
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
        return evaluate_structure_events(
            bars,
            events,
            symbol="BTCUSDT",
            venue="Binance Spot",
            timeframe="1h",
            data_split="test",
            dataset_id="fixture-v1",
            **kwargs,
        )

    def test_stored_evaluation_uses_only_selected_venue_and_as_of_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            db_path = str(Path(temporary) / "stored-market.sqlite3")
            interval = CANDLE_INTERVAL_MS["1h"]
            start = 1_700_000_000_000
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
                              fee_adjusted_expectancy_pct,data_split
                       FROM visual_structure_evaluations"""
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["structure_id"], "double_bottom")
                self.assertEqual(rows[0]["sample_count"], 1)
                self.assertEqual(rows[0]["validation_status"], "IN_PROGRESS")
                self.assertEqual(rows[0]["human_reviewed"], 0)
                self.assertEqual(rows[0]["data_split"], "test")
                self.assertIsNotNone(rows[0]["fee_adjusted_expectancy_pct"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
