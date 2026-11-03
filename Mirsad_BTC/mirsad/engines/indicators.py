from __future__ import annotations

import math
from typing import Any

TIMEFRAME_WEIGHTS = {"1m": 1.0, "5m": 2.0, "15m": 3.0, "1h": 4.0, "4h": 5.0, "1d": 5.0}
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m")
CORE_INDICATORS = ("ema20", "ema50", "rsi14", "atr14")


def _finite_values(values: list[float]) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _ema_series(values: list[float], period: int) -> list[float | None]:
    if period < 2 or len(values) < period or not _finite_values(values):
        return [None] * len(values)
    result: list[float | None] = [None] * len(values)
    alpha = 2.0 / (period + 1)
    value = sum(values[:period]) / period
    result[period - 1] = value
    for index in range(period, len(values)):
        value = alpha * values[index] + (1 - alpha) * value
        result[index] = value if math.isfinite(value) else None
    return result


def _ema(values: list[float], period: int) -> float | None:
    series = _ema_series(values, period)
    return series[-1] if series else None


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


def _true_ranges(candles: list[dict[str, Any]]) -> list[float] | None:
    if len(candles) < 2:
        return None
    ranges: list[float] = []
    try:
        for previous, current in zip(candles[:-1], candles[1:]):
            high = float(current["high"])
            low = float(current["low"])
            previous_close = float(previous["close"])
            if not _finite_values([high, low, previous_close]) or high < low:
                return None
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return ranges


def _wilder_average(values: list[float], period: int) -> float | None:
    if period < 2 or len(values) < period or not _finite_values(values):
        return None
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = (result * (period - 1) + value) / period
    return result if math.isfinite(result) else None


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    ranges = _true_ranges(candles)
    if ranges is None:
        return None
    return _wilder_average(ranges, period)


def _rolling_mean(values: list[float], period: int) -> float | None:
    if period < 1 or len(values) < period or not _finite_values(values):
        return None
    return sum(values[-period:]) / period


def _macd(values: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float | None, float | None, float | None]:
    if fast >= slow or len(values) < slow + signal - 1 or not _finite_values(values):
        return None, None, None
    fast_series = _ema_series(values, fast)
    slow_series = _ema_series(values, slow)
    main: list[float | None] = []
    compact: list[float] = []
    for a, b in zip(fast_series, slow_series):
        value = a - b if a is not None and b is not None else None
        main.append(value)
        if value is not None:
            compact.append(value)
    signal_value = _ema(compact, signal)
    main_value = main[-1] if main else None
    osma = main_value - signal_value if main_value is not None and signal_value is not None else None
    return main_value, signal_value, osma


def _bollinger(values: list[float], period: int = 20, deviations: float = 2.0) -> tuple[float | None, float | None, float | None]:
    if period < 2 or len(values) < period or not _finite_values(values):
        return None, None, None
    window = values[-period:]
    middle = sum(window) / period
    variance = sum((value - middle) ** 2 for value in window) / period
    stddev = math.sqrt(variance)
    upper, lower = middle + deviations * stddev, middle - deviations * stddev
    if not _finite_values([middle, upper, lower]):
        return None, None, None
    return middle, upper, lower


def _stochastic(
    candles: list[dict[str, Any]],
    k_period: int = 5,
    d_period: int = 3,
    slowing: int = 3,
) -> tuple[float | None, float | None]:
    """Match MT5 iStochastic(K=5, D=3, slowing=3, MODE_SMA).

    MT5's main line is the SMA-smoothed raw %K (the slowing period), while
    the signal line is the SMA of that smoothed %K over D periods.
    """
    if (
        k_period < 1 or d_period < 1 or slowing < 1
        or len(candles) < k_period + slowing + d_period - 2
    ):
        return None, None
    try:
        raw_k: list[float] = []
        for end in range(k_period, len(candles) + 1):
            window = candles[end - k_period:end]
            highest = max(float(row["high"]) for row in window)
            lowest = min(float(row["low"]) for row in window)
            close = float(candles[end - 1]["close"])
            if not _finite_values([highest, lowest, close]) or highest < lowest:
                return None, None
            raw_k.append(50.0 if highest == lowest else 100.0 * (close - lowest) / (highest - lowest))

        slow_k = [
            sum(raw_k[index - slowing + 1:index + 1]) / slowing
            for index in range(slowing - 1, len(raw_k))
        ]
        if len(slow_k) < d_period:
            return None, None
        slow_d = sum(slow_k[-d_period:]) / d_period
        return slow_k[-1], slow_d
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, None


