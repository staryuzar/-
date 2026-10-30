import unittest

from bitcoinlab.decision import central_decision


FRESH = {"spot": {"status": "fresh"}, "orderflow": {"status": "fresh"}, "derivatives": {"status": "fresh"}}
TECH = {"status": "ok", "score": 0.8}
FLOW = {"status": "ok", "score": 0.7}
DERIV = {"status": "ok", "score": 0.5}


class DecisionTests(unittest.TestCase):
    def call(self, **kwargs):
        base = dict(
            technical=TECH, orderflow=FLOW, derivatives=DERIV,
            source_states=FRESH, spread_bps=2.0, reward_risk_ratio=2.0,
        )
        base.update(kwargs)
        return central_decision(**base)

    def test_fresh_confluence_produces_buy(self):
        result = self.call()
        self.assertEqual(result["action"], "BUY")
        self.assertGreater(result["score"], 0.28)
        self.assertNotIn("win_probability", result)

    def test_stale_source_forces_hold(self):
        sources = dict(FRESH)
        sources["derivatives"] = {"status": "stale"}
        result = self.call(source_states=sources)
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("derivatives_not_fresh", result["blockers"])

    def test_strong_cross_domain_conflict_forces_hold(self):
        result = self.call(orderflow={"status": "ok", "score": -0.9})
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("strong_cross_domain_conflict", result["blockers"])

    def test_high_spread_forces_hold(self):
        result = self.call(spread_bps=30.0)
        self.assertNotEqual(result["action"], "HOLD")
        self.assertIn("spread_above_optional_threshold", result["warnings"])

    def test_poor_reward_risk_forces_hold(self):
        result = self.call(reward_risk_ratio=1.1)
        self.assertEqual(result["action"], "BUY")
        self.assertIn("reward_risk_below_optional_reference", result["warnings"])

    def test_weak_confluence_holds(self):
        result = self.call(
            technical={"status": "ok", "score": 0.1},
            orderflow={"status": "ok", "score": 0.0},
            derivatives={"status": "ok", "score": 0.1},
        )
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("insufficient_cross_domain_confluence", result["blockers"])


if __name__ == "__main__":
    unittest.main()
