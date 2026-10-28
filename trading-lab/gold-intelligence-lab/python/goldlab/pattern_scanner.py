"""Rule-based chart-structure scanner using supplied CLOSED OHLC bars only.

Detects context, not trade instructions: trend state, ATR regime, confirmed
swings, approximate support/resistance clusters, closing-bar breakouts,
engulfing candles, and double-top/bottom candidates. It never places orders.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .technical_rating import DataQualityError, TechnicalRatingError

SCAN_TIMEFRAME_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600}


def _validate_bars(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe not in SCAN_TIMEFRAME_SECONDS:
        raise TechnicalRatingError("Unsupported timeframe. Choose M1, M5, M15, M30 or H1.")
    if not isinstance(frame, pd.DataFrame):
        raise DataQualityError("Scanner input must be a pandas DataFrame.")
    if frame.empty:
        raise DataQualityError("No closed bars were supplied to the chart scanner.")
    names = {str(name).strip().lower(): name for name in frame.columns}
    missing = [name for name in ("open", "high", "low", "close") if name not in names]
    if missing:
        raise DataQualityError("Scanner input is missing: " + ", ".join(missing))
    data = pd.DataFrame({
        key: pd.to_numeric(frame[names[key]].reset_index(drop=True), errors="raise")
        for key in ("open", "high", "low", "close")
    })
    values = data[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise DataQualityError("Scanner input contains missing or non-finite OHLC values.")
    if (data[["open", "high", "low", "close"]] <= 0).any().any():
        raise DataQualityError("Scanner received a non-positive gold price.")
    if (data["high"] < data[["open", "close"]].max(axis=1) - 1e-12).any():
        raise DataQualityError("Candle high is below its open or close.")
    if (data["low"] > data[["open", "close"]].min(axis=1) + 1e-12).any():
        raise DataQualityError("Candle low is above its open or close.")
    if (data["high"] < data["low"]).any():
        raise DataQualityError("Candle high is below its low.")
    time_col = next((names[key] for key in ("time", "timestamp", "datetime") if key in names), None)
    if time_col is not None:
        raw = frame[time_col].reset_index(drop=True)
        try:
            parsed = (
                pd.to_datetime(raw, unit="s", utc=True, errors="raise")
                if pd.api.types.is_numeric_dtype(raw)
                else pd.to_datetime(raw, utc=True, errors="raise")
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise DataQualityError(f"Invalid scanner timestamp: {exc}") from exc
        if parsed.isna().any() or parsed.duplicated().any():
            raise DataQualityError("Scanner timestamps contain missing or duplicate values.")
        if not parsed.is_monotonic_increasing:
            raise DataQualityError("Scanner bars must be ordered oldest-to-newest; input was not silently sorted.")
        data["time"] = parsed
    return data


def _wilder_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = np.full(len(close), np.nan, dtype=float)
    if len(close) > 1:
        tr[1:] = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
    atr = np.full(len(close), np.nan, dtype=float)
    valid = np.flatnonzero(np.isfinite(tr))
    if len(valid) < period:
        return atr
    seed_index = int(valid[period - 1])
    previous = float(np.mean(tr[valid[:period]]))
    atr[seed_index] = previous
    for i in range(seed_index + 1, len(close)):
        if np.isfinite(tr[i]):
            previous = (previous * (period - 1) + tr[i]) / period
        atr[i] = previous
    return atr


def _timestamp(data: pd.DataFrame, index: int) -> str | None:
    if "time" not in data:
        return None
    value = data["time"].iloc[index]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _confirmed_pivots(
    high: np.ndarray, low: np.ndarray, data: pd.DataFrame, left: int, right: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    highs: list[dict[str, Any]] = []
    lows: list[dict[str, Any]] = []
    for i in range(left, len(high) - right):
        high_window = high[i - left : i + right + 1]
        low_window = low[i - left : i + right + 1]
        if high[i] == float(np.max(high_window)) and int(np.count_nonzero(high_window == high[i])) == 1:
            highs.append({"index": i, "price": float(high[i]), "time": _timestamp(data, i)})
        if low[i] == float(np.min(low_window)) and int(np.count_nonzero(low_window == low[i])) == 1:
            lows.append({"index": i, "price": float(low[i]), "time": _timestamp(data, i)})
    return highs, lows


def _zones(
    pivots: list[dict[str, Any]], *, current: float, tolerance: float, side: str, limit: int = 6
) -> list[dict[str, Any]]:
    eligible = [
        p for p in pivots
        if (p["price"] < current if side == "support" else p["price"] > current)
    ]
    eligible.sort(key=lambda p: p["price"])
    groups: list[list[dict[str, Any]]] = []
    for pivot in eligible:
        if groups:
            centre = float(np.mean([item["price"] for item in groups[-1]]))
            if abs(float(pivot["price"]) - centre) <= tolerance:
                groups[-1].append(pivot)
                continue
        groups.append([pivot])
    result = []
    for group in groups:
        level = float(np.mean([item["price"] for item in group]))
        ordered_by_time = sorted(group, key=lambda p: p["index"])
        result.append({
            "level": level,
            "lower": float(min(p["price"] for p in group)),
            "upper": float(max(p["price"] for p in group)),
            "touches": len(group),
            "first_touch_utc": ordered_by_time[0]["time"],
            "last_touch_utc": ordered_by_time[-1]["time"],
            "method": "cluster of confirmed swing " + ("lows" if side == "support" else "highs"),
        })
    result.sort(key=lambda z: abs(z["level"] - current))
    return result[:limit]


def scan_market_structure(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    tick_size: float | None = None,
    lookback: int = 120,
    swing_left: int = 3,
    swing_right: int = 2,
) -> dict[str, Any]:
    """Return descriptive chart structure from closed bars; no entries or orders."""
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 20:
        raise ValueError("lookback must be an integer of at least 20 closed bars.")
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in (swing_left, swing_right)):
        raise ValueError("swing_left and swing_right must be positive integers.")
    if tick_size is not None and (not math.isfinite(float(tick_size)) or float(tick_size) <= 0):
        raise ValueError("tick_size must be finite and positive when supplied.")
    data = _validate_bars(frame, timeframe)
    minimum = max(lookback + 1, swing_left + swing_right + 5, 40)
    if len(data) < minimum:
        raise DataQualityError(f"Scanner needs at least {minimum} closed bars; received {len(data)}.")

    o = data["open"].to_numpy(dtype=float)
    h = data["high"].to_numpy(dtype=float)
    l = data["low"].to_numpy(dtype=float)
    c = data["close"].to_numpy(dtype=float)
    n = len(data)
    current = float(c[-1])
    ema20 = pd.Series(c).ewm(span=20, adjust=False, min_periods=1).mean().to_numpy()
    ema50 = pd.Series(c).ewm(span=50, adjust=False, min_periods=1).mean().to_numpy()
    if ema20[-1] > ema50[-1] and current > ema20[-1]:
        trend_state, trend_ar = "bullish", "اتجاه صاعد مبدئي"
    elif ema20[-1] < ema50[-1] and current < ema20[-1]:
        trend_state, trend_ar = "bearish", "اتجاه هابط مبدئي"
    else:
        trend_state, trend_ar = "mixed", "اتجاه مختلط أو غير محسوم"

    atr_values = _wilder_atr(h, l, c, 14)
    atr_now = float(atr_values[-1]) if np.isfinite(atr_values[-1]) else None
    atr_history = atr_values[np.isfinite(atr_values)][-100:]
    atr_median = float(np.median(atr_history)) if len(atr_history) else None
    atr_ratio = atr_now / atr_median if atr_now is not None and atr_median and atr_median > 0 else None
    if atr_ratio is None:
        atr_state, atr_ar = "unavailable", "التذبذب غير متاح"
    elif atr_ratio >= 1.35:
        atr_state, atr_ar = "elevated", "تذبذب أعلى من خطه المرجعي"
    elif atr_ratio <= 0.75:
        atr_state, atr_ar = "quiet", "تذبذب أدنى من خطه المرجعي"
    else:
        atr_state, atr_ar = "normal", "تذبذب قريب من خطه المرجعي"

    base_tolerance = (float(tick_size) * 3.0) if tick_size else current * 1e-5
    tolerance = max(base_tolerance, (atr_now * 0.25) if atr_now is not None else 0.0)
    pivot_highs, pivot_lows = _confirmed_pivots(h, l, data, swing_left, swing_right)
    cut = max(0, n - lookback - swing_right)
    recent_highs = [p for p in pivot_highs if p["index"] >= cut]
    recent_lows = [p for p in pivot_lows if p["index"] >= cut]
    support_zones = _zones(recent_lows, current=current, tolerance=tolerance, side="support")
    resistance_zones = _zones(recent_highs, current=current, tolerance=tolerance, side="resistance")

    setups: list[dict[str, Any]] = []
    prior_high = float(np.max(h[-lookback - 1 : -1]))
    prior_low = float(np.min(l[-lookback - 1 : -1]))
    if current > prior_high:
        setups.append({
            "type": "closing-bar breakout", "direction": "bullish",
            "status": "confirmed_on_closed_bar",
            "reason_ar": f"إغلاق الشمعة المكتملة تجاوز أعلى قمة في {lookback} شموع سابقة، مع استبعاد شمعة الإشارة من مستوى المقارنة.",
            "reference_level": prior_high, "invalidation_level": prior_high,
        })
    elif current < prior_low:
        setups.append({
            "type": "closing-bar breakout", "direction": "bearish",
            "status": "confirmed_on_closed_bar",
            "reason_ar": f"إغلاق الشمعة المكتملة كسر أدنى قاع في {lookback} شموع سابقة، مع استبعاد شمعة الإشارة من مستوى المقارنة.",
            "reference_level": prior_low, "invalidation_level": prior_low,
        })

    if n >= 2:
        if c[-2] < o[-2] and c[-1] > o[-1] and o[-1] <= c[-2] and c[-1] >= o[-2]:
            setups.append({
                "type": "engulfing candle", "direction": "bullish",
                "status": "confirmed_on_closed_bar",
                "reason_ar": "جسم الشمعة الصاعدة المكتملة احتوى جسم الشمعة الهابطة السابقة.",
                "reference_level": float(c[-2]), "invalidation_level": float(l[-1]),
            })
        elif c[-2] > o[-2] and c[-1] < o[-1] and o[-1] >= c[-2] and c[-1] <= o[-2]:
            setups.append({
                "type": "engulfing candle", "direction": "bearish",
                "status": "confirmed_on_closed_bar",
                "reason_ar": "جسم الشمعة الهابطة المكتملة احتوى جسم الشمعة الصاعدة السابقة.",
                "reference_level": float(c[-2]), "invalidation_level": float(h[-1]),
            })

    if len(recent_highs) >= 2:
        p1, p2 = sorted(recent_highs, key=lambda p: p["index"])[-2:]
        if p2["index"] - p1["index"] >= swing_left + swing_right + 1 and abs(p1["price"] - p2["price"]) <= tolerance:
            valley_index = p1["index"] + int(np.argmin(l[p1["index"] + 1 : p2["index"]]))
            valley = float(l[valley_index])
            broken = current < valley
            setups.append({
                "type": "double-top candidate", "direction": "bearish",
                "status": "confirmed_breakdown" if broken else "candidate_unconfirmed",
                "reason_ar": (
                    "تكوّن قمتان متقاربتان واُغلق السعر أسفل القاع الفاصل بينهما."
                    if broken else
                    "تكوّنت قمتان متقاربتان؛ لا يُعد النموذج مؤكدًا قبل إغلاق أسفل القاع الفاصل."
                ),
                "reference_level": valley,
                "invalidation_level": max(p1["price"], p2["price"]) + tolerance,
            })

    if len(recent_lows) >= 2:
        p1, p2 = sorted(recent_lows, key=lambda p: p["index"])[-2:]
        if p2["index"] - p1["index"] >= swing_left + swing_right + 1 and abs(p1["price"] - p2["price"]) <= tolerance:
            peak_index = p1["index"] + int(np.argmax(h[p1["index"] + 1 : p2["index"]]))
            peak = float(h[peak_index])
            broken = current > peak
            setups.append({
                "type": "double-bottom candidate", "direction": "bullish",
                "status": "confirmed_breakout" if broken else "candidate_unconfirmed",
                "reason_ar": (
                    "تكوّن قاعان متقاربان واُغلق السعر أعلى القمة الفاصلة بينهما."
                    if broken else
                    "تكوّن قاعان متقاربان؛ لا يُعد النموذج مؤكدًا قبل إغلاق أعلى القمة الفاصلة."
                ),
                "reference_level": peak,
                "invalidation_level": min(p1["price"], p2["price"]) - tolerance,
            })

    return {
        "engine": "Gold Intelligence Lab chart-structure scanner",
        "version": "0.1.0",
        "mode": "analysis_only",
        "timeframe": timeframe,
        "bar_time_utc": _timestamp(data, n - 1),
        "bars_received": int(n),
        "latest_closed_close": current,
        "trend": {
            "state": trend_state, "state_ar": trend_ar,
            "ema20": float(ema20[-1]), "ema50": float(ema50[-1]),
            "reason_ar": "اتجاه وصفي من EMA20 وEMA50 وإغلاق آخر شمعة مكتملة؛ ليس إشارة دخول.",
        },
        "volatility": {
            "atr14": atr_now, "atr_median_recent": atr_median,
            "atr_ratio": atr_ratio, "state": atr_state, "state_ar": atr_ar,
        },
        "parameters": {
            "lookback": lookback, "swing_left": swing_left, "swing_right": swing_right,
            "level_tolerance": tolerance, "tick_size": tick_size,
        },
        "confirmed_swings": {
            "highs": sorted(recent_highs, key=lambda p: p["index"])[-6:],
            "lows": sorted(recent_lows, key=lambda p: p["index"])[-6:],
            "confirmation_rule_ar": "يُسجّل المحور بعد اكتمال عدد شموع اليمين؛ لذلك لا يستخدم محورًا غير مؤكد.",
        },
        "support_zones": support_zones,
        "resistance_zones": resistance_zones,
        "nearest_support": support_zones[0] if support_zones else None,
        "nearest_resistance": resistance_zones[0] if resistance_zones else None,
        "setups": setups,
        "limitations_ar": [
            "هذه مستويات تقريبية مجمعة من محاور مؤكدة، وليست مناطق يضمن السعر احترامها.",
            "الأنماط والاختراقات وصف للسعر بعد إغلاق الشمعة؛ لا توفر سعر دخول أو وقف تداول معتمدًا.",
            "الماسح لا ينفذ أوامر ولا يحاكي صفقات؛ يجب جمع أدلته مع جودة البيانات وإدارة المخاطر قبل أي قرار منفصل.",
        ],
    }


__all__ = ["scan_market_structure"]
