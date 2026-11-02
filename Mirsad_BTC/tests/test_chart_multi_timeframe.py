from __future__ import annotations

import unittest

from mirsad.engines.chart_multi_timeframe import analyze_multi_timeframe_structure


def bars_for(timeframe_ms: int, start_ms: int = 1_000_000, count: int = 40) -> list[dict[str, float]]:
    # Swing-rich test data provides confirmed pivots at the 2/2 scale.
    closes = [
    100, 106, 112, 108, 104, 102, 110, 118, 114, 108,
    106, 114, 122, 118, 112, 110, 118, 126, 122, 116,
    114, 122, 130, 126, 120, 118, 126, 134, 130, 124,
    122, 130, 138, 134, 128, 126, 134, 142, 138, 132,
    ][:count]
    return [
        {
            "open_time_ms": start_ms + index * timeframe_ms,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        }
        for index, close in enumerate(closes)
    ]


class ChartMultiTimeframeTests(unittest.TestCase):
    def test_two_timestamped_frames_are_analysed_independently_at_one_cutoff(self) -> None:
        as_of = 50_000_000
        one_minute = bars_for(60_000, start_ms=as_of - 40 * 60_000)
        five_minute = bars_for(5 * 60_000, start_ms=as_of - 40 * 5 * 60_000)
        result = analyze_multi_timeframe_structure(
            {"1m": one_minute, "5m": five_minute}, as_of_ms=int(as_of)
        )
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["available_timeframes"], ["1m", "5m"])
        self.assertTrue(all(
            item["as_of_ms"] == as_of
            for item in result["timeframe_reports"].values()
        ))
        self.assertIn(
            result["alignment"],
            {"BULLISH_TIMEFRAME_CONFLUENCE", "BEARISH_TIMEFRAME_CONFLUENCE",
             "MIXED_TIMEFRAME_STRUCTURE", "INSUFFICIENT_TIMEFRAME_CONFLUENCE"},
        )

    def test_future_or_not_yet_closed_candles_are_excluded_by_cutoff(self) -> None:
        bars = bars_for(60_000)
        cutoff = int(bars[20]["open_time_ms"] + 60_000)
        result = analyze_multi_timeframe_structure({"1m": bars}, as_of_ms=cutoff)
        report = result["timeframe_reports"]["1m"]
        self.assertEqual(report["confirmed_bars"], 21)
        self.assertLessEqual(report["last_close_time_ms"], cutoff)

    def test_missing_timestamps_do_not_allow_false_timeframe_alignment(self) -> None:
        bars = [{"open": 100+i, "high": 101+i, "low": 99+i, "close": 100+i} for i in range(10)]
        result = analyze_multi_timeframe_structure({"1m": bars}, as_of_ms=10_000_000)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["available_timeframes"], [])
        self.assertEqual(result["errors"]["1m"], "MISSING_OPEN_TIME_MS_AT_INDEX_0")

    def test_stale_timeframe_is_excluded_from_confluence(self) -> None:
        as_of = 50_000_000
        stale = bars_for(60_000, start_ms=as_of - 3 * 60 * 60_000)
        fresh = bars_for(5 * 60_000, start_ms=as_of - 40 * 5 * 60_000)
        result = analyze_multi_timeframe_structure(
            {"1m": stale, "5m": fresh}, as_of_ms=as_of
        )
        self.assertEqual(result["errors"]["1m"], "STALE_TIMEFRAME_DATA")
        self.assertNotIn("1m", result["available_timeframes"])
        self.assertIn("5m", result["available_timeframes"])

    def test_missing_candle_intervals_mark_frame_partial_and_exclude_it_from_confluence(self) -> None:
        timeframe_ms = 60_000
        as_of = 50_000_000
        bars = bars_for(timeframe_ms, start_ms=as_of - 40 * timeframe_ms)
        # Remove a candle in the middle while keeping the series chronological.
        del bars[15]
        result = analyze_multi_timeframe_structure(
            {"1m": bars, "5m": bars_for(5 * 60_000, start_ms=as_of - 40 * 5 * 60_000)},
            as_of_ms=as_of,
        )
        frame = result["timeframe_reports"]["1m"]
        self.assertEqual(frame["data_continuity"], "GAPS_DETECTED")
        self.assertTrue(frame["candle_gaps"])
        self.assertEqual(frame["status"], "PARTIAL")
        self.assertNotIn("1m", result["directional_structure_by_timeframe"])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotIn("1m", result["eligible_timeframes"])

    def test_non_chronological_bars_are_rejected(self) -> None:
        bars = bars_for(60_000, count=10)
        bars[5], bars[6] = bars[6], bars[5]
        result = analyze_multi_timeframe_structure(
            {"1m": bars}, as_of_ms=int(bars[-1]["open_time_ms"] + 60_000)
        )
        self.assertEqual(
            result["errors"]["1m"], "CANDLES_NOT_STRICTLY_CHRONOLOGICAL"
        )

    def test_declared_unclosed_latest_bar_is_excluded_even_before_next_frame_arrives(self) -> None:
        bars = bars_for(60_000)
        as_of = int(bars[-1]["open_time_ms"] + 60_000)
        result = analyze_multi_timeframe_structure(
            {"1m": bars}, as_of_ms=as_of,
            last_candle_closed_by_timeframe={"1m": False},
        )
        self.assertEqual(result["timeframe_reports"]["1m"]["confirmed_bars"], len(bars)-1)


if __name__ == "__main__":
    unittest.main()
