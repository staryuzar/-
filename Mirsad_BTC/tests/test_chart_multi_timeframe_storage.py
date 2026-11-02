from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mirsad.engines.chart_multi_timeframe import analyze_stored_multi_timeframe_structure
from mirsad.storage import load_candles_by_timeframe, save_market_snapshot


def make_bars(
    timeframe_ms: int,
    start_ms: int,
    *,
    count: int = 40,
    closed: bool = True,
    price_offset: float = 0.0,
) -> list[dict]:
    closes = [
        100, 104, 101, 108, 103, 112, 107, 116, 110, 120,
        114, 124, 118, 128, 121, 132, 125, 136, 129, 140,
        133, 144, 137, 148, 141, 152, 145, 156, 149, 160,
        153, 164, 157, 168, 161, 172, 165, 176, 169, 180,
    ][:count]
    return [
        {
            "open_time_ms": start_ms + index * timeframe_ms,
            "open": close + price_offset,
            "high": close + price_offset + 0.5,
            "low": close + price_offset - 0.5,
            "close": close + price_offset,
            "volume": 1.0 + index,
            "closed": closed,
        }
        for index, close in enumerate(closes)
    ]


class StoredMultiTimeframeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "mirsad-test.sqlite3"
        self.as_of_ms = 100_000_000

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _save_two_venues(self) -> None:
        snapshot = {
            "captured_at_ms": self.as_of_ms,
            "symbol": "BTCUSDT",
            "price": 100_000.0,
            "primary_venue": "Binance Spot",
            "venue_count": 2,
            "status": "LIVE",
            "venues": {
                "Binance Spot": {
                    "status": "LIVE",
                    "candles_by_tf": {
                        "1m": make_bars(60_000, self.as_of_ms - 40 * 60_000),
                        "5m": make_bars(300_000, self.as_of_ms - 40 * 300_000),
                    },
                },
                "OKX Spot": {
                    "status": "LIVE",
                    "candles_by_tf": {
                        "1m": make_bars(
                            60_000, self.as_of_ms - 40 * 60_000,
                            price_offset=500.0,
                        ),
                        "5m": make_bars(
                            300_000, self.as_of_ms - 40 * 300_000,
                            price_offset=500.0,
                        ),
                    },
                },
            },
        }
        save_market_snapshot(snapshot, self.db_path)

    def test_reader_keeps_venue_candles_isolated_and_chronological(self) -> None:
        self._save_two_venues()
        data = load_candles_by_timeframe(
            symbol="BTCUSDT",
            venue="Binance Spot",
            timeframes=("1m", "5m"),
            as_of_ms=self.as_of_ms,
            limit=120,
            db_path=self.db_path,
        )
        self.assertEqual(len(data["1m"]), 40)
        self.assertEqual(len(data["5m"]), 40)
        self.assertEqual(data["1m"][0]["open_time_ms"], self.as_of_ms - 40 * 60_000)
        self.assertEqual(data["1m"][-1]["open_time_ms"], self.as_of_ms - 60_000)
        self.assertTrue(all(item["closed"] for item in data["1m"]))
        self.assertAlmostEqual(data["1m"][0]["close"], 100.0)

        okx = load_candles_by_timeframe(
            symbol="BTCUSDT",
            venue="OKX Spot",
            timeframes=("1m",),
            as_of_ms=self.as_of_ms,
            db_path=self.db_path,
        )
        self.assertAlmostEqual(okx["1m"][0]["close"], 600.0)

    def test_reader_excludes_unclosed_and_not_yet_finished_candles(self) -> None:
        self._save_two_venues()
        # Add two later records: one marked open and one whose scheduled close
        # is after as_of_ms despite a corrupt/over-eager closed flag.
        snapshot = {
            "captured_at_ms": self.as_of_ms,
            "symbol": "BTCUSDT",
            "venues": {
                "Binance Spot": {
                    "status": "LIVE",
                    "candles_by_tf": {
                        "1m": [
                            {
                                "open_time_ms": self.as_of_ms - 30_000,
                                "open": 200, "high": 201, "low": 199,
                                "close": 200, "volume": 1, "closed": True,
                            },
                            {
                                "open_time_ms": self.as_of_ms - 10_000,
                                "open": 201, "high": 202, "low": 200,
                                "close": 201, "volume": 1, "closed": False,
                            },
                        ],
                    },
                },
            },
        }
        save_market_snapshot(snapshot, self.db_path)
        data = load_candles_by_timeframe(
            symbol="BTCUSDT",
            venue="Binance Spot",
            timeframes=("1m",),
            as_of_ms=self.as_of_ms,
            db_path=self.db_path,
        )
        self.assertEqual(len(data["1m"]), 40)
        self.assertEqual(data["1m"][-1]["open_time_ms"], self.as_of_ms - 60_000)

    def test_stored_analyser_returns_timestamp_aligned_reports_without_cross_venue_merge(self) -> None:
        self._save_two_venues()
        report = analyze_stored_multi_timeframe_structure(
            symbol="BTCUSDT",
            venue="Binance Spot",
            as_of_ms=self.as_of_ms,
            timeframes=("1m", "5m"),
            db_path=str(self.db_path),
        )
        self.assertEqual(report["source"], "market_candles_sqlite")
        self.assertEqual(report["venue"], "Binance Spot")
        self.assertEqual(report["status"], "READY")
        self.assertEqual(report["loaded_candle_counts"], {"1m": 40, "5m": 40})
        self.assertEqual(report["available_timeframes"], ["1m", "5m"])
        self.assertTrue(report["does_not_affect_decision_engine"])
        self.assertEqual(
            report["venue_policy"],
            "SINGLE_PRIMARY_VENUE_NO_CROSS_EXCHANGE_CANDLE_MERGE",
        )
        self.assertLess(
            report["timeframe_reports"]["1m"]["last_close_time_ms"],
            self.as_of_ms + 1,
        )

    def test_missing_primary_venue_returns_partial_not_fake_alignment(self) -> None:
        report = analyze_stored_multi_timeframe_structure(
            symbol="BTCUSDT",
            venue=None,
            as_of_ms=self.as_of_ms,
            db_path=str(self.db_path),
        )
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["available_timeframes"], [])
        self.assertEqual(report["errors"]["venue"], "NO_PRIMARY_VENUE_AVAILABLE")

    def test_unsupported_timeframe_and_bad_limit_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported timeframe"):
            load_candles_by_timeframe(
                symbol="BTCUSDT", venue="Binance Spot",
                timeframes=("3m",), as_of_ms=self.as_of_ms,
                db_path=self.db_path,
            )
        with self.assertRaisesRegex(ValueError, "limit"):
            load_candles_by_timeframe(
                symbol="BTCUSDT", venue="Binance Spot",
                timeframes=("1m",), as_of_ms=self.as_of_ms,
                limit=7, db_path=self.db_path,
            )


if __name__ == "__main__":
    unittest.main()
