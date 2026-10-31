import tempfile
import unittest
from pathlib import Path

from bitcoinlab.market_store import MarketDataStore
from bitcoinlab.trade_analytics import (
    ensure_trade_footprint_schema,
    prune_trade_footprint,
    read_trade_analytics,
    record_trade_batch,
)


NOW = 1_800_000_000_000


def trade_event(key, venue, side, when, *, price=67000.0, qty=0.01, market_type="linear_perpetual"):
    return {
        "event_key": key,
        "venue": venue,
        "symbol": "BTCUSDT",
        "market_type": market_type,
        "event_time_ms": when,
        "aggressor_side": side,
        "price": price,
        "base_quantity": qty,
        "quantity_unit": "BTC",
        "notional_usd": price * qty,
        "trade_count": 1,
        "price_bucket_usd": (price // 10) * 10,
    }


class TradeAnalyticsStoreTests(unittest.TestCase):
    def test_dedup_is_atomic_for_cvd_and_footprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                ensure_trade_footprint_schema(store)
                event = trade_event("same-id", "binance_usdm", "BUY", NOW - 10_000)
                self.assertEqual(record_trade_batch(store, events=[event], received_at_ms=NOW), 1)
                self.assertEqual(record_trade_batch(store, events=[event], received_at_ms=NOW + 1), 0)
                result = read_trade_analytics(path, now_ms=NOW)
            rows = [r for r in result["trade_flow_summary"] if r["timeframe"] == "5m"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["trade_count"], 1)
            self.assertEqual(len(result["trade_footprint"]), 1)
            self.assertEqual(result["trade_footprint"][0]["trade_count"], 1)

    def test_dashboard_keeps_venues_and_market_types_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                events = [
                    trade_event("bn-1", "binance_usdm", "BUY", NOW - 10_000),
                    trade_event("bb-1", "bybit_linear", "SELL", NOW - 9_000),
                    trade_event("ok-1", "okx_spot", "BUY", NOW - 8_000, market_type="spot"),
                ]
                record_trade_batch(store, events=events, received_at_ms=NOW)
                result = read_trade_analytics(path, now_ms=NOW)
            rows = [r for r in result["trade_flow_summary"] if r["timeframe"] == "5m" and r["status"] == "ok"]
            self.assertEqual({r["venue"] for r in rows}, {"binance_usdm", "bybit_linear", "okx_spot"})
            self.assertEqual({r["market_type"] for r in rows}, {"linear_perpetual", "spot"})

    def test_price_footprint_uses_configured_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path, retention_hours=1) as store:
                ensure_trade_footprint_schema(store)
                event = trade_event("old", "binance_usdm", "BUY", NOW - 2 * 3_600_000)
                record_trade_batch(store, events=[event], received_at_ms=NOW)
                removed = prune_trade_footprint(store, now_ms=NOW)
                self.assertEqual(removed, 1)
                result = read_trade_analytics(path, now_ms=NOW)
            self.assertEqual(result["trade_footprint"], [])

    def test_missing_database_is_not_created_by_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.sqlite"
            result = read_trade_analytics(path, now_ms=NOW)
            self.assertEqual(result["status"], "not_started")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
