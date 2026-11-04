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
    def test_execution_ea_guards_netting_exposure_and_position_ownership(self) -> None:
        source = (
            PROJECT_ROOT / "mt5" / "Mirsad_BTC_ExecutionBridge.mq5"
        ).read_text(encoding="utf-8")

        self.assertIn("ACCOUNT_MARGIN_MODE_RETAIL_NETTING", source)
        self.assertIn("ACCOUNT_MARGIN_MODE_EXCHANGE", source)
        self.assertIn("ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", source)
        self.assertIn("HasOpenNettingSymbolExposure(command_symbol)", source)
        self.assertIn("PositionHistoryIsMirsadOwned(position_ticket)", source)
        self.assertIn("HistorySelectByPosition((ulong)position_identifier)", source)
        self.assertIn('"margin_mode\\":%I64d', source)
        self.assertIn('"hedging_mode\\":%s', source)

    def test_mir1_status_and_ack_are_published_from_flushed_atomic_snapshots(self) -> None:
        source = (
            PROJECT_ROOT / "mt5" / "Mirsad_BTC_ExecutionBridge.mq5"
        ).read_text(encoding="utf-8")

        writer_start = source.index("bool WriteCommonText(")
        writer_end = source.index("\n}", writer_start) + 2
        writer = source[writer_start:writer_end]
        self.assertIn('string temporary_name = file_name + ".tmp";', writer)
        self.assertIn("FileFlush(handle);", writer)
        self.assertIn("FileClose(handle);", writer)
        self.assertIn("FileMove(CommonPath(temporary_name), FILE_COMMON,", writer)
        self.assertIn("FILE_COMMON | FILE_REWRITE", writer)
        self.assertNotIn("FileOpen(CommonPath(file_name)", writer)
        self.assertIn('WriteCommonText("status.json", payload);', source)
        self.assertIn('WriteCommonText("ack.json", payload);', source)

    def test_mir1_command_id_is_persisted_and_read_back_before_broker_send(self) -> None:
        source = (
            PROJECT_ROOT / "mt5" / "Mirsad_BTC_ExecutionBridge.mq5"
        ).read_text(encoding="utf-8")

        save_start = source.index("bool SaveLastCommandId(")
        save_end = source.index("\n}", save_start) + 2
        save = source[save_start:save_end]
        self.assertIn('FileWriteString(handle, command_id + "\\r\\n")', save)
        self.assertIn("FileFlush(handle);", save)
        self.assertIn("if(!WasCommandSeen(command_id))", save)
        self.assertIn('if(!WriteCommonText("last_command_id.txt", command_id))', save)
        process_start = source.index("void ProcessCommand()")
        process = source[process_start:]
        self.assertLess(
            process.index("if(!SaveLastCommandId(command_id))"),
            process.index("OrderSend(request, result)"),
        )
        self.assertIn("This command ID exists in the persistent ledger.", process)
        self.assertIn("It will not be resent to avoid a duplicate trade.", process)

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
        # Give the risk budget room for the broker minimum so this case
        # isolates the independent USD 1,000 notional cap.
        state["account"]["equity"] = 20_000.0
        state["symbol_spec"]["volume_min"] = 0.02
        state["symbol_spec"]["volume_step"] = 0.02
        with self.assertRaisesRegex(RuntimeError, "minimum lot exceeds"):
            build_open_decision(state)


if __name__ == "__main__":
    unittest.main()