def _adx(candles: list[dict[str, Any]], period: int = 14) -> tuple[float | None, float | None, float | None]:
    if period < 2 or len(candles) < period * 2:
        return None, None, None
    try:
        plus_dm: list[float] = []
        minus_dm: list[float] = []
        true_ranges: list[float] = []
        for previous, current in zip(candles[:-1], candles[1:]):
            up = float(current["high"]) - float(previous["high"])
            down = float(previous["low"]) - float(current["low"])
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            high, low, previous_close = float(current["high"]), float(current["low"]), float(current["close"])
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        if not _finite_values(plus_dm + minus_dm + true_ranges) or len(true_ranges) < period * 2 - 1:
            return None, None, None

        # Seed Wilder's smoothed directional movement with the first period
        # observations, then calculate the first DX immediately.
        smoothed_tr = sum(true_ranges[:period])
        smoothed_plus = sum(plus_dm[:period])
        smoothed_minus = sum(minus_dm[:period])
        dx_values: list[float] = []
        latest_plus = latest_minus = None

        for index in range(period - 1, len(true_ranges)):
            if index >= period:
                smoothed_tr = smoothed_tr - smoothed_tr / period + true_ranges[index]
                smoothed_plus = smoothed_plus - smoothed_plus / period + plus_dm[index]
                smoothed_minus = smoothed_minus - smoothed_minus / period + minus_dm[index]
            if smoothed_tr <= 0:
                plus_di = minus_di = 0.0
            else:
                plus_di = 100.0 * smoothed_plus / smoothed_tr
                minus_di = 100.0 * smoothed_minus / smoothed_tr
            denominator = plus_di + minus_di
            dx_values.append(0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator)
            latest_plus, latest_minus = plus_di, minus_di

        adx_value = _wilder_average(dx_values, period)
        if adx_value is None or latest_plus is None or latest_minus is None:
            return None, None, None
        return adx_value, latest_plus, latest_minus
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None, None, None


