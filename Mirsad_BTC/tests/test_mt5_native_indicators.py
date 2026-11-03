from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from mirsad.engines.mt5_native_indicators import (
    INDICATORS,
    MT5NativeIndicatorHistory,
)


def make_payload(*, captured_at_ms: int | None = None) -> dict:
    now = int(time.time() * 1000) if captured_at_ms is None else captured_at_ms
    frames = {}
    for index, timeframe in enumerate(("1m", "5m", "15m", "1h", "4h", "1d")):
        values = {}
        for metric_index, name in enumerate(INDICATORS):
            base = 90_000.0 + index * 100 + metric_index
            if name.startswith("rsi") or name.startswith("stochastic"):
                base = 55.0 + metric_index
            elif name.startswith("adx") or name.endswith("_di14"):
                base = 20.0 + metric_index
            elif name == "wpr14":
                base = -45.0
            values[name] = {
                "status": "READY",
                "closed": base,
                "current": base + 0.25,
                "error_code": 0,
            }
        frames[timeframe] = {
            "closed_bar_time_utc_ms": now - 60_000,
            "forming_bar_time_utc_ms": now,
            "values": values,
        }
    return {
        "schema": "MIR-MT5-INDICATORS-1",
        "captured_at_utc_ms": now,
        "terminal_connected": True,
        "broker_symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
        "time_basis": "UTC_NORMALIZED_FROM_MT5_SERVER_TIME",
        "calculation_source": "MT5_NATIVE_INDICATOR_BUFFERS",
        "timeframes": frames,
    }


class MT5NativeIndicatorHistoryTests(unittest.TestCase):
    def _engine(self, directory: str) -> MT5NativeIndicatorHistory:
        return MT5NativeIndicatorHistory(common_files=directory)

    def _write(self, directory: str, payload: dict) -> None:
        root = Path(directory) / "MirsadBTC" / "observer"
        root.mkdir(parents=True, exist_ok=True)
        (root / "indicators.json").write_text(json.dumps(payload), encoding="utf-8")

    def _bridge(self) -> dict:
        return {
            "status": "CONNECTED",
            "symbol": "BTC",
            "market_symbol": "BTCUSDT",
            "account": {"server": "Headway-Demo"},
        }

    def _candles(self) -> dict:
        return {
            "status": "READY",
            "symbol": "BTCUSDT",
            "broker_symbol": "BTC",
            "account_server": "Headway-Demo",
        }

    def test_reads_native_copybuffer_values_for_all_six_timeframes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload()
            self._write(directory, payload)
            result = self._engine(directory).collect(
                bridge=self._bridge(),
                candle_history=self._candles(),
            )

        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["decision_eligible"])
        self.assertEqual(result["source"], "MT5_COPYBUFFER")
        self.assertEqual(result["ready_timeframe_count"], 6)
        self.assertEqual(result["timeframes"]["1m"]["values"]["ema20"]["closed"], 90_000.0)
        self.assertEqual(result["timeframes"]["1m"]["values"]["ema20"]["current"], 90_000.25)
        self.assertEqual(result["timeframes"]["1d"]["values"]["obv"]["status"], "READY")

    def test_forming_and_closed_values_are_kept_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write(directory, make_payload())
            result = self._engine(directory).collect()

        rsi = result["timeframes"]["5m"]["values"]["rsi14"]
        self.assertNotEqual(rsi["closed"], rsi["current"])
        self.assertLess(
            result["timeframes"]["5m"]["closed_bar_time_utc_ms"],
            result["timeframes"]["5m"]["forming_bar_time_utc_ms"],
        )

    def test_stale_native_indicator_snapshot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload(captured_at_ms=int(time.time() * 1000) - 60_000)
            self._write(directory, payload)
            result = self._engine(directory).collect()
        self.assertEqual(result["status"], "STALE")

    def test_native_indicator_identity_must_match_execution_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write(directory, make_payload())
            bridge = self._bridge()
            bridge["account"]["server"] = "Other-Demo"
            result = self._engine(directory).collect(bridge=bridge)
        self.assertEqual(result["status"], "BRIDGE_IDENTITY_MISMATCH")

    def test_native_indicator_identity_must_match_engine2_candles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._write(directory, make_payload())
            candles = self._candles()
            candles["broker_symbol"] = "BTCUSD"
            result = self._engine(directory).collect(candle_history=candles)
        self.assertEqual(result["status"], "CANDLE_IDENTITY_MISMATCH")

    def test_missing_required_metrics_yield_partial_not_false_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload()
            for timeframe in ("1m", "5m", "15m"):
                payload["timeframes"][timeframe]["values"]["rsi14"]["status"] = "UNAVAILABLE"
                payload["timeframes"][timeframe]["values"]["rsi14"]["closed"] = None
                payload["timeframes"][timeframe]["values"]["rsi14"]["current"] = None
            self._write(directory, payload)
            result = self._engine(directory).collect()
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["missing_required_timeframes"], ["1m", "5m", "15m"])

    def test_invalid_numeric_indicator_is_not_passed_through(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = make_payload()
            payload["timeframes"]["1m"]["values"]["cci20"]["current"] = "NaN"
            self._write(directory, payload)
            result = self._engine(directory).collect()
        cci = result["timeframes"]["1m"]["values"]["cci20"]
        self.assertEqual(cci["status"], "INVALID")
        self.assertIsNone(cci["current"])


if __name__ == "__main__":
    unittest.main()
