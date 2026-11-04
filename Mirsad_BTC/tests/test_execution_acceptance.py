from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from mirsad_mt5_execution_acceptance import build_open_decision


def valid_mt5_state() -> dict:
    return {
        "status": "CONNECTED",
        "symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "quote_age_seconds": 0.5,
        "quote": {
            "bid": 77756.56,
            "ask": 77756.66,
            "tick_age_seconds": 1,
        },
        "symbol_spec": {
            "tick_size": 0.01,
            "tick_value_loss": 0.01,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
            "point": 0.01,
            "digits": 2,
            "stops_level_points": 0,
            "freeze_level_points": 0,
        },
        "account": {"equity": 500.87},
    }


class ExecutionAcceptanceSizingTests(unittest.TestCase):
    def test_acceptance_order_respects_risk_and_notional_caps(self) -> None:
        decision, sizing = build_open_decision(valid_mt5_state())

        self.assertEqual(decision["status"], "READY")
        self.assertTrue(decision["command_ready"])
        self.assertEqual(decision["action"], "BUY")
        self.assertLessEqual(sizing["estimated_notional"], 1000.0)
        self.assertLessEqual(sizing["estimated_stop_loss"], sizing["risk_budget"])
        self.assertAlmostEqual(sizing["risk_fraction"], 0.005)
        self.assertGreater(sizing["volume"], 0)

    def test_acceptance_order_rejects_stale_tick(self) -> None:
        state = valid_mt5_state()
        state["quote"]["tick_age_seconds"] = 11
        with self.assertRaisesRegex(RuntimeError, "stale or outside"):
            build_open_decision(state)

    def test_acceptance_order_rejects_excessive_spread(self) -> None:
        state = valid_mt5_state()
        state["quote"]["bid"] = 77000.0
        state["quote"]["ask"] = 77756.66
        with self.assertRaisesRegex(RuntimeError, "stale or outside"):
            build_open_decision(state)

    def test_acceptance_order_refuses_broker_minimum_above_notional_cap(self) -> None:
        state = valid_mt5_state()
        state["symbol_spec"]["volume_min"] = 0.02
        state["symbol_spec"]["volume_step"] = 0.02
        with self.assertRaisesRegex(RuntimeError, "minimum lot exceeds"):
            build_open_decision(state)


if __name__ == "__main__":
    unittest.main()
