import unittest

from bitcoinlab.screener import build_market_screener


NOW = 1_800_000_000_000


def frame(*, status="fresh", breakout="none", stamp=NOW - 5_000, close=100_000):
    return {
        "status": status,
        "breakout": breakout,
        "last_bar": {
            "open_time_ms": stamp - 60_000,
            "close_time_ms": stamp,
            "open": close - 50,
            "high": close + 100,
            "low": close - 100,
            "close": close,
            "volume": 200,
        },
    }


def mtf():
    return {
        "frames": {
            "1d": frame(breakout="none"),
            "4h": frame(breakout="up"),
            "1h": frame(breakout="none"),
            "15m": frame(breakout="down"),
            "5m": frame(breakout="none"),
            "1m": frame(breakout="none"),
        }
    }


class MarketScreenerTests(unittest.TestCase):
    def test_breakout_events_require_fresh_completed_bars(self):
        profile = mtf()
        profile["frames"]["5m"] = frame(status="stale", breakout="up")
        result = build_market_screener(
            multi_timeframe=profile,
            market_structure={},
            market_interval="1m",
            now_ms=NOW,
        )
        breakouts = [event for event in result["events"] if event["type"] == "completed_bar_breakout"]
        self.assertEqual({event["timeframe"] for event in breakouts}, {"4h", "15m"})
        self.assertTrue(all(event["creates_order"] is False for event in result["events"]))

    def test_relative_volume_and_range_expansion_emit_separate_events(self):
        result = build_market_screener(
            multi_timeframe=mtf(),
            market_structure={
                "bars": {
                    "status": "ok",
                    "relative_volume_20": 2.4,
                    "range_expansion_vs_prior_median": 2.0,
                }
            },
            market_interval="1m",
            now_ms=NOW,
        )
        types = {event["type"] for event in result["events"]}
        self.assertIn("relative_volume_surge", types)
        self.assertIn("range_expansion", types)
        self.assertTrue(all(event["timeframe"] == "1m" for event in result["events"] if event["type"] in types - {"completed_bar_breakout"}))

    def test_orderbook_pressure_and_wide_spread_are_context_events(self):
        result = build_market_screener(
            multi_timeframe=mtf(),
            market_structure={},
            market_interval="1m",
            order_book={
                "imbalance": 0.8,
                "spread_bps": 34.0,
                "observed_at_ms": NOW - 1_000,
            },
            now_ms=NOW,
        )
        types = {event["type"] for event in result["events"]}
        self.assertIn("extreme_orderbook_imbalance", types)
        self.assertIn("wide_spread", types)
        self.assertTrue(all(event["direction"] is None for event in result["events"] if event["type"] == "wide_spread"))

    def test_stale_orderbook_does_not_create_liquidity_event(self):
        result = build_market_screener(
            multi_timeframe=mtf(),
            market_structure={},
            market_interval="1m",
            order_book={
                "imbalance": 0.9,
                "spread_bps": 40.0,
                "observed_at_ms": NOW - 60_000,
            },
            now_ms=NOW,
        )
        types = {event["type"] for event in result["events"]}
        self.assertNotIn("extreme_orderbook_imbalance", types)
        self.assertNotIn("wide_spread", types)

    def test_spot_perpetual_flow_disagreement_creates_warning_event(self):
        result = build_market_screener(
            multi_timeframe=mtf(),
            market_structure={},
            market_interval="1m",
            streamed_trade_flow={
                "status": "ok", "score": 0.1,
                "spot_score": -0.5, "perpetual_score": 0.6,
                "last_trade_time_ms": NOW - 2_000, "timeframe": "5m",
            },
            now_ms=NOW,
        )
        event = next(e for e in result["events"] if e["type"] == "spot_perpetual_cvd_disagreement")
        self.assertEqual(event["direction"], None)
        self.assertIn(event["type"], result["decision_warnings"])

    def test_cross_venue_funding_and_liquidation_pressure_are_deduplicated_separately(self):
        result = build_market_screener(
            multi_timeframe=mtf(),
            market_structure={},
            market_interval="1m",
            cross_venue_derivatives={
                "warnings": ["funding_rate_dispersion_across_venues"],
                "venues": [
                    {"venue": "binance_usdm", "status": "ok", "observed_at_ms": NOW - 3_000},
                    {"venue": "bybit_linear", "status": "ok", "observed_at_ms": NOW - 2_000},
                ],
            },
            liquidation_risk={
                "warnings": [
                    "cross_venue_long_liquidation_pressure",
                    "cross_venue_short_liquidation_pressure",
                ],
                "by_venue": {
                    "binance_usdm": {"latest_event_time_ms": NOW - 5_000},
                    "bybit_linear": {"latest_event_time_ms": NOW - 4_000},
                },
            },
            now_ms=NOW,
        )
        event_types = [event["type"] for event in result["events"]]
        self.assertEqual(event_types.count("cross_venue_funding_dispersion"), 1)
        liquidation_events = [event for event in result["events"] if event["type"] == "cross_venue_liquidation_pressure"]
        self.assertEqual(len(liquidation_events), 2)
        self.assertEqual({event["value"] for event in liquidation_events}, {
            "cross_venue_long_liquidation_pressure",
            "cross_venue_short_liquidation_pressure",
        })

    def test_incomplete_inputs_are_not_fabricated_as_events(self):
        result = build_market_screener(
            multi_timeframe={"frames": {"1m": frame(status="stale", breakout="up")}},
            market_structure={"bars": {"status": "incomplete", "relative_volume_20": 10}},
            market_interval="1m",
            streamed_trade_flow={"status": "incomplete", "score": None},
            order_book={"imbalance": 0.9, "spread_bps": 30, "observed_at_ms": NOW - 90_000},
            now_ms=NOW,
        )
        self.assertEqual(result["events"], [])
        self.assertIn("some_screener_inputs_were_missing_stale_or_incomplete", result["warnings"])

    def test_screener_thresholds_are_validated(self):
        with self.assertRaises(ValueError):
            build_market_screener(
                multi_timeframe=mtf(), market_structure={}, market_interval="1m",
                thresholds={"book_imbalance_abs": 1.5}, now_ms=NOW,
            )

    def test_events_have_stable_keys_and_never_create_orders(self):
        result = build_market_screener(
            multi_timeframe=mtf(), market_structure={}, market_interval="1m",
            cross_venue_derivatives={
                "warnings": ["funding_rate_dispersion_across_venues"],
                "venues": [
                    {"status": "ok", "observed_at_ms": NOW - 1_000},
                    {"status": "ok", "observed_at_ms": NOW - 2_000},
                ],
            },
            liquidation_risk={
                "warnings": [
                    "cross_venue_long_liquidation_pressure",
                    "cross_venue_short_liquidation_pressure",
                ],
                "by_venue": {
                    "one": {"latest_event_time_ms": NOW - 2_000},
                    "two": {"latest_event_time_ms": NOW - 2_000},
                },
            },
            now_ms=NOW,
        )
        keys = [event["event_key"] for event in result["events"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(event["creates_order"] is False for event in result["events"]))


if __name__ == "__main__":
    unittest.main()
