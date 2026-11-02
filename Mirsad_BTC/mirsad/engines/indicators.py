from __future__ import annotations

import math
from typing import Any

TIMEFRAME_WEIGHTS = {"1m": 1.0, "5m": 2.0, "15m": 3.0, "1h": 4.0, "4h": 5.0, "1d": 5.0}
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m")


def _finite_values(values: list[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _ema(values: list[float], period: int) -> float | None:
    if period < 2 or len(values) < period or not _finite_values(values):
        return None
    alpha = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    for item in values[period:]:
        value = alpha * item + (1 - alpha) * value
    return value if math.isfinite(value) else None


def _rsi(values: list[float], period: int = 14) -> float | None:
    if period < 2 or len(values) <= period or not _finite_values(values):
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 50.0 if avg_gain == 0 else 100.0
    result = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return result if math.isfinite(result) else None


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if period < 2 or len(candles) <= period:
        return None
    ranges = []
    try:
        for previous, current in zip(candles[:-1], candles[1:]):
            high = float(current["high"])
            low = float(current["low"])
            previous_close = float(previous["close"])
            if not all(math.isfinite(value) for value in (high, low, previous_close)):
                return None
            ranges.append(max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            ))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    result = sum(ranges[-period:]) / period
    return result if math.isfinite(result) and result >= 0 else None


def _timeframe_trend(candles: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        closed = [c for c in candles if c.get("closed")]
        closes = [float(c["close"]) for c in closed]
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID", "trend": "UNKNOWN", "closed_candles": 0}
    if not _finite_values(closes):
        return {"status": "INVALID", "trend": "UNKNOWN", "closed_candles": len(closes)}
    fast, slow = _ema(closes, 20), _ema(closes, 50)
    if fast is None or slow is None:
        return {"status": "INSUFFICIENT", "trend": "UNKNOWN", "closed_candles": len(closes)}
    last = closes[-1]
    trend = "BULLISH" if fast > slow and last > fast else (
        "BEARISH" if fast < slow and last < fast else "NEUTRAL"
    )
    return {
        "status": "READY", "trend": trend, "ema20": fast, "ema50": slow,
        "last_close": last, "closed_candles": len(closes),
    }


class IndicatorsEngine:
    """Engine 3: indicators are calculated exclusively from Engine 2 candle history."""

    def analyze(self, chart_candles: dict[str, Any]) -> dict[str, Any]:
        base = {
            "engine": "engine_3_indicators",
            "source": "engine_2_chart_candles",
            "method": "deterministic_ohlc",
            "required_timeframes": list(REQUIRED_TIMEFRAMES),
        }
        if not isinstance(chart_candles, dict) or chart_candles.get("status") != "READY":
            return {
                **base,
                "status": "NOT_READY",
                "reason": "Engine 2 has not supplied a fresh, validated multi-timeframe candle history.",
                "timeframes": {},
                "values": {},
                "trend_score": None,
                "last_closed_candle_time_ms": None,
            }

        candle_sets = chart_candles.get("candles_by_tf")
        if not isinstance(candle_sets, dict):
            return {
                **base,
                "status": "NOT_READY",
                "reason": "Engine 2 candle-history payload is missing its timeframe map.",
                "timeframes": {},
                "values": {},
                "trend_score": None,
                "last_closed_candle_time_ms": None,
            }

        timeframes = {
            timeframe: _timeframe_trend(candle_sets.get(timeframe, []))
            for timeframe in TIMEFRAME_WEIGHTS
        }
        one = [c for c in candle_sets.get("1m", []) if c.get("closed")]
        five = [c for c in candle_sets.get("5m", []) if c.get("closed")]
        closes: list[float] = []
        try:
            closes = [float(c["close"]) for c in one]
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
        values = {
            "ema20_1m": _ema(closes, 20),
            "ema50_1m": _ema(closes, 50),
            "rsi14_1m": _rsi(closes),
            "atr14_1m": _atr(one),
            "atr14_5m": _atr(five),
        }
        missing_timeframes = [
            timeframe for timeframe in REQUIRED_TIMEFRAMES
            if timeframes[timeframe]["status"] != "READY"
        ]
        missing_values = [
            name for name, value in values.items()
            if value is None or not math.isfinite(float(value))
        ]
        weighted = 0.0
        weight_total = 0.0
        for timeframe, weight in TIMEFRAME_WEIGHTS.items():
            row = timeframes[timeframe]
            if row["status"] != "READY":
                continue
            weight_total += weight
            weighted += weight * (
                1 if row["trend"] == "BULLISH"
                else -1 if row["trend"] == "BEARISH"
                else 0
            )
        trend_score = weighted / weight_total if weight_total else None
        ready = not missing_timeframes and not missing_values and trend_score is not None
        last_time = None
        if one:
            try:
                last_time = int(one[-1]["open_time_ms"])
            except (KeyError, TypeError, ValueError, OverflowError):
                last_time = None
        return {
            **base,
            "status": "READY" if ready and last_time is not None else "NOT_READY",
            "source_capture_at_ms": chart_candles.get("captured_at_ms"),
            "primary_venue": "MT5 Broker",
            "timeframes": timeframes,
            "values": values,
            "trend_score": trend_score,
            "missing_timeframes": missing_timeframes,
            "missing_values": missing_values,
            "closed_candles": {"1m": len(one), "5m": len(five)},
            "last_closed_candle_time_ms": last_time,
            "reason": None if ready and last_time is not None else (
                "Engine 2 completed OHLC history is insufficient for required indicators/timeframes."
            ),
        }
