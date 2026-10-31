import tempfile
import unittest
from pathlib import Path

from bitcoinlab.liquidation_heatmap import read_liquidation_heatmap
from bitcoinlab.market_store import MarketDataStore


NOW = 1_800_000_000_000


def event(key, venue, *, side="LONG", unit="BTC", price_kind="average_fill_price",
          price=67025, raw_size=0.1, notional="auto",
          symbol="BTCUSDT", market_type="linear perpetual", age_ms=10_000):
    return {
        "event_key": key,
        "venue": venue,
        "symbol": symbol,
        "market_type": market_type,
        "event_time_ms": NOW - age_ms,
        "liquidated_side": side,
        "order_side": "SELL" if side == "LONG" else "BUY",
        "raw_size": raw_size,
        "quantity_unit": unit,
        "reference_price": price,
        "reference_price_kind": price_kind,
        "notional_usd": price * raw_size if notional == "auto" else notional,
    }


class LiquidationHeatmapTests(unittest.TestCase):
    def test_clusters_are_separate_by_venue_reference_kind_and_native_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                store.record_liquidation(event=event("bn-1", "binance_usdm"), received_at_ms=NOW)
                store.record_liquidation(
                    event=event("bb-1", "bybit_linear", unit="venue_reported_contract_units",
                                price_kind="bankruptcy_price", notional=None),
                    received_at_ms=NOW,
                )
                store.record_liquidation(
                    event=event("ok-1", "okx_swap", unit="contracts",
                                price_kind="bankruptcy_price", notional=None,
                                symbol="BTC-USDT-SWAP", market_type="USDT swap"),
                    received_at_ms=NOW,
                )
            result = read_liquidation_heatmap(path, now_ms=NOW)
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["cluster_count"], 3)
        self.assertEqual({row["venue"] for row in result["clusters"]}, {
            "binance_usdm", "bybit_linear", "okx_swap",
        })
        self.assertEqual(
            {row["quantity_unit"] for row in result["clusters"]},
            {"BTC", "venue_reported_contract_units", "contracts"},
        )
        self.assertTrue(all(
            row["priced_notional_usd"] is None
            for row in result["clusters"] if row["venue"] != "binance_usdm"
        ))

    def test_only_events_with_source_notional_contribute_to_partial_usd_sum(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                store.record_liquidation(
                    event=event("bn-priced", "binance_usdm", notional=6702.5),
                    received_at_ms=NOW,
                )
                store.record_liquidation(
                    event=event("bn-unpriced", "binance_usdm", notional=None),
                    received_at_ms=NOW,
                )
            result = read_liquidation_heatmap(path, now_ms=NOW)
        cluster = result["clusters"][0]
        self.assertEqual(cluster["event_count"], 2)
        self.assertEqual(cluster["priced_event_count"], 1)
        self.assertAlmostEqual(cluster["priced_notional_usd"], 6702.5)
        self.assertEqual(cluster["coverage_note"], "notional_is_partial_subset")
        self.assertIn("some_liquidation_cluster_usd_notionals_are_partial", result["warnings"])

    def test_old_events_are_excluded_from_selected_lookback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                store.record_liquidation(
                    event=event("old", "binance_usdm", age_ms=2 * 3_600_000),
                    received_at_ms=NOW,
                )
            result = read_liquidation_heatmap(path, now_ms=NOW, lookback_minutes=60)
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("no_liquidation_events_in_selected_window", result["warnings"])

    def test_feed_health_is_attached_to_venue_without_merging_venues(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                store.record_liquidation(
                    event=event("bb-1", "bybit_linear", unit="venue_reported_contract_units",
                                price_kind="bankruptcy_price", notional=None),
                    received_at_ms=NOW,
                )
                store.record_status(
                    venue="bybit_linear_liquidations", symbol="BTCUSDT",
                    status="connected", updated_at_ms=NOW, reconnects=2,
                )
            result = read_liquidation_heatmap(path, now_ms=NOW)
        self.assertEqual(len(result["venues"]), 1)
        self.assertEqual(result["venues"][0]["feed_status"], "connected")
        self.assertEqual(result["venues"][0]["feed_reconnects"], 2)

    def test_cluster_filter_and_threshold_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.sqlite"
            with MarketDataStore(path) as store:
                store.record_liquidation(
                    event=event("one", "binance_usdm"), received_at_ms=NOW,
                )
            result = read_liquidation_heatmap(path, now_ms=NOW, minimum_cluster_events=2)
        self.assertEqual(result["cluster_count"], 0)
        with self.assertRaises(ValueError):
            read_liquidation_heatmap(path, now_ms=NOW, price_bucket_usd=0)

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.sqlite"
            result = read_liquidation_heatmap(path, now_ms=NOW)
            self.assertEqual(result["status"], "not_started")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
