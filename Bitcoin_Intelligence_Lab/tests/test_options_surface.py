from datetime import datetime, timedelta, timezone
import math
import unittest

from bitcoinlab.options_surface import (
    black_scholes_option_greeks,
    build_btc_options_surface,
)


class BlackScholesOptionsTests(unittest.TestCase):
    def test_call_and_put_delta_sign_and_positive_gamma(self):
        call = black_scholes_option_greeks(
            spot=70_000, strike=70_000, time_years=30 / 365,
            volatility=0.60, option_type="call",
        )
        put = black_scholes_option_greeks(
            spot=70_000, strike=70_000, time_years=30 / 365,
            volatility=0.60, option_type="put",
        )
        self.assertGreater(call["delta"], 0)
        self.assertLess(put["delta"], 0)
        self.assertGreater(call["gamma"], 0)
        self.assertAlmostEqual(call["gamma"], put["gamma"], places=12)
        self.assertAlmostEqual(call["delta"] - put["delta"], 1.0, places=8)

    def test_invalid_black_scholes_values_are_rejected(self):
        with self.assertRaises(ValueError):
            black_scholes_option_greeks(
                spot=0, strike=70_000, time_years=0.1,
                volatility=0.6, option_type="call",
            )
        with self.assertRaises(ValueError):
            black_scholes_option_greeks(
                spot=70_000, strike=70_000, time_years=0.1,
                volatility=0, option_type="call",
            )


class DeribitOptionsSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.now_ms = int(datetime(2026, 10, 31, tzinfo=timezone.utc).timestamp() * 1000)
        self.expiry = int((datetime(2026, 11, 30, tzinfo=timezone.utc)).timestamp() * 1000)

    def inputs(self):
        rows = [
            ("BTC-C-ATM", "call", 70_000, 62.0, 4.0),
            ("BTC-P-ATM", "put", 70_000, 64.0, 3.0),
            ("BTC-C-25D", "call", 82_000, 68.0, 1.5),
            ("BTC-P-25D", "put", 60_000, 74.0, 2.5),
            ("BTC-C-ZERO-OI", "call", 90_000, 80.0, 0.0),
        ]
        instruments = []
        summaries = []
        for name, kind, strike, iv, oi in rows:
            instruments.append({
                "instrument_name": name,
                "kind": "option",
                "option_type": kind,
                "strike": strike,
                "expiration_timestamp": self.expiry,
                "is_active": True,
                "contract_size": 1.0,
            })
            summaries.append({
                "instrument_name": name,
                "underlying_price": 70_000,
                "mark_iv": iv,
                "open_interest": oi,
            })
        return instruments, summaries

    def test_builds_term_structure_skew_and_btc_oi(self):
        instruments, summaries = self.inputs()
        result = build_btc_options_surface(
            instruments, summaries, now_ms=self.now_ms,
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["currency"], "BTC")
        self.assertEqual(result["option_count"], 5)
        expiry = result["expiries"][0]
        self.assertIsNotNone(expiry["atm_iv_pct"])
        self.assertIsNotNone(expiry["risk_reversal_25d_vol_points"])
        self.assertEqual(expiry["risk_reversal_status"], "ok")
        self.assertAlmostEqual(expiry["call_open_interest_btc"], 5.5)
        self.assertAlmostEqual(expiry["put_open_interest_btc"], 5.5)
        self.assertAlmostEqual(expiry["put_call_oi_ratio"], 1.0)
        self.assertAlmostEqual(expiry["total_open_interest_btc"], 11.0)
        self.assertIn("unsigned_gamma_open_interest_btc_proxy_by_strike", expiry)
        self.assertNotIn("gross_gamma_oi_map", result)
        self.assertNotIn("dealer_gex", str(result).lower())

    def test_zero_oi_option_is_retained_for_iv_but_does_not_add_oi(self):
        instruments, summaries = self.inputs()
        result = build_btc_options_surface(
            instruments, summaries, now_ms=self.now_ms,
        )
        self.assertEqual(result["option_count"], 5)
        expiry = result["expiries"][0]
        self.assertAlmostEqual(expiry["call_open_interest_btc"], 5.5)
        self.assertEqual(expiry["option_count"], 5)

    def test_expired_inactive_and_incomplete_quotes_are_rejected(self):
        instruments, summaries = self.inputs()
        expired = dict(instruments[0], instrument_name="BTC-EXPIRED", expiration_timestamp=self.now_ms - 1000)
        inactive = dict(instruments[1], instrument_name="BTC-INACTIVE", is_active=False)
        instruments.extend([expired, inactive])
        summaries.extend([
            {
                "instrument_name": "BTC-EXPIRED", "underlying_price": 70_000,
                "mark_iv": 60, "open_interest": 1,
            },
            {
                "instrument_name": "BTC-INACTIVE", "underlying_price": 70_000,
                "mark_iv": 60, "open_interest": 1,
            },
            {
                "instrument_name": "BTC-MISSING-META", "underlying_price": 70_000,
                "mark_iv": 60, "open_interest": 1,
            },
            {
                "instrument_name": "BTC-NO-IV", "underlying_price": 70_000,
                "mark_iv": None, "open_interest": 1,
            },
        ])
        result = build_btc_options_surface(
            instruments, summaries, now_ms=self.now_ms,
        )
        self.assertEqual(result["option_count"], 5)
        self.assertEqual(result["rejected_count"], 4)

    def test_empty_and_invalid_timestamp_cases_are_explicit(self):
        empty = build_btc_options_surface([], [], now_ms=self.now_ms)
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["option_count"], 0)
        with self.assertRaises(ValueError):
            build_btc_options_surface([], [], now_ms=0)

    def test_expiry_cap_is_respected(self):
        instruments, summaries = self.inputs()
        expiry_two = self.expiry + 30 * 24 * 60 * 60 * 1000
        next_instrument = dict(
            instruments[0], instrument_name="BTC-NEXT", expiration_timestamp=expiry_two,
        )
        next_summary = dict(
            summaries[0], instrument_name="BTC-NEXT",
        )
        instruments.append(next_instrument)
        summaries.append(next_summary)
        result = build_btc_options_surface(
            instruments, summaries, now_ms=self.now_ms, max_expiries=1,
        )
        self.assertEqual(result["expiry_count"], 1)
        self.assertEqual(len(result["expiries"]), 1)


if __name__ == "__main__":
    unittest.main()
