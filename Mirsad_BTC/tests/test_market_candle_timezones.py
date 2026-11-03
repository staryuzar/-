from __future__ import annotations

import unittest
from datetime import datetime, timezone

from mirsad.engines.market import OKX_INTERVALS, _candle_rows


class MarketCandleTimezoneTests(unittest.TestCase):
    def test_okx_daily_market_feed_uses_utc_not_utc_plus_eight(self) -> None:
        self.assertEqual(OKX_INTERVALS["1d"], "1Dutc")

    def test_okx_daily_utc_timestamp_is_preserved_for_weekly_aggregation(self) -> None:
        expected_open = int(
            datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc).timestamp() * 1000
        )
        row = [
            str(expected_open), "100", "102", "99", "101", "500",
            "50000", "500", "1",
        ]
        candle = _candle_rows(
            [row],
            source="okx",
            timeframe="1d",
        )[0]
        self.assertEqual(candle["open_time_ms"], expected_open)
        self.assertTrue(candle["closed"])
        self.assertEqual(candle["open"], 100.0)
        self.assertEqual(candle["high"], 102.0)
        self.assertEqual(candle["low"], 99.0)
        self.assertEqual(candle["close"], 101.0)


if __name__ == "__main__":
    unittest.main()
