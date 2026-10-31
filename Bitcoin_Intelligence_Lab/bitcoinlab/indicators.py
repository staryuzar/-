from __future__ import annotations

import math
from typing import Sequence

from .models import Bar


def _period(period: int) -> int:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")
    return period


def ema(values: Sequence[float], period: int) -> list[float | None]:
    period = _period(period)
    if len(values) < period:
        return [None] * len(values)
    if any(not math.isfinite(float(x)) for x in values):
        raise ValueError("EMA inputs must be finite")
    out: list[float | None] = [None] * (period - 1)
    current = sum(float(x) for x in values[:period]) / period
    out.append(current)
    alpha = 2.0 / (period + 1.0)
    for value in values[period:]:
        current = alpha * float(value) + (1.0 - alpha) * current
        out.append(current)
    return out


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    result: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        tr = bar.high - bar.low
        if previous_close is not None:
            tr = max(tr, abs(bar.high - previous_close), abs(bar.low - previous_close))
        result.append(tr)
        previous_close = bar.close
    return result


def atr(bars: Sequence[Bar], period: int = 14) -> float | None:
    period = _period(period)
    ranges = true_ranges(bars)
    if len(ranges) < period:
        return None
    value = sum(ranges[:period]) / period
    for item in ranges[period:]:
        value = ((period - 1) * value + item) / period
    return value


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    period = _period(period)
    if len(values) <= period:
        return None
    deltas = [float(values[i]) - float(values[i - 1]) for i in range(1, len(values))]
    if any(not math.isfinite(x) for x in deltas):
        raise ValueError("RSI inputs must be finite")
    gains = [max(x, 0.0) for x in deltas]
    losses = [max(-x, 0.0) for x in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = ((period - 1) * avg_gain + gain) / period
        avg_loss = ((period - 1) * avg_loss + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def technical_profile(bars: Sequence[Bar], *, breakout_period: int = 20) -> dict:
    completed = [bar for bar in bars if bar.is_closed]
    if len(completed) < max(60, breakout_period + 2):
        return {"status": "incomplete", "score": None, "reason": "Insufficient completed bars."}
    times = [bar.open_time_ms for bar in completed]
    if times != sorted(times) or len(set(times)) != len(times):
        return {"status": "invalid", "score": None, "reason": "Duplicate or unordered candles."}
    closes = [bar.close for bar in completed]
    fast = ema(closes, 20)[-1]
    slow = ema(closes, 50)[-1]
    atr_value = atr(completed, 14)
    rsi_value = rsi(closes, 14)
    if fast is None or slow is None or atr_value is None or rsi_value is None or atr_value <= 0:
        return {"status": "incomplete", "score": None, "reason": "Indicator warmup incomplete."}
    last = completed[-1]
    previous = completed[-breakout_period - 1:-1]
    prior_high = max(bar.high for bar in previous)
    prior_low = min(bar.low for bar in previous)
    trend = 1.0 if last.close > fast > slow else (-1.0 if last.close < fast < slow else 0.0)
    momentum = max(-1.0, min(1.0, (rsi_value - 50.0) / 25.0))
    breakout = 1.0 if last.close > prior_high else (-1.0 if last.close < prior_low else 0.0)
    score = max(-1.0, min(1.0, 0.55 * trend + 0.30 * momentum + 0.15 * breakout))
    state = "bullish" if score >= 0.2 else ("bearish" if score <= -0.2 else "mixed")
    return {
        "status": "ok", "score": score, "state": state, "close": last.close,
        "ema20": fast, "ema50": slow, "atr14": atr_value, "rsi14": rsi_value,
        "breakout": "up" if breakout > 0 else ("down" if breakout < 0 else "none"),
        "prior_high": prior_high, "prior_low": prior_low,
        "evidence": ["completed_bars_only", "ema_alignment", "rsi_momentum", "closed_bar_range_break"],
    }
