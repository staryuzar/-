import tempfile
import unittest
from pathlib import Path

from bitcoinlab.market_store import MarketDataStore
from bitcoinlab.market_stream import OKX_WS, _install_binance_snapshot, _parse_binance_depth


class MarketStreamTests(unittest.TestCase):
    def test_okx_websocket_uses_port_443_not_retired_8443(self):
        self.assertEqual(OKX_WS, "wss://ws.okx.com/ws/v5/public")
        self.assertNotIn(":8443", OKX_WS)

    def test_binance_depth_message_is_normalized(self):
        event = _parse_binance_depth({
            "e": "depthUpdate", "E": 1_800_000_000_000,
            "s": "BTCUSDT", "U": 101, "u": 105,
            "b": [["100", "2"]], "a": [["101", "3"]],
        }, "BTCUSDT")
        self.assertEqual(event["first_update_id"], 101)
        self.assertEqual(event["final_update_id"], 105)
        self.assertEqual(event["bids"], [["100", "2"]])

    def test_binance_depth_message_rejects_wrong_symbol(self):
        with self.assertRaisesRegex(ValueError, "symbol mismatch"):
            _parse_binance_depth({
                "e": "depthUpdate", "E": 1_800_000_000_000,
                "s": "ETHUSDT", "U": 101, "u": 105, "b": [], "a": [],
            }, "BTCUSDT")

    def test_binance_snapshot_bootstrap_discards_stale_buffer_and_bridges(self):
        from bitcoinlab.orderbook_sync import BinanceOrderBook
        book = BinanceOrderBook()
        buffered = [
            {
                "first_update_id": 90, "final_update_id": 100,
                "event_time_ms": 1_800_000_000_000,
                "bids": [["100", "9"]], "asks": [],
            },
            {
                "first_update_id": 99, "final_update_id": 102,
                "event_time_ms": 1_800_000_001_000,
                "bids": [["100", "4"]], "asks": [["101", "0"]],
            },
        ]
        result = _install_binance_snapshot(book, {
            "snapshot_id": 100,
            "bids": [["100", "2"], ["99", "1"]],
            "asks": [["101", "3"], ["102", "1"]],
        }, buffered)
        self.assertTrue(result)
        self.assertEqual(book.last_update_id, 102)
        self.assertEqual(book.bids[100.0], 4.0)
        self.assertNotIn(101.0, book.asks)

    def test_binance_bootstrap_refuses_buffer_gap(self):
        from bitcoinlab.orderbook_sync import BinanceOrderBook
        book = BinanceOrderBook()
        buffered = [{
            "first_update_id": 110, "final_update_id": 115,
            "event_time_ms": 1_800_000_000_000,
            "bids": [["100", "4"]], "asks": [],
        }]
        result = _install_binance_snapshot(book, {
            "snapshot_id": 100,
            "bids": [["100", "2"]], "asks": [["101", "3"]],
        }, buffered)
        self.assertFalse(result)
        self.assertFalse(book.synchronized)

    def test_market_store_persists_events_snapshots_and_feed_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.sqlite"
            with MarketDataStore(db_path) as store:
                store.record_event(
                    venue="binance_spot", symbol="BTCUSDT",
                    event_time_ms=1_800_000_000_000,
                    received_at_ms=1_800_000_000_010,
                    event_type="depthUpdate",
                    sequence_id=100,
                    payload={"U": 99, "u": 100},
                )
                store.record_snapshot(
                    venue="binance_spot", symbol="BTCUSDT",
                    observed_at_ms=1_800_000_000_010,
                    book={
                        "bids": [[100.0, 2.0]], "asks": [[101.0, 3.0]],
                        "last_update_id": 100, "sequence_id": None,
                    },
                    metrics={
                        "best_bid": 100.0, "best_ask": 101.0,
                        "spread_bps": 99.5, "imbalance": -0.2,
                    },
                )
                store.record_status(
                    venue="binance_spot", symbol="BTCUSDT",
                    status="live", updated_at_ms=1_800_000_000_010,
                    last_message_ms=1_800_000_000_010,
                )
                statuses = store.latest_status()
                history = store.recent_snapshots(
                    venue="binance_spot", symbol="BTCUSDT",
                    since_ms=1_799_000_000_000,
                )
                pruned = store.prune(now_ms=1_800_000_000_010)
            self.assertEqual(statuses[0]["status"], "live")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["bids"], [[100.0, 2.0]])
            self.assertEqual(pruned["orderbook_snapshots"], 0)

    def test_market_store_prunes_expired_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            with MarketDataStore(Path(tmp) / "market.sqlite", retention_hours=1) as store:
                store.record_event(
                    venue="bybit_linear", symbol="BTCUSDT",
                    event_time_ms=1_800_000_000_000,
                    received_at_ms=1_800_000_000_000,
                    event_type="snapshot", payload={"type": "snapshot"},
                )
                removed = store.prune(now_ms=1_800_000_000_000 + 3_600_001)
                self.assertEqual(removed["stream_events"], 1)


if __name__ == "__main__":
    unittest.main()
