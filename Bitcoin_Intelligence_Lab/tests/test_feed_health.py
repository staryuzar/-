import unittest

from bitcoinlab.feed_health import build_data_health


NOW = 1_800_000_000_000


class FeedHealthTests(unittest.TestCase):
    def sources(self):
        return {
            "spot": {"status": "fresh", "age_seconds": 5},
            "orderflow": {"status": "fresh", "age_seconds": 4},
            "derivatives": {"status": "stale", "age_seconds": 900},
        }

    def streams(self):
        return {
            "status": "ok",
            "venues": [
                {
                    "venue": "binance_spot", "symbol": "BTCUSDT",
                    "status": "live", "last_message_ms": NOW - 2_000,
                    "reconnects": 1,
                },
                {
                    "venue": "bybit_linear", "symbol": "BTCUSDT",
                    "status": "live", "last_message_ms": NOW - 3_000,
                    "reconnects": 0,
                },
                {
                    "venue": "binance_usdm_liquidations", "symbol": "BTCUSDT",
                    "status": "connected", "updated_at_ms": NOW - 2_000,
                    "last_message_ms": NOW - 600_000, "reconnects": 0,
                },
            ],
            "latest_books": [
                {
                    "venue": "binance_spot",
                    "observed_at_ms": NOW - 3_000,
                    "imbalance": 0.3,
                },
                {
                    "venue": "bybit_linear",
                    "observed_at_ms": NOW - 4_000,
                    "imbalance": -0.2,
                },
            ],
        }

    def test_healthy_core_sources_and_live_books(self):
        result = build_data_health(
            source_states=self.sources(),
            stream_state=self.streams(),
            now_ms=NOW,
        )
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["core_ready"])
        self.assertEqual(result["fresh_core_feeds"], ["spot", "orderflow"])
        self.assertEqual(
            set(result["live_orderbook_venues"]),
            {"binance_spot", "bybit_linear"},
        )

    def test_quiet_liquidation_stream_is_not_marked_stale(self):
        result = build_data_health(
            source_states=self.sources(),
            stream_state=self.streams(),
            now_ms=NOW,
        )
        self.assertIn(
            "binance_usdm_liquidations",
            result["connected_quiet_event_feeds"],
        )
        self.assertNotIn(
            "binance_usdm_liquidations",
            result["non_live_stream_feeds"],
        )
        self.assertIn(
            "event_driven_feeds_connected_no_recent_liquidation_events",
            result["warnings"],
        )

    def test_old_liquidation_heartbeat_is_stale_even_without_events(self):
        stream = self.streams()
        stream["venues"][2]["updated_at_ms"] = NOW - 120_000
        result = build_data_health(
            source_states=self.sources(),
            stream_state=stream,
            now_ms=NOW,
        )
        row = next(
            x for x in result["stream_feeds"]
            if x["name"] == "binance_usdm_liquidations"
        )
        self.assertEqual(row["status"], "stale")
        self.assertIn("binance_usdm_liquidations", result["non_live_stream_feeds"])

    def test_stale_orderbook_snapshot_is_reported(self):
        stream = self.streams()
        stream["latest_books"][0]["observed_at_ms"] = NOW - 90_000
        result = build_data_health(
            source_states=self.sources(),
            stream_state=stream,
            now_ms=NOW,
        )
        row = next(x for x in result["stream_feeds"] if x["name"] == "binance_spot")
        self.assertEqual(row["status"], "stale")
        self.assertIn("binance_spot", result["non_live_stream_feeds"])

    def test_reconnecting_venue_is_not_marked_live(self):
        stream = self.streams()
        stream["venues"][1]["status"] = "reconnecting"
        result = build_data_health(
            source_states=self.sources(),
            stream_state=stream,
            now_ms=NOW,
        )
        row = next(x for x in result["stream_feeds"] if x["name"] == "bybit_linear")
        self.assertEqual(row["status"], "recovering")

    def test_missing_spot_blocks_core_readiness(self):
        sources = self.sources()
        sources["spot"] = {"status": "unavailable"}
        result = build_data_health(
            source_states=sources,
            stream_state={},
            now_ms=NOW,
        )
        self.assertFalse(result["core_ready"])
        self.assertEqual(result["status"], "degraded")
        self.assertIn("spot", result["missing_core_feeds"])
        self.assertIn("market_stream_not_started", result["warnings"])

    def test_fresh_derivatives_can_substitute_for_stale_orderflow_core_feed(self):
        sources = self.sources()
        sources["derivatives"] = {"status": "fresh"}
        sources["orderflow"] = {"status": "stale"}
        result = build_data_health(
            source_states=sources,
            stream_state={},
            now_ms=NOW,
        )
        self.assertTrue(result["core_ready"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["fresh_core_count"], 2)

    def test_rejects_invalid_monitoring_configuration(self):
        with self.assertRaises(ValueError):
            build_data_health(
                source_states={}, now_ms=NOW, book_stale_seconds=2,
            )


if __name__ == "__main__":
    unittest.main()
