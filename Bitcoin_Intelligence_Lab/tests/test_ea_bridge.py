import json
import tempfile
import time
import unittest
from pathlib import Path

from bitcoinlab.ea_bridge import read_ea_status, publish_decision_order


class EABridgeTests(unittest.TestCase):
    def write_status(self, root, *, when=None, symbol="BTCUSD", message="READY: Headway demo board-execution mode"):
        folder = Path(root) / "BitcoinIntelligenceLab"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time()) if when is None else when
        line = f"BTCIL1|{symbol}|PERIOD_M1|{stamp}|CONNECTED|70000.0|70001.0|0|{message}|0.01|0\n"
        (folder / "ea_status.tsv").write_text(line, encoding="utf-8")

    def report(self):
        return {
            "decision": {"action": "BUY", "score": 0.62},
            "technical": {"atr14": 120.0},
            "spot": {"last_bar": {"close_time_ms": 1_799_000_000_000}},
        }

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

    def test_hold_does_not_publish_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = publish_decision_order(report={"decision": {"action": "HOLD"}}, common_files=tmp)
        self.assertEqual(result["status"], "no_directional_decision")


if __name__ == "__main__":
    unittest.main()
