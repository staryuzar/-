from __future__ import annotations

import unittest

from scripts.validate_engine2_public_btc import (
    longest_contiguous_segment,
    normalise_kline_rows,
)


class PublicBtcValidationTests(unittest.TestCase):
    def _rows(self) -> list[list[object]]:
        duration = 60_000
        first = 1_700_000_000_000
        rows = []
        for index in range(26):
            open_time = first + index * duration
            rows.append([
                open_time,
                "50000.0",
                "50100.0",
                "49900.0",
                "50050.0",
                "12.5",
                open_time + duration - 1,
                "0", 0, "0", "0", "0",
            ])
        return rows

    def test_normalises_closed_and_forming_klines(self) -> None:
        rows = self._rows()
        as_of = int(rows[-1][0]) + 20_000
        result = normalise_kline_rows(rows, "1m", as_of_ms=as_of)
        self.assertEqual(len(result), 26)
        self.assertTrue(all(row["closed"] for row in result[:-1]))
        self.assertFalse(result[-1]["closed"])

    def test_rejects_invalid_ohlc_geometry(self) -> None:
        rows = self._rows()
        rows[4][2] = "1"
        with self.assertRaisesRegex(ValueError, "OHLC geometry"):
            normalise_kline_rows(rows, "1m", as_of_ms=int(rows[-1][0]) + 20_000)

    def test_rejects_duplicate_or_non_chronological_times(self) -> None:
        rows = self._rows()
        rows[6][0] = rows[5][0]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            normalise_kline_rows(rows, "1m", as_of_ms=int(rows[-1][0]) + 20_000)

    def test_requires_current_forming_bar(self) -> None:
        rows = self._rows()
        with self.assertRaisesRegex(ValueError, "no current forming candle"):
            normalise_kline_rows(rows, "1m", as_of_ms=int(rows[-1][0]) + 60_000)

    def test_longest_contiguous_segment_does_not_bridge_a_gap(self) -> None:
        bars = [
            {"open_time_ms": 1_000 + index * 60_000, "close": 1.0}
            for index in (0, 1, 2, 5, 6, 7, 8)
        ]
        segment, excluded = longest_contiguous_segment(bars, interval_ms=60_000)
        self.assertEqual(
            [row["open_time_ms"] for row in segment],
            [1_000 + index * 60_000 for index in (5, 6, 7, 8)],
        )
        self.assertGreater(excluded, 0)


if __name__ == "__main__":
    unittest.main()
