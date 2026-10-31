import unittest

from bitcoinlab.trade_profile import (
    blend_orderflow_evidence,
    build_streamed_footprint_profiles,
    build_streamed_trade_flow_profile,
)


NOW = 1_800_000_000_000


def flow_row(venue, market_type, ratio, *, age_ms=5_000, count=10, timeframe="5m"):
    buy = 1000.0 * (1.0 + ratio) / 2.0
    sell = 1000.0 * (1.0 - ratio) / 2.0
    return {
        "venue": venue,
        "market_type": market_type,
        "timeframe": timeframe,
        "status": "ok",
        "delta_notional_ratio": ratio,
        "total_notional_usd": buy + sell,
        "trade_count": count,
        "last_trade_time_ms": NOW - age_ms,
    }


class StreamedTradeProfileTests(unittest.TestCase):
    def test_cvd_uses_unique_venues_and_separate_spot_perpetual_medians(self):
        rows = [
            flow_row("binance_usdm", "linear_perpetual", 0.2),
            flow_row("bybit_linear", "linear_perpetual", 0.4),
            flow_row("okx_spot", "spot", 0.6),
        ]
        result = build_streamed_trade_flow_profile(rows, now_ms=NOW)
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["perpetual_score"], 0.3)
        self.assertAlmostEqual(result["spot_score"], 0.6)
        self.assertAlmostEqual(result["score"], 0.465)
        self.assertEqual(result["venue_count"], 3)

    def test_cvd_needs_two_fresh_distinct_venues_and_enough_trades(self):
        one_venue = [
            flow_row("binance_usdm", "linear_perpetual", 0.8),
            flow_row("binance_usdm", "spot", 0.9),
        ]
        result = build_streamed_trade_flow_profile(one_venue, now_ms=NOW)
        self.assertEqual(result["status"], "incomplete")
        stale_and_small = [
            flow_row("binance_usdm", "linear_perpetual", 0.8, age_ms=100_000),
            flow_row("bybit_linear", "linear_perpetual", 0.9, count=2),
        ]
        result = build_streamed_trade_flow_profile(stale_and_small, now_ms=NOW)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["score"])

    def test_spot_perpetual_disagreement_is_warned(self):
        rows = [
            flow_row("okx_spot", "spot", -0.7),
            flow_row("binance_usdm", "linear_perpetual", 0.6),
        ]
        result = build_streamed_trade_flow_profile(rows, now_ms=NOW)
        self.assertEqual(result["status"], "ok")
        self.assertIn("spot_perpetual_aggressor_flow_disagreement", result["warnings"])

    def test_footprint_is_separated_by_venue_and_calculates_value_area(self):
        rows = [
            {"venue": "binance_usdm", "market_type": "linear_perpetual",
             "price_bucket_usd": 67000, "buy_base_volume_btc": 1, "sell_base_volume_btc": 0,
             "buy_notional_usd": 67000, "sell_notional_usd": 0, "trade_count": 4},
            {"venue": "binance_usdm", "market_type": "linear_perpetual",
             "price_bucket_usd": 67010, "buy_base_volume_btc": 0, "sell_base_volume_btc": 0.5,
             "buy_notional_usd": 0, "sell_notional_usd": 33505, "trade_count": 2},
            {"venue": "okx_spot", "market_type": "spot",
             "price_bucket_usd": 67000, "buy_base_volume_btc": 0.1, "sell_base_volume_btc": 0,
             "buy_notional_usd": 6700, "sell_notional_usd": 0, "trade_count": 1},
        ]
        profiles = build_streamed_footprint_profiles(rows)
        self.assertEqual(len(profiles), 2)
        perp = next(row for row in profiles if row["venue"] == "binance_usdm")
        self.assertEqual(perp["poc"], 67000)
        self.assertLessEqual(perp["val"], perp["poc"])
        self.assertGreaterEqual(perp["vah"], perp["poc"])
        self.assertEqual(len(perp["bins"]), 2)

    def test_orderflow_blend_weights_streamed_cvd_thirty_five_percent(self):
        result = blend_orderflow_evidence(
            {"status": "ok", "score": 0.2},
            {"status": "ok", "score": 0.8},
        )
        self.assertAlmostEqual(result["score"], 0.41)
        self.assertAlmostEqual(result["weights"]["book_and_bounded_rest_flow"], 0.65)
        self.assertAlmostEqual(result["weights"]["multi_venue_cvd_5m"], 0.35)

    def test_streamed_cvd_can_supply_orderflow_when_rest_sample_missing(self):
        result = blend_orderflow_evidence(
            {"status": "incomplete", "score": None},
            {"status": "ok", "score": -0.5},
        )
        self.assertAlmostEqual(result["score"], -0.5)
        self.assertIn("orderflow_uses_streamed_cvd_without_fresh_rest_sample", result["warnings"])


if __name__ == "__main__":
    unittest.main()
