from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mirsad.engines.decision import DecisionEngine, _matching_positions, calculate_volume
import mirsad.engines.mt5_bridge as bridge_module
from mirsad.engines.mt5_bridge import MT5BridgeEngine


def make_open_decision(command_id: str = "MIR-" + "a" * 24) -> dict:
    return {
        "status": "READY",
        "command_ready": True,
        "action": "BUY",
        "signal_id": command_id,
        "symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "entry_reference": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "risk_plan": {"status": "READY", "volume": 0.2},
    }


def make_close_decision(command_id: str = "MIR-" + "b" * 24) -> dict:
    return {
        "status": "READY",
        "command_ready": True,
        "action": "CLOSE",
        "signal_id": command_id,
        "symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "position_ticket": 123456,
        "risk_plan": {
            "status": "READY",
            "volume": 0.1,
            "purpose": "close_existing_opposite_position",
        },
    }


class RiskSizingTests(unittest.TestCase):
    def test_volume_is_floored_to_allowed_step_from_minimum(self) -> None:
        # risk cash = 9.7; loss per lot = 10; raw volume = 0.97.
        result = calculate_volume(
            equity=9700,
            entry=100,
            stop_loss=90,
            tick_size=1,
            tick_value_loss=1,
            volume_min=0.1,
            volume_step=0.05,
            volume_max=2.0,
            risk_fraction=0.001,
        )
        self.assertEqual(result["status"], "READY")
        self.assertAlmostEqual(result["volume"], 0.95)
        self.assertLessEqual(result["estimated_loss"], result["risk_cash"])

    def test_volume_below_broker_minimum_is_blocked(self) -> None:
        result = calculate_volume(
            equity=100,
            entry=100,
            stop_loss=90,
            tick_size=1,
            tick_value_loss=1,
            volume_min=0.1,
            volume_step=0.1,
            volume_max=10,
            risk_fraction=0.001,
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_non_finite_specs_are_rejected(self) -> None:
        result = calculate_volume(
            equity=float("nan"),
            entry=100,
            stop_loss=90,
            tick_size=1,
            tick_value_loss=1,
            volume_min=0.1,
            volume_step=0.1,
            volume_max=10,
        )
        self.assertEqual(result["status"], "UNAVAILABLE")


class DecisionBoundaryTests(unittest.TestCase):
    def test_single_venue_cannot_generate_directional_decision(self) -> None:
        result = DecisionEngine().analyze(
            {"status": "PARTIAL", "venue_count": 1, "primary_venue": "OKX Spot"},
            {},
            {},
        )
        self.assertEqual(result["action"], "WAIT")
        self.assertEqual(result["status"], "NOT_READY")
        self.assertIn("two current independent public venues", result["reason"])

    def test_position_manager_only_sees_mirsad_magic(self) -> None:
        bridge = {
            "magic_number": 26110201,
            "positions": [
                {"ticket": 1, "symbol": "BTC", "type": 0, "magic": 26110201, "volume": 0.1},
                {"ticket": 2, "symbol": "BTC", "type": 1, "magic": 888, "volume": 0.2},
                {"ticket": 3, "symbol": "ETH", "type": 0, "magic": 26110201, "volume": 0.3},
            ],
        }
        positions = _matching_positions(bridge, "BTC")
        self.assertEqual([p["ticket"] for p in positions], [1])


class BridgeProtocolTests(unittest.TestCase):
    def test_open_and_close_envelopes_validate(self) -> None:
        open_envelope = MT5BridgeEngine._validate_decision(make_open_decision())
        close_envelope = MT5BridgeEngine._validate_decision(make_close_decision())
        self.assertEqual(open_envelope["action"], "BUY")
        self.assertEqual(open_envelope["schema"], "MIR1")
        self.assertEqual(close_envelope["action"], "CLOSE")
        self.assertEqual(close_envelope["position_ticket"], 123456)

    def test_close_without_ticket_is_rejected(self) -> None:
        decision = make_close_decision()
        decision["position_ticket"] = 0
        with self.assertRaises(ValueError):
            MT5BridgeEngine._validate_decision(decision)

    def test_command_is_not_replaced_while_previous_command_is_unsettled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = MT5BridgeEngine(common_files=temp)
            with patch.object(bridge_module, "ENABLE_ORDER_PUBLISH", True):
                first = engine.publish_decision(make_open_decision(), {"status": "CONNECTED"})
                self.assertEqual(first["status"], "PUBLISHED")

                second = make_open_decision("MIR-" + "c" * 24)
                blocked = engine.publish_decision(second, {"status": "CONNECTED"})
                self.assertEqual(blocked["status"], "PENDING_COMMAND_BLOCKED")

                command_path = Path(temp) / "MirsadBTC" / "command.json"
                command = json.loads(command_path.read_text(encoding="utf-8"))
                ack_path = Path(temp) / "MirsadBTC" / "ack.json"
                ack_path.write_text(json.dumps({
                    "schema": "MIR1",
                    "command_id": command["command_id"],
                    "state": "FILLED",
                }), encoding="utf-8")

                published = engine.publish_decision(second, {"status": "CONNECTED"})
                self.assertEqual(published["status"], "PUBLISHED")
                replacement = json.loads(command_path.read_text(encoding="utf-8"))
                self.assertEqual(replacement["command_id"], second["signal_id"])

    def test_bridge_reads_live_magic_and_position_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "MirsadBTC"
            root.mkdir()
            payload = {
                "schema": "MIR1",
                "terminal_connected": True,
                "heartbeat_at_ms": int(time.time() * 1000),
                "magic_number": 26110201,
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "quote": {"bid": 99999.0, "ask": 100000.0, "time_ms": int(time.time() * 1000),
                          "tick_age_seconds": 1},
                "symbol_spec": {"tick_size": 0.01},
                "positions": [],
            }
            (root / "status.json").write_text(json.dumps(payload), encoding="utf-8")
            bridge = MT5BridgeEngine(common_files=temp).inspect()
            self.assertEqual(bridge["status"], "CONNECTED")
            self.assertEqual(bridge["magic_number"], 26110201)
            self.assertEqual(bridge["symbol"], "BTC")


if __name__ == "__main__":
    unittest.main()
