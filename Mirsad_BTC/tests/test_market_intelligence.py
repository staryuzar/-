from __future__ import annotations

import unittest
from datetime import datetime, timezone

from mirsad.engines.market_intelligence import (
    MarketIntelligenceEngine,
    compose_directional_context,
    parse_rss,
    score_derivatives,
    score_headline_text,
)


class MarketIntelligenceEngineTests(unittest.TestCase):
    def test_rss_parser_preserves_source_link_and_utc_publication_time(self) -> None:
        payload = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Bitcoin ETF inflows rise after institutional adoption</title>
          <link>https://news.example.test/bitcoin-etf</link>
          <pubDate>Wed, 04 Nov 2026 12:30:00 GMT</pubDate>
          <description>Institutional adoption and ETF inflows.</description>
        </item></channel></rss>"""
        items = parse_rss(payload, source="Example News")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "Example News")
        self.assertEqual(items[0]["url"], "https://news.example.test/bitcoin-etf")
        self.assertEqual(items[0]["published_at_ms"], int(
            datetime(2026, 11, 4, 12, 30, tzinfo=timezone.utc).timestamp() * 1000
        ))
        self.assertGreater(items[0]["sentiment_score"], 0)

    def test_headline_keyword_score_is_explainable_and_neutral_when_no_terms_match(self) -> None:
        positive, positive_hits, negative_hits = score_headline_text("ETF inflows and institutional adoption")
        negative, _, _ = score_headline_text("Exchange hack triggers withdrawals paused")
        neutral, _, _ = score_headline_text("Bitcoin developer speaks at a conference")
        self.assertGreater(positive, 0)
        self.assertTrue(positive_hits)
        self.assertEqual(negative_hits, [])
        self.assertLess(negative, 0)
        self.assertEqual(neutral, 0.0)

    def test_derivatives_score_treats_extreme_long_positioning_as_crowding_risk(self) -> None:
        result = score_derivatives({
            "Binance": {
                "status": "READY", "funding_rate": 0.0005,
                "long_short_ratio": 3.0,
            },
            "Bybit": {
                "status": "READY", "funding_rate": -0.0005,
                "long_short_ratio": 1.0,
            },
        })
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["venue_count"], 2)
        self.assertLess(result["score"], 0)
        self.assertIn("open-interest change is context", result["scope"])

    def test_context_requires_two_independent_evidence_categories_for_ready(self) -> None:
        result = compose_directional_context(
            news={"status": "READY", "score": 0.5, "confidence": 0.8},
            fear_greed={"status": "READY", "score": -0.2, "confidence": 0.7},
            derivatives={"status": "OFFLINE", "score": None, "confidence": 0.0},
        )
        self.assertEqual(result["status"], "READY")
        self.assertGreaterEqual(result["evidence_coverage"], 0.55)
        self.assertAlmostEqual(result["directional_score"], 0.2455, places=3)
        self.assertIn("not a probability", result["confidence_basis"])

    def test_single_source_score_is_partial_not_full_readiness(self) -> None:
        result = compose_directional_context(
            news={"status": "READY", "score": 0.8, "confidence": 0.7},
            fear_greed={"status": "OFFLINE", "score": None, "confidence": 0.0},
            derivatives={"status": "OFFLINE", "score": None, "confidence": 0.0},
        )
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "BULLISH")

    def test_high_impact_calendar_event_sets_only_the_new_entry_window(self) -> None:
        now = 1_798_000_000_000
        market = {
            "market_context": {
                "economic_calendar": {
                    "status": "AVAILABLE",
                    "events": [{
                        "event_id": 7,
                        "event_time_utc_ms": now + 5 * 60_000,
                        "name": "US CPI",
                        "importance": "HIGH",
                        "currency": "USD",
                    }],
                },
            },
        }
        result = MarketIntelligenceEngine._calendar_context(
            market,
            {"status": "NOT_CONFIGURED", "events": []},
            now,
        )
        self.assertTrue(result["high_impact_window_active"])
        self.assertEqual(result["new_entry_gate"], "WAIT")
        self.assertEqual(result["active_high_impact_events"][0]["name"], "US CPI")
        self.assertEqual(result["gate_window_minutes"], {"before": 15, "after": 10})

    def test_collect_composes_independent_providers_and_exposes_provenance(self) -> None:
        engine = MarketIntelligenceEngine()
        engine._collect_news = lambda: {
            "status": "READY", "count": 4, "items": [],
            "sources": {"CoinDesk": "READY"},
            "sentiment": {"status": "READY", "score": 0.7, "confidence": 0.8},
        }
        engine._collect_fear_greed = lambda: {
            "status": "READY", "value": 25, "classification": "Extreme Fear",
            "score": 0.8, "confidence": 0.7, "attribution": "Data from alternative.me",
        }
        engine._collect_global_metrics = lambda: {
            "status": "READY", "metrics": {"bitcoin_dominance_pct": 55.0},
        }
        engine._collect_derivatives = lambda: {
            "status": "READY", "score": -0.2, "confidence": 0.8, "venue_count": 2, "venues": {},
        }
        engine._collect_trading_economics = lambda: {
            "status": "NOT_CONFIGURED", "events": [],
        }
        result = engine.collect(
            {"market_context": {"economic_calendar": {"status": "NOT_AVAILABLE", "events": []}}},
            now_ms=1_798_000_000_000,
        )
        self.assertEqual(result["schema"], "MIR-ENGINE1-INTELLIGENCE-1")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BULLISH")
        self.assertEqual(result["source_statuses"]["news"], "READY")
        self.assertIn("confidence_basis", result)
        self.assertTrue(any("does not read" in item for item in result["boundaries"]))


if __name__ == "__main__":
    unittest.main()
