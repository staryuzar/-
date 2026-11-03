from __future__ import annotations

import unittest

from scripts.validate_engine3_mt5_indicator_parity import validate
from mirsad.engines.indicators import _calculate_timeframe_indicators


TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")


def make_snapshots() -> tuple[dict, dict]:
    candle_frames = {}
    native_frames = {}
    for frame_index, timeframe in enumerate(TIMEFRAMES):
        bars = []
        for index in range(70):
            close = 100.0 + frame_index * 10 + index * 0.37 + (index % 5) * 0.11
            bars.append({
                "open_time_ms": 1_700_000_000_000 + index * 60_000,
                "open": close - 0.08,
                "high": close + 0.9 + (index % 3) * 0.07,
                "low": close - 0.8 - (index % 4) * 0.05,
                "close": close,
                "volume": float(10 + index % 7),
                "closed": True,
            })
        forming = dict(bars[-1])
        forming["open_time_ms"] += 60_000
        forming["close"] += 0.2
        forming["high"] += 0.3
        forming["closed"] = False
        bars.append(forming)
        candle_frames[timeframe] = {"copied": len(bars), "error_code": 0, "bars": bars}

        calculated = _calculate_timeframe_indicators(bars)
        native_values = {}
        for name, value in calculated.items():
            native_values[name] = {
                "status": "READY",
                "previous_closed": value,
                "closed": value,
                "current": value,
            }
        previous, current = [bar for bar in bars if bar["closed"]][-2:]
        delta = (
            current["volume"] if current["close"] > previous["close"]
            else -current["volume"] if current["close"] < previous["close"]
            else 0.0
        )
        native_values["obv"]["previous_closed"] = calculated["obv"] - delta
        native_frames[timeframe] = {
            "closed_bar_time_utc_ms": bars[-2]["open_time_ms"],
            "forming_bar_time_utc_ms": bars[-1]["open_time_ms"],
            "values": native_values,
        }

    candles = {
        "schema": "MIR-ENGINE2-CANDLES-1",
        "broker_symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
        "timeframes": candle_frames,
    }
    native = {
        "schema": "MIR-MT5-INDICATORS-1",
        "broker_symbol": "BTC",
        "market_symbol": "BTCUSDT",
        "account": {"server": "Headway-Demo"},
        "timeframes": native_frames,
    }
    return candles, native


class Engine3MT5ParityTests(unittest.TestCase):
    def test_same_closed_bars_pass_all_twenty_metrics_on_six_timeframes(self) -> None:
        candles, native = make_snapshots()
        result = validate(candles, native)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["passed_metrics"], 120)
        self.assertEqual(result["total_metrics"], 120)

    def test_native_indicator_mismatch_fails_parity(self) -> None:
        candles, native = make_snapshots()
        native["timeframes"]["5m"]["values"]["rsi14"]["closed"] += 10.0
        result = validate(candles, native)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("5m: rsi14" in failure for failure in result["failures"]))

    def test_closed_bar_timestamp_mismatch_fails_parity(self) -> None:
        candles, native = make_snapshots()
        native["timeframes"]["15m"]["closed_bar_time_utc_ms"] += 60_000
        result = validate(candles, native)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("15m: Closed-bar timestamp mismatch" in failure for failure in result["failures"]))


if __name__ == "__main__":
    unittest.main()
