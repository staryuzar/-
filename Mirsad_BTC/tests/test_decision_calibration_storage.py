from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mirsad.config import DB_PATH, DECISION_CALIBRATION_DB_PATH
from mirsad.storage import (
    DECISION_CALIBRATION_PROFILE_VERSION,
    save_decision_calibration_sample,
)


def make_sample_inputs():
    timeframes = ("1m", "5m", "15m", "1h", "4h", "1d")
    candles_by_tf = {}
    for index, timeframe in enumerate(timeframes):
        step = (60_000, 300_000, 900_000, 3_600_000, 14_400_000, 86_400_000)[index]
        bars = []
        for offset in range(3):
            stamp = 1_798_000_000_000 + offset * step
            close = 90_000.0 + index * 100 + offset * 5
            bars.append({
                "open_time_ms": stamp,
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 10 + offset,
                "closed": offset < 2,
            })
        candles_by_tf[timeframe] = bars

    market = {
        "symbol": "BTCUSDT",
        "price": 90_010.0,
        "captured_at_ms": 1_798_000_200_000,
    }
    candle_history = {
        "status": "READY",
        "symbol": "BTCUSDT",
        "captured_at_ms": 1_798_000_200_000,
        "candles_by_tf": candles_by_tf,
    }
    market_intelligence = {
        "status": "READY",
        "direction": "BEARISH",
        "directional_score": -0.25,
        "confidence": 0.80,
        "evidence_coverage": 0.90,
        "components": {
            "derivatives": {"status": "READY", "score": -0.30, "weight": 0.45},
            "news": {"status": "READY", "score": -0.20, "weight": 0.35},
            "fear_greed": {"status": "READY", "score": 0.10, "weight": 0.20},
        },
        "source_statuses": {"news": "READY", "derivatives": "READY"},
    }
    engine2_price_action = {
        "status": "READY",
        "direction": "MIXED_TIMEFRAME_DIRECTIONS",
        "structure_score": 0.08,
        "summary": {
            "timeframe_alignment": "MIXED_TIMEFRAME_DIRECTIONS",
            "timeframe_weight_coverage": 1.0,
            "directional_structure_agreement": 0.5,
            "directional_evidence_weights": {
                "confirmed_swing_structure": 0.70,
                "latest_confirmed_bos_choch": 0.15,
                "latest_candle_pattern": 0.10,
                "latest_liquidity_sweep": 0.05,
            },
        },
        "timeframes": {
            "1m": {"status": "READY", "direction": "BULLISH", "directional_evidence_score": 0.2},
        },
    }
    indicators = {
        "status": "READY",
        "signal_score": -0.18,
        "signal_quality": 0.95,
        "signal_timeframe_weight_coverage": 1.0,
        "signal_group_weights": {"trend": 0.25, "momentum": 0.30},
        "signal_components_by_timeframe": {
            "1m": {"status": "READY", "score": -0.2, "quality": 0.9, "groups": {}},
        },
        "mt5_native": {"status": "READY"},
        "mt5_native_parity": {
            "status": "PASS", "passed_metrics": 120, "total_metrics": 120, "failures": [],
        },
    }
    decision = {
        "status": "WAITING_FOR_ENGINE_2",
        "action": "WAIT",
        "candidate_action": "WAIT",
        "broker_spread_pct": 0.08,
        "decision_weights": {
            "engine_1_market_intelligence": 0.16,
            "engine_2_price_action": 0.0,
            "engine_3_indicators": 0.285,
            "configured": {
                "engine_1_market_intelligence": 0.20,
                "engine_2_price_action": 0.50,
                "engine_3_indicators": 0.30,
            },
        },
        "decision_scores": {
            "engine_1_market_intelligence": -0.25,
            "engine_1_quality": 0.80,
            "engine_2_native_ohlc_score": 0.08,
            "engine_2_quality": 0.0,
            "engine_3_indicators": -0.18,
            "engine_3_quality": 0.95,
            "effective_weight_coverage": 0.445,
            "combined_score": None,
            "threshold": 0.40,
            "minimum_engine_2_direction_score": 0.20,
        },
        "engine_2_native_price_action_context": {
            "decision_eligible": False,
            "gate": "MIXED_OR_NO_CONFLUENCE",
        },
        "chart_gate": "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE",
    }
    return market, candle_history, market_intelligence, engine2_price_action, indicators, decision


