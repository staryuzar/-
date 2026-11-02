from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from mirsad.engines.mt5_market import MT5MarketDataEngine


def make_snapshot(*, captured_at_ms: int | None = None) -> dict:
    now = int(time.time() * 1000)
    frames = {}
    for timeframe, duration in (
        ("1m", 60_000), ("5m", 300_000), ("15m", 900_000),
        ("1h", 3_600_000), ("4h", 14_400_000), ("1d", 86_400_000),
    ):
        bars = []
        for index in range(70):
            close = 90_000.0 + index
            bars.append({
                "open_time_ms": now - (70 - index) * duration,
                "open": close - 1.0, "high": close + 2.0,
                "low": close - 2.0, "close": close,
                "volume": 10.0, "closed": index < 69,
            })
        frames[timeframe] = {"copied": len(bars), "error_code": 0, "bars": bars}
    return {
        "schema": "MIR-MT5-MARKET-1",
        "captured_at_utc_ms": captured_at_ms or now,
        "terminal_connected": True,
        "broker_symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
        "quote": {"bid": 90_000.0, "ask": 90_001.0, "tick_age_seconds": 1.0},
        "timeframes": frames,
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

    def test_reads_one_fresh_mt5_source_with_all_six_timeframes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write_snapshot(directory, make_snapshot())
            market = self._engine(directory).collect(bridge=self._bridge())
        self.assertEqual(market["status"], "LIVE")
        self.assertEqual(market["source"], "MT5_TERMINAL")
        self.assertEqual(market["venue_count"], 1)
        self.assertEqual(market["primary_venue"], "MT5 Broker")
        self.assertEqual(set(market["venues"]["MT5 Broker"]["candles_by_tf"]), {
            "1m", "5m", "15m", "1h", "4h", "1d"
        })
        self.assertEqual(market["feed_health"]["bridge_quote_check"]["status"], "MATCHED")

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

    def test_insufficient_closed_history_blocks_engine_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            payload["timeframes"]["5m"]["bars"] = payload["timeframes"]["5m"]["bars"][-20:]
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()
        self.assertEqual(market["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(market["venue_count"], 0)

    def test_bad_ohlc_geometry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_snapshot()
            payload["timeframes"]["1m"]["bars"][5]["high"] = 1.0
            self._write_snapshot(directory, payload)
            market = self._engine(directory).collect()
        self.assertEqual(market["status"], "INVALID_HISTORY")
        self.assertEqual(market["venue_count"], 0)


if __name__ == "__main__":
    unittest.main()
