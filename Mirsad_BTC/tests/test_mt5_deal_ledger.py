from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from mirsad.engines.mt5_bridge import MT5BridgeEngine
from mirsad.storage import load_mt5_deal_history, save_mt5_deal_history


def make_deal_history(**overrides):
    now = int(time.time() * 1000)
    deal = {
        "deal_ticket": "10001",
        "order_ticket": "20001",
        "position_id": "30001",
        "magic": 26110201,
        "symbol": "BTC",
        "type": 1,
        "entry": 1,
        "reason": 3,
        "time_utc_ms": now - 1000,
        "volume": 0.01,
        "price": 65000.0,
        "profit": 12.5,
        "commission": -0.25,
        "swap": -0.05,
        "fee": -0.02,
        "net_cashflow": 12.18,
        "currency": "USD",
        "comment": "MIR-test",
    }
    deal.update(overrides.pop("deal", {}))
    return {
        "schema": "MIR1-DEALS-1",
        "status": "READY",
        "queried_at_utc_ms": now,
        "window_start_utc_ms": now - 90 * 86400 * 1000,
        "window_end_utc_ms": now,
        "history_total_selected": 1,
        "history_start_index": 0,
        "returned_count": 1,
        "truncated": False,
        "symbol": "BTC",
        "magic": 26110201,
        "currency": "USD",
        "time_basis": "UTC_NORMALIZED_FROM_MT5_SERVER_TIME",
        "deals": [deal],
        **overrides,
    }


class MT5DealHistoryBridgeTests(unittest.TestCase):
    def test_bridge_accepts_only_matching_mirsad_magic_and_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MirsadBTC"
            root.mkdir(parents=True)
            now = int(time.time() * 1000)
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1",
                "terminal_connected": True,
                "execution_enabled": False,
                "heartbeat_at_ms": now,
                "symbol": "BTC",
                "market_symbol": "BTCUSDT",
                "magic_number": 26110201,
                "account": {"server": "Headway-Demo", "currency": "USD"},
                "quote": {"time_ms": now, "bid": 64999.0, "ask": 65000.0,
                          "tick_age_seconds": 1},
                "symbol_spec": {},
                "positions": [],
            }), encoding="utf-8")
            (root / "deals.json").write_text(
                json.dumps(make_deal_history()), encoding="utf-8"
            )

            result = MT5BridgeEngine(str(directory)).inspect()

            self.assertEqual(result["status"], "CONNECTED")
            self.assertEqual(result["deal_history"]["status"], "READY")
            self.assertEqual(len(result["deal_history"]["deals"]), 1)
            self.assertEqual(result["deal_history"]["deals"][0]["deal_ticket"], "10001")
            self.assertTrue(result["common_files_files"]["deals.json"])

    def test_bridge_rejects_manual_or_other_ea_magic_in_deal_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MirsadBTC"
            root.mkdir(parents=True)
            now = int(time.time() * 1000)
            (root / "status.json").write_text(json.dumps({
                "schema": "MIR1", "terminal_connected": True,
                "execution_enabled": False, "heartbeat_at_ms": now,
                "symbol": "BTC", "market_symbol": "BTCUSDT",
                "magic_number": 26110201, "account": {"server": "Headway-Demo"},
                "quote": {"time_ms": now}, "symbol_spec": {}, "positions": [],
            }), encoding="utf-8")
            (root / "deals.json").write_text(
                json.dumps(make_deal_history(deal={"magic": 999})), encoding="utf-8"
            )

            result = MT5BridgeEngine(str(directory)).inspect()

            self.assertEqual(result["deal_history"]["status"], "INVALID")
            self.assertEqual(result["deal_history"]["deals"], [])


class MT5DealHistoryStorageTests(unittest.TestCase):
    def test_deals_are_upserted_once_and_loaded_by_magic_and_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "mirsad.sqlite3"
            history = make_deal_history()

            first = save_mt5_deal_history(history, db_path=db)
            second = save_mt5_deal_history(history, db_path=db)
            rows = load_mt5_deal_history(
                magic_number=26110201, symbol="BTC", db_path=db
            )

            self.assertEqual(first["status"], "READY")
            self.assertEqual(first["stored"], 1)
            self.assertEqual(second["stored"], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["deal_ticket"], "10001")
            self.assertAlmostEqual(rows[0]["net_cashflow"], 12.18)

    def test_invalid_net_cashflow_is_never_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "mirsad.sqlite3"
            history = make_deal_history(deal={"net_cashflow": 999.0})

            result = save_mt5_deal_history(history, db_path=db)
            rows = load_mt5_deal_history(
                magic_number=26110201, symbol="BTC", db_path=db
            )

            self.assertEqual(result["status"], "INVALID")
            self.assertEqual(rows, [])

    def test_unavailable_history_does_not_become_an_empty_success(self):
        result = save_mt5_deal_history({
            "schema": "MIR1-DEALS-1",
            "status": "UNAVAILABLE",
            "deals": [],
        })
        self.assertEqual(result["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
