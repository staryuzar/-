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
            "derivatives": {"status": "UNAVAILABLE", "venues": {}, "venue_scores": {}},
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
            self.assertEqual(report["provider_response_count"], 4)
            self.assertNotIn("mt5_broker", report["economic_calendar"]["source_statuses"])
            self.assertIn("standalone", report["scope"].lower())
            self.assertIn("no MT5 quote", report["scope"])

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
