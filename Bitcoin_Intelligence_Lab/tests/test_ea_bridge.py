import json
import tempfile
import time
from datetime import datetime, timezone
import unittest
from pathlib import Path

from bitcoinlab.ea_bridge import (
    PositionSnapshotError, read_ea_status, read_execution_loop_status,
    publish_decision_order, read_positions, publish_close_order,
    pending_command_state,
)


class EABridgeTests(unittest.TestCase):
    def write_status(self, root, *, when=None, symbol="BTCUSD", message="READY: Headway board-execution mode", trading="TRADE_READY", server="Headway-Demo", daily_loss=0.25, daily_limit=2.00, include_risk_specs=True):
        folder = Path(root) / "BitcoinIntelligenceLab"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time()) if when is None else when
        line = f"BTCIL1|{symbol}|PERIOD_M1|{stamp}|CONNECTED|70000.0|70001.0|0|{message}|0.01|0|{trading}|{server}|{daily_loss}|{daily_limit}"
        if include_risk_specs:
            line += "|10000.00|0.0100000000|0.0100000000|0.01000000|0.01000000|100.00000000"
        line += "\n"
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

    def test_status_accepts_headway_server_dns_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, server="demo.trade-hw.online")
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "fresh")
        self.assertTrue(result["headway_server_ok"])
        self.assertNotIn("account_mode", result)

    def test_execution_loop_heartbeat_without_cycle_result_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            (folder / "execution_loop_status.json").write_text(
                json.dumps({
                    "schema": "BTCIL-EXEC1",
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                }),
                encoding="utf-8",
            )
            result = read_execution_loop_status(tmp)
        self.assertEqual(result["status"], "invalid")

    def test_non_headway_broker_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, server="OtherBroker-Demo")
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "wrong_broker")

    def test_status_exposes_daily_loss_and_limit_for_dashboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "fresh")
        self.assertAlmostEqual(result["daily_loss_percent"], 0.25)
        self.assertAlmostEqual(result["daily_loss_limit_percent"], 2.0)
        self.assertTrue(result["risk_specs_ready"])
        self.assertAlmostEqual(result["account_equity"], 10_000)
        self.assertAlmostEqual(result["tick_value_loss"], 0.01)
        self.assertAlmostEqual(result["volume_step"], 0.01)

    def test_malformed_daily_risk_fields_block_ea_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            path = Path(tmp) / "BitcoinIntelligenceLab" / "ea_status.tsv"
            fields = path.read_text(encoding="utf-8").strip().split("|")
            fields[13] = "not-a-number"
            path.write_text("|".join(fields) + "\n", encoding="utf-8")
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "invalid")

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

    def test_order_volume_is_sized_from_actual_broker_tick_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            result = publish_decision_order(
                report=self.report(), common_files=tmp,
                volume=100.0, risk_fraction=0.0025,
            )
            command = (Path(tmp) / "BitcoinIntelligenceLab" / "trade_command.txt").read_text(encoding="ascii").strip().split("|")
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["risk_sizing"]["sizing_method"], "broker_tick_value_loss")
        self.assertLess(result["volume"], 1.0)
        self.assertAlmostEqual(float(command[7]), result["volume"], places=8)
        self.assertLessEqual(result["risk_sizing"]["estimated_loss"], result["risk_sizing"]["risk_budget"])

    def test_daily_loss_at_limit_blocks_new_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, daily_loss=2.00, daily_limit=2.00)
            result = publish_decision_order(
                report=self.report(), common_files=tmp, volume=0.01,
            )
            command_path = Path(tmp) / "BitcoinIntelligenceLab" / "trade_command.txt"
        self.assertEqual(result["status"], "daily_loss_limit_reached")
        self.assertFalse(command_path.exists())

    def test_daily_loss_above_limit_blocks_new_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, daily_loss=2.10, daily_limit=2.00)
            result = publish_decision_order(
                report=self.report(), common_files=tmp, volume=0.01,
            )
            command_path = Path(tmp) / "BitcoinIntelligenceLab" / "trade_command.txt"
        self.assertEqual(result["status"], "daily_loss_limit_reached")
        self.assertFalse(command_path.exists())

    def test_daily_loss_below_limit_allows_risk_sized_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, daily_loss=1.99, daily_limit=2.00)
            result = publish_decision_order(
                report=self.report(), common_files=tmp, volume=0.01,
            )
        self.assertEqual(result["status"], "published")

    def test_old_ea_status_without_broker_risk_specs_cannot_open_new_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, include_risk_specs=False)
            terminal = read_ea_status(tmp)
            result = publish_decision_order(
                report=self.report(), common_files=tmp, volume=0.01,
            )
            command_path = Path(tmp) / "BitcoinIntelligenceLab" / "trade_command.txt"
        self.assertEqual(terminal["status"], "fresh")
        self.assertFalse(terminal["risk_specs_ready"])
        self.assertEqual(result["status"], "risk_specs_unavailable")
        self.assertFalse(command_path.exists())

    def test_malformed_broker_risk_specs_invalidate_terminal_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            path = Path(tmp) / "BitcoinIntelligenceLab" / "ea_status.tsv"
            line = path.read_text(encoding="utf-8")
            path.write_text(line.replace("|0.0100000000|0.0100000000|", "|bad|0.0100000000|"), encoding="utf-8")
            result = read_ea_status(tmp)
        self.assertEqual(result["status"], "invalid")

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

    def test_close_command_remains_available_without_new_entry_risk_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp, include_risk_specs=False)
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "12345|BTCUSD|0|0.01|70000|70100|69800|70400|1.25\n",
                encoding="utf-8",
            )
            terminal = read_ea_status(tmp)
            result = publish_close_order(ticket=12345, common_files=tmp)
        self.assertEqual(terminal["status"], "fresh")
        self.assertFalse(terminal["risk_specs_ready"])
        self.assertEqual(result["status"], "published")

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

    def test_stale_positions_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            path = folder / "positions.tsv"
            path.write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\\n",
                encoding="utf-8",
            )
            with self.assertRaises(PositionSnapshotError):
                read_positions(tmp, now_seconds=time.time() + 60)

    def test_missing_positions_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PositionSnapshotError):
                read_positions(tmp)

    def test_malformed_positions_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "12345|BTCUSD|0|not-a-volume|70000|70100|69800|70400|1.25\n",
                encoding="utf-8",
            )
            with self.assertRaises(PositionSnapshotError):
                read_positions(tmp)

    def test_pending_open_command_is_not_overwritten_by_direct_publisher(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            first = publish_decision_order(report=self.report(), common_files=tmp)
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            original = (folder / "trade_command.txt").read_text(encoding="ascii")
            (folder / "trade_command_ack.txt").write_text(
                json.dumps({
                    "schema": "BTCIL1", "id": first["command_id"],
                    "status": "SUBMITTED_PENDING", "action": "OPEN",
                    "detail": "broker request still pending",
                }),
                encoding="utf-8",
            )
            second = publish_decision_order(report=self.report(), common_files=tmp)
            current = (folder / "trade_command.txt").read_text(encoding="ascii")
        self.assertEqual(second["status"], "command_pending")
        self.assertEqual(current, original)

    def test_rejected_close_is_retried_with_new_attempt_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_status(tmp)
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            (folder / "positions.tsv").write_text(
                "ticket|symbol|type|volume|price_open|price_current|stop_loss|take_profit|profit\n"
                "12345|BTCUSD|0|0.01|70000|70100|69800|70400|1.25\n",
                encoding="utf-8",
            )
            first = publish_close_order(ticket=12345, common_files=tmp)
            first_id = first["command_id"]
            (folder / "trade_command_ack.txt").write_text(
                json.dumps({
                    "schema": "BTCIL1", "id": first_id,
                    "status": "ORDER_REJECTED_OR_CANCELLED", "action": "CLOSE",
                    "detail": "broker rejected close",
                }),
                encoding="utf-8",
            )
            second = publish_close_order(ticket=12345, common_files=tmp)
            second_id = second["command_id"]
            (folder / "trade_command_ack.txt").write_text(
                json.dumps({
                    "schema": "BTCIL1", "id": second_id,
                    "status": "REJECTED", "action": "CLOSE",
                    "detail": "broker rejected retry",
                }),
                encoding="utf-8",
            )
            third = publish_close_order(ticket=12345, common_files=tmp)
        self.assertEqual(first_id, "BTC-CLOSE-12345-V1000000")
        self.assertEqual(second_id, first_id + "-R1")
        self.assertEqual(third["command_id"], first_id + "-R2")
        self.assertEqual(third["status"], "published")

    def test_future_issued_command_is_invalid_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            (folder / "trade_command.txt").write_text(
                "BTCIL1|future-1|2000000010|2000000070|BTC|OPEN|BUY|0.01000000|69000|72000|0\n",
                encoding="ascii",
            )
            state = pending_command_state(tmp, now_seconds=2_000_000_000)
        self.assertEqual(state["status"], "invalid")
        self.assertTrue(state["pending"])
        self.assertIn("inconsistent", state["reason"])

    def test_command_ttl_outside_protocol_range_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "BitcoinIntelligenceLab"
            folder.mkdir(parents=True)
            (folder / "trade_command.txt").write_text(
                "BTCIL1|long-ttl|2000000000|2000000400|BTC|OPEN|BUY|0.01000000|69000|72000|0\n",
                encoding="ascii",
            )
            state = pending_command_state(tmp, now_seconds=2_000_000_000)
        self.assertEqual(state["status"], "invalid")
        self.assertTrue(state["pending"])

    def test_hold_does_not_publish_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = publish_decision_order(report={"decision": {"action": "HOLD"}}, common_files=tmp)
        self.assertEqual(result["status"], "no_directional_decision")


if __name__ == "__main__":
    unittest.main()
