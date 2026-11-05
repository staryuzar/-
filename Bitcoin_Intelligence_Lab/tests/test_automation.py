import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bitcoinlab.automation import run_auto_management_cycle


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.common = Path(self.tmp.name)
        folder = self.common / "BitcoinIntelligenceLab"
        folder.mkdir(parents=True)
        (folder / "ea_status.tsv").write_text(
            f"BTCIL1|BTCUSD|PERIOD_M1|{int(time.time())}|CONNECTED|70000|70001|0|READY: demo|0.01|0\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, action="BUY"):
        return {
            "as_of_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "decision": {"action": action, "blockers": []},
            "technical": {"atr14": 120.0},
            "spot": {"last_bar": {"close_time_ms": 1_799_000_000_000}},
        }

    def test_hold_does_not_publish_or_close(self):
        with patch("bitcoinlab.automation.current_ack", return_value={}):
            result = run_auto_management_cycle(
                report=self.report("HOLD"),
                positions=[{"ticket": 1, "symbol": "BTCUSD", "type": "SELL"}],
                common_files=self.common,
            )
        self.assertEqual(result["status"], "holding")
        self.assertFalse((self.common / "BitcoinIntelligenceLab" / "trade_command.txt").exists())

    def test_open_command_is_not_duplicated_while_waiting_for_ack(self):
        pending_state = {
            "pending": {
                "command_id": "BTC-OLD", "action": "OPEN", "side": "BUY",
                "issued_at": int(time.time()),
            }
        }
        with patch("bitcoinlab.automation.current_ack", return_value={}):
            result = run_auto_management_cycle(
                report=self.report(),
                positions=[],
                common_files=self.common,
                state=pending_state,
            )
        self.assertEqual(result["status"], "waiting_for_mt5")
        self.assertFalse((self.common / "BitcoinIntelligenceLab" / "trade_command.txt").exists())

    def test_acknowledged_opposite_position_is_closed_before_reversal(self):
        with patch(
            "bitcoinlab.automation.current_ack",
            return_value={"id": "BTC-CLOSE-10", "status": "CLOSED"},
        ):
            result = run_auto_management_cycle(
                report=self.report("SELL"),
                positions=[],
                common_files=self.common,
                state={
                    "pending": {
                        "command_id": "BTC-CLOSE-10", "action": "CLOSE",
                        "ticket": 10, "issued_at": int(time.time()),
                    }
                },
            )
        self.assertEqual(result["status"], "confirmed")
        self.assertIsNone(result["state"]["pending"])

    def test_expired_pending_command_is_cleared_without_new_order(self):
        now = int(time.time())
        with patch("bitcoinlab.automation.current_ack", return_value={}):
            result = run_auto_management_cycle(
                report=self.report(),
                positions=[],
                common_files=self.common,
                state={
                    "pending": {
                        "command_id": "BTC-OLD", "action": "OPEN", "side": "BUY",
                        "issued_at": now - 200,
                    }
                },
                now_seconds=now,
            )
        self.assertEqual(result["status"], "timeout")
        self.assertFalse((self.common / "BitcoinIntelligenceLab" / "trade_command.txt").exists())


if __name__ == "__main__":
    unittest.main()
