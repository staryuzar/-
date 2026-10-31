import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bitcoinlab.execution_loop import execute_once
from bitcoinlab.ea_bridge import read_execution_loop_status


class ExecutionLoopTests(unittest.TestCase):
    def write_terminal(self, root):
        folder = Path(root) / "BitcoinIntelligenceLab"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        status = (
            f"BTCIL1|BTCUSD|PERIOD_M1|{stamp}|CONNECTED|70000|70001|0|"
            "READY: Headway board-execution mode|0.01|0|TRADE_READY|Headway-Live\n"
        )
        (folder / "ea_status.tsv").write_text(status, encoding="utf-8")
        (folder / "positions.tsv").write_text(
            "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n",
            encoding="utf-8",
        )
        return folder

    def report(self, action):
        return {
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
            "decision": {"action": action, "score": 0.62, "blockers": []},
            "technical": {"atr14": 120.0},
            "spot": {"last_bar": {"close_time_ms": 1_799_000_000_000}},
        }

    def test_hold_never_publishes_a_trade_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            result = execute_once(common_files=tmp, report=self.report("HOLD"))
            self.assertEqual(result["status"], "no_command")
            self.assertFalse((folder / "trade_command.txt").exists())

    def test_buy_publishes_one_expiring_open_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            result = execute_once(common_files=tmp, report=self.report("BUY"), volume=0.01)
            fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            self.assertEqual(result["status"], "published")
            self.assertEqual(fields[5], "OPEN")
            self.assertEqual(fields[6], "BUY")
            self.assertGreater(int(fields[3]), int(fields[2]))

    def test_opposite_decision_publishes_close_for_owned_ticket_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "4321|BTCUSD|0|0.01|70000|69900|69800|70400|-1.0\n",
                encoding="utf-8",
            )
            result = execute_once(common_files=tmp, report=self.report("SELL"))
            fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            self.assertEqual(result["status"], "published")
            self.assertEqual(fields[5], "CLOSE")
            self.assertEqual(fields[10], "4321")

    def test_repeated_close_cycle_uses_the_same_idempotent_command_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "4321|BTCUSD|0|0.01|70000|69900|69800|70400|-1.0\n",
                encoding="utf-8",
            )
            first = execute_once(common_files=tmp, report=self.report("SELL"))
            first_id = first["command"]["command_id"]
            time.sleep(1)
            second = execute_once(common_files=tmp, report=self.report("SELL"))
            second_id = second["command"]["command_id"]
            self.assertEqual(first_id, "BTC-CLOSE-4321")
            self.assertEqual(second_id, first_id)

    def test_execution_loop_writes_fresh_dashboard_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_terminal(tmp)
            execute_once(common_files=tmp, report=self.report("HOLD"))
            state = read_execution_loop_status(tmp)
            self.assertEqual(state["status"], "fresh")
            self.assertEqual(state["cycle_status"], "no_command")
            self.assertEqual(state["schema"], "BTCIL-EXEC1")
            self.assertEqual(state["plan"]["action"], "HOLD")

    def test_stale_execution_heartbeat_is_reported_as_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            old = datetime.fromtimestamp(1_700_000_000, timezone.utc).isoformat()
            (folder / "execution_loop_status.json").write_text(
                '{"schema":"BTCIL-EXEC1","updated_at_utc":"'
                + old + '","status":"no_command","plan":{"action":"HOLD"}}',
                encoding="utf-8",
            )
            from bitcoinlab.ea_bridge import read_execution_loop_status
            result = read_execution_loop_status(tmp, now_seconds=1_700_000_200)
            self.assertEqual(result["status"], "stale")
            self.assertEqual(result["cycle_status"], "no_command")

    def test_blocked_central_decision_never_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            report = self.report("BUY")
            report["decision"]["blockers"] = ["technical_source_not_fresh"]
            result = execute_once(common_files=tmp, report=report)
            self.assertEqual(result["status"], "decision_blocked")
            self.assertFalse((folder / "trade_command.txt").exists())


if __name__ == "__main__":
    unittest.main()
