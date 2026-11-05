import unittest
from datetime import datetime, timezone

from bitcoinlab.models import Bar
from bitcoinlab.multi_timeframe import build_multi_timeframe_profile


NOW = 1_800_000_000_000


def make_bars(count=80, *, start=NOW - 80 * 60_000, rise=10.0):
    rows = []
    price = 50_000.0
    for index in range(count):
        price += rise
        interval_ms = 60_000
        rows.append(Bar(
            open_time_ms=start + index * interval_ms,
            open=price - 1, high=price + 2, low=price - 2,
            close=price, volume=1.0,
            close_time_ms=start + (index + 1) * interval_ms - 1,
            is_closed=True,
        ))
    return rows


class MultiTimeframeTests(unittest.TestCase):
    def test_top_down_profile_reports_fresh_frames_and_roles(self):
        data = {frame: make_bars() for frame in ("1d", "4h", "1h", "15m", "5m", "1m")}
        result = build_multi_timeframe_profile(
            symbol="BTCUSDT", now_ms=NOW, preloaded_bars=data,
            fetcher=lambda *_args, **_kwargs: [],
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["direction"], "BUY")
        self.assertEqual(result["coverage"]["fresh_frames"], 6)
        self.assertEqual(result["frames"]["1d"]["role"], "daily_regime")
        self.assertEqual(result["frames"]["1m"]["role"], "microstructure_timing")

    def test_missing_micro_frame_does_not_replace_it_with_zero(self):
        data = {frame: make_bars() for frame in ("1d", "4h", "1h", "15m")}
        result = build_multi_timeframe_profile(
            symbol="BTCUSDT", now_ms=NOW, preloaded_bars=data,
            fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("unavailable")),
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["frames"]["5m"]["status"], "error")
        self.assertIsNone(result["frames"]["5m"]["score"])
        self.assertIn("micro_timing_incomplete", result["warnings"])

    def test_insufficient_coverage_cannot_create_direction(self):
        data = {"1d": make_bars(), "1h": make_bars()}
        result = build_multi_timeframe_profile(
            symbol="BTCUSDT", now_ms=NOW, preloaded_bars=data,
            fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["direction"], "HOLD")
        self.assertIsNone(result["score"])
        self.assertIn("insufficient_fresh_timeframes", result["blockers"])

    def test_stale_macro_frames_are_not_used_as_valid_context(self):
        stale = make_bars(start=NOW - 10 * 24 * 60 * 60_000)
        fresh = make_bars()
        data = {"1d": stale, "4h": stale, "1h": fresh, "15m": fresh, "5m": fresh, "1m": fresh}
        result = build_multi_timeframe_profile(
            symbol="BTCUSDT", now_ms=NOW, preloaded_bars=data,
            fetcher=lambda *_args, **_kwargs: [],
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("missing_daily_or_four_hour_context", result["blockers"])

    def test_non_bitcoin_symbol_is_rejected(self):
        with self.assertRaises(ValueError):
            build_multi_timeframe_profile(symbol="XAUUSD", now_ms=NOW)


if __name__ == "__main__":
    unittest.main()
