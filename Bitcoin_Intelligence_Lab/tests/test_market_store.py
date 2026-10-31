import tempfile
import unittest
from pathlib import Path

from bitcoinlab.market_store import MarketDataStore, read_market_stream_dashboard


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
