from __future__ import annotations

import json
import sqlite3
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
        "time_server_ms": now - 1000,
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
        "window_start_server_ms": now - 90 * 86400 * 1000,
        "window_end_server_ms": now,
        "server_utc_offset_seconds_at_query": 0,
        "history_total_selected": 1,
        "history_matching_total": 1,
        "history_start_index": 0,
        "returned_count": 1,
        "truncated": False,
        "symbol": "BTC",
        "magic": 26110201,
        "currency": "USD",
        "time_basis": "MT5_SERVER_TIME",
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

    def test_large_account_history_does_not_mark_small_mirsad_subset_truncated(self):
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
            history = make_deal_history(
                history_total_selected=6000,
                history_matching_total=12,
                history_start_index=5000,
                truncated=False,
            )
            base_deal = history["deals"][0]
            history["deals"] = [
                {
                    **base_deal,
                    "deal_ticket": str(10001 + index),
                    "order_ticket": str(20001 + index),
                    "position_id": str(30001 + index),
                    "time_server_ms": base_deal["time_server_ms"] + index,
                }
                for index in range(12)
            ]
            history["returned_count"] = 12
            (root / "deals.json").write_text(json.dumps(history), encoding="utf-8")

            result = MT5BridgeEngine(str(directory)).inspect()

            self.assertEqual(result["deal_history"]["status"], "READY")
            self.assertEqual(result["deal_history"]["history_matching_total"], 12)
            self.assertFalse(result["deal_history"]["truncated"])
            self.assertEqual(len(result["deal_history"]["deals"]), 12)

    def test_bridge_rejects_inconsistent_filtered_deal_truncation(self):
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
            history = make_deal_history(
                history_total_selected=6000,
                history_matching_total=1001,
                truncated=False,
            )
            (root / "deals.json").write_text(json.dumps(history), encoding="utf-8")

            result = MT5BridgeEngine(str(directory)).inspect()

            self.assertEqual(result["deal_history"]["status"], "INVALID")
            self.assertEqual(result["deal_history"]["deals"], [])

    def test_bridge_marks_stale_deal_snapshot_stale(self):
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
            history = make_deal_history(queried_at_utc_ms=now - 300_000)
            (root / "deals.json").write_text(json.dumps(history), encoding="utf-8")

            result = MT5BridgeEngine(str(directory)).inspect()

            self.assertEqual(result["deal_history"]["status"], "STALE")
            self.assertEqual(result["deal_history"]["deals"], [])

    def test_bridge_preserves_unavailable_history_as_unavailable(self):
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
            (root / "deals.json").write_text(json.dumps({
                "schema": "MIR1-DEALS-1", "status": "UNAVAILABLE",
                "queried_at_utc_ms": now, "history_error": 4401, "deals": [],
            }), encoding="utf-8")

            result = MT5BridgeEngine(str(directory)).inspect()

            self.assertEqual(result["deal_history"]["status"], "UNAVAILABLE")
            self.assertIn("4401", result["deal_history"]["reason"])

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
            self.assertEqual(rows[0]["time_basis"], "MT5_SERVER_TIME")

    def test_legacy_utc_ledger_schema_migrates_without_losing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "legacy-mirsad.sqlite3"
            legacy_time = int(time.time() * 1000) - 60_000
            conn = sqlite3.connect(db)
            conn.execute("""CREATE TABLE mt5_deals (
                deal_ticket TEXT PRIMARY KEY, order_ticket TEXT NOT NULL,
                position_id TEXT NOT NULL, magic INTEGER NOT NULL,
                symbol TEXT NOT NULL, deal_type INTEGER NOT NULL,
                deal_entry INTEGER NOT NULL, deal_reason INTEGER NOT NULL,
                time_utc_ms INTEGER NOT NULL, volume REAL NOT NULL,
                price REAL NOT NULL, profit REAL NOT NULL, commission REAL NOT NULL,
                swap REAL NOT NULL, fee REAL NOT NULL, net_cashflow REAL NOT NULL,
                currency TEXT NOT NULL, comment TEXT NOT NULL,
                payload_json TEXT NOT NULL, observed_at_ms INTEGER NOT NULL
            )""")
            conn.execute("CREATE INDEX ix_mt5_deals_position_time ON mt5_deals(magic,symbol,position_id,time_utc_ms)")
            conn.execute("CREATE INDEX ix_mt5_deals_time ON mt5_deals(magic,symbol,time_utc_ms)")
            conn.execute("""INSERT INTO mt5_deals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                "10001", "20001", "30001", 26110201, "BTC", 1, 1, 3,
                legacy_time, 0.01, 65000.0, 12.5, -0.25, -0.05, -0.02,
                12.18, "USD", "legacy", json.dumps({"legacy": True}), legacy_time,
            ))
            conn.commit()
            conn.close()

            legacy_rows = load_mt5_deal_history(
                magic_number=26110201, symbol="BTC", db_path=db
            )
            self.assertEqual(len(legacy_rows), 1)
            self.assertEqual(legacy_rows[0]["deal_ticket"], "10001")
            self.assertEqual(legacy_rows[0]["time_server_ms"], legacy_time)
            self.assertEqual(legacy_rows[0]["time_basis"], "LEGACY_UTC_NORMALIZED")

            native_history = make_deal_history(deal={"deal_ticket": "10002"})
            saved = save_mt5_deal_history(native_history, db_path=db)
            all_rows = load_mt5_deal_history(
                magic_number=26110201, symbol="BTC", db_path=db
            )
            self.assertEqual(saved["status"], "READY")
            self.assertEqual(len(all_rows), 2)
            by_ticket = {row["deal_ticket"]: row for row in all_rows}
            self.assertEqual(by_ticket["10001"]["time_basis"], "LEGACY_UTC_NORMALIZED")
            self.assertEqual(by_ticket["10002"]["time_basis"], "MT5_SERVER_TIME")

    def test_invalid_net_cashflow_is_never_persisted(self) -> None:
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
