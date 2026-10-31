import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bitcoinlab.ea_bridge import read_execution_loop_status
from bitcoinlab.execution_loop import execute_once


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
        self.write_positions(folder, [])
        return folder

    def write_positions(self, folder, rows):
        header = (
            "ticket|symbol|type|volume|price_open|price_current|"
            "stop_loss|take_profit|profit\n"
        )
        body = "".join(
            f"{ticket}|BTCUSD|{kind}|{volume}|70000|69900|69800|70400|-1.0\n"
            for ticket, kind, volume in rows
        )
        (folder / "positions.tsv").write_text(header + body, encoding="utf-8")

    def write_ack(self, folder, command_id, status, action="OPEN"):
        (folder / "trade_command_ack.txt").write_text(
            json.dumps({
                "schema": "BTCIL1",
                "id": command_id,
                "status": status,
                "action": action,
                "detail": "broker confirmation fixture",
            }),
            encoding="utf-8",
        )

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
            self.write_positions(folder, [(4321, 0, "0.01")])
            result = execute_once(common_files=tmp, report=self.report("SELL"))
            fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            self.assertEqual(result["status"], "published")
            self.assertEqual(fields[5], "CLOSE")
            self.assertEqual(fields[10], "4321")

    def test_repeated_close_cycle_waits_for_the_same_command_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            self.write_positions(folder, [(4321, 0, "0.01")])
            first = execute_once(common_files=tmp, report=self.report("SELL"))
            first_id = first["command"]["command_id"]
            second = execute_once(common_files=tmp, report=self.report("SELL"))
            self.assertEqual(first_id, "BTC-CLOSE-4321-V1000000")
            self.assertEqual(second["status"], "command_pending")
            self.assertEqual(second["command"]["command_id"], first_id)

    def test_partial_close_remainder_gets_a_new_volume_scoped_command_id_after_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            self.write_positions(folder, [(4321, 0, "0.01")])
            first = execute_once(common_files=tmp, report=self.report("SELL"))
            first_id = first["command"]["command_id"]
            self.write_ack(folder, first_id, "CLOSE_PARTIAL_FILL_CONFIRMED", "CLOSE")
            self.write_positions(folder, [(4321, 0, "0.005")])

            second = execute_once(common_files=tmp, report=self.report("SELL"))
            self.assertEqual(first_id, "BTC-CLOSE-4321-V1000000")
            self.assertEqual(second["command"]["command_id"], "BTC-CLOSE-4321-V500000")
            self.assertNotEqual(first_id, second["command"]["command_id"])

    def test_inflight_broker_command_is_not_overwritten_by_new_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            first = execute_once(common_files=tmp, report=self.report("BUY"), volume=0.01)
            first_command = first["command"]["command_id"]
            command_path = folder / "trade_command.txt"
            original_command = command_path.read_text(encoding="ascii")
            self.write_ack(folder, first_command, "PARTIAL_FILL_PENDING", "OPEN")

            later = execute_once(common_files=tmp, report=self.report("SELL"), volume=0.01)
            self.assertEqual(later["status"], "command_pending")
            self.assertEqual(later["pending_command"]["ack_status"], "PARTIAL_FILL_PENDING")
            self.assertEqual(command_path.read_text(encoding="ascii"), original_command)

    def test_unconsumed_expired_command_retries_with_a_new_attempt_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            first = execute_once(common_files=tmp, report=self.report("BUY"), volume=0.01)
            fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            fields[2] = str(int(time.time()) - 100)
            fields[3] = str(int(time.time()) - 40)
            (folder / "trade_command.txt").write_text("|".join(fields) + "\n", encoding="ascii")

            retry = execute_once(common_files=tmp, report=self.report("SELL"), volume=0.01)
            self.assertEqual(retry["status"], "published")
            new_fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            self.assertEqual(new_fields[1], first["command"]["command_id"] + "-R1")
            self.assertEqual(new_fields[6], "SELL")

    def test_expired_command_consumed_by_ea_without_ack_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            first = execute_once(common_files=tmp, report=self.report("BUY"), volume=0.01)
            command_id = first["command"]["command_id"]
            fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            fields[2] = str(int(time.time()) - 100)
            fields[3] = str(int(time.time()) - 40)
            (folder / "trade_command.txt").write_text("|".join(fields) + "\n", encoding="ascii")
            (folder / "last_command_id.txt").write_text(command_id, encoding="ascii")

            later = execute_once(common_files=tmp, report=self.report("SELL"), volume=0.01)
            self.assertEqual(later["status"], "command_pending")
            self.assertEqual(later["pending_command"]["status"], "expired_unconfirmed")
            self.assertEqual(later["command"]["command_id"], command_id)
            self.assertTrue(later["pending_command"]["requires_reconciliation"])

    def test_final_broker_ack_allows_the_next_cycle_to_manage_updated_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            first = execute_once(common_files=tmp, report=self.report("BUY"), volume=0.01)
            command_id = first["command"]["command_id"]
            self.write_ack(folder, command_id, "OPEN_FILL_CONFIRMED", "OPEN")
            self.write_positions(folder, [(4321, 0, "0.01")])

            later = execute_once(common_files=tmp, report=self.report("SELL"))
            fields = (folder / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
            self.assertEqual(later["status"], "published")
            self.assertEqual(fields[5], "CLOSE")
            self.assertEqual(fields[10], "4321")

    def test_execution_loop_writes_fresh_dashboard_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_terminal(tmp)
            execute_once(common_files=tmp, report=self.report("HOLD"))
            state = read_execution_loop_status(tmp)
            self.assertEqual(state["status"], "fresh")
            self.assertEqual(state["cycle_status"], "no_command")
            self.assertEqual(state["schema"], "BTCIL-EXEC1")
            self.assertEqual(state["plan"]["action"], "HOLD")

    def test_last_command_id_survives_later_hold_cycles_after_final_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = self.write_terminal(tmp)
            opened = execute_once(
                common_files=tmp, report=self.report("BUY"), volume=0.01
            )
            command_id = opened["command"]["command_id"]
            self.write_ack(folder, command_id, "OPEN_FILL_CONFIRMED", "OPEN")
            execute_once(common_files=tmp, report=self.report("HOLD"))
            state = read_execution_loop_status(tmp)
            self.assertEqual(state["status"], "fresh")
            self.assertEqual(state["cycle_status"], "no_command")
            self.assertEqual(state["command_id"], command_id)
            self.assertEqual(state["last_command_id"], command_id)

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
            self.assertEqual(result["status"], "no_command")
            self.assertEqual(result["plan"]["reason"], "central_decision_is_not_executable")
            self.assertFalse((folder / "trade_command.txt").exists())


if __name__ == "__main__":
    unittest.main()
