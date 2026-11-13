from __future__ import annotations

import unittest

from mirsad.decision_coordinator import build_final_decision, publish_engine_share
from mirsad.decision_integrity import validate_decision_integrity


def vote(name: str, score: float, quality: float = 1.0) -> dict:
    return publish_engine_share(name, status="READY", score=score, quality=quality)


class DecisionIntegrityTests(unittest.TestCase):
    def test_matching_open_intent_and_risk_plan_pass(self) -> None:
        coordinator = build_final_decision(
            vote("engine_1_market_intelligence", 0.8),
            vote("engine_2_price_action", 0.8),
            vote("engine_3_indicators", 0.8),
        )
        decision = {
            "candidate_action": "BUY", "action": "BUY", "command_ready": True,
            "entry_reference": 100.0, "stop_loss": 98.0, "take_profit": 104.0,
            "risk_plan": {"status": "READY", "volume": 0.1},
        }
        result = validate_decision_integrity(coordinator, decision)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["execution_eligible"])

    def test_inconsistent_candidate_is_blocked(self) -> None:
        coordinator = build_final_decision(
            vote("engine_1_market_intelligence", -0.8),
            vote("engine_2_price_action", -0.8),
            vote("engine_3_indicators", -0.8),
        )
        result = validate_decision_integrity(
            coordinator,
            {"candidate_action": "BUY", "action": "WAIT", "command_ready": False},
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("CANDIDATE_DIRECTION_DIFFERS_FROM_COORDINATOR", result["errors"])

    def test_open_without_risk_plan_is_blocked(self) -> None:
        coordinator = build_final_decision(
            vote("engine_1_market_intelligence", 0.8),
            vote("engine_2_price_action", 0.8),
            vote("engine_3_indicators", 0.8),
        )
        result = validate_decision_integrity(
            coordinator,
            {
                "candidate_action": "BUY", "action": "BUY", "command_ready": True,
                "entry_reference": 100.0, "stop_loss": 98.0, "take_profit": 104.0,
                "risk_plan": {"status": "BLOCKED", "volume": 0.1},
            },
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("OPEN_RISK_PLAN_INVALID", result["errors"])


    def test_missing_engine_is_normal_wait_not_integrity_failure(self) -> None:
        missing = publish_engine_share(
            "engine_1_market_intelligence", status="OFFLINE",
            score=None, quality=0.0, eligible=False,
        )
        coordinator = build_final_decision(
            missing,
            vote("engine_2_price_action", 0.9),
            vote("engine_3_indicators", 0.9),
        )
        result = validate_decision_integrity(
            coordinator,
            {"candidate_action": "WAIT", "action": "WAIT", "command_ready": False},
        )
        self.assertEqual(coordinator["status"], "WAITING_FOR_ENGINE_DECISIONS")
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["valid"])
        self.assertFalse(result["execution_eligible"])


if __name__ == "__main__":
    unittest.main()
