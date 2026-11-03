from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from mirsad.engines.mt5_market import MT5MarketDataEngine


def make_snapshot(*, captured_at_ms: int | None = None) -> dict:
    now = int(time.time() * 1000) if captured_at_ms is None else captured_at_ms
    return {
        "schema": "MIR-MT5-MARKET-2",
        "captured_at_utc_ms": now,
        "terminal_connected": True,
        "broker_symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
        "time_basis": "UTC_NORMALIZED_FROM_MT5_SERVER_TIME",
        "quote": {"bid": 90_000.0, "ask": 90_001.0, "tick_age_seconds": 1.0},
        "tick_window_seconds": 30,
        "ticks": [
            {"time_utc_ms": now - 2_000, "bid": 89_998.0, "ask": 89_999.0},
            {"time_utc_ms": now - 1_000, "bid": 89_999.0, "ask": 90_000.0,
             "last": 90_000.0, "volume": 2, "volume_real": 2.5, "flags": 24},
            {"time_utc_ms": now - 500, "bid": 90_000.0, "ask": 90_001.0,
             "last": 90_001.0, "volume": 3, "volume_real": 3.5, "flags": 56},
        ],
        "depth_of_market": {
            "status": "AVAILABLE", "source": "MT5_MARKET_BOOK",
            "captured_at_utc_ms": now,
            "levels": [
                {"side": "BUY", "price": 89_999.0, "volume": 4, "volume_real": 4.5},
                {"side": "BUY", "price": 89_998.0, "volume": 3, "volume_real": 3.5},
                {"side": "SELL", "price": 90_002.0, "volume": 5, "volume_real": 5.5},
            ],
        },
        "economic_calendar": {
            "status": "AVAILABLE", "source": "MT5_ECONOMIC_CALENDAR",
            "currency": "USD",
            "events": [{
                "event_id": 11, "event_time_utc_ms": now + 600_000,
                "name": "US inflation release", "importance": "HIGH",
                "currency": "USD", "country_code": "US",
            }],
        },
    }


