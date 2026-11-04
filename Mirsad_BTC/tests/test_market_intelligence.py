from __future__ import annotations

import unittest
from datetime import datetime, timezone

from mirsad.engines.market_intelligence import (
    MarketIntelligenceEngine,
    assess_market_risk,
    compose_directional_context,
    deduplicate_news_items,
    parse_rss,
    score_derivatives,
    score_headline_text,
    score_news_items,
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
                "long_short_ratio": 3.0, "timestamp_ms": 1_798_000_000_000,
                "funding_timestamp_ms": 1_798_000_000_000,
                "long_short_timestamp_ms": 1_798_000_000_000,
            },
            "Bybit": {
                "status": "READY", "funding_rate": -0.0005,
                "long_short_ratio": 1.0, "timestamp_ms": 1_798_000_000_000,
                "funding_timestamp_ms": 1_798_000_000_000,
                "long_short_timestamp_ms": 1_798_000_000_000,
            },
        }, now_ms=1_798_000_000_000)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["venue_count"], 2)
        self.assertLess(result["score"], 0)
        self.assertIn("open-interest change is context", result["scope"])

    def test_bybit_derivatives_include_account_long_short_ratio(self) -> None:
        engine = MarketIntelligenceEngine()

        def fake_json(url: str, *, ttl_seconds: int = 30):
            if "/tickers?" in url:
                return {"retCode": 0, "result": {"list": [{
                    "fundingRate": "0.0001", "nextFundingTime": "1794000000000",
                    "markPrice": "90000", "indexPrice": "89990",
                    "openInterest": "2100", "openInterestValue": "189000000",
                    "turnover24h": "1000000000", "volume24h": "12000",
                }]}}
            if "/open-interest?" in url:
                return {"retCode": 0, "result": {"list": [
                    {"openInterest": "2100", "timestamp": "1794000000000"},
                    {"openInterest": "2000", "timestamp": "1793999700000"},
                ]}}
            if "/account-ratio?" in url:
                return {"retCode": 0, "result": {"list": [
                    {"buyRatio": "0.6", "sellRatio": "0.4", "timestamp": "1794000000000"},
                ]}}
            raise AssertionError("Unexpected Bybit endpoint.")

        engine._json = fake_json
        result = engine._collect_bybit_derivatives()
        self.assertEqual(result["status"], "READY")
        self.assertAlmostEqual(result["long_short_ratio"], 1.5)
        self.assertAlmostEqual(result["open_interest_change_pct_35m"], 5.0)
        self.assertEqual(result["long_short_sample_count"], 1)

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
        self.assertTrue(any("chart images" in item and "EMA" in item for item in result["boundaries"]))


    def test_duplicate_headlines_are_counted_once_but_keep_both_publishers(self) -> None:
        now = 1_798_000_000_000
        items = deduplicate_news_items([
            {"source": "CoinDesk", "title": "Bitcoin ETF inflows rise after institutional adoption",
             "url": "https://one.example/story", "published_at_ms": now, "sentiment_score": 0.5},
            {"source": "Decrypt", "title": "Bitcoin ETF inflows rise after institutional adoption!",
             "url": "https://two.example/story", "published_at_ms": now - 30_000, "sentiment_score": 0.5},
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["duplicate_count"], 2)
        self.assertEqual(set(items[0]["sources"]), {"CoinDesk", "Decrypt"})
        score = score_news_items(items)
        self.assertEqual(score["source_count"], 2)

    def test_stale_derivatives_are_excluded_from_directional_score(self) -> None:
        now = 1_798_000_000_000
        result = score_derivatives({
            "Binance": {"status": "READY", "funding_rate": 0.001,
                        "long_short_ratio": 3.0, "timestamp_ms": now,
                        "funding_timestamp_ms": now - 901_000,
                        "long_short_timestamp_ms": now - 901_000},
            "Bybit": {"status": "READY", "funding_rate": 0.0002,
                      "long_short_ratio": 1.5, "timestamp_ms": now},
        }, now_ms=now, max_age_seconds=900)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["stale_venue_count"], 1)
        self.assertEqual(result["venues"]["Binance"]["directional_status"], "STALE")
        self.assertEqual(result["venues"]["Bybit"]["directional_status"], "FRESHNESS_UNKNOWN")

    def test_fear_greed_stale_daily_observation_is_not_directional(self) -> None:
        now = 1_798_000_000_000
        engine = MarketIntelligenceEngine()
        engine._json = lambda *args, **kwargs: {"data": [{
            "value": "95", "value_classification": "Extreme Greed",
            "timestamp": str((now - 48 * 60 * 60_000) // 1000),
        }]}
        result = engine._collect_fear_greed(now_ms=now)
        self.assertEqual(result["status"], "STALE")
        self.assertIsNone(result["score"])
        self.assertEqual(result["confidence"], 0.0)

    def test_trading_economics_calendar_requests_multiple_btc_relevant_countries(self) -> None:
        from datetime import datetime, timezone
        engine = MarketIntelligenceEngine(
            trading_economics_api_key="test-key",
            calendar_countries=["United States", "China", "Euro Area"],
        )
        captured_urls = []
        engine._json = lambda url, **kwargs: captured_urls.append(url) or [{
            "CalendarId": 77, "Date": "11/05/2026 12:30:00 PM",
            "Event": "CPI", "Country": "United States", "Currency": "USD",
            "Importance": 3, "Forecast": "2.5%", "Previous": "2.6%",
        }]
        result = engine._collect_trading_economics(now=datetime(2026, 11, 4, tzinfo=timezone.utc))
        self.assertIn("/united%20states,china,euro%20area/", captured_urls[0])
        self.assertEqual(result["countries"], ["united states", "china", "euro area"])
        self.assertEqual(result["events"][0]["importance"], "HIGH")
        self.assertEqual(result["events"][0]["forecast"], "2.5%")

    def test_market_risk_overlay_is_descriptive_and_never_blocks_entries(self) -> None:
        now = 1_798_000_000_000
        result = assess_market_risk(
            news={"items": [], "sentiment": {"status": "READY"}},
            fear_greed={"status": "READY", "value": 90},
            derivatives={"status": "UNAVAILABLE", "venue_scores": {}},
            calendar={"high_impact_window_active": False},
            now_ms=now,
        )
        self.assertEqual(result["level"], "ELEVATED")
        self.assertIn("EXTREME_CROWD_SENTIMENT", result["drivers"])
        self.assertFalse(result["automatic_entry_block"])


    def test_fresh_funding_survives_stale_long_short_ratio(self) -> None:
        now = 1_798_000_000_000
        result = score_derivatives({
            "Binance": {
                "status": "READY", "funding_rate": 0.0005,
                "long_short_ratio": 3.0,
                "funding_timestamp_ms": now,
                "long_short_timestamp_ms": now - 901_000,
            },
        }, now_ms=now, max_age_seconds=900)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["venue_count"], 1)
        details = result["venues"]["Binance"]
        self.assertEqual(details["funding_directional_status"], "FRESH")
        self.assertEqual(details["long_short_directional_status"], "STALE")
        self.assertEqual(details["directional_inputs_used"], {
            "funding_rate": True, "long_short_ratio": False,
        })
        self.assertAlmostEqual(result["score"], -1.0)

    def test_derivative_values_without_per_factor_timestamps_are_not_directional(self) -> None:
        now = 1_798_000_000_000
        result = score_derivatives({
            "Bybit": {
                "status": "READY", "funding_rate": 0.001,
                "long_short_ratio": 2.0, "timestamp_ms": now,
            },
        }, now_ms=now, max_age_seconds=900)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["venues"]["Bybit"]["directional_status"], "FRESHNESS_UNKNOWN")


if __name__ == "__main__":
    unittest.main()
