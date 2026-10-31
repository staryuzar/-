import json
import tempfile
import time
from datetime import datetime, timezone
import unittest
from pathlib import Path

from bitcoinlab.ea_bridge import read_ea_status, publish_decision_order, read_positions, publish_close_order


class EABridgeTests(unittest.TestCase):
    def write_status(self, root, *, when=None, symbol="BTCUSD", message="READY: Headway board-execution mode", trading="TRADE_READY", server="Headway-Demo"):
        folder = Path(root) / "BitcoinIntelligenceLab"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time()) if when is None else when
        line = f"BTCIL1|{symbol}|PERIOD_M1|{stamp}|CONNECTED|70000.0|70001.0|0|{message}|0.01|0|{trading}|{server}\n"
        (folder / "ea_status.tsv").write_text(line, encoding="utf-8")

    def report(self):
        return {
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
            "decision": {"action": "BUY", "score": 0.62, "blockers": []},
            "technical": {"atr14": 120.0},
            "spot": {"last_bar": {"close_time_ms": 1_799_000_000_000}},
        }

    def test_status_stays_ready_after_trade_fill_message_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(
                tmp,
                message="OPEN_FILL_CONFIRMED: deal=123",
                trading="TRADE_READY",
            )
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "fresh")
        self.assertTrue(result["trading_ready"])

    def test_trade_blocked_marker_is_not_ready_even_if_message_says_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(
                tmp,
                message="READY: old message",
                trading="TRADE_BLOCKED",
            )
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "not_ready")
        self.assertFalse(result["trading_ready"])

    def test_status_rejects_non_headway_broker(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, server="OtherBroker-Demo")
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "wrong_broker")
        self.assertFalse(result["headway_server_ok"])

    def test_status_accepts_headway_live_server_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(
                tmp, message="READY: Headway board-execution mode",
                server="Headway-Live",
            )
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "fresh")
        self.assertTrue(result["headway_server_ok"])
        self.assertNotIn("demo_account_ok", result)
        self.assertNotIn("account_mode", result)

    def test_status_accepts_headway_demo_endpoint_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, server="demo.trade-hw.online")
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "fresh")
        self.assertTrue(result["headway_server_ok"])
        self.assertNotIn("account_mode", result)

    def test_old_status_without_broker_identity_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            stamp = int(time.time())
            (folder / "ea_status.tsv").write_text(
                f"BTCIL1|BTCUSD|PERIOD_M1|{stamp}|CONNECTED|70000|70001|0|READY: Headway demo|0.01|0|TRADE_READY\\n",
                encoding="utf-8",
            )
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "wrong_broker")

    def test_status_accepts_broker_suffix_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["symbol"], "BTCUSD")

    def test_stale_status_is_not_used_for_an_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, when=int(time.time()) - 300)
            result = publish_decision_order(report=self.report(), common_files=tmp)
        self.assertEqual(result["status"], "terminal_not_ready")

    def test_publish_uses_actual_headway_symbol_and_broker_quote(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            result = publish_decision_order(report=self.report(), common_files=tmp, volume=0.01)
            content = (Path(tmp) / "BitcoinIntelligenceLab" / "trade_command.txt").read_text(encoding="ascii")
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["symbol"], "BTCUSD")
        fields = content.strip().split("|")
        self.assertEqual(fields[4], "BTC")
        self.assertEqual(fields[5], "OPEN")
        self.assertEqual(fields[6], "BUY")
        self.assertGreater(float(fields[9]), 70001.0)

    def test_stale_signal_does_not_publish_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = self.report()
            report["as_of_utc"] = "2020-01-01T00:00:00+00:00"
            self.write_status(tmp)
            result = publish_decision_order(report=report, common_files=tmp)
        self.assertEqual(result["status"], "signal_stale")

    def test_positions_are_parsed_from_mt5_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir()
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "12345|BTCUSD|0|0.01|70000|70100|69800|70400|1.25\n",
                encoding="utf-8",
            )
            rows = read_positions(tmp)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticket"], 12345)
        self.assertEqual(rows[0]["type"], "BUY")
        self.assertAlmostEqual(rows[0]["profit"], 1.25)

    def test_close_command_requires_position_owned_by_ea(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "12345|BTCUSD|0|0.01|70000|70100|69800|70400|1.25\n",
                encoding="utf-8",
            )
            result = publish_close_order(ticket=12345, common_files=tmp)
            command = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
        self.assertEqual(result["status"], "published")
        self.assertEqual(command[5], "CLOSE")
        self.assertEqual(command[10], "12345")

    def test_hold_does_not_publish_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = publish_decision_order(report={"decision": {"action": "HOLD"}}, common_files=tmp)
        self.assertEqual(result["status"], "no_directional_decision")


if __name__ == "__main__":
    unittest.main()
