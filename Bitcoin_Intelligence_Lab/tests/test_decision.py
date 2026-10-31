import unittest

from bitcoinlab.decision import central_decision


FRESH = {
    "spot": {"status": "fresh"},
    "technical": {"status": "fresh"},
    "orderflow": {"status": "fresh"},
    "derivatives": {"status": "fresh"},
}
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

    def test_stale_technical_source_forces_hold_even_with_valid_engine_score(self):
        sources = dict(FRESH)
        sources["technical"] = {"status": "stale"}
        result = self.call(source_states=sources)
        self.assertEqual(result["action"], "HOLD")
        self.assertIsNone(result["score"])
        self.assertIn("technical_source_not_fresh", result["blockers"])
        self.assertIn("technical_unavailable_or_stale", result["warnings"])

    def test_one_optional_stale_source_does_not_block_other_fresh_domains(self):
        sources = dict(FRESH)
        sources["derivatives"] = {"status": "stale"}
        result = self.call(source_states=sources)
        self.assertEqual(result["action"], "BUY")
        self.assertIn("derivatives_unavailable_or_stale", result["warnings"])
        self.assertEqual(result["active_domains"], ["technical", "orderflow"])

    def test_strong_cross_domain_conflict_forces_hold(self):
        result = self.call(orderflow={"status": "ok", "score": -0.9})
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("strong_cross_domain_conflict", result["blockers"])

    def test_high_spread_is_advisory_when_optional_limit_is_enabled(self):
        result = self.call(spread_bps=30.0, max_spread_bps=12.0)
        self.assertNotEqual(result["action"], "HOLD")
        self.assertIn("spread_above_optional_threshold", result["warnings"])

    def test_poor_reward_risk_forces_hold(self):
        result = self.call(reward_risk_ratio=1.1)
        self.assertEqual(result["action"], "BUY")
        self.assertIn("reward_risk_below_optional_reference", result["warnings"])

    def test_market_structure_and_cross_venue_engines_add_weight_when_fresh(self):
        sources = dict(FRESH)
        sources["market_structure"] = {"status": "fresh"}
        sources["cross_venue"] = {"status": "fresh"}
        result = self.call(
            source_states=sources,
            market_structure={"status": "ok", "score": 0.6},
            cross_venue={"status": "ok", "score": 0.4},
        )
        self.assertEqual(result["action"], "BUY")
        self.assertIn("market_structure", result["active_domains"])
        self.assertIn("cross_venue", result["active_domains"])
        self.assertAlmostEqual(sum(result["weights"].values()), 1.0)
        self.assertAlmostEqual(result["weights"]["technical"], 0.35)
        self.assertAlmostEqual(result["weights"]["orderflow"], 0.25)
        self.assertAlmostEqual(result["weights"]["derivatives"], 0.20)
        self.assertAlmostEqual(result["weights"]["market_structure"], 0.10)
        self.assertAlmostEqual(result["weights"]["cross_venue"], 0.10)

    def test_auxiliary_engines_cannot_replace_fresh_core_evidence(self):
        sources = {
            "spot": {"status": "fresh"},
            "technical": {"status": "fresh"},
            "orderflow": {"status": "stale"},
            "derivatives": {"status": "stale"},
            "market_structure": {"status": "fresh"},
            "cross_venue": {"status": "fresh"},
        }
        result = self.call(
            source_states=sources,
            market_structure={"status": "ok", "score": 0.9},
            cross_venue={"status": "ok", "score": 0.8},
        )
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("insufficient_fresh_core_evidence_domains", result["blockers"])

    def test_liquidation_pressure_is_a_warning_not_an_extra_direction_vote(self):
        risk = {
            "warnings": ["cross_venue_long_liquidation_pressure"],
            "use_in_decision": "risk_context_only_not_directional_vote",
        }
        result = self.call(liquidation_risk=risk)
        self.assertEqual(result["action"], "BUY")
        self.assertIn("cross_venue_long_liquidation_pressure", result["warnings"])
        self.assertEqual(result["risk_context_only"], "risk_context_only_not_directional_vote")

    def test_cross_venue_derivatives_warnings_do_not_change_vote_or_weights(self):
        context = {
            "status": "ok",
            "warnings": ["funding_rate_dispersion_across_venues"],
            "funding_8h_equivalent": {"median": 0.0001},
        }
        enriched_derivatives = dict(DERIV)
        enriched_derivatives["cross_venue_context_only"] = context
        base = self.call()
        enriched = self.call(derivatives=enriched_derivatives)
        self.assertEqual(enriched["action"], base["action"])
        self.assertEqual(enriched["score"], base["score"])
        self.assertEqual(enriched["weights"], base["weights"])
        self.assertIn("funding_rate_dispersion_across_venues", enriched["warnings"])

    def test_screener_events_are_context_only_and_do_not_change_decision(self):
        context = {
            "status": "ok",
            "event_count": 1,
            "decision_warnings": ["relative_volume_surge", "wide_spread"],
            "events": [{"type": "wide_spread", "creates_order": False}],
        }
        base = self.call()
        enriched = self.call(event_context=context)
        self.assertEqual(enriched["action"], base["action"])
        self.assertEqual(enriched["score"], base["score"])
        self.assertEqual(enriched["weights"], base["weights"])
        self.assertIn("wide_spread", enriched["warnings"])
        self.assertIn("relative_volume_surge", enriched["warnings"])

    def test_daily_four_hour_regime_conflict_forces_hold(self):
        technical = dict(TECH)
        technical["macro_conflict"] = True
        technical["warnings"] = ["daily_and_four_hour_regimes_conflict"]
        result = self.call(technical=technical)
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("daily_and_four_hour_regimes_conflict", result["blockers"])

    def test_weak_countertrend_buy_is_blocked_when_technical_opposes(self):
        sources = dict(FRESH)
        sources["derivatives"] = {"status": "stale"}
        result = self.call(
            technical={"status": "ok", "score": -0.30},
            orderflow={"status": "ok", "score": 0.60},
            derivatives={"status": "incomplete", "score": None},
            market_structure={"status": "ok", "score": 0.84},
            source_states=sources,
        )
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("technical_opposition_requires_stronger_confluence", result["blockers"])
        self.assertIn("technical_domain_opposes_direction", result["warnings"])
        self.assertEqual(result["buy_aligned_domains"], 2)

    def test_three_domain_countertrend_confluence_can_override_technical_opposition(self):
        sources = dict(FRESH)
        sources["market_structure"] = {"status": "fresh"}
        result = self.call(
            technical={"status": "ok", "score": -0.30},
            orderflow={"status": "ok", "score": 0.90},
            derivatives={"status": "ok", "score": 0.80},
            market_structure={"status": "ok", "score": 0.80},
            source_states=sources,
        )
        self.assertEqual(result["action"], "BUY")
        self.assertGreaterEqual(result["buy_aligned_domains"], 3)
        self.assertIn("technical_domain_opposes_direction", result["warnings"])

    def test_weak_confluence_holds(self):
        result = self.call(
            technical={"status": "ok", "score": 0.1},
            orderflow={"status": "ok", "score": 0.0},
            derivatives={"status": "ok", "score": 0.1},
        )
        self.assertEqual(result["action"], "HOLD")
        self.assertIn("insufficient_directional_confluence", result["blockers"])


if __name__ == "__main__":
    unittest.main()
