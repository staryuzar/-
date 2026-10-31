import tempfile
import unittest
from pathlib import Path

from bitcoinlab.market_store import MarketDataStore


class MarketDataStoreTests(unittest.TestCase):
    def test_invalid_retention_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                MarketDataStore(Path(tmp) / "bad.sqlite", retention_hours=0)

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
