import unittest

from bitcoinlab.market_structure import (
    bar_market_structure,
    trade_volume_profile,
)
from bitcoinlab.models import Bar


def make_bars(count=30):
    rows = []
    price = 100.0
    start = 1_800_000_000_000
    for index in range(count):
        price += 0.5
        high = price + 1.0
        low = price - 1.0
        if index == count - 1:
            high = price + 3.0
            low = price - 2.0
        rows.append(Bar(
            open_time_ms=start + index * 60_000,
            open=price - 0.2,
            high=high,
            low=low,
            close=price,
            volume=20.0 if index == count - 1 else 10.0,
            close_time_ms=start + (index + 1) * 60_000 - 1,
            is_closed=True,
        ))
    return rows


class MarketStructureTests(unittest.TestCase):
    def test_trade_profile_computes_poc_value_area_and_aggressor_delta(self):
        trades = [
            {"p": "100.1", "q": "1", "m": False, "T": 1_800_000_000_000},
            {"p": "100.2", "q": "2", "m": True, "T": 1_800_000_001_000},
            {"p": "100.9", "q": "3", "m": False, "T": 1_800_000_002_000},
            {"p": "101.1", "q": "1", "m": False, "T": 1_800_000_003_000},
        ]
        result = trade_volume_profile(trades, bin_size=1.0, value_area_fraction=0.70)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["scope"], "recent_sample_not_full_session")
        self.assertEqual(result["poc"], 100.5)
        self.assertEqual(result["val"], 100.0)
        self.assertEqual(result["vah"], 101.0)
        self.assertAlmostEqual(result["total_buy_volume_btc"], 5.0)
        self.assertAlmostEqual(result["total_sell_volume_btc"], 2.0)
        self.assertAlmostEqual(result["delta_ratio"], 3 / 7, places=6)

    def test_trade_profile_rejects_missing_aggressor_side(self):
        with self.assertRaisesRegex(ValueError, "buyer-maker"):
            trade_volume_profile([{"p": "100", "q": "1"}])

    def test_trade_profile_rejects_invalid_bin_size(self):
        with self.assertRaises(ValueError):
            trade_volume_profile([{"p": "100", "q": "1", "m": False}], bin_size=0)

    def test_bar_metrics_calculate_relative_volume_vwap_and_expansion(self):
        result = bar_market_structure(make_bars())
        self.assertEqual(result["status"], "ok")
        self.assertAlmostEqual(result["relative_volume_20"], 2.0)
        self.assertIsNotNone(result["session_vwap_utc"])
        self.assertGreater(result["range_expansion_vs_prior_median"], 1.0)
        self.assertGreaterEqual(result["realized_volatility_bars"], 2)

    def test_open_bars_are_not_used_in_structure(self):
        bars = make_bars()
        last = bars[-1]
        bars[-1] = Bar(
            open_time_ms=last.open_time_ms, open=last.open, high=last.high,
            low=last.low, close=last.close, volume=last.volume,
            close_time_ms=last.close_time_ms, is_closed=False,
        )
        result = bar_market_structure(bars)
        self.assertEqual(result["last_close"], bars[-2].close)


if __name__ == "__main__":
    unittest.main()
