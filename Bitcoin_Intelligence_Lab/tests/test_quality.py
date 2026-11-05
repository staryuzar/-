import unittest

from bitcoinlab.models import Bar
from bitcoinlab.quality import freshness, validate_bars


class QualityTests(unittest.TestCase):
    def bars(self):
        start = 1_700_000_000_000
        return [Bar(start + i * 60_000, 100, 102, 99, 101, 10, start + (i + 1) * 60_000 - 1) for i in range(60)]

    def test_freshness_detects_stale_source(self):
        self.assertEqual(freshness(1000, 1, now_ms=10_000)["status"], "stale")

    def test_small_future_timestamp_skew_reports_zero_age(self):
        result = freshness(10_500, 60, now_ms=10_000)
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(result["age_seconds"], 0.0)

    def test_large_future_timestamp_skew_remains_clock_skew(self):
        result = freshness(20_000, 60, now_ms=10_000)
        self.assertEqual(result["status"], "clock_skew")
        self.assertEqual(result["age_seconds"], 10.0)

    def test_valid_bar_series_passes(self):
        rows = self.bars()
        result = validate_bars(rows, min_bars=60, max_age_seconds=120, now_ms=rows[-1].close_time_ms + 10_000)
        self.assertEqual(result["status"], "fresh")

    def test_duplicate_candles_fail(self):
        rows = self.bars()
        rows[-1] = rows[-2]
        self.assertEqual(validate_bars(rows, min_bars=60, now_ms=rows[-1].close_time_ms + 1)["status"], "invalid_order")

    def test_recent_open_bar_fails(self):
        rows = self.bars()
        last = rows[-1]
        rows[-1] = Bar(last.open_time_ms, last.open, last.high, last.low, last.close, last.volume, last.close_time_ms, False)
        self.assertEqual(validate_bars(rows, min_bars=60, max_age_seconds=120, now_ms=last.close_time_ms + 1)["status"], "open_bar_present")


if __name__ == "__main__":
    unittest.main()
