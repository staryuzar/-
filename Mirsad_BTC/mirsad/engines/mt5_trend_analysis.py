from __future__ import annotations

import math
from statistics import mean, median
from typing import Any

from .chart_pattern_knowledge import analyze_candle_patterns
from .chart_structure_knowledge import analyze_chart_structure_knowledge

TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}
TIMEFRAME_WEIGHTS = {
    "1m": 1.0,
    "5m": 1.5,
    "15m": 2.5,
    "1h": 4.0,
    "4h": 5.0,
    "1d": 5.0,
}
MIN_CLOSED_BARS = 55
EMA_SLOPE_LOOKBACK = 5
ADX_PERIOD = 14
ATR_PERIOD = 14
RSI_PERIOD = 14
DIRECTION_THRESHOLD = 0.30


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _ema_series(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if period < 2 or len(values) < period:
        return output
    if not all(math.isfinite(value) for value in values):
        return output
    alpha = 2.0 / (period + 1.0)
    value = sum(values[:period]) / period
    output[period - 1] = value
    for index in range(period, len(values)):
        value = alpha * values[index] + (1.0 - alpha) * value
        output[index] = value
    return output


def _rsi_series(values: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if period < 2 or len(values) <= period:
        return output
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[:-1], values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    def to_rsi(gain: float, loss: float) -> float:
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        if gain == 0:
            return 0.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    output[period] = to_rsi(average_gain, average_loss)
    for change_index in range(period, len(gains)):
        average_gain = (average_gain * (period - 1) + gains[change_index]) / period
        average_loss = (average_loss * (period - 1) + losses[change_index]) / period
        output[change_index + 1] = to_rsi(average_gain, average_loss)
    return output


def _true_range_series(bars: list[dict[str, Any]]) -> list[float]:
    output: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        if previous_close is None:
            value = high - low
        else:
            value = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        output.append(value)
        previous_close = close
    return output


def _wilder_average_series(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if period < 2 or len(values) < period:
        return output
    current = sum(values[:period])
    output[period - 1] = current
    for index in range(period, len(values)):
        current = current - current / period + values[index]
        output[index] = current
    return output


def _atr_series(bars: list[dict[str, Any]], period: int = ATR_PERIOD) -> list[float | None]:
    true_ranges = _true_range_series(bars)
    smoothed = _wilder_average_series(true_ranges, period)
    return [
        (value / period) if value is not None else None
        for value in smoothed
    ]


def _adx_snapshot(
    bars: list[dict[str, Any]], period: int = ADX_PERIOD
) -> dict[str, float | None]:
    count = len(bars)
    if period < 2 or count < 2 * period + 1:
        return {"adx": None, "plus_di": None, "minus_di": None, "dx": None}

    true_ranges = _true_range_series(bars)
    plus_dm = [0.0] * count
    minus_dm = [0.0] * count
    for index in range(1, count):
        up_move = float(bars[index]["high"]) - float(bars[index - 1]["high"])
        down_move = float(bars[index - 1]["low"]) - float(bars[index]["low"])
        if up_move > down_move and up_move > 0:
            plus_dm[index] = up_move
        elif down_move > up_move and down_move > 0:
            minus_dm[index] = down_move

    tr_smooth = sum(true_ranges[:period])
    plus_smooth = sum(plus_dm[:period])
    minus_smooth = sum(minus_dm[:period])
    dx_values: list[float] = []
    plus_di = minus_di = dx = None

    for index in range(period - 1, count):
        if index > period - 1:
            tr_smooth = tr_smooth - tr_smooth / period + true_ranges[index]
            plus_smooth = plus_smooth - plus_smooth / period + plus_dm[index]
            minus_smooth = minus_smooth - minus_smooth / period + minus_dm[index]
        if tr_smooth <= 0:
            plus_di = minus_di = dx = 0.0
        else:
            plus_di = 100.0 * plus_smooth / tr_smooth
            minus_di = 100.0 * minus_smooth / tr_smooth
            denominator = plus_di + minus_di
            dx = (
                100.0 * abs(plus_di - minus_di) / denominator
                if denominator > 0 else 0.0
            )
        dx_values.append(float(dx))

    if len(dx_values) < period:
        return {
            "adx": None,
            "plus_di": plus_di,
            "minus_di": minus_di,
            "dx": dx,
        }
    adx = sum(dx_values[:period]) / period
    for current_dx in dx_values[period:]:
        adx = (adx * (period - 1) + current_dx) / period
    return {
        "adx": adx if math.isfinite(adx) else None,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "dx": dx,
    }


def _macd_histogram(
    closes: list[float],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> float | None:
    if len(closes) < slow_period + signal_period:
        return None
    fast = _ema_series(closes, fast_period)
    slow = _ema_series(closes, slow_period)
    macd: list[float] = []
    for fast_value, slow_value in zip(fast, slow):
        if fast_value is not None and slow_value is not None:
            macd.append(fast_value - slow_value)
    signal = _ema_series(macd, signal_period)
    if not macd or not signal or signal[-1] is None:
        return None
    value = macd[-1] - float(signal[-1])
    return value if math.isfinite(value) else None


def _direction_from_score(score: float | None) -> str:
    if score is None or not math.isfinite(score):
        return "UNKNOWN"
    if score >= DIRECTION_THRESHOLD:
        return "BULLISH"
    if score <= -DIRECTION_THRESHOLD:
        return "BEARISH"
    return "NEUTRAL"


def _structure_summary(
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    structure = analyze_chart_structure_knowledge(
        bars, last_candle_closed=True
    )
    highs = (structure.get("scales") or {}).get("swing", {}).get("swing_highs", [])
    lows = (structure.get("scales") or {}).get("swing", {}).get("swing_lows", [])

    def add_event_times(rows: list[dict[str, Any]], index_key: str) -> None:
        for row in rows:
            index = row.get(index_key)
            if isinstance(index, int) and 0 <= index < len(bars):
                row["time_utc_ms"] = bars[index]["open_time_ms"]

    for key in ("bos_choch_events", "liquidity_sweeps"):
        add_event_times(structure.get(key, []), "confirmation_index")
    for key in ("order_block_candidates",):
        add_event_times(structure.get(key, []), "break_index")

    return {
        "status": structure.get("status", "UNKNOWN"),
        "direction": structure.get("structure_direction", "UNKNOWN"),
        "swing_high_count": len(highs),
        "swing_low_count": len(lows),
        "higher_highs": bool((structure.get("scales") or {}).get("swing", {}).get("higher_highs")),
        "higher_lows": bool((structure.get("scales") or {}).get("swing", {}).get("higher_lows")),
        "lower_highs": bool((structure.get("scales") or {}).get("swing", {}).get("lower_highs")),
        "lower_lows": bool((structure.get("scales") or {}).get("swing", {}).get("lower_lows")),
        "bos_choch_events": structure.get("bos_choch_events", [])[-8:],
        "liquidity_sweeps": structure.get("liquidity_sweeps", [])[-8:],
        "equal_highs": structure.get("equal_highs", [])[-8:],
        "equal_lows": structure.get("equal_lows", [])[-8:],
        "fair_value_gaps": structure.get("fair_value_gaps", [])[-12:],
        "order_block_candidates": structure.get("order_block_candidates", [])[-8:],
        "premium_discount": structure.get("premium_discount"),
        "limitations": structure.get("limitations", []),
    }


def _patterns_summary(bars: list[dict[str, Any]]) -> dict[str, Any]:
    result = analyze_candle_patterns(bars, last_candle_closed=True)
    detected = result.get("detected", [])
    for item in detected:
        end = item.get("end_index")
        start = item.get("start_index")
        if isinstance(start, int) and 0 <= start < len(bars):
            item["start_time_utc_ms"] = bars[start]["open_time_ms"]
        if isinstance(end, int) and 0 <= end < len(bars):
            item["end_time_utc_ms"] = bars[end]["open_time_ms"]
    return {
        "status": result.get("status", "UNKNOWN"),
        "count": result.get("count", len(detected)),
        "detected": detected[-40:],
        "interpretation": "RULE_MATCH_NOT_PROBABILITY",
        "limitations": [
            "Pattern rules classify candle geometry and prior context; they do not predict returns.",
            "Every pattern here uses closed native MT5 OHLC candles only.",
            "Empirical BTC pattern precision/recall has not been established on a human-labelled independent dataset.",
        ],
    }


def _validate_frame(
    timeframe: str,
    raw_bars: Any,
    *,
    as_of_ms: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    duration = TIMEFRAME_MS[timeframe]
    if not isinstance(raw_bars, list):
        return None, {"status": "INVALID", "reason": "Candle frame must be a list."}
    if len(raw_bars) < 2:
        return None, {"status": "INSUFFICIENT", "reason": "Fewer than two native bars were supplied."}

    bars: list[dict[str, Any]] = []
    previous_time = 0
    errors: list[str] = []
    for index, raw in enumerate(raw_bars):
        if not isinstance(raw, dict):
            return None, {"status": "INVALID", "reason": f"Candle {index} is not an object."}
        try:
            stamp = int(raw["open_time_ms"])
            values = {
                key: float(raw[key])
                for key in ("open", "high", "low", "close")
            }
            volume = float(raw.get("volume", 0.0))
            closed = raw["closed"]
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, {"status": "INVALID", "reason": f"Candle {index} has incomplete OHLC/time data."}
        if stamp <= previous_time:
            return None, {"status": "INVALID", "reason": "Candle timestamps are not strictly increasing."}
        if not isinstance(closed, bool):
            return None, {"status": "INVALID", "reason": "Candle closed flag is missing or not boolean."}
        if not all(math.isfinite(value) for value in (*values.values(), volume)):
            return None, {"status": "INVALID", "reason": f"Candle {index} contains non-finite values."}
        if min(values.values()) <= 0 or volume < 0:
            return None, {"status": "INVALID", "reason": f"Candle {index} contains non-positive prices or negative tick volume."}
        if values["high"] < max(values["open"], values["close"], values["low"]):
            return None, {"status": "INVALID", "reason": f"Candle {index} has invalid High geometry."}
        if values["low"] > min(values["open"], values["close"], values["high"]):
            return None, {"status": "INVALID", "reason": f"Candle {index} has invalid Low geometry."}
        if index < len(raw_bars) - 1 and not closed:
            return None, {"status": "INVALID", "reason": "A forming candle appears before the final row."}
        if index == len(raw_bars) - 1 and closed:
            return None, {"status": "INVALID", "reason": "The newest MT5 candle must remain marked as forming."}
        bars.append({
            "open_time_ms": stamp,
            **values,
            "volume": volume,
            "closed": closed,
        })
        previous_time = stamp

    closed_bars = bars[:-1]
    if len(closed_bars) < MIN_CLOSED_BARS:
        return None, {
            "status": "INSUFFICIENT",
            "closed_bars": len(closed_bars),
            "required_closed_bars": MIN_CLOSED_BARS,
            "reason": f"At least {MIN_CLOSED_BARS} completed candles are required for EMA50 slope and indicator warm-up.",
        }

    last_close_time_ms = closed_bars[-1]["open_time_ms"] + duration
    staleness_ms = as_of_ms - last_close_time_ms
    if staleness_ms < -2_000:
        return None, {
            "status": "FUTURE_DATA",
            "last_close_time_ms": last_close_time_ms,
            "staleness_ms": staleness_ms,
            "reason": "The latest completed candle closes after the analysis cutoff.",
        }
    if staleness_ms > duration * 2:
        return None, {
            "status": "STALE",
            "last_close_time_ms": last_close_time_ms,
            "staleness_ms": staleness_ms,
            "reason": "The timeframe's latest completed candle is older than two intervals.",
        }

    gaps: list[dict[str, int]] = []
    for index, (left, right) in enumerate(zip(closed_bars[:-1], closed_bars[1:])):
        delta = right["open_time_ms"] - left["open_time_ms"]
        if delta > duration * 1.5:
            gaps.append({
                "after_closed_bar_index": index,
                "gap_duration_ms": delta,
                "estimated_missing_intervals": max(1, int(round(delta / duration)) - 1),
            })
    missing_intervals = sum(
        int(item["estimated_missing_intervals"]) for item in gaps
    )
    observed_intervals = max(1, len(closed_bars) - 1)
    gap_fraction = missing_intervals / (observed_intervals + missing_intervals)
    status = "PARTIAL" if gap_fraction > 0.03 else "READY"
    return closed_bars, {
        "status": status,
        "closed_bars": len(closed_bars),
        "forming_bar_open_time_ms": bars[-1]["open_time_ms"],
        "last_closed_bar_open_time_ms": closed_bars[-1]["open_time_ms"],
        "last_closed_bar_close_time_ms": last_close_time_ms,
        "staleness_ms": staleness_ms,
        "gap_count": len(gaps),
        "estimated_missing_intervals": missing_intervals,
        "gap_fraction": round(gap_fraction, 5),
        "gaps": gaps[-10:],
        "reason": (
            "Time gaps exceed 3% of completed intervals; this frame is diagnostic only."
            if status == "PARTIAL" else None
        ),
    }


def _analyze_timeframe(
    timeframe: str,
    bars: list[dict[str, Any]],
    frame_health: dict[str, Any],
) -> dict[str, Any]:
    closes = [float(bar["close"]) for bar in bars]
    ema20_series = _ema_series(closes, 20)
    ema50_series = _ema_series(closes, 50)
    rsi_series = _rsi_series(closes)
    atr_series = _atr_series(bars)
    adx = _adx_snapshot(bars)
    macd_hist = _macd_histogram(closes)

    ema20 = ema20_series[-1]
    ema50 = ema50_series[-1]
    atr = atr_series[-1]
    rsi = rsi_series[-1]
    close = closes[-1]
    if any(value is None for value in (ema20, ema50, atr, rsi, adx["adx"])):
        return {
            "status": "INDICATOR_WARMUP",
            "timeframe": timeframe,
            "closed_bars": len(bars),
            "reason": "One or more core indicators have insufficient warm-up history.",
        }

    ema20_value = float(ema20)
    ema50_value = float(ema50)
    atr_value = max(float(atr), 1e-12)
    rsi_value = float(rsi)
    adx_value = float(adx["adx"])
    plus_di = float(adx["plus_di"] or 0.0)
    minus_di = float(adx["minus_di"] or 0.0)
    slope_index = max(0, len(ema20_series) - 1 - EMA_SLOPE_LOOKBACK)
    slope_reference = ema20_series[slope_index]
    ema20_slope_atr = (
        (ema20_value - float(slope_reference)) / atr_value
        if slope_reference is not None else 0.0
    )
    price_vs_ema20_atr = (close - ema20_value) / atr_value
    atr_pct = atr_value / close * 100.0 if close > 0 else 0.0
    macd_hist_atr = (
        float(macd_hist) / atr_value if macd_hist is not None else None
    )

    if close > ema20_value > ema50_value:
        ema_alignment_score = 1.0
    elif close < ema20_value < ema50_value:
        ema_alignment_score = -1.0
    elif ema20_value > ema50_value:
        ema_alignment_score = 0.25
    elif ema20_value < ema50_value:
        ema_alignment_score = -0.25
    else:
        ema_alignment_score = 0.0

    if ema20_slope_atr >= 0.08:
        slope_score = 1.0
    elif ema20_slope_atr <= -0.08:
        slope_score = -1.0
    else:
        slope_score = 0.0

    di_difference = plus_di - minus_di
    di_score = 1.0 if di_difference >= 2.0 else -1.0 if di_difference <= -2.0 else 0.0
    rsi_score = 1.0 if rsi_value >= 55.0 else -1.0 if rsi_value <= 45.0 else 0.0
    macd_score = (
        1.0 if macd_hist_atr is not None and macd_hist_atr >= 0.03
        else -1.0 if macd_hist_atr is not None and macd_hist_atr <= -0.03
        else 0.0
    )

    structure = _structure_summary(bars)
    structure_score = (
        1.0 if structure["direction"] == "BULLISH"
        else -1.0 if structure["direction"] == "BEARISH"
        else 0.0
    )

    component_weights = {
        "ema_alignment": 0.25,
        "ema20_slope": 0.20,
        "directional_movement": 0.20,
        "rsi_momentum": 0.10,
        "macd_histogram": 0.10,
        "confirmed_structure": 0.15,
    }
    component_scores = {
        "ema_alignment": ema_alignment_score,
        "ema20_slope": slope_score,
        "directional_movement": di_score,
        "rsi_momentum": rsi_score,
        "macd_histogram": macd_score,
        "confirmed_structure": structure_score,
    }
    trend_score = sum(
        component_scores[name] * component_weights[name]
        for name in component_weights
    )
    direction = _direction_from_score(trend_score)

    if adx_value >= 40.0:
        strength = "VERY_STRONG"
    elif adx_value >= 25.0:
        strength = "STRONG"
    elif adx_value >= 20.0:
        strength = "DEVELOPING"
    else:
        strength = "WEAK_OR_RANGING"

    if adx_value < 18.0 and abs(trend_score) < DIRECTION_THRESHOLD:
        regime = "RANGING"
    elif adx_value >= 25.0 and abs(trend_score) >= DIRECTION_THRESHOLD:
        regime = "TRENDING"
    else:
        regime = "TRANSITIONAL"

    if atr_pct >= 4.0:
        volatility = "HIGH"
    elif atr_pct <= 0.5:
        volatility = "LOW"
    else:
        volatility = "NORMAL"

    volume_values = [float(bar.get("volume", 0.0)) for bar in bars[-21:]]
    baseline_volume = mean(volume_values[:-1]) if len(volume_values) > 1 else 0.0
    latest_tick_volume = volume_values[-1] if volume_values else 0.0
    relative_tick_volume = (
        latest_tick_volume / baseline_volume if baseline_volume > 0 else None
    )

    evidence = [
        name for name, score in component_scores.items() if score != 0.0
    ]
    return {
        "status": frame_health["status"],
        "timeframe": timeframe,
        "direction": direction,
        "trend_score": round(trend_score, 4),
        "trend_strength": strength,
        "market_regime": regime,
        "closed_bars": len(bars),
        "last_close": close,
        "last_closed_bar_open_time_ms": frame_health["last_closed_bar_open_time_ms"],
        "last_closed_bar_close_time_ms": frame_health["last_closed_bar_close_time_ms"],
        "staleness_ms": frame_health["staleness_ms"],
        "indicators": {
            "ema20": ema20_value,
            "ema50": ema50_value,
            "ema20_slope_atr_5bars": round(ema20_slope_atr, 6),
            "price_vs_ema20_atr": round(price_vs_ema20_atr, 6),
            "rsi14": round(rsi_value, 4),
            "atr14": round(atr_value, 8),
            "atr14_pct": round(atr_pct, 6),
            "adx14": round(adx_value, 4),
            "plus_di14": round(plus_di, 4),
            "minus_di14": round(minus_di, 4),
            "di_difference": round(di_difference, 4),
            "macd_histogram": round(float(macd_hist), 8) if macd_hist is not None else None,
            "macd_histogram_atr": round(macd_hist_atr, 6) if macd_hist_atr is not None else None,
            "tick_volume_latest": latest_tick_volume,
            "tick_volume_average_previous_20": round(baseline_volume, 4),
            "relative_tick_volume": round(relative_tick_volume, 4) if relative_tick_volume is not None else None,
        },
        "evidence_components": {
            name: {
                "score": component_scores[name],
                "weight": component_weights[name],
            }
            for name in component_weights
        },
        "active_evidence": evidence,
        "structure": structure,
        "patterns": _patterns_summary(bars),
        "data_quality": frame_health,
        "interpretation": "DETERMINISTIC_MULTI_FACTOR_TREND_CLASSIFICATION_NOT_A_RETURN_PROBABILITY",
        "limitations": [
            "ADX is interpreted as trend strength, not direction; +DI/-DI provide directional movement.",
            "Tick volume is the broker's tick count proxy, not consolidated traded volume.",
            "EMA/RSI/ATR/ADX thresholds are explicit engineering defaults and require independent out-of-sample calibration.",
            "A direction label describes the completed-candle evidence at the cutoff; it does not forecast a guaranteed next move.",
        ],
    }


def _native_indicator_comparison(
    frame_reports: dict[str, dict[str, Any]],
    native_indicators: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(native_indicators, dict) or native_indicators.get("status") not in {"READY", "PARTIAL"}:
        return {
            "status": "NOT_AVAILABLE",
            "source": "MT5_COPYBUFFER",
            "compared_timeframes": [],
            "reason": "Native CopyBuffer indicators were not supplied; OHLC-derived analysis remains available.",
        }
    rows: dict[str, Any] = {}
    compared: list[str] = []
    for timeframe, report in frame_reports.items():
        native_frame = (native_indicators.get("timeframes") or {}).get(timeframe)
        if not isinstance(native_frame, dict) or native_frame.get("status") != "READY":
            rows[timeframe] = {"status": "NOT_AVAILABLE"}
            continue
        native_values = native_frame.get("values") or {}
        computed = report.get("indicators") or {}
        try:
            native_time = int(native_frame["closed_bar_time_utc_ms"])
            candle_time = int(report["last_closed_bar_open_time_ms"])
        except (KeyError, TypeError, ValueError, OverflowError):
            rows[timeframe] = {"status": "INVALID_TIMESTAMP"}
            continue
        if native_time != candle_time:
            rows[timeframe] = {
                "status": "BAR_TIME_MISMATCH",
                "native_closed_bar_time_utc_ms": native_time,
                "ohlc_closed_bar_open_time_utc_ms": candle_time,
            }
            continue
        comparisons: dict[str, Any] = {}
        specifications = {
            "ema20": ("ema20", "relative", 0.001),
            "ema50": ("ema50", "relative", 0.001),
            "rsi14": ("rsi14", "absolute", 2.0),
            "atr14": ("atr14", "relative", 0.15),
        }
        for native_name, (computed_name, mode, threshold) in specifications.items():
            native_item = native_values.get(native_name)
            native_value = (
                _finite(native_item.get("closed"))
                if isinstance(native_item, dict) and native_item.get("status") == "READY"
                else None
            )
            computed_value = _finite(computed.get(computed_name))
            if native_value is None or computed_value is None:
                comparisons[native_name] = {"status": "UNAVAILABLE"}
                continue
            difference = abs(computed_value - native_value)
            normalized = (
                difference / max(abs(native_value), 1e-12)
                if mode == "relative" else difference
            )
            comparisons[native_name] = {
                "status": "WITHIN_TOLERANCE" if normalized <= threshold else "DIVERGENT",
                "computed_from_ohlc": computed_value,
                "native_copybuffer": native_value,
                "absolute_difference": difference,
                "normalized_difference": normalized,
                "comparison_mode": mode,
                "tolerance": threshold,
            }
        rows[timeframe] = {
            "status": (
                "WITHIN_TOLERANCE"
                if all(item.get("status") == "WITHIN_TOLERANCE" for item in comparisons.values())
                else "DIVERGENT_OR_PARTIAL"
            ),
            "closed_bar_time_utc_ms": candle_time,
            "indicators": comparisons,
        }
        compared.append(timeframe)
    return {
        "status": "COMPARED" if compared else "NO_ALIGNED_FRAMES",
        "source": "MT5_COPYBUFFER",
        "compared_timeframes": compared,
        "timeframes": rows,
        "interpretation": "Parity is a diagnostic cross-check only and does not override OHLC-derived values.",
    }


def analyze_mt5_native_trend(
    candle_history: dict[str, Any],
    *,
    native_indicators: dict[str, Any] | None = None,
    multi_timeframe_structure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify BTC trend using timestamped, completed MT5 OHLC across six periods.

    The result is an explainable descriptive analysis. It never authorizes orders,
    sizes positions, or presents heuristic evidence as a probability.
    """
    blocked = {
        "engine": "engine_2_native_market_analysis",
        "schema": "MIR-ENGINE2-NATIVE-ANALYSIS-1",
        "source": "MT5_COPYRATES_CLOSED_BARS",
        "status": "NOT_READY",
        "decision_eligible": False,
        "direction": "UNKNOWN",
        "trend_score": None,
        "timeframes": {},
        "reason": None,
    }
    if not isinstance(candle_history, dict) or candle_history.get("status") != "READY":
        return {
            **blocked,
            "reason": "Engine 2 needs a fresh, identity-validated MT5 candle history before classifying direction.",
            "candle_history_status": (
                candle_history.get("status") if isinstance(candle_history, dict) else None
            ),
        }
    frames = candle_history.get("candles_by_tf")
    if not isinstance(frames, dict):
        return {**blocked, "status": "INVALID", "reason": "The Engine 2 candle timeframe map is missing."}
    try:
        as_of_ms = int(candle_history["captured_at_ms"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {**blocked, "status": "INVALID", "reason": "The candle snapshot cutoff timestamp is missing."}
    if as_of_ms <= 0:
        return {**blocked, "status": "INVALID", "reason": "The candle snapshot cutoff timestamp is invalid."}

    frame_reports: dict[str, dict[str, Any]] = {}
    frame_health: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for timeframe, duration in TIMEFRAME_MS.items():
        bars, health = _validate_frame(
            timeframe, frames.get(timeframe), as_of_ms=as_of_ms
        )
        frame_health[timeframe] = health
        if bars is None:
            errors[timeframe] = str(health.get("reason", health.get("status")))
            frame_reports[timeframe] = {
                "status": health.get("status", "NOT_READY"),
                "direction": "UNKNOWN",
                "reason": health.get("reason"),
                "data_quality": health,
            }
            continue
        try:
            frame_reports[timeframe] = _analyze_timeframe(
                timeframe, bars, health
            )
            if health.get("status") == "PARTIAL":
                errors[timeframe] = str(health.get("reason"))
        except (TypeError, ValueError, OverflowError, KeyError) as exc:
            errors[timeframe] = f"{type(exc).__name__}: {exc}"
            frame_reports[timeframe] = {
                "status": "ERROR",
                "direction": "UNKNOWN",
                "reason": errors[timeframe],
            }

    eligible = [
        timeframe for timeframe, report in frame_reports.items()
        if report.get("status") == "READY"
    ]
    directional = {
        timeframe: report["direction"]
        for timeframe, report in frame_reports.items()
        if report.get("status") == "READY"
        and report.get("direction") in {"BULLISH", "BEARISH", "NEUTRAL"}
    }
    weights = {
        timeframe: TIMEFRAME_WEIGHTS[timeframe]
        for timeframe in directional
    }
    weight_total = sum(weights.values())
    weighted_score = (
        sum(
            weights[timeframe] * float(frame_reports[timeframe]["trend_score"])
            for timeframe in directional
        ) / weight_total
        if weight_total > 0 else None
    )
    overall_direction = _direction_from_score(weighted_score)

    short_frames = [tf for tf in ("1m", "5m", "15m") if tf in directional]
    higher_frames = [tf for tf in ("15m", "1h", "4h", "1d") if tf in directional]

    def weighted_subset_score(names: list[str]) -> float | None:
        denominator = sum(TIMEFRAME_WEIGHTS[name] for name in names)
        if denominator <= 0:
            return None
        return sum(
            TIMEFRAME_WEIGHTS[name] * float(frame_reports[name]["trend_score"])
            for name in names
        ) / denominator

    short_score = weighted_subset_score(short_frames)
    higher_score = weighted_subset_score(higher_frames)
    short_direction = _direction_from_score(short_score)
    higher_direction = _direction_from_score(higher_score)

    bullish = [tf for tf, direction in directional.items() if direction == "BULLISH"]
    bearish = [tf for tf, direction in directional.items() if direction == "BEARISH"]
    neutral = [tf for tf, direction in directional.items() if direction == "NEUTRAL"]
    disagreement = bool(bullish and bearish)
    required_higher_context = ("15m" in eligible and "1h" in eligible
                               and bool({"4h", "1d"} & set(eligible)))
    enough_frames = len(eligible) >= 4
    analysis_ready = enough_frames and required_higher_context
    alignment = (
        "MIXED_TIMEFRAME_DIRECTIONS" if disagreement
        else "BULLISH_TIMEFRAME_CONFLUENCE" if bullish and not bearish and len(bullish) >= 3
        else "BEARISH_TIMEFRAME_CONFLUENCE" if bearish and not bullish and len(bearish) >= 3
        else "PARTIAL_OR_NEUTRAL_ALIGNMENT"
    )
    directional_count = len(bullish) + len(bearish)
    agreement_ratio = (
        max(len(bullish), len(bearish)) / directional_count
        if directional_count else 0.0
    )
    available_weight = weight_total
    all_weight = sum(TIMEFRAME_WEIGHTS.values())
    weight_coverage = available_weight / all_weight if all_weight else 0.0

    per_frame_strengths = [
        frame_reports[timeframe]["indicators"]["adx14"]
        for timeframe in eligible
        if isinstance(frame_reports[timeframe].get("indicators"), dict)
    ]
    average_adx = mean(per_frame_strengths) if per_frame_strengths else None
    if average_adx is None:
        market_regime = "UNKNOWN"
    elif average_adx >= 25.0 and abs(weighted_score or 0.0) >= DIRECTION_THRESHOLD:
        market_regime = "TRENDING"
    elif average_adx < 18.0 and abs(weighted_score or 0.0) < DIRECTION_THRESHOLD:
        market_regime = "RANGING"
    else:
        market_regime = "TRANSITIONAL"

    native_comparison = _native_indicator_comparison(
        frame_reports, native_indicators
    )
    native_structure = (
        multi_timeframe_structure
        if isinstance(multi_timeframe_structure, dict) else {}
    )
    structure_alignment = native_structure.get(
        "alignment", "NOT_SUPPLIED"
    )

    warnings: list[str] = []
    if errors:
        warnings.append("Some timeframes are unavailable, stale, or failed data-quality checks.")
    if disagreement:
        warnings.append("Bullish and bearish timeframe directions conflict; the market is not aligned.")
    if market_regime == "RANGING":
        warnings.append("The combined ADX readings indicate a weak/ranging environment; directional movement may be noisy.")
    if native_comparison.get("status") == "NO_ALIGNED_FRAMES":
        warnings.append("Native MT5 CopyBuffer values were not aligned to the same closed OHLC candles.")
    if any(
        item.get("status") == "DIVERGENT_OR_PARTIAL"
        for item in (native_comparison.get("timeframes") or {}).values()
    ):
        warnings.append("At least one OHLC-derived indicator differs from its MT5 CopyBuffer counterpart; see parity diagnostics.")

    summary = {
        "direction": overall_direction if analysis_ready else "INSUFFICIENT_CONTEXT",
        "direction_ar": {
            "BULLISH": "صاعد",
            "BEARISH": "هابط",
            "NEUTRAL": "محايد",
            "UNKNOWN": "غير معروف",
        }.get(overall_direction if analysis_ready else "UNKNOWN", "غير معروف"),
        "trend_score": round(weighted_score, 4) if weighted_score is not None else None,
        "short_term_direction": short_direction,
        "short_term_score": round(short_score, 4) if short_score is not None else None,
        "higher_timeframe_direction": higher_direction,
        "higher_timeframe_score": round(higher_score, 4) if higher_score is not None else None,
        "market_regime": market_regime,
        "average_adx14": round(average_adx, 3) if average_adx is not None else None,
        "timeframe_alignment": alignment,
        "bullish_timeframes": bullish,
        "bearish_timeframes": bearish,
        "neutral_timeframes": neutral,
        "directional_agreement_ratio": round(agreement_ratio, 4),
        "eligible_timeframe_count": len(eligible),
        "eligible_timeframes": eligible,
        "timeframe_weight_coverage": round(weight_coverage, 4),
    }
    return {
        **blocked,
        "status": "READY" if analysis_ready else "PARTIAL",
        "symbol": candle_history.get("symbol"),
        "broker_symbol": candle_history.get("broker_symbol"),
        "account_server": candle_history.get("account_server"),
        "as_of_utc_ms": as_of_ms,
        "analysis_scope": "NATIVE_OHLC_ONLY_CHART_IMAGE_NOT_REQUIRED",
        "decision_eligible": False,
        "direction": summary["direction"],
        "direction_ar": summary["direction_ar"],
        "trend_score": summary["trend_score"],
        "summary": summary,
        "timeframes": frame_reports,
        "timeframe_errors": errors,
        "multi_timeframe_structure_alignment": structure_alignment,
        "native_indicator_parity": native_comparison,
        "evidence_quality": {
            "eligible_timeframe_count": len(eligible),
            "expected_timeframe_count": len(TIMEFRAME_MS),
            "timeframe_weight_coverage": round(weight_coverage, 4),
            "directional_agreement_ratio": round(agreement_ratio, 4),
            "interpretation": "EVIDENCE_COVERAGE_AND_CROSS_TIMEFRAME_AGREEMENT_NOT_STATISTICAL_PROBABILITY",
        },
        "warnings": warnings,
        "reason": None if analysis_ready else (
            "A multi-timeframe direction requires at least four complete frames, including 15m, 1h and at least one of 4h/1d."
        ),
        "safety": {
            "read_only": True,
            "decision_eligible": False,
            "creates_orders": False,
            "controls_positions": False,
        },
        "methodology": {
            "ema": "EMA20/EMA50 from completed MT5 closes, SMA-seeded and recursively smoothed.",
            "momentum": "Wilder RSI14 and MACD 12/26/9 histogram.",
            "trend_strength": "Wilder ADX14; direction is assessed separately by +DI/-DI.",
            "volatility": "Wilder ATR14 and ATR as percentage of last close.",
            "structure": "Confirmed pivots, BOS/CHOCH, liquidity-sweep candidates, FVG and order-block candidates from completed native OHLC.",
            "patterns": "Rule-based candle geometry and prior context on completed native OHLC.",
            "consensus": "Weighted direction across 1m/5m/15m/1h/4h/1d; higher frames receive larger weights.",
            "thresholds": {
                "direction_score": DIRECTION_THRESHOLD,
                "adx_trending_convention": 25.0,
                "adx_ranging_convention": 18.0,
                "minimum_closed_bars_per_frame": MIN_CLOSED_BARS,
            },
        },
        "limitations": [
            "The direction is a deterministic summary of closed-bar evidence, not a prediction guarantee or a trading probability.",
            "ADX measures trend strength, not direction; +DI/-DI and price/EMA relationships contribute direction.",
            "The conventional ADX 25 threshold is a regime heuristic, not an empirically optimized BTC threshold.",
            "Tick volume is broker tick count, not consolidated exchange-traded volume.",
            "Native indicator parity is diagnostic only and cannot silently replace or rewrite OHLC-derived calculations.",
            "No custom iCustom indicators, order-book depth, or multi-venue trade tape are inferred when the broker does not supply them.",
            "Chart-image extraction and pixel calibration are deliberately outside this native data-only analysis path.",
        ],
    }


__all__ = ["analyze_mt5_native_trend", "TIMEFRAME_MS", "TIMEFRAME_WEIGHTS"]