class MT5MarketDataEngineTests(unittest.TestCase):
    def _engine(self, directory: str) -> MT5MarketDataEngine:
        return MT5MarketDataEngine(common_files=directory)

    def _write_snapshot(self, directory: str, payload: dict) -> None:
        root = Path(directory) / "MirsadBTC"
        root.mkdir(parents=True, exist_ok=True)
        (root / "market.json").write_text(json.dumps(payload), encoding="utf-8")

    def _bridge(self) -> dict:
        return {
            "status": "CONNECTED", "symbol": "BTC", "market_symbol": "BTCUSDT",
            "account": {"server": "Headway-Demo"},
            "quote": {"bid": 90_000.0, "ask": 90_001.0}, "quote_age_seconds": 1.0,
        }

    def test_reads_fresh_mt5_quote_pulse_and_economic_calendar_without_candles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write_snapshot(directory, make_snapshot())
            market = self._engine(directory).collect(bridge=self._bridge())
        self.assertEqual(market["status"], "LIVE")
        self.assertEqual(market["source"], "MT5_TERMINAL")
        self.assertEqual(market["venue_count"], 1)
        self.assertEqual(market["primary_venue"], "MT5 Broker")
        self.assertEqual(market["feed_health"]["bridge_quote_check"]["status"], "MATCHED")
        pulse = market["market_context"]["microstructure"]
        self.assertEqual(pulse["status"], "READY")
        self.assertEqual(pulse["upticks"], 2)
        self.assertGreater(pulse["quote_direction_balance"], 0)
        self.assertEqual(market["market_context"]["economic_calendar"]["events"][0]["importance"], "HIGH")
        book = market["market_context"]["order_book"]
        self.assertEqual(book["status"], "AVAILABLE")
        self.assertEqual(book["bid_level_count"], 2)
        self.assertEqual(book["ask_level_count"], 1)
        self.assertAlmostEqual(book["bid_volume"], 8.0)
        self.assertAlmostEqual(book["ask_volume"], 5.5)
        self.assertEqual(pulse["reported_last_price_tick_count"], 2)
        self.assertEqual(pulse["reported_volume_update_count"], 2)
        self.assertAlmostEqual(pulse["reported_volume_sum"], 6.0)
        self.assertEqual(pulse["reported_buy_flag_count"], 1)
        venue = market["venues"]["MT5 Broker"]
        self.assertNotIn("candles", venue)
        self.assertNotIn("candles_by_tf", venue)
        self.assertNotIn("timeframes", market)

    def test_trade_only_ticks_are_kept_without_contaminating_quote_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            now = payload["captured_at_utc_ms"]
            payload["ticks"] = [
                {
                    "time_utc_ms": now - 2_000,
                    "bid": 0, "ask": 0, "last": 90_000,
                    "volume": 2, "volume_real": 2.5, "flags": 24,
                },
                {
                    "time_utc_ms": now - 1_000,
                    "bid": 90_000, "ask": 90_001,
                    "last": 90_000.5, "volume": 3, "volume_real": 3.5, "flags": 56,
                },
                {
                    "time_utc_ms": now - 500,
                    "bid": 90_001, "ask": 90_002,
                    "last": 90_001.5, "volume": 1, "volume_real": 1.5, "flags": 56,
                },
            ]
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()

        pulse = market["market_context"]["microstructure"]
        self.assertEqual(market["status"], "LIVE")
        self.assertEqual(pulse["status"], "READY")
        self.assertEqual(pulse["tick_count"], 3)
        self.assertEqual(pulse["quote_tick_count"], 2)
        self.assertEqual(pulse["reported_last_price_tick_count"], 3)
        self.assertEqual(pulse["reported_volume_update_count"], 3)
        self.assertEqual(pulse["reported_buy_flag_count"], 2)
        self.assertEqual(pulse["reported_sell_flag_count"], 0)
        self.assertEqual(pulse["upticks"], 1)
        self.assertEqual(pulse["downticks"], 0)
        self.assertAlmostEqual(pulse["reported_volume_sum"], 7.5)

    def test_depth_of_market_unavailable_is_reported_without_inventing_levels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            payload["depth_of_market"] = {
                "status": "UNAVAILABLE", "source": "MT5_MARKET_BOOK",
                "subscribed": False, "error_code": 4302, "levels": [],
            }
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()
        book = market["market_context"]["order_book"]
        self.assertEqual(book["status"], "NOT_AVAILABLE")
        self.assertEqual(book["levels"], [])

    def test_missing_common_files_configuration_is_not_ready(self) -> None:
        market = MT5MarketDataEngine(common_files="").collect()
        self.assertEqual(market["status"], "NOT_CONFIGURED")
        self.assertEqual(market["venue_count"], 0)

    def test_stale_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stale = make_snapshot(captured_at_ms=int(time.time() * 1000) - 60_000)
            self._write_snapshot(directory, stale)
            market = self._engine(directory).collect()
        self.assertEqual(market["status"], "STALE")
        self.assertEqual(market["venue_count"], 0)

    def test_stale_tick_is_rejected_even_when_snapshot_is_recent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            payload["quote"]["tick_age_seconds"] = 30
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()
        self.assertEqual(market["status"], "STALE_QUOTE")

    def test_bridge_server_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write_snapshot(directory, make_snapshot())
            bridge = self._bridge()
            bridge["account"]["server"] = "Other-Demo"
            market = self._engine(directory).collect(bridge=bridge)
        self.assertEqual(market["status"], "BRIDGE_IDENTITY_MISMATCH")

    def test_bridge_quote_divergence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write_snapshot(directory, make_snapshot())
            bridge = self._bridge()
            bridge["quote"] = {"bid": 91_000.0, "ask": 91_001.0}
            market = self._engine(directory).collect(bridge=bridge)
        self.assertEqual(market["status"], "QUOTE_DIVERGENCE")

    def test_invalid_tick_history_is_not_silently_used_for_direction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            payload["ticks"][1]["time_utc_ms"] = payload["ticks"][0]["time_utc_ms"] - 1
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()
        self.assertEqual(market["status"], "LIVE")
        self.assertEqual(market["market_context"]["microstructure"]["status"], "INVALID")
        self.assertIsNone(market["market_context"]["microstructure"]["quote_direction_balance"])

    def test_unavailable_economic_calendar_is_reported_not_invented(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            payload["economic_calendar"] = {"status": "UNAVAILABLE", "error_code": 5402}
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()
        calendar = market["market_context"]["economic_calendar"]
        self.assertEqual(calendar["status"], "NOT_AVAILABLE")
        self.assertEqual(calendar["events"], [])


if __name__ == "__main__":
    unittest.main()
