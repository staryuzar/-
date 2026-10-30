import unittest

from bitcoinlab.indicators import atr, ema, rsi, technical_profile
from bitcoinlab.models import Bar


def make_bars(count=80, *, start=1_700_000_000_000, step=60_000, rise=10.0, open_last=False):
    rows = []
    price = 100.0
    for index in range(count):
        price += rise
        is_closed = not (open_last and index == count - 1)
        rows.append(Bar(
            open_time_ms=start + index * step, open=price - 1, high=price + 2,
            low=price - 2, close=price, volume=10.0,
            close_time_ms=start + index * step + step - 1, is_closed=is_closed,
        ))
    return rows


class IndicatorTests(unittest.TestCase):
    def test_ema_seed_is_sma_then_recursive(self):
        self.assertEqual(ema([1, 2, 3, 4], 3), [None, None, 2.0, 3.0])

    def test_ema_rejects_nonfinite(self):
        with self.assertRaises(ValueError):
            ema([1, float("nan"), 3], 2)

    def test_atr_uses_gap_from_previous_close(self):
        bars = [
            Bar(1000, 10, 12, 9, 11, 1, 1999),
            Bar(2000, 15, 16, 14, 15, 1, 2999),
        ]
        self.assertAlmostEqual(atr(bars, 2), 4.0)

    def test_rsi_uptrend_is_100(self):
        self.assertEqual(rsi(list(range(1, 20)), 14), 100.0)

    def test_rsi_flat_series_is_neutral(self):
        self.assertEqual(rsi([10.0] * 20, 14), 50.0)

    def test_technical_profile_uses_only_closed_bars(self):
        result = technical_profile(make_bars(80, open_last=True))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["close"], 900.0)
        self.assertEqual(result["state"], "bullish")

    def test_technical_profile_rejects_short_history(self):
        self.assertEqual(technical_profile(make_bars(20))["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
