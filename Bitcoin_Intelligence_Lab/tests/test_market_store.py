import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bitcoinlab.market_store import MarketDataStore, read_market_stream_dashboard
from bitcoinlab.liquidations import normalize_binance_force_order


class MarketDataStoreTests(unittest.TestCase):
    def test_invalid_retention_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                MarketDataStore(Path(tmp) / "bad.sqlite", retention_hours=0)

    def test_read_only_dashboard_returns_status_and_latest_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite"
            self.assertEqual(
                read_market_stream_dashboard(db_path)["status"], "not_started"
            )
            with MarketDataStore(db_path) as store:
                store.record_status(
                    venue="binance_spot", symbol="BTCUSDT",
                    status="live", updated_at_ms=1_800_000_000_000,
                    last_message_ms=1_800_000_000_000,
                )
                store.record_snapshot(
                    venue="binance_spot", symbol="BTCUSDT",
                    observed_at_ms=1_800_000_000_000,
                    book={"bids": [[100.0, 1.0]], "asks": [[101.0, 1.0]]},
                    metrics={
                        "best_bid": 100.0, "best_ask": 101.0,
                        "spread_bps": 99.5, "imbalance": 0.0,
                    },
                )
            result = read_market_stream_dashboard(db_path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["venues"][0]["status"], "live")
            self.assertEqual(result["latest_books"][0]["best_bid"], 100.0)

    def test_liquidations_persist_dedupe_and_recent_dashboard_excludes_old_events(self):
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        event = normalize_binance_force_order({
            "e": "forceOrder",
            "o": {
                "s": "BTCUSDT", "S": "SELL", "X": "FILLED",
                "z": "0.1", "ap": "67000", "T": now,
            },
        })
        old_event = {
            **event,
            "event_key": event["event_key"] + "-old",
            "event_time_ms": now - 2 * 60 * 60_000,
        }
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite"
            with MarketDataStore(db_path) as store:
                self.assertTrue(store.record_liquidation(
                    event=event, received_at_ms=now + 10,
                ))
                self.assertFalse(store.record_liquidation(
                    event=event, received_at_ms=now + 20,
                ))
                self.assertTrue(store.record_liquidation(
                    event=old_event, received_at_ms=now + 30,
                ))
                summary = store.liquidation_summary(since_ms=now - 60 * 60_000)
            dashboard = read_market_stream_dashboard(db_path)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["event_count"], 1)
        self.assertEqual(summary[0]["quantity_unit"], "BTC")
        self.assertEqual(summary[0]["notional_usd"], 6700.0)
        self.assertEqual(dashboard["liquidation_summary"][0]["event_count"], 1)
        self.assertEqual(len(dashboard["recent_liquidations"]), 1)
        self.assertEqual(dashboard["recent_liquidations"][0]["liquidated_side"], "LONG")
        self.assertEqual(dashboard["recent_liquidations"][0]["event_time_ms"], now)

    def test_trade_flow_summary_includes_total_btc_base_volume(self):
        now = 1_800_000_030_000
        with tempfile.TemporaryDirectory() as tmp:
            with MarketDataStore(Path(tmp) / "market.sqlite") as store:
                for key, side, quantity in (
                    ("buy-1", "BUY", 0.2),
                    ("sell-1", "SELL", 0.15),
                ):
                    store.record_trade_event(
                        event={
                            "event_key": key,
                            "venue": "binance_usdm",
                            "symbol": "BTCUSDT",
                            "market_type": "linear",
                            "event_time_ms": now - 10_000,
                            "aggressor_side": side,
                            "price": 70000.0,
                            "base_quantity": quantity,
                            "quantity_unit": "BTC",
                            "notional_usd": 70000.0 * quantity,
                            "trade_count": 1,
                        },
                        received_at_ms=now,
                    )
                summary = store.trade_flow_summary(
                    symbol="BTCUSDT", now_ms=now, windows_seconds=(60,),
                )
        self.assertEqual(len(summary), 1)
        self.assertAlmostEqual(summary[0]["total_base_volume_btc"], 0.35)

    def test_future_trade_bucket_is_excluded_from_flow_summary(self):
        now = 1_800_000_030_000
        with tempfile.TemporaryDirectory() as tmp:
            with MarketDataStore(Path(tmp) / "market.sqlite") as store:
                store.record_trade_event(
                    event={
                        "event_key": "future", "venue": "binance_usdm",
                        "symbol": "BTCUSDT", "market_type": "linear_perpetual",
                        "event_time_ms": now + 120_000, "aggressor_side": "BUY",
                        "price": 70000.0, "base_quantity": 0.2,
                        "quantity_unit": "BTC", "notional_usd": 14000.0,
                        "trade_count": 1,
                    },
                    received_at_ms=now,
                )
                summary = store.trade_flow_summary(
                    symbol="BTCUSDT", now_ms=now, windows_seconds=(60,),
                )
        self.assertEqual(summary, [])

    def test_same_venue_symbol_minute_keeps_market_types_separate(self):
        now = 1_800_000_030_000
        with tempfile.TemporaryDirectory() as tmp:
            with MarketDataStore(Path(tmp) / "market.sqlite") as store:
                for key, market_type, side, quantity in (
                    ("spot-1", "spot", "BUY", 0.2),
                    ("perp-1", "linear_perpetual", "SELL", 0.1),
                ):
                    store.record_trade_event(
                        event={
                            "event_key": key, "venue": "shared_venue",
                            "symbol": "BTCUSDT", "market_type": market_type,
                            "event_time_ms": now - 10_000, "aggressor_side": side,
                            "price": 70000.0, "base_quantity": quantity,
                            "quantity_unit": "BTC",
                            "notional_usd": 70000.0 * quantity, "trade_count": 1,
                        },
                        received_at_ms=now,
                    )
                summary = store.trade_flow_summary(
                    symbol="BTCUSDT", now_ms=now, windows_seconds=(60,),
                )
        self.assertEqual({row["market_type"] for row in summary}, {"spot", "linear_perpetual"})
        by_type = {row["market_type"]: row for row in summary}
        self.assertAlmostEqual(by_type["spot"]["total_base_volume_btc"], 0.2)
        self.assertAlmostEqual(by_type["linear_perpetual"]["total_base_volume_btc"], 0.1)

    def test_old_trade_flow_schema_is_archived_not_mislabeled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                """CREATE TABLE trade_flow_minutes (
                    venue TEXT NOT NULL, symbol TEXT NOT NULL, market_type TEXT NOT NULL,
                    bucket_start_ms INTEGER NOT NULL,
                    buy_base_volume_btc REAL NOT NULL DEFAULT 0,
                    sell_base_volume_btc REAL NOT NULL DEFAULT 0,
                    buy_notional_usd REAL NOT NULL DEFAULT 0,
                    sell_notional_usd REAL NOT NULL DEFAULT 0,
                    buy_trade_count INTEGER NOT NULL DEFAULT 0,
                    sell_trade_count INTEGER NOT NULL DEFAULT 0,
                    last_trade_time_ms INTEGER NOT NULL,
                    PRIMARY KEY(venue,symbol,bucket_start_ms)
                )"""
            )
            connection.execute(
                "INSERT INTO trade_flow_minutes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("shared_venue", "BTCUSDT", "linear_perpetual", 1_800_000_000_000,
                 1.0, 0.0, 70000.0, 0.0, 1, 0, 1_800_000_000_000),
            )
            connection.execute(
                "CREATE INDEX trade_flow_minutes_venue_time ON trade_flow_minutes(venue,symbol,bucket_start_ms)"
            )
            connection.commit()
            connection.close()

            with MarketDataStore(path) as store:
                columns = store.db.execute("PRAGMA table_info(trade_flow_minutes)").fetchall()
                primary_key = tuple(
                    row[1] for row in sorted(
                        (row for row in columns if row[5] > 0), key=lambda row: row[5],
                    )
                )
                active_rows = store.db.execute(
                    "SELECT COUNT(*) FROM trade_flow_minutes"
                ).fetchone()[0]
                archived_rows = store.db.execute(
                    "SELECT COUNT(*) FROM trade_flow_minutes_legacy_pk_v1"
                ).fetchone()[0]
        self.assertEqual(primary_key, ("venue", "symbol", "market_type", "bucket_start_ms"))
        self.assertEqual(active_rows, 0)
        self.assertEqual(archived_rows, 1)

    def test_legacy_flow_archive_uses_configured_retention(self):
        now = 1_800_000_000_000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy-retention.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                """CREATE TABLE trade_flow_minutes (
                    venue TEXT NOT NULL, symbol TEXT NOT NULL, market_type TEXT NOT NULL,
                    bucket_start_ms INTEGER NOT NULL,
                    buy_base_volume_btc REAL NOT NULL DEFAULT 0,
                    sell_base_volume_btc REAL NOT NULL DEFAULT 0,
                    buy_notional_usd REAL NOT NULL DEFAULT 0,
                    sell_notional_usd REAL NOT NULL DEFAULT 0,
                    buy_trade_count INTEGER NOT NULL DEFAULT 0,
                    sell_trade_count INTEGER NOT NULL DEFAULT 0,
                    last_trade_time_ms INTEGER NOT NULL,
                    PRIMARY KEY(venue,symbol,bucket_start_ms)
                )"""
            )
            connection.execute(
                "INSERT INTO trade_flow_minutes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("binance_usdm", "BTCUSDT", "linear_perpetual", now, 0.1, 0.0,
                 7000.0, 0.0, 1, 0, now),
            )
            connection.execute(
                "CREATE INDEX trade_flow_minutes_venue_time ON trade_flow_minutes(venue,symbol,bucket_start_ms)"
            )
            connection.commit()
            connection.close()

            with MarketDataStore(path, retention_hours=1) as store:
                removed = store.prune(now_ms=now + 2 * 3_600_000)
                archived = store.db.execute(
                    "SELECT COUNT(*) FROM trade_flow_minutes_legacy_pk_v1"
                ).fetchone()[0]
        self.assertEqual(removed["trade_flow_minutes_legacy_pk_v1"], 1)
        self.assertEqual(archived, 0)

    def test_one_minute_flow_window_excludes_previous_minute_bucket(self):
        now = 1_800_000_059_000
        with tempfile.TemporaryDirectory() as tmp:
            with MarketDataStore(Path(tmp) / "market.sqlite") as store:
                for key, event_time, quantity in (
                    ("outside", 1_799_999_945_000, 0.5),
                    ("inside", 1_800_000_000_000, 0.1),
                ):
                    store.record_trade_event(
                        event={
                            "event_key": key, "venue": "binance_usdm",
                            "symbol": "BTCUSDT", "market_type": "linear_perpetual",
                            "event_time_ms": event_time, "aggressor_side": "BUY",
                            "price": 70000.0, "base_quantity": quantity,
                            "quantity_unit": "BTC", "notional_usd": 70000.0 * quantity,
                            "trade_count": 1,
                        },
                        received_at_ms=now,
                    )
                summary = store.trade_flow_summary(
                    symbol="BTCUSDT", now_ms=now, windows_seconds=(60,),
                )
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["trade_count"], 1)
        self.assertAlmostEqual(summary[0]["total_base_volume_btc"], 0.1)

    def test_invalid_snapshot_is_not_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MarketDataStore(Path(tmp) / "book.sqlite") as store:
                with self.assertRaises(ValueError):
                    store.record_snapshot(
                        venue="okx_spot", symbol="BTC-USDT",
                        observed_at_ms=1_800_000_000_000,
                        book={"bids": [], "asks": []},
                        metrics={"best_bid": 0, "best_ask": 0, "spread_bps": 0, "imbalance": 0},
                    )


if __name__ == "__main__":
    unittest.main()
