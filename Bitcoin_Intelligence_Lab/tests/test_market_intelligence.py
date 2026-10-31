import unittest

from bitcoinlab.market_intelligence import (
    build_market_intelligence,
    cross_venue_orderbook_profile,
    liquidation_risk_profile,
    market_structure_signal,
)


class MarketStructureSignalTests(unittest.TestCase):
    def test_vwap_location_and_sampled_delta_produce_bounded_direction_score(self):
        result = market_structure_signal({
            "bars": {
                "status": "ok", "last_close": 70_500,
                "session_vwap_utc": 70_000,
                "last_true_range": 500,
                "session_vwap_coverage_minutes": 90,
                "session_vwap_bars": 90,
            },
            "volume_profile": {
                "status": "ok", "delta_ratio": 0.6,
                "sample_trade_count": 400,
            },
        })
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["score"], 0)
        self.assertLessEqual(result["score"], 1)
        self.assertIn("session_vwap_location", result["components"])
        self.assertIn("sampled_trade_delta", result["components"])

    def test_short_session_and_small_trade_sample_do_not_create_signal(self):
        result = market_structure_signal({
            "bars": {
                "status": "ok", "last_close": 70_500,
                "session_vwap_utc": 70_000,
                "last_true_range": 500,
                "session_vwap_coverage_minutes": 5,
                "session_vwap_bars": 5,
            },
            "volume_profile": {
                "status": "ok", "delta_ratio": 0.9,
                "sample_trade_count": 8,
            },
        })
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["score"])


class CrossVenueOrderBookTests(unittest.TestCase):
    def state(self, *, binance=0.4, okx=0.2, bybit=-0.1, age=3):
        rows = [
            ("binance_spot", binance),
            ("okx_spot", okx),
            ("bybit_linear", bybit),
        ]
        return {
            "status": "ok",
            "venues": [
                {
                    "venue": venue, "status": "live",
                    "last_message_ms": 1_800_000_000_000,
                }
                for venue, _ in rows
            ],
            "latest_books": [
                {
                    "venue": venue,
                    "imbalance": value,
                    "spread_bps": 1.5,
                    "observed_at_ms": 1_800_000_000_000 - age * 1000,
                }
                for venue, value in rows
            ],
        }

    def test_median_cross_venue_book_score_uses_distinct_venues(self):
        result = cross_venue_orderbook_profile(
            self.state(), now_ms=1_800_000_000_000,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["venue_count"], 3)
        # Median raw imbalance is 0.2; the opposing perpetual venue halves confidence.
        self.assertAlmostEqual(result["score"], 0.1)
        self.assertAlmostEqual(result["agreement_ratio"], 2 / 3, places=4)

    def test_conflicting_spot_and_perpetual_books_reduce_score_and_warn(self):
        state = self.state(binance=0.8, okx=0.7, bybit=-0.9)
        result = cross_venue_orderbook_profile(
            state, now_ms=1_800_000_000_000,
        )
        self.assertEqual(result["status"], "ok")
        self.assertLess(result["score"], 0.7)
        self.assertIn("spot_or_perpetual_book_imbalance_conflict", result["warnings"])

    def test_stale_book_snapshots_are_excluded(self):
        result = cross_venue_orderbook_profile(
            self.state(age=60), now_ms=1_800_000_000_000,
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["venue_count"], 0)

    def test_one_fresh_venue_is_not_enough(self):
        state = self.state()
        state["latest_books"] = state["latest_books"][:1]
        state["venues"] = state["venues"][:1]
        result = cross_venue_orderbook_profile(
            state, now_ms=1_800_000_000_000,
        )
        self.assertEqual(result["status"], "incomplete")


class LiquidationRiskTests(unittest.TestCase):
    def test_multi_venue_long_and_short_liquidations_are_risk_context(self):
        result = liquidation_risk_profile({
            "liquidation_short_window_summary": [
                {"venue": "binance_usdm", "liquidated_side": "LONG", "event_count": 2},
                {"venue": "bybit_linear", "liquidated_side": "LONG", "event_count": 3},
                {"venue": "okx_swap", "liquidated_side": "SHORT", "event_count": 1},
                {"venue": "bybit_linear", "liquidated_side": "SHORT", "event_count": 1},
            ],
        })
        self.assertEqual(result["status"], "ok")
        self.assertIn("cross_venue_long_liquidation_pressure", result["warnings"])
        self.assertIn("cross_venue_short_liquidation_pressure", result["warnings"])
        self.assertEqual(result["use_in_decision"], "risk_context_only_not_directional_vote")

    def test_build_market_intelligence_keeps_independent_outputs(self):
        result = build_market_intelligence(
            {
                "venues": [], "latest_books": [],
                "liquidation_short_window_summary": [],
            },
            {
                "bars": {"status": "incomplete"},
                "volume_profile": {"status": "unavailable"},
            },
            now_ms=1_800_000_000_000,
        )
        self.assertEqual(result["cross_venue_orderbook"]["status"], "incomplete")
        self.assertEqual(result["market_structure_signal"]["status"], "incomplete")
        self.assertEqual(result["liquidation_risk"]["status"], "empty")


if __name__ == "__main__":
    unittest.main()