class DecisionCalibrationStorageTests(unittest.TestCase):
    def test_calibration_database_is_separate_from_market_and_deal_database(self) -> None:
        self.assertNotEqual(DB_PATH, DECISION_CALIBRATION_DB_PATH)
        self.assertEqual(DECISION_CALIBRATION_DB_PATH.name, "decision_calibration.sqlite3")

    def test_stores_one_synchronized_sample_and_matching_closed_candles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "calibration.sqlite3"
            inputs = make_sample_inputs()
            result = save_decision_calibration_sample(
                market=inputs[0],
                candle_history=inputs[1],
                market_intelligence=inputs[2],
                engine2_price_action=inputs[3],
                indicators=inputs[4],
                decision=inputs[5],
                db_path=db_path,
            )
            self.assertEqual(result["status"], "STORED")
            self.assertEqual(result["profile_version"], DECISION_CALIBRATION_PROFILE_VERSION)
            self.assertEqual(result["candles_inserted"], 12)
            self.assertEqual(result["sample_count"], 1)

            with sqlite3.connect(db_path) as conn:
                sample = conn.execute(
                    "SELECT engine1_score,engine2_score,engine3_score,combined_score,"
                    "native_parity_status,candidate_action,final_action,evidence_json,"
                    "calibration_config_json,effective_weights_json FROM decision_calibration_samples"
                ).fetchone()
                candle_count = conn.execute(
                    "SELECT COUNT(*) FROM decision_calibration_candles"
                ).fetchone()[0]
            self.assertEqual(sample[0], -0.25)
            self.assertEqual(sample[1], 0.08)
            self.assertEqual(sample[2], -0.18)
            self.assertIsNone(sample[3])
            self.assertEqual(sample[4], "PASS")
            self.assertEqual(sample[5], "WAIT")
            self.assertEqual(sample[6], "WAIT")
            evidence = json.loads(sample[7])
            config = json.loads(sample[8])
            effective_weights = json.loads(sample[9])
            self.assertEqual(evidence["engine3"]["native_parity"]["passed_metrics"], 120)
            self.assertAlmostEqual(config["decision_weights"]["configured"]["engine_2_price_action"], 0.50)
            self.assertAlmostEqual(effective_weights["engine_1_market_intelligence"], 0.16)
            self.assertAlmostEqual(effective_weights["engine_2_price_action"], 0.0)
            self.assertAlmostEqual(effective_weights["engine_3_indicators"], 0.285)
            self.assertAlmostEqual(sum(effective_weights.values()), 0.445)
            self.assertEqual(candle_count, 12)

    def test_same_closed_m1_bar_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "calibration.sqlite3"
            args = make_sample_inputs()
            first = save_decision_calibration_sample(
                market=args[0], candle_history=args[1], market_intelligence=args[2],
                engine2_price_action=args[3], indicators=args[4], decision=args[5],
                db_path=db_path,
            )
            second = save_decision_calibration_sample(
                market=args[0], candle_history=args[1], market_intelligence=args[2],
                engine2_price_action=args[3], indicators=args[4], decision=args[5],
                db_path=db_path,
            )
            self.assertEqual(first["status"], "STORED")
            self.assertEqual(first["sample_count"], 1)
            self.assertEqual(second["status"], "ALREADY_STORED")
            self.assertEqual(second["sample_count"], 1)
            with sqlite3.connect(db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM decision_calibration_samples"
                ).fetchone()[0]
            self.assertEqual(count, 1)

    def test_rejects_engine3_when_native_parity_is_not_120_of_120(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "calibration.sqlite3"
            args = list(make_sample_inputs())
            args[4]["mt5_native_parity"] = {
                "status": "PASS", "passed_metrics": 119, "total_metrics": 120,
            }
            result = save_decision_calibration_sample(
                market=args[0], candle_history=args[1], market_intelligence=args[2],
                engine2_price_action=args[3], indicators=args[4], decision=args[5],
                db_path=db_path,
            )
            self.assertEqual(result["status"], "SKIPPED")
            self.assertIn("all 120 metrics", result["reason"])
            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()
