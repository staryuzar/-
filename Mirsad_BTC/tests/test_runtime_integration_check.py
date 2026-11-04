from __future__ import annotations

import unittest

from scripts.mirsad_runtime_integration_check import (
    evaluate_engine4_runtime,
    summarize_calibration_archive,
    summarize_calibration_persistence,
)


class Engine4IntegrationReadinessTests(unittest.TestCase):
    def test_calibration_archive_status_is_reported_as_diagnostic(self) -> None:
        summary = summarize_calibration_persistence({
            "status": "STORED",
            "profile_version": "mirsad-engine-weights-fixed-share-v5-2026-11-04",
            "sample_count": 42,
            "signal_bar_time_ms": 1_798_000_000_000,
            "candles_inserted": 12,
        })
        self.assertEqual(summary["status"], "STORED")
        self.assertEqual(summary["write_reported_sample_count"], 42)
        self.assertEqual(summary["candles_inserted"], 12)
        self.assertEqual(summarize_calibration_persistence(None)["status"], "NOT_REPORTED")

    def test_archive_summary_counts_current_profile_and_actions_independently(self) -> None:
        import sqlite3
        import tempfile
        from pathlib import Path
        from mirsad.storage import DECISION_CALIBRATION_PROFILE_VERSION

        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "decision_calibration.sqlite3"
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "CREATE TABLE decision_calibration_samples "
                    "(profile_version TEXT, final_action TEXT)"
                )
                conn.executemany(
                    "INSERT INTO decision_calibration_samples VALUES (?,?)",
                    [
                        (DECISION_CALIBRATION_PROFILE_VERSION, "WAIT"),
                        (DECISION_CALIBRATION_PROFILE_VERSION, "WAIT"),
                        (DECISION_CALIBRATION_PROFILE_VERSION, "BUY"),
                        ("old-profile", "SELL"),
                    ],
                )
            summary = summarize_calibration_archive(db_path)
        self.assertEqual(summary["status"], "READY")
        self.assertEqual(summary["total_samples"], 4)
        self.assertEqual(summary["current_profile_sample_count"], 3)
        self.assertEqual(summary["current_profile_final_action_counts"], {"WAIT": 2, "BUY": 1})
        self.assertEqual(summary["profiles"][DECISION_CALIBRATION_PROFILE_VERSION], 3)

    def test_missing_calibration_archive_is_reported_without_failing_runtime(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            summary = summarize_calibration_archive(Path(directory) / "missing.sqlite3")
        self.assertEqual(summary["status"], "MISSING")
        self.assertEqual(summary["total_samples"], 0)

    def test_directional_entry_requires_engine2_eligibility_and_ready_status(self) -> None:
        result = evaluate_engine4_runtime({
            "status": "READY",
            "action": "BUY",
            "candidate_action": "BUY",
            "command_ready": True,
            "engine_2_native_price_action_context": {
                "decision_eligible": True,
                "gate": "BULLISH_CONFLUENCE",
            },
        })
        self.assertTrue(result["cycle_completed"])
        self.assertTrue(result["gate_consistent"])
        self.assertEqual(result["readiness"], "DIRECTIONAL_ENTRY_ELIGIBLE")
        self.assertTrue(result["entry_eligible"])

    def test_mixed_native_structure_is_a_successful_safe_wait_not_entry_ready(self) -> None:
        result = evaluate_engine4_runtime({
            "status": "WAITING_FOR_ENGINE_2",
            "action": "WAIT",
            "candidate_action": "WAIT",
            "command_ready": False,
            "chart_gate": "WAITING_FOR_ENGINE_2_PRICE_ACTION_CONFLUENCE",
            "engine_2_native_price_action_context": {
                "decision_eligible": False,
                "gate": "MIXED_OR_NO_CONFLUENCE",
                "direction": "MIXED_OR_UNCONFIRMED",
                "structure_score": -0.0769,
                "timeframe_weight_coverage": 1.0,
                "directional_structure_agreement": 0.5,
            },
        })
        self.assertTrue(result["cycle_completed"])
        self.assertTrue(result["gate_consistent"])
        self.assertTrue(result["safe_wait"])
        self.assertFalse(result["entry_eligible"])
        self.assertEqual(result["readiness"], "SAFE_WAIT_NO_ENGINE2_DIRECTION")

    def test_engine3_parity_safe_wait_is_a_completed_non_entry_cycle(self) -> None:
        result = evaluate_engine4_runtime({
            "status": "WAITING_FOR_ENGINE_3_PARITY",
            "action": "WAIT",
            "candidate_action": "WAIT",
            "command_ready": False,
            "chart_gate": "WAITING_FOR_ENGINE_3_NATIVE_PARITY",
            "engine_2_native_price_action_context": {
                "decision_eligible": True,
                "gate": "BULLISH_CONFLUENCE",
            },
        })
        self.assertTrue(result["cycle_completed"])
        self.assertTrue(result["gate_consistent"])
        self.assertTrue(result["safe_wait"])
        self.assertFalse(result["entry_eligible"])
        self.assertTrue(result["engine2_entry_eligible"])
        self.assertEqual(result["readiness"], "SAFE_WAIT_ENGINE3_PARITY_NOT_VERIFIED")

    def test_engine2_not_ready_must_not_be_reported_as_a_directional_entry(self) -> None:
        result = evaluate_engine4_runtime({
            "status": "WAITING_FOR_ENGINE_2",
            "action": "BUY",
            "candidate_action": "BUY",
            "command_ready": True,
            "engine_2_native_price_action_context": {
                "decision_eligible": False,
                "gate": "NOT_READY",
            },
        })
        self.assertFalse(result["gate_consistent"])
        self.assertEqual(result["readiness"], "INCONSISTENT_OR_INCOMPLETE")

    def test_wait_with_a_command_ready_flag_is_not_a_safe_wait(self) -> None:
        result = evaluate_engine4_runtime({
            "status": "WAITING_FOR_ENGINE_2",
            "action": "WAIT",
            "candidate_action": "WAIT",
            "command_ready": True,
            "engine_2_native_price_action_context": {
                "decision_eligible": False,
                "gate": "NOT_READY",
            },
        })
        self.assertFalse(result["safe_wait"])
        self.assertFalse(result["gate_consistent"])

    def test_protective_position_action_is_valid_without_new_entry_vote(self) -> None:
        result = evaluate_engine4_runtime({
            "status": "READY",
            "action": "MODIFY",
            "candidate_action": "WAIT",
            "command_ready": True,
            "engine_2_native_price_action_context": {
                "decision_eligible": False,
                "gate": "NOT_EVALUATED",
            },
        })
        self.assertTrue(result["cycle_completed"])
        self.assertTrue(result["gate_consistent"])
        self.assertEqual(result["readiness"], "POSITION_PROTECTION_ACTION")


if __name__ == "__main__":
    unittest.main()
