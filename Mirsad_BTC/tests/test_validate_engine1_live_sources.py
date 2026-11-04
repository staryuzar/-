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
    def test_cli_passes_real_mt5_market_snapshot_into_market_intelligence(self) -> None:
        market = {
            "schema": "MIR-MT5-MARKET-2",
            "status": "LIVE",
            "market_context": {
                "economic_calendar": {
                    "status": "AVAILABLE",
                    "events": [],
                },
            },
        }
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
                "sources": {"mt5_broker": "AVAILABLE", "trading_economics": "NOT_CONFIGURED"},
                "countries_covered": [], "event_count": 0,
                "next_24h_high_impact_events": [],
            },
            "market_risk_assessment": {"status": "READY", "level": "NORMAL", "drivers": []},
            "source_statuses": {"news": "READY", "fear_greed": "READY", "global_metrics": "READY", "derivatives": "OFFLINE"},
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market_path = root / "market.json"
            output_path = root / "engine1-report.json"
            market_path.write_text(json.dumps(market), encoding="utf-8")
            args = [
                "validate_engine1_live_sources.py",
                "--market-snapshot", str(market_path),
                "--output", str(output_path),
            ]
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
            collect.assert_called_once_with(market)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(report["economic_calendar"]["source_statuses"]["mt5_broker"], "AVAILABLE")
            self.assertEqual(report["provider_response_count"], 3)

    def test_cli_rejects_non_mirsad_market_snapshot_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            market_path = root / "wrong.json"
            market_path.write_text(json.dumps({"schema": "WRONG"}), encoding="utf-8")
            with (
                patch.object(sys, "argv", [
                    "validate_engine1_live_sources.py",
                    "--market-snapshot", str(market_path),
                    "--output", str(root / "report.json"),
                ]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                with self.assertRaises(SystemExit):
                    main()


if __name__ == "__main__":
    unittest.main()