def _cci(candles: list[dict[str, Any]], period: int = 20) -> float | None:
    if len(candles) < period:
        return None
    try:
        typical = [(float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0 for row in candles[-period:]]
        mean = sum(typical) / period
        deviation = sum(abs(value - mean) for value in typical) / period
        if deviation == 0:
            return 0.0
        result = (typical[-1] - mean) / (0.015 * deviation)
        return result if math.isfinite(result) else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _mfi(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) <= period:
        return None
    try:
        positive: list[float] = []
        negative: list[float] = []
        for previous, current in zip(candles[:-1], candles[1:]):
            typical_previous = (float(previous["high"]) + float(previous["low"]) + float(previous["close"])) / 3.0
            typical_current = (float(current["high"]) + float(current["low"]) + float(current["close"])) / 3.0
            volume = float(current.get("volume", current.get("tick_volume", 0.0)))
            if not _finite_values([typical_previous, typical_current, volume]) or volume < 0:
                return None
            flow = typical_current * volume
            positive.append(flow if typical_current > typical_previous else 0.0)
            negative.append(flow if typical_current < typical_previous else 0.0)
        pos, neg = sum(positive[-period:]), sum(negative[-period:])
        if neg == 0:
            return 50.0 if pos == 0 else 100.0
        ratio = pos / neg
        return 100.0 - 100.0 / (1.0 + ratio)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return None


def _momentum(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period or not _finite_values(values):
        return None
    previous = values[-period - 1]
    if previous == 0:
        return None
    result = 100.0 * values[-1] / previous
    return result if math.isfinite(result) else None


def _wpr(candles: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(candles) < period:
        return None
    try:
        window = candles[-period:]
        highest = max(float(row["high"]) for row in window)
        lowest = min(float(row["low"]) for row in window)
        close = float(window[-1]["close"])
        if not _finite_values([highest, lowest, close]) or highest < lowest:
            return None
        return -50.0 if highest == lowest else -100.0 * (highest - close) / (highest - lowest)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _obv(candles: list[dict[str, Any]]) -> float | None:
    if len(candles) < 2:
        return None
    try:
        total = 0.0
        for previous, current in zip(candles[:-1], candles[1:]):
            previous_close = float(previous["close"])
            close = float(current["close"])
            volume = float(current.get("volume", current.get("tick_volume", 0.0)))
            if not _finite_values([previous_close, close, volume]) or volume < 0:
                return None
            if close > previous_close:
                total += volume
            elif close < previous_close:
                total -= volume
        return total if math.isfinite(total) else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _calculate_timeframe_indicators(candles: list[dict[str, Any]]) -> dict[str, float | None]:
    try:
        closed = [row for row in candles if row.get("closed")]
        closes = [float(row["close"]) for row in closed]
        if not _finite_values(closes):
            raise ValueError("non-finite close")
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return {name: None for name in (
            "ema20", "ema50", "rsi14", "atr14", "macd_main", "macd_signal",
            "bollinger_middle", "bollinger_upper", "bollinger_lower",
            "stochastic_k", "stochastic_d", "adx14", "plus_di14", "minus_di14",
            "cci20", "mfi14", "momentum14", "wpr14", "obv", "osma",
        )}
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    macd_main, macd_signal, osma = _macd(closes)
    bb_middle, bb_upper, bb_lower = _bollinger(closes)
    stochastic_k, stochastic_d = _stochastic(closed)
    adx14, plus_di14, minus_di14 = _adx(closed)
    return {
        "ema20": ema20,
        "ema50": ema50,
        "rsi14": _rsi(closes),
        "atr14": _atr(closed),
        "macd_main": macd_main,
        "macd_signal": macd_signal,
        "bollinger_middle": bb_middle,
        "bollinger_upper": bb_upper,
        "bollinger_lower": bb_lower,
        "stochastic_k": stochastic_k,
        "stochastic_d": stochastic_d,
        "adx14": adx14,
        "plus_di14": plus_di14,
        "minus_di14": minus_di14,
        "cci20": _cci(closed),
        "mfi14": _mfi(closed),
        "momentum14": _momentum(closes),
        "wpr14": _wpr(closed),
        "obv": _obv(closed),
        "osma": osma,
    }


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
    """Engine 3: independent technical indicators calculated only from Engine 2 closed OHLC bars."""

    def analyze(self, chart_candles: dict[str, Any]) -> dict[str, Any]:
        base = {
            "engine": "engine_3_indicators",
            "source": "engine_2_chart_candles",
            "method": "deterministic_ohlc",
            "required_timeframes": list(REQUIRED_TIMEFRAMES),
            "indicator_catalog": [
                "ema20", "ema50", "rsi14", "atr14", "macd_main", "macd_signal",
                "bollinger_middle", "bollinger_upper", "bollinger_lower",
                "stochastic_k", "stochastic_d", "adx14", "plus_di14", "minus_di14",
                "cci20", "mfi14", "momentum14", "wpr14", "obv", "osma",
            ],
        }
        if not isinstance(chart_candles, dict) or chart_candles.get("status") != "READY":
            return {
                **base, "status": "NOT_READY",
                "reason": "Engine 2 has not supplied a fresh, validated multi-timeframe candle history.",
                "timeframes": {}, "values": {}, "indicators_by_timeframe": {},
                "trend_score": None, "last_closed_candle_time_ms": None,
            }

        candle_sets = chart_candles.get("candles_by_tf")
        if not isinstance(candle_sets, dict):
            return {
                **base, "status": "NOT_READY",
                "reason": "Engine 2 candle-history payload is missing its timeframe map.",
                "timeframes": {}, "values": {}, "indicators_by_timeframe": {},
                "trend_score": None, "last_closed_candle_time_ms": None,
            }

        timeframes = {
            timeframe: _timeframe_trend(candle_sets.get(timeframe, []))
            for timeframe in TIMEFRAME_WEIGHTS
        }
        indicators_by_timeframe = {
            timeframe: _calculate_timeframe_indicators(candle_sets.get(timeframe, []))
            for timeframe in TIMEFRAME_WEIGHTS
        }
        for timeframe in TIMEFRAME_WEIGHTS:
            timeframes[timeframe]["indicators"] = indicators_by_timeframe[timeframe]

        one = [c for c in candle_sets.get("1m", []) if c.get("closed")]
        five = [c for c in candle_sets.get("5m", []) if c.get("closed")]
        values = {
            "ema20_1m": indicators_by_timeframe["1m"]["ema20"],
            "ema50_1m": indicators_by_timeframe["1m"]["ema50"],
            "rsi14_1m": indicators_by_timeframe["1m"]["rsi14"],
            "atr14_1m": indicators_by_timeframe["1m"]["atr14"],
            "atr14_5m": indicators_by_timeframe["5m"]["atr14"],
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
            "indicators_by_timeframe": indicators_by_timeframe,
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


__all__ = [
    "TIMEFRAME_WEIGHTS",
    "REQUIRED_TIMEFRAMES",
    "CORE_INDICATORS",
    "IndicatorsEngine",
]
