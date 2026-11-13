from __future__ import annotations

import unittest

from mirsad.decision_coordinator import (
    ENGINE_SHARES,
    build_final_decision,
    publish_engine_share,
)


def vote(name: str, score: float, quality: float = 1.0) -> dict:
    return publish_engine_share(
        name, status="READY", score=score, quality=quality, eligible=True
    )


class DecisionCoordinatorTests(unittest.TestCase):
    def test_fixed_shares_are_preserved_and_sum_to_one_hundred(self) -> None:
        report = build_final_decision(
            vote("engine_1_market_intelligence", 0.8),
            vote("engine_2_price_action", 0.6),
            vote("engine_3_indicators", 0.5),
        )
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["configured_shares"], ENGINE_SHARES)
        self.assertAlmostEqual(report["total_reported_share_percent"], 100.0, places=6)
        self.assertEqual(report["action"], "BUY")

    def test_missing_engine_is_not_redistributed_and_prevents_entry(self) -> None:
        missing = publish_engine_share(
            "engine_1_market_intelligence", status="OFFLINE",
            score=None, quality=0.0, eligible=False,
        )
        report = build_final_decision(
            missing,
            vote("engine_2_price_action", 1.0),
            vote("engine_3_indicators", 1.0),
        )
        self.assertEqual(report["status"], "WAITING_FOR_ENGINE_DECISIONS")
        self.assertEqual(report["action"], "WAIT")
        self.assertFalse(report["entry_eligible"])
        self.assertAlmostEqual(report["received_share_percent"], 80.0, places=6)
        self.assertIn("engine_1_market_intelligence", report["pending_engines"])

    def test_low_quality_share_becomes_neutral_not_reassigned(self) -> None:
        partial = vote("engine_1_market_intelligence", 1.0, quality=0.25)
        split = partial["decision_share_distribution_percent"]
        self.assertAlmostEqual(sum(split.values()), 20.0, places=6)
        self.assertAlmostEqual(split["NEUTRAL"], 15.0, places=6)
        self.assertAlmostEqual(split["BUY"], 5.0, places=6)

    def test_tied_directional_shares_produce_wait(self) -> None:
        report = build_final_decision(
            vote("engine_1_market_intelligence", 0.0),
            vote("engine_2_price_action", 0.0),
            vote("engine_3_indicators", 0.0),
        )
        self.assertEqual(report["action"], "WAIT")

    def test_invalid_scores_are_withheld(self) -> None:
        invalid = publish_engine_share(
            "engine_1_market_intelligence", status="READY",
            score=2.0, quality=1.0,
        )
        self.assertFalse(invalid["received"])


if __name__ == "__main__":
    unittest.main()
