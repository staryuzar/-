from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validate_engine1_live_sources import _acceptance_findings, build_report, main


def make_engine1_result() -> dict:
    now = int(time.time() * 1000)
    fresh_venues = {
        name: {
            "status": "READY", "provider_status": "READY", "directional_status": "FRESH", "age_seconds": age,
            "funding_directional_status": "FRESH", "long_short_directional_status": "FRESH",
            "funding_rate": 0.0001, "long_short_ratio": 2.0,
            "long_short_ratio_scope": "BTC perpetual account ratio",
            "endpoint_statuses": {"ticker": "RESPONSE"}, "endpoint_errors": {},
        }
        for name, age in (("Binance", 10.0), ("OKX", 20.0), ("Bybit", 30.0))
    }
    return {
        "schema": "MIR-ENGINE1-INTELLIGENCE-1", "engine": "engine_1_market_intelligence",
        "status": "READY", "symbol": "BTCUSDT", "captured_at_ms": now,
        "direction": "BEARISH", "directional_score": -0.25,
        "confidence": 0.82, "evidence_coverage": 1.0,
        "components": {
            "derivatives": {"status": "READY", "score": -0.3, "weight": 0.55, "confidence": 0.8, "contributes": True},
            "news": {"status": "READY", "score": -0.2, "weight": 0.4, "confidence": 1.0, "contributes": True},
            "fear_greed": {"status": "READY", "score": 0.4, "weight": 0.05, "confidence": 0.7, "contributes": True},
        },
        "news": {
            "status": "READY", "count": 40, "fresh_count_72h": 30,
            "freshest_age_seconds": 300.0, "headline_source_count": 4,
            "sources": {"CoinDesk": "READY", "Cointelegraph": "READY", "The Block": "READY", "Decrypt": "READY"},
            "sentiment": {"status": "READY", "score": -0.2, "classified_count": 20},
        },
        "fear_greed": {"status": "READY", "value": 28, "classification": "Fear", "freshness_age_seconds": 3600.0, "score": 0.44},
        "global_metrics": {"status": "READY", "freshness_status": "FRESH", "freshness_age_seconds": 300.0,
                           "metrics": {"total_market_cap_usd": 1e12, "bitcoin_dominance_pct": 55.0}},
        "derivatives": {"status": "READY", "score": -0.3, "confidence": 0.8, "venue_count": 3,
                         "stale_venue_count": 0, "freshness_max_age_seconds": 900,
                         "venues": fresh_venues, "venue_scores": fresh_venues},
        "economic_calendar": {"status": "READY", "sources": {"showmytrades": "READY", "forex_factory": "READY",
                              "trading_economics": "NOT_CONFIGURED"}, "countries_covered": ["USD", "EUR"],
                              "event_count": 80, "next_24h_high_impact_events": [], "high_impact_window_active": False},
        "market_risk_assessment": {"status": "READY", "level": "ELEVATED", "drivers": ["RECENT_HEADLINE_RISK"],
                                   "automatic_entry_block": False},
        "source_statuses": {
            "news": "READY", "fear_greed": "READY", "global_metrics": "READY", "derivatives": "READY",
            "public_calendar": "READY", "forex_factory_calendar": "READY",
            "showmytrades_calendar": "READY", "trading_economics": "NOT_CONFIGURED",
            "trading_economics_calendar": "NOT_CONFIGURED",
        },
    }


class Engine1LiveSourceValidatorTests(unittest.TestCase):
    def test_cli_collects_standalone_engine1_and_passes_strict_operational_gate(self) -> None:
        result = make_engine1_result()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "engine1-report.json"
            with (
                patch.object(sys, "argv", ["validate_engine1_live_sources.py", "--output", str(output_path)]),
                patch("scripts.validate_engine1_live_sources.MarketIntelligenceEngine.collect", return_value=result) as collect,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = main()
            self.assertEqual(exit_code, 0)
            collect.assert_called_once_with()
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["overall_status"], "READY")
            self.assertEqual(report["acceptance"]["status"], "PASS")
            self.assertEqual(report["provider_response_count"], 7)
            self.assertEqual(report["economic_calendar"]["source_statuses"]["showmytrades"], "READY")
            self.assertEqual(report["economic_calendar"]["source_statuses"]["forex_factory"], "READY")
            self.assertFalse(report["acceptance"]["trading_economics_required"])
            self.assertTrue(any("optional" in warning.lower() for warning in report["acceptance"]["warnings"]))
            gate = report["derivatives"]["venues"]["OKX"]
            self.assertEqual(gate["long_short_ratio_scope"], "BTC perpetual account ratio")
            self.assertIn("standalone", report["scope"].lower())
            self.assertIn("no mt5 quote", report["scope"].lower())

    def test_acceptance_fails_when_primary_source_coverage_is_incomplete(self) -> None:
        result = make_engine1_result()
        result["news"]["fresh_count_72h"] = 1
        result["news"]["headline_source_count"] = 1
        result["news"]["sources"] = {"CoinDesk": "READY"}
        result["derivatives"]["venues"] = {"Binance": result["derivatives"]["venues"]["Binance"]}
        result["economic_calendar"]["sources"]["forex_factory"] = "OFFLINE"
        result["source_statuses"]["forex_factory_calendar"] = "OFFLINE"
        report = build_report(result)
        self.assertEqual(report["acceptance"]["status"], "FAIL")
        self.assertGreaterEqual(len(report["acceptance"]["blockers"]), 3)

    def test_acceptance_requires_all_three_directional_components(self) -> None:
        result = make_engine1_result()
        result["components"]["fear_greed"]["contributes"] = False
        result["evidence_coverage"] = 0.95
        report = build_report(result)
        self.assertEqual(report["acceptance"]["status"], "FAIL")
        self.assertTrue(any("3 configured directional components" in item for item in report["acceptance"]["blockers"]))

    def test_acceptance_requires_three_fresh_derivative_venues(self) -> None:
        result = make_engine1_result()
        result["derivatives"]["venues"] = {"Binance": result["derivatives"]["venues"]["Binance"],
                                            "OKX": result["derivatives"]["venues"]["OKX"]}
        report = build_report(result)
        self.assertEqual(report["acceptance"]["status"], "FAIL")
        self.assertTrue(any("at least 3 independent venues" in item for item in report["acceptance"]["blockers"]))

    def test_acceptance_rejects_stale_engine1_snapshot(self) -> None:
        result = make_engine1_result()
        result["captured_at_ms"] -= 180_000
        blockers, _ = _acceptance_findings(build_report(result), now_ms=result["captured_at_ms"] + 180_000)
        self.assertTrue(any("not fresh" in item.lower() for item in blockers))

    def test_cli_returns_failure_when_strict_gate_fails_even_with_provider_response(self) -> None:
        result = make_engine1_result()
        result["derivatives"]["venues"] = {}
        result["economic_calendar"]["sources"] = {"showmytrades": "OFFLINE", "forex_factory": "OFFLINE"}
        result["source_statuses"]["public_calendar"] = "OFFLINE"
        result["source_statuses"]["forex_factory_calendar"] = "OFFLINE"
        result["economic_calendar"]["status"] = "NOT_AVAILABLE"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.json"
            with (
                patch.object(sys, "argv", ["validate_engine1_live_sources.py", "--output", str(output)]),
                patch("scripts.validate_engine1_live_sources.MarketIntelligenceEngine.collect", return_value=result),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main(), 2)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["acceptance"]["status"], "FAIL")

    def test_cli_rejects_legacy_mt5_snapshot_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(sys, "argv", ["validate_engine1_live_sources.py", "--market-snapshot", str(Path(directory) / "market.json")]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

