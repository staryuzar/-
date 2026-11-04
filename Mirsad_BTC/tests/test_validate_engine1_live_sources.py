from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.validate_engine1_live_sources import main


class Engine1LiveSourceValidatorTests(unittest.TestCase):
    def test_cli_collects_standalone_engine1_intelligence_without_mt5_input(self) -> None:
        result = {
            "schema": "MIR-ENGINE1-INTELLIGENCE-1",
            "status": "READY",
            "symbol": "BTCUSDT",
            "captured_at_ms": 1_798_000_000_000,
            "direction": "NEUTRAL",
            "directional_score": 0.0,
            "confidence": 0.7,
            "evidence_coverage": 0.8,
            "components": {"news": {"contributes": True, "status": "READY"}},
            "news": {
                "status": "READY", "count": 1, "items": [],
                "sources": {"CoinDesk": "READY"},
                "sentiment": {"status": "READY", "score": 0.0},
            },
            "fear_greed": {"status": "READY", "value": 50},
            "global_metrics": {"status": "READY", "metrics": {}},
            "derivatives": {
                "status": "PARTIAL",
                "venues": {"Gate.io": {
                    "status": "READY", "funding_rate": 0.0001,
                    "funding_timestamp_ms": None,
                    "funding_timestamp_basis": "UNSTAMPED_TICKER_SNAPSHOT_NOT_USED_DIRECTIONALLY",
                    "long_short_ratio": 1.4,
                    "long_short_ratio_scope": "Gate USDT-perpetual account-level position-user ratio (lsr_account)",
                    "top_trader_long_short_account_ratio": 1.6,
                    "top_trader_long_short_position_ratio": 1.7,
                    "taker_long_short_ratio": 1.05,
                    "open_interest_change_pct_35m": 5.0,
                    "timestamp_basis": "PROVIDER_TIMESTAMP",
                    "endpoint_statuses": {"ticker": "RESPONSE", "contract_stats": "RESPONSE"},
                    "endpoint_errors": {},
                }},
                "venue_scores": {"Gate.io": {
                    "directional_status": "FRESH",
                    "age_seconds": 10,
                    "funding_directional_status": "FRESHNESS_UNKNOWN",
                    "long_short_directional_status": "FRESH",
                }},
            },
            "economic_calendar": {
                "status": "READY",
                "sources": {"showmytrades": "READY", "trading_economics": "NOT_CONFIGURED"},
                "countries_covered": ["US"], "event_count": 0,
                "next_24h_high_impact_events": [],
            },
            "market_risk_assessment": {"status": "READY", "level": "NORMAL", "drivers": []},
            "source_statuses": {
                "news": "READY", "fear_greed": "READY", "global_metrics": "READY",
                "derivatives": "OFFLINE", "showmytrades_calendar": "READY",
                "trading_economics_calendar": "NOT_CONFIGURED",
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "engine1-report.json"
            args = ["validate_engine1_live_sources.py", "--output", str(output_path)]
            with (
                patch.object(sys, "argv", args),
                patch(
                    "scripts.validate_engine1_live_sources.MarketIntelligenceEngine.collect",
                    return_value=result,
                ) as collect,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            collect.assert_called_once_with()
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["overall_status"], "READY")
            self.assertEqual(report["economic_calendar"]["source_statuses"]["showmytrades"], "READY")
            gate = report["derivatives"]["venues"]["Gate.io"]
            self.assertIn("lsr_account", gate["long_short_ratio_scope"])
            self.assertEqual(gate["funding_timestamp_basis"], "UNSTAMPED_TICKER_SNAPSHOT_NOT_USED_DIRECTIONALLY")
            self.assertEqual(gate["top_trader_long_short_account_ratio"], 1.6)
            self.assertEqual(report["provider_response_count"], 4)
            self.assertNotIn("mt5_broker", report["economic_calendar"]["source_statuses"])
            self.assertIn("standalone", report["scope"].lower())
            self.assertIn("no mt5 quote", report["scope"].lower())

    def test_cli_rejects_legacy_mt5_snapshot_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(sys, "argv", [
                    "validate_engine1_live_sources.py",
                    "--market-snapshot", str(Path(directory) / "market.json"),
                ]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    main()
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
