from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from mirsad.engines.mt5_chart_candles import MT5ChartCandleHistory


def make_payload(*, captured_at_ms: int | None = None) -> dict:
    now = int(time.time() * 1000) if captured_at_ms is None else captured_at_ms
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
        "schema": "MIR-ENGINE2-CANDLES-1",
        "captured_at_utc_ms": now,
        "terminal_connected": True,
        "broker_symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
        "time_basis": "UTC_NORMALIZED_FROM_MT5_SERVER_TIME",
        "timeframes": frames,
    }


class MT5ChartCandleHistoryTests(unittest.TestCase):
    def _engine(self, directory: str) -> MT5ChartCandleHistory:
        return MT5ChartCandleHistory(common_files=directory)

    def _write(self, directory: str, payload: dict) -> None:
        root = Path(directory) / "MirsadBTC" / "observer"
        root.mkdir(parents=True, exist_ok=True)
        (root / "candles.json").write_text(json.dumps(payload), encoding="utf-8")

    def _market(self) -> dict:
        return {
            "status": "LIVE", "symbol": "BTCUSDT",
            "feed_health": {"broker_symbol": "BTC", "account_server": "Headway-Demo"},
        }

    def _bridge(self) -> dict:
        return {
            "status": "CONNECTED", "symbol": "BTC", "market_symbol": "BTCUSDT",
            "account": {"server": "Headway-Demo"},
        }

    def test_engine2_reads_separate_multi_timeframe_candle_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write(directory, make_payload())
            result = self._engine(directory).collect(bridge=self._bridge(), market=self._market())
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["source"], "MT5_CHART_OBSERVER")
        self.assertEqual(result["closed_candles"]["1m"], 69)
        self.assertEqual(set(result["candles_by_tf"]), {"1m", "5m", "15m", "1h", "4h", "1d"})

    def test_engine2_candle_feed_is_blocked_when_required_history_is_short(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload()
            payload["timeframes"]["5m"]["bars"] = payload["timeframes"]["5m"]["bars"][-20:]
            payload["timeframes"]["5m"]["copied"] = 20
            self._write(directory, payload)
            result = self._engine(directory).collect()
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORY")

    def test_engine2_rejects_bad_candle_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload()
            payload["timeframes"]["1m"]["bars"][3]["high"] = 1
            self._write(directory, payload)
            result = self._engine(directory).collect()
        self.assertEqual(result["status"], "INVALID_HISTORY")

    def test_engine2_rejects_stale_candle_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload(captured_at_ms=int(time.time() * 1000) - 60_000)
            self._write(directory, payload)
            result = self._engine(directory).collect()
        self.assertEqual(result["status"], "STALE")

    def test_engine2_requires_matching_engine1_market_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write(directory, make_payload())
            market = self._market()
            market["feed_health"]["broker_symbol"] = "BTCUSD"
            result = self._engine(directory).collect(market=market)
        self.assertEqual(result["status"], "MARKET_IDENTITY_MISMATCH")

    def test_engine2_requires_matching_engine5_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write(directory, make_payload())
            bridge = self._bridge()
            bridge["account"]["server"] = "Other-Demo"
            result = self._engine(directory).collect(bridge=bridge)
        self.assertEqual(result["status"], "BRIDGE_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
