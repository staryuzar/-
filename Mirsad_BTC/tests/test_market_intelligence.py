from __future__ import annotations

import time
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
                return {"retCode": 0, "time": "1794000000000", "result": {"list": [{
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
        self.assertEqual(result["funding_timestamp_ms"], 1_794_000_000_000)
        self.assertEqual(result["long_short_timestamp_ms"], 1_794_000_000_000)
        self.assertEqual(result["endpoint_statuses"]["ticker"], "RESPONSE")
        self.assertEqual(result["endpoint_statuses"]["interest"], "RESPONSE")
        self.assertEqual(result["endpoint_statuses"]["account_ratio"], "RESPONSE")

    def test_context_requires_minimum_configured_weight_coverage_for_ready(self) -> None:
        result = compose_directional_context(
            news={"status": "READY", "score": 0.5, "confidence": 0.8},
            fear_greed={"status": "READY", "score": -0.2, "confidence": 0.7},
            derivatives={"status": "OFFLINE", "score": None, "confidence": 0.0},
        )
        self.assertEqual(result["status"], "PARTIAL")
        self.assertAlmostEqual(result["evidence_coverage"], 0.45)
        self.assertAlmostEqual(result["directional_score"], 0.4222, places=3)
        self.assertIn("not a probability", result["confidence_basis"])

    def test_context_is_ready_when_derivatives_and_news_cover_required_weight(self) -> None:
        result = compose_directional_context(
            news={"status": "READY", "score": 0.5, "confidence": 0.8},
            fear_greed={"status": "OFFLINE", "score": None, "confidence": 0.0},
            derivatives={"status": "READY", "score": 0.2, "confidence": 0.9},
        )
        self.assertEqual(result["status"], "READY")
        self.assertAlmostEqual(result["evidence_coverage"], 0.95)
        self.assertAlmostEqual(result["directional_score"], 0.3263, places=3)

    def test_single_source_score_is_partial_not_full_readiness(self) -> None:
        result = compose_directional_context(
            news={"status": "READY", "score": 0.8, "confidence": 0.7},
            fear_greed={"status": "OFFLINE", "score": None, "confidence": 0.0},
            derivatives={"status": "OFFLINE", "score": None, "confidence": 0.0},
        )
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["direction"], "BULLISH")

    def test_high_impact_calendar_event_uses_independent_public_providers(self) -> None:
        now = 1_798_000_000_000
        result = MarketIntelligenceEngine._calendar_context(
            {
                "showmytrades": {"status": "READY", "events": [{
                    "event_id": "usd-cpi",
                    "event_time_utc_ms": now + 5 * 60_000,
                    "name": "US CPI",
                    "importance": "HIGH",
                    "currency": "USD",
                    "provider": "ShowMyTrades",
                }]},
                "trading_economics": {"status": "NOT_CONFIGURED", "events": []},
            },
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
        engine._collect_public_calendar = lambda *, now_ms=None: {
            "status": "EMPTY", "events": [], "server_time_ms": now_ms,
        }
        result = engine.collect(now_ms=1_798_000_000_000)
        self.assertEqual(result["schema"], "MIR-ENGINE1-INTELLIGENCE-1")
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["direction"], "BULLISH")
        self.assertEqual(result["source_statuses"]["news"], "READY")
        self.assertIn("confidence_basis", result)
        self.assertTrue(any("chart images" in item and "EMA" in item for item in result["boundaries"]))


    def test_public_calendar_uses_provider_clock_and_normalizes_events(self) -> None:
        engine = MarketIntelligenceEngine()
        now = 1_798_000_000_000
        requests = []
        engine._json = lambda url, **kwargs: requests.append((url, kwargs)) or {
            "server_time": now // 1000,
            "events": [{
                "ts": now // 1000 + 300,
                "currency": "USD",
                "impact": "high",
                "title": "US CPI",
                "forecast": "2.5%",
                "previous": "2.6%",
                "id": "usd-cpi",
            }],
        }
        result = engine._collect_public_calendar(now_ms=now)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["events"][0]["event_time_utc_ms"], now + 300_000)
        self.assertEqual(result["events"][0]["importance"], "HIGH")
        self.assertEqual(result["events"][0]["provider"], "ShowMyTrades")
        self.assertEqual(requests[0][1]["ttl_seconds"], 900)

    def test_public_calendar_rejects_stale_provider_clock(self) -> None:
        engine = MarketIntelligenceEngine()
        engine._json = lambda *args, **kwargs: {"server_time": 1_790_000_000, "events": []}
        result = engine._collect_public_calendar(now_ms=1_798_000_000_000)
        self.assertEqual(result["status"], "STALE")
        self.assertEqual(result["events"], [])

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
        }, now_ms=now, max_age_seconds=900)
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["stale_venue_count"], 1)
        self.assertEqual(result["venues"]["Binance"]["directional_status"], "STALE")

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
        self.assertEqual(result["stale_venue_count"], 1)
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


    def test_risk_overlay_does_not_use_stale_long_short_for_crowding_alert(self) -> None:
        now = 1_798_000_000_000
        result = assess_market_risk(
            news={"items": [], "sentiment": {"status": "READY"}},
            fear_greed={"status": "READY", "value": 50},
            derivatives={
                "status": "READY",
                "venue_scores": {
                    "Binance": {
                        "directional_status": "FRESH",
                        "funding_directional_status": "FRESH",
                        "long_short_directional_status": "STALE",
                        "funding_rate": 0.00001,
                        "long_short_ratio": 3.0,
                    }
                },
            },
            calendar={"high_impact_window_active": False},
            now_ms=now,
        )
        self.assertNotIn("EXTREME_DERIVATIVES_POSITIONING", result["drivers"])
        self.assertEqual(result["level"], "NORMAL")



    def test_binance_derivatives_emit_independent_funding_and_ratio_timestamps(self) -> None:
        engine = MarketIntelligenceEngine()
        stamp = 1_794_000_000_000

        def fake_json(url: str, *, ttl_seconds: int = 30):
            if "/premiumIndex?" in url:
                return {"time": str(stamp), "lastFundingRate": "0.0001",
                        "markPrice": "90000", "indexPrice": "89990"}
            if "/openInterest?" in url:
                return {"time": str(stamp), "openInterest": "2000"}
            if "openInterestHist" in url:
                return [{"sumOpenInterest": "1000", "timestamp": stamp - 300_000},
                        {"sumOpenInterest": "1010", "timestamp": stamp}]
            if "globalLongShortAccountRatio" in url:
                return [{"longShortRatio": "1.4", "timestamp": stamp}]
            raise AssertionError("Unexpected Binance endpoint.")

        engine._json = fake_json
        result = engine._collect_binance_derivatives()
        self.assertEqual(result["funding_timestamp_ms"], stamp)
        self.assertEqual(result["long_short_timestamp_ms"], stamp)
        scored = score_derivatives({"Binance": result}, now_ms=stamp)
        self.assertEqual(scored["status"], "PARTIAL")
        self.assertTrue(scored["venues"]["Binance"]["directional_inputs_used"]["funding_rate"])
        self.assertTrue(scored["venues"]["Binance"]["directional_inputs_used"]["long_short_ratio"])


    def test_okx_derivatives_emit_provider_timestamps_and_mark_ratio_scope(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDT")
        stamp = 1_798_000_000_000

        def fake_json(url: str, *, ttl_seconds: int = 30):
            if "/public/funding-rate?" in url:
                self.assertIn("instId=BTC-USDT-SWAP", url)
                return {"code": "0", "data": [{
                    "fundingRate": "0.0002", "settFundingRate": "0.00015",
                    "settState": "processing", "nextFundingTime": str(stamp + 3_600_000),
                    "ts": str(stamp),
                }]}
            if "/public/open-interest?" in url:
                self.assertIn("instType=SWAP", url)
                return {"code": "0", "data": [{
                    "instId": "BTC-USDT-SWAP", "oi": "35000",
                    "oiUsd": "3150000000", "ts": str(stamp),
                }]}
            if "/long-short-account-ratio?" in url:
                self.assertIn("ccy=BTC", url)
                return {"code": "0", "data": [
                    [str(stamp), "1.35"],
                    [str(stamp - 300_000), "1.30"],
                ]}
            raise AssertionError(f"Unexpected OKX endpoint: {url}")

        engine._json = fake_json
        result = engine._collect_okx_derivatives()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["instrument_id"], "BTC-USDT-SWAP")
        self.assertAlmostEqual(result["funding_rate"], 0.00015)
        self.assertEqual(result["funding_basis"], "CURRENT_SETTLEMENT_RATE")
        self.assertAlmostEqual(result["long_short_ratio"], 1.35)
        self.assertEqual(result["funding_timestamp_ms"], stamp)
        self.assertEqual(result["long_short_timestamp_ms"], stamp)
        self.assertIn("currency aggregate", result["long_short_ratio_scope"])
        scored = score_derivatives({"OKX": result}, now_ms=stamp)
        self.assertEqual(scored["venue_count"], 1)
        self.assertTrue(scored["venues"]["OKX"]["directional_inputs_used"]["funding_rate"])
        self.assertTrue(scored["venues"]["OKX"]["directional_inputs_used"]["long_short_ratio"])

    def test_okx_symbol_without_supported_quote_fails_closed_without_requests(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCXYZ")
        def fail_if_called(*args, **kwargs):
            raise AssertionError("Unsupported OKX symbol must not call any endpoint.")
        engine._json = fail_if_called
        result = engine._collect_okx_derivatives()
        self.assertEqual(result["status"], "OFFLINE")
        self.assertEqual(result["endpoint_statuses"]["funding"], "NOT_REQUESTED")

    def test_gateio_derivatives_use_provider_timestamped_account_ratio(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDT")
        stamp_seconds = 1_798_000_000
        stamp_ms = stamp_seconds * 1000

        def fake_json(url: str, *, ttl_seconds: int = 30):
            if "/tickers?" in url:
                self.assertIn("contract=BTC_USDT", url)
                return [{
                    "contract": "BTC_USDT",
                    "funding_rate": "0.00012",
                    "mark_price": "90010",
                    "index_price": "90000",
                }]
            if "/contract_stats?" in url:
                self.assertIn("interval=5m", url)
                return [
                    {"time": stamp_seconds - 300, "open_interest": "1000",
                     "open_interest_usd": 90000000, "lsr_account": 1.10,
                     "top_lsr_account": 1.25, "top_lsr_size": "1.3",
                     "lsr_taker": 0.95},
                    {"time": stamp_seconds, "open_interest": "1050",
                     "open_interest_usd": 94500000, "lsr_account": 1.40,
                     "top_lsr_account": 1.60, "top_lsr_size": "1.7",
                     "lsr_taker": 1.05},
                ]
            raise AssertionError(f"Unexpected Gate endpoint: {url}")

        engine._json = fake_json
        result = engine._collect_gateio_derivatives()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["contract"], "BTC_USDT")
        self.assertAlmostEqual(result["funding_rate"], 0.00012)
        self.assertIsNone(result["funding_timestamp_ms"])
        self.assertEqual(result["funding_timestamp_basis"], "UNSTAMPED_TICKER_SNAPSHOT_NOT_USED_DIRECTIONALLY")
        self.assertEqual(result["long_short_timestamp_ms"], stamp_ms)
        self.assertAlmostEqual(result["long_short_ratio"], 1.40)
        self.assertAlmostEqual(result["open_interest_change_pct_35m"], 5.0)
        self.assertAlmostEqual(result["top_trader_long_short_account_ratio"], 1.60)
        self.assertEqual(result["endpoint_statuses"]["ticker"], "RESPONSE")
        self.assertEqual(result["endpoint_statuses"]["contract_stats"], "RESPONSE")

        scored = score_derivatives({"Gate.io": result}, now_ms=stamp_ms)
        self.assertEqual(scored["venue_count"], 1)
        self.assertTrue(scored["venues"]["Gate.io"]["directional_inputs_used"]["long_short_ratio"])
        self.assertFalse(scored["venues"]["Gate.io"]["directional_inputs_used"]["funding_rate"])

    def test_gateio_unsupported_symbol_fails_closed_without_requests(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDC")

        def fail_if_called(*args, **kwargs):
            raise AssertionError("Unsupported Gate settlement mapping must not call any endpoint.")

        engine._json = fail_if_called
        result = engine._collect_gateio_derivatives()
        self.assertEqual(result["status"], "OFFLINE")
        self.assertEqual(result["endpoint_statuses"]["ticker"], "NOT_REQUESTED")

    def test_gateio_endpoint_failures_preserve_provider_reasons(self) -> None:
        engine = MarketIntelligenceEngine()

        def fake_json(url: str, *, ttl_seconds: int = 30):
            if "/tickers?" in url:
                raise TimeoutError("Gate ticker timed out")
            raise OSError("Gate stats route unavailable")

        engine._json = fake_json
        result = engine._collect_gateio_derivatives()
        self.assertEqual(result["status"], "OFFLINE")
        self.assertEqual(result["endpoint_statuses"]["ticker"], "OFFLINE")
        self.assertEqual(result["endpoint_statuses"]["contract_stats"], "OFFLINE")
        self.assertIn("TimeoutError", result["endpoint_errors"]["ticker"])
        self.assertIn("OSError", result["endpoint_errors"]["contract_stats"])

    def test_duplicate_non_latin_headlines_are_collapsed_across_publishers(self) -> None:
        now = 1_798_000_000_000
        items = deduplicate_news_items([
            {
                "source": "Arabic Publisher A",
                "title": "بيتكوين ترتفع بعد تدفقات صناديق التداول",
                "url": "https://one.example/bitcoin",
                "published_at_ms": now,
                "sentiment_score": 0.5,
            },
            {
                "source": "Arabic Publisher B",
                "title": "بيتكوين ترتفع بعد تدفقات صناديق التداول!",
                "url": "https://two.example/bitcoin",
                "published_at_ms": now - 30_000,
                "sentiment_score": 0.5,
            },
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["duplicate_count"], 2)
        self.assertEqual(set(items[0]["sources"]), {"Arabic Publisher A", "Arabic Publisher B"})


    def test_binance_derivative_endpoint_failures_preserve_provider_reasons(self) -> None:
        engine = MarketIntelligenceEngine()

        def fake_json(url: str, *, ttl_seconds: int = 30):
            if "/premiumIndex?" in url:
                raise TimeoutError("provider request timed out")
            raise OSError("network route unavailable")

        engine._json = fake_json
        result = engine._collect_binance_derivatives()
        self.assertEqual(result["status"], "OFFLINE")
        self.assertEqual(result["endpoint_statuses"]["premium"], "OFFLINE")
        self.assertIn("TimeoutError", result["endpoint_errors"]["premium"])
        self.assertIn("OSError", result["endpoint_errors"]["open_interest"])
        self.assertNotIn("api_key", result["endpoint_errors"]["premium"].lower())



    def test_deribit_fallback_collects_eight_hour_funding_with_provider_timestamp(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDT")
        stamp = 1_798_000_000_000
        captured_urls = []

        def fake_json(url: str, *, ttl_seconds: int = 30):
            captured_urls.append((url, ttl_seconds))
            return {
                "jsonrpc": "2.0",
                "result": {
                    "instrument_name": "BTC-PERPETUAL",
                    "timestamp": stamp,
                    "funding8h": "0.00016",
                    "currentFunding": "0.00002",
                    "openInterest": "12345",
                    "markPrice": "90010",
                    "indexPrice": "90000",
                },
            }

        engine._json = fake_json
        result = engine._collect_deribit_derivatives()
        self.assertIn("BTC-PERPETUAL", captured_urls[0][0])
        self.assertEqual(captured_urls[0][1], 30)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["funding_timestamp_ms"], stamp)
        self.assertEqual(result["funding_rate_basis"], "8H_RATE")
        self.assertIsNone(result["long_short_ratio"])
        self.assertEqual(result["open_interest"], 12345.0)

        scored = score_derivatives({"Deribit": result}, now_ms=stamp)
        self.assertEqual(scored["status"], "PARTIAL")
        self.assertEqual(scored["venue_count"], 1)
        self.assertTrue(scored["venues"]["Deribit"]["directional_inputs_used"]["funding_rate"])
        self.assertFalse(scored["venues"]["Deribit"]["directional_inputs_used"]["long_short_ratio"])

    def test_deribit_live_rest_snake_case_payload_maps_funding_and_provider_time(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDT")
        stamp = int(time.time() * 1000)
        engine._json = lambda *args, **kwargs: {
            "jsonrpc": "2.0",
            "result": {
                "timestamp": stamp,
                "instrument_name": "BTC-PERPETUAL",
                "funding_8h": 0.00007642,
                "current_funding": 0.00008376,
                "open_interest": 643331210,
                "mark_price": 78196.48,
                "index_price": 78170.39,
            },
        }
        result = engine._collect_deribit_derivatives()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["funding_rate"], 0.00007642)
        self.assertEqual(result["funding_timestamp_ms"], stamp)
        self.assertEqual(result["funding_rate_basis"], "8H_RATE")
        self.assertEqual(result["open_interest"], 643331210.0)
        self.assertEqual(result["mark_price"], 78196.48)
        self.assertEqual(result["index_price"], 78170.39)
        scored = score_derivatives({"Deribit": result}, now_ms=stamp)
        self.assertEqual(scored["venues"]["Deribit"]["funding_directional_status"], "FRESH")
        self.assertTrue(scored["venues"]["Deribit"]["directional_inputs_used"]["funding_rate"])

    def test_deribit_ticker_without_provider_timestamp_is_not_directional(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDT")
        engine._json = lambda *args, **kwargs: {
            "result": {"funding8h": "0.0002", "openInterest": "1000"}
        }
        result = engine._collect_deribit_derivatives()
        self.assertIsNone(result["funding_timestamp_ms"])
        scored = score_derivatives({"Deribit": result}, now_ms=1_798_000_000_000)
        self.assertEqual(scored["status"], "UNAVAILABLE")
        self.assertEqual(scored["venues"]["Deribit"]["funding_directional_status"], "FRESHNESS_UNKNOWN")

    def test_derivatives_collector_registers_deribit_as_an_independent_venue(self) -> None:
        engine = MarketIntelligenceEngine(symbol="BTCUSDT")
        current_stamp = int(time.time() * 1000)
        engine._collect_binance_derivatives = lambda: {"status": "OFFLINE"}
        engine._collect_bybit_derivatives = lambda: {"status": "OFFLINE"}
        engine._collect_okx_derivatives = lambda: {"status": "OFFLINE"}
        engine._collect_gateio_derivatives = lambda: {"status": "OFFLINE"}
        engine._collect_deribit_derivatives = lambda: {
            "status": "READY",
            "funding_rate": 0.0001,
            "funding_timestamp_ms": current_stamp,
            "long_short_ratio": None,
            "long_short_timestamp_ms": None,
        }
        result = engine._collect_derivatives()
        self.assertIn("Deribit", result["venues"])
        self.assertEqual(result["venue_count"], 1)
        self.assertEqual(result["status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
