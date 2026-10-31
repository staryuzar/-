import tempfile
import unittest
from pathlib import Path

from bitcoinlab.depth_analytics import read_depth_liquidity_context
from bitcoinlab.market_store import MarketDataStore


NOW = 1_800_000_000_000


def save_snapshot(store, venue, time_ms, bid_size, ask_size, *, symbol="BTCUSDT", bid_price=66990, ask_price=67010):
    book = {
        "bids": [[bid_price, bid_size], [bid_price - 50, 0.2]],
        "asks": [[ask_price, ask_size], [ask_price + 50, 0.2]],
    }
    metrics = {
        "best_bid": bid_price,
        "best_ask": ask_price,
        "spread_bps": (ask_price - bid_price) / ((ask_price + bid_price) / 2) * 10000,
        "imbalance": 0.0,
    }
    store.record_snapshot(
        venue=venue, symbol=symbol, observed_at_ms=time_ms,
        book=book, metrics=metrics,
    )


class DepthAnalyticsTests(unittest.TestCase):
    def test_persistence_and_pull_stack_are_per_venue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "depth.sqlite"
            with MarketDataStore(path) as store:
                for venue in ("binance_spot", "bybit_linear"):
                    save_snapshot(store, venue, NOW - 15_000, 0.5, 0.4)
                    save_snapshot(store, venue, NOW - 10_000, 0.8, 0.4)
                    save_snapshot(store, venue, NOW - 5_000, 0.4, 0.4)
            result = read_depth_liquidity_context(path, now_ms=NOW, lookback_minutes=1)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fresh_venue_count"], 2)
        self.assertEqual(len(result["venues"]), 2)
        profile = next(row for row in result["venues"] if row["venue"] == "binance_spot")
        bid = next(row for row in profile["heatmap"]["bid"] if row["price_bucket_usd"] == 66950)
        self.assertEqual(bid["persistence_ratio"], 1.0)
        self.assertAlmostEqual(bid["current_size_btc"], 0.4)
        changes = [
            row for row in profile["pull_stack"]
            if row["side"] == "bid" and row["price_bucket_usd"] == 66950
        ]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["stack_events"], 1)
        self.assertEqual(changes[0]["pull_events"], 1)

    def test_disappearing_from_top_depth_is_not_called_a_pull(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "depth.sqlite"
            with MarketDataStore(path) as store:
                save_snapshot(store, "binance_spot", NOW - 15_000, 0.5, 0.4)
                save_snapshot(store, "binance_spot", NOW - 10_000, 0.5, 0.4)
                save_snapshot(
                    store, "binance_spot", NOW - 5_000, 0.5, 0.4,
                    bid_price=66880, ask_price=67120,
                )
            result = read_depth_liquidity_context(path, now_ms=NOW)
        profile = result["venues"][0]
        self.assertEqual(profile["pull_stack"], [])

    def test_stale_last_snapshot_is_not_marked_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "depth.sqlite"
            with MarketDataStore(path) as store:
                for i in range(3):
                    save_snapshot(store, "binance_spot", NOW - 120_000 + i * 5_000, 0.5, 0.4)
            result = read_depth_liquidity_context(path, now_ms=NOW)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["venues"][0]["status"], "stale")
        self.assertEqual(result["fresh_venue_count"], 0)

    def test_reader_does_not_create_missing_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.sqlite"
            result = read_depth_liquidity_context(path, now_ms=NOW)
            self.assertEqual(result["status"], "not_started")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
