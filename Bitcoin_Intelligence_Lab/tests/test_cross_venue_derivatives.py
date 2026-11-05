import unittest

from bitcoinlab.cross_venue_derivatives import (
    build_cross_venue_derivatives_context,
    funding_rate_per_8h,
)


NOW = 1_800_000_000_000


def row(venue, *, spot=100_000, perp=100_100, mark=100_120, index=100_000,
        rate=0.0001, interval=480, oi_btc=None, oi_native=None,
        native_unit=None, oi_quote=None, quote_currency=None, funding_kind="source_reported_rate", age_ms=5_000):
    return {
        "venue": venue,
        "symbol": "BTCUSDT",
        "observed_at_ms": NOW - age_ms,
        "timestamp_kind": "exchange",
        "spot_bid": spot - 5,
        "spot_ask": spot + 5,
        "perp_bid": perp - 5,
        "perp_ask": perp + 5,
        "mark_price": mark,
        "index_price": index,
        "funding_rate": rate,
        "funding_interval_minutes": interval,
        "funding_rate_kind": funding_kind,
        "open_interest_btc": oi_btc,
        "open_interest_native": oi_native,
        "open_interest_native_unit": native_unit,
        "open_interest_quote_value": oi_quote,
        "open_interest_quote_currency": quote_currency,
    }


class CrossVenueDerivativesTests(unittest.TestCase):
    def test_funding_is_scaled_by_actual_settlement_interval(self):
        self.assertAlmostEqual(funding_rate_per_8h(0.0002, 240), 0.0004)
        self.assertAlmostEqual(funding_rate_per_8h(0.0001, 480), 0.0001)
        self.assertAlmostEqual(funding_rate_per_8h(-0.0003, 720), -0.0002)
        self.assertIsNone(funding_rate_per_8h(None, 480))

    def test_basis_and_mark_index_premium_are_calculated_per_venue(self):
        result = build_cross_venue_derivatives_context([
            row("binance_usdm", rate=0.0001),
            row("bybit_linear", spot=100_020, perp=100_070, mark=100_080,
                rate=0.0002, interval=240),
        ], now_ms=NOW)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["venue_count"], 2)
        first = next(item for item in result["venues"] if item["venue"] == "binance_usdm")
        self.assertAlmostEqual(first["perpetual_vs_spot_bps"], 10.0, places=3)
        self.assertAlmostEqual(first["mark_vs_index_bps"], 12.0, places=3)
        self.assertAlmostEqual(first["funding_rate_per_8h_equivalent"], 0.0001)
        second = next(item for item in result["venues"] if item["venue"] == "bybit_linear")
        self.assertAlmostEqual(second["funding_rate_per_8h_equivalent"], 0.0004)

    def test_okx_funding_settlement_state_is_preserved(self):
        result = build_cross_venue_derivatives_context([
            row("okx_swap", funding_kind="settled"),
        ], now_ms=NOW)
        venue = result["venues"][0]
        self.assertEqual(venue["funding_rate_kind"], "settled")

    def test_open_interest_units_are_retained_and_never_summed(self):
        result = build_cross_venue_derivatives_context([
            row("bybit_linear", oi_btc=12.5, oi_quote=1_250_000, quote_currency="USDT"),
            row("okx_swap", oi_btc=10.2, oi_native=10_200, native_unit="contracts",
                oi_quote=1_020_000, quote_currency="USD"),
        ], now_ms=NOW)
        oi = result["open_interest_by_venue"]
        self.assertEqual(len(oi), 2)
        self.assertEqual({item["open_interest_quote_currency"] for item in oi}, {"USD", "USDT"})
        self.assertEqual({item["open_interest_btc"] for item in oi}, {10.2, 12.5})
        self.assertNotIn("total_open_interest", result)
        self.assertIn("no cross-venue sum", " ".join(result["limitations"]))

    def test_stale_or_duplicate_venue_rows_do_not_inflate_coverage(self):
        result = build_cross_venue_derivatives_context([
            row("binance_usdm", age_ms=300_000),
            row("bybit_linear"),
            row("bybit_linear", perp=101_000),
        ], now_ms=NOW, max_age_seconds=120)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["venue_count"], 1)
        self.assertTrue(any(item["error"] == "duplicate_venue_row" for item in result["errors"]))
        stale = next(item for item in result["venues"] if item["venue"] == "binance_usdm")
        self.assertEqual(stale["status"], "stale")

    def test_incompatible_or_missing_funding_period_is_not_normalized(self):
        result = build_cross_venue_derivatives_context([
            row("binance_usdm", interval=None),
            row("okx_swap", interval=480),
        ], now_ms=NOW)
        binance = next(item for item in result["venues"] if item["venue"] == "binance_usdm")
        self.assertIsNone(binance["funding_rate_per_8h_equivalent"])
        self.assertEqual(result["funding_8h_equivalent"]["venue_count"], 1)

    def test_invalid_market_prices_are_rejected(self):
        result = build_cross_venue_derivatives_context([
            row("binance_usdm", spot=100_000, perp=100_100)
            | {"spot_bid": 100_010, "spot_ask": 100_000}
        ], now_ms=NOW)
        self.assertTrue(any("non-crossed" in item["error"] for item in result["errors"]))
        self.assertEqual(result["venue_count"], 0)


if __name__ == "__main__":
    unittest.main()
