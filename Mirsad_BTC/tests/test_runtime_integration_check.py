from __future__ import annotations

import unittest

from scripts.mirsad_runtime_integration_check import evaluate_engine4_runtime


class Engine4IntegrationReadinessTests(unittest.TestCase):
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
