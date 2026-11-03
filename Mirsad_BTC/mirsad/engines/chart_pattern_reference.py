from __future__ import annotations

from typing import Any

import numpy as np

try:
    import talib
except Exception:  # pragma: no cover - dependency failure is surfaced in the result
    talib = None


PATTERN_REFERENCE_VERSION = "1.0.0"
MAX_REFERENCE_EVENTS = 120
DEFAULT_EVENT_WINDOW = 30

FORMATION_BARS = {
    "CDL2CROWS": 2,
    "CDL3BLACKCROWS": 3,
    "CDL3INSIDE": 3,
    "CDL3LINESTRIKE": 4,
    "CDL3OUTSIDE": 3,
    "CDL3STARSINSOUTH": 3,
    "CDL3WHITESOLDIERS": 3,
    "CDLABANDONEDBABY": 3,
    "CDLADVANCEBLOCK": 3,
    "CDLBELTHOLD": 1,
    "CDLBREAKAWAY": 5,
    "CDLCLOSINGMARUBOZU": 1,
    "CDLCONCEALBABYSWALL": 4,
    "CDLCOUNTERATTACK": 2,
    "CDLDARKCLOUDCOVER": 2,
    "CDLDOJISTAR": 2,
    "CDLDRAGONFLYDOJI": 1,
    "CDLENGULFING": 2,
    "CDLEVENINGDOJISTAR": 3,
    "CDLEVENINGSTAR": 3,
    "CDLGAPSIDESIDEWHITE": 3,
    "CDLHAMMER": 1,
    "CDLHANGINGMAN": 1,
    "CDLHARAMI": 2,
    "CDLHARAMICROSS": 2,
    "CDLHIGHWAVE": 1,
    "CDLHIKKAKE": 3,
    "CDLHIKKAKEMOD": 3,
    "CDLHOMINGPIGEON": 2,
    "CDLIDENTICAL3CROWS": 3,
    "CDLINNECK": 2,
    "CDLINVERTEDHAMMER": 1,
    "CDLKICKING": 2,
    "CDLKICKINGBYLENGTH": 2,
    "CDLLADDERBOTTOM": 5,
    "CDLLONGLEGGEDDOJI": 1,
    "CDLLONGLINE": 1,
    "CDLMARUBOZU": 1,
    "CDLMATCHINGLOW": 2,
    "CDLMATHOLD": 5,
    "CDLMORNINGDOJISTAR": 3,
    "CDLMORNINGSTAR": 3,
    "CDLONNECK": 2,
    "CDLPIERCING": 2,
    "CDLRICKSHAWMAN": 1,
    "CDLRISEFALL3METHODS": 5,
    "CDLSEPARATINGLINES": 2,
    "CDLSHOOTINGSTAR": 1,
    "CDLSHORTLINE": 1,
    "CDLSPINNINGTOP": 1,
    "CDLSTALLEDPATTERN": 3,
    "CDLSTICKSANDWICH": 3,
    "CDLTAKURI": 1,
    "CDLTASUKIGAP": 3,
    "CDLTHRUSTING": 2,
    "CDLTRISTAR": 3,
    "CDLUNIQUE3RIVER": 3,
    "CDLUPSIDEGAP2CROWS": 3,
    "CDLXSIDEGAP3METHODS": 3,
}


def _validated_ohlc(bars: list[dict[str, Any]]) -> tuple[np.ndarray, ...]:
    if not isinstance(bars, list):
        raise TypeError("bars must be a list of calibrated OHLC dictionaries")
    if not bars:
        return tuple(np.asarray([], dtype=np.float64) for _ in range(4))

    arrays: list[np.ndarray] = []
    for name in ("open", "high", "low", "close"):
        try:
            values = np.ascontiguousarray(
                [float(bar[name]) for bar in bars], dtype=np.float64
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid calibrated OHLC field: {name}") from exc
        if not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError(f"Calibrated {name} values must be finite and positive")
        arrays.append(values)

    open_, high, low, close = arrays
    if np.any(high < np.maximum.reduce([open_, close, low])):
        raise ValueError("Invalid calibrated OHLC: high is below open/close/low")
    if np.any(low > np.minimum.reduce([open_, close, high])):
        raise ValueError("Invalid calibrated OHLC: low is above open/close/high")
    return open_, high, low, close


def _pattern_signal_arrays(
    bars: list[dict[str, Any]],
) -> tuple[dict[str, np.ndarray], str | None]:
    """Return TA-Lib raw signed outputs without translating strength to probability."""
    if talib is None:
        return {}, "TA-Lib could not be imported. Install the pinned TA-Lib dependency."
    open_, high, low, close = _validated_ohlc(bars)
    if len(close) == 0:
        return {}, "No calibrated candles were supplied."

    groups = talib.get_function_groups()
    names = sorted(groups.get("Pattern Recognition", []))
    signals: dict[str, np.ndarray] = {}
    for name in names:
        function = getattr(talib, name, None)
        if function is None:
            continue
        raw = np.asarray(function(open_, high, low, close))
        if raw.ndim != 1 or len(raw) != len(close):
            raise RuntimeError(f"TA-Lib returned an invalid output shape for {name}")
        if not np.issubdtype(raw.dtype, np.number) or not np.isfinite(raw).all():
            raise RuntimeError(f"TA-Lib returned non-finite output for {name}")
        signals[name] = np.ascontiguousarray(raw, dtype=np.int32)
    return signals, None


def _candidate_state(
    *,
    name: str,
    index: int,
    side: str,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    last_candle_closed: bool,
) -> dict[str, Any]:
    span = FORMATION_BARS.get(name, 1)
    start = max(0, index - span + 1)
    formation_high = float(np.max(high[start:index + 1]))
    formation_low = float(np.min(low[start:index + 1]))
    later_closes = close[index + 1:]
    # The latest screenshot candle may still be forming. It can be displayed
    # as a live candidate, but it cannot invalidate an earlier closed pattern
    # until its own close has been confirmed.
    if not last_candle_closed and index < len(close) - 1:
        later_closes = later_closes[:-1]

    invalidation_reason = None
    invalidation_level = None
    state = "COMPLETED"
    if side == "BULLISH":
        invalidation_level = formation_low
        if later_closes.size and bool(np.any(later_closes < formation_low)):
            state = "INVALIDATED"
            invalidation_reason = "A later closed candle closed below the formation low."
        else:
            invalidation_reason = "Invalidated only by a later close below the formation low."
    elif side == "BEARISH":
        invalidation_level = formation_high
        if later_closes.size and bool(np.any(later_closes > formation_high)):
            state = "INVALIDATED"
            invalidation_reason = "A later closed candle closed above the formation high."
        else:
            invalidation_reason = "Invalidated only by a later close above the formation high."
    else:
        invalidation_reason = "This pattern is non-directional and has no generic invalidation level."

    if index == len(close) - 1 and not last_candle_closed:
        state = "FORMING"
        invalidation_reason = "The last chart candle is not confirmed closed."

    return {
        "state": state,
        "formation_start_index": start,
        "formation_end_index": index,
        "formation_bars": index - start + 1,
        "formation_high": round(formation_high, 10),
        "formation_low": round(formation_low, 10),
        "invalidation_level": (
            round(float(invalidation_level), 10)
            if invalidation_level is not None else None
        ),
        "invalidation_rule": (
            "close_below_formation_low" if side == "BULLISH"
            else "close_above_formation_high" if side == "BEARISH"
            else "not_directional"
        ),
        "invalidation_reason": invalidation_reason,
    }


def analyze_talib_pattern_reference(
    bars: list[dict[str, Any]],
    *,
    last_candle_closed: bool = False,
    event_window: int = DEFAULT_EVENT_WINDOW,
) -> dict[str, Any]:
    """Scan calibrated chart OHLC with TA-Lib as an independent pattern reference.

    This is a second detector, not a probability model or trading signal.
    The original visual-geometry detector remains separately available in
    pattern_candidates so disagreements can be inspected rather than counted
    twice as if they were independent confirming votes.
    """
    if event_window < 1:
        raise ValueError("event_window must be positive")
    if talib is None:
        return {
            "status": "UNAVAILABLE",
            "source": "TA-Lib",
            "version": None,
            "pattern_definition_count": 0,
            "bar_count": len(bars) if isinstance(bars, list) else 0,
            "events": [],
            "error": "TA-Lib could not be imported.",
            "interpretation": "Reference pattern analysis is unavailable; visual candidates remain separate.",
        }

    open_, high, low, close = _validated_ohlc(bars)
    if len(close) == 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "source": "TA-Lib",
            "version": getattr(talib, "__version__", "unknown"),
            "pattern_definition_count": len(talib.get_function_groups().get("Pattern Recognition", [])),
            "bar_count": 0,
            "events": [],
            "error": "No calibrated OHLC bars were supplied.",
            "interpretation": "Price calibration is required before candlestick formulas can be applied.",
        }

    signal_arrays, error = _pattern_signal_arrays(bars)
    if error:
        return {
            "status": "INSUFFICIENT_DATA",
            "source": "TA-Lib",
            "version": getattr(talib, "__version__", "unknown"),
            "pattern_definition_count": len(talib.get_function_groups().get("Pattern Recognition", [])),
            "bar_count": len(close),
            "events": [],
            "error": error,
            "interpretation": "No values are inferred when OHLC input is missing or invalid.",
        }

    first_index = max(0, len(close) - int(event_window))
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    invalidated = forming = completed = 0

    for name, values in signal_arrays.items():
        event_indices = np.flatnonzero(values[first_index:] != 0) + first_index
        if len(event_indices):
            counts[name] = int(len(event_indices))
        for raw_index in event_indices:
            index = int(raw_index)
            raw_value = int(values[index])
            side = "BULLISH" if raw_value > 0 else "BEARISH" if raw_value < 0 else "NEUTRAL"
            state = _candidate_state(
                name=name,
                index=index,
                side=side,
                high=high,
                low=low,
                close=close,
                last_candle_closed=bool(last_candle_closed),
            )
            state_name = state["state"]
            invalidated += state_name == "INVALIDATED"
            forming += state_name == "FORMING"
            completed += state_name == "COMPLETED"
            start_index = int(state["formation_start_index"])
            try:
                start_x = float(bars[start_index].get("x_px", start_index))
                end_x = float(bars[index].get("x_px", index))
            except (TypeError, ValueError, OverflowError):
                start_x, end_x = float(start_index), float(index)
            events.append({
                "pattern": name,
                "side": side,
                "state": state_name,
                "bar_index": index,
                "x_px": round(end_x, 3),
                "formation_center_x_px": round((start_x + end_x) / 2.0, 3),
                "talib_value": raw_value,
                "strength_semantics": "TA-Lib pattern output integer; not probability or expected return.",
                **state,
            })

    events.sort(key=lambda item: (item["bar_index"], item["pattern"]), reverse=True)
    truncated = max(0, len(events) - MAX_REFERENCE_EVENTS)
    events = events[:MAX_REFERENCE_EVENTS]

    return {
        "status": "READY",
        "source": "TA-Lib",
        "version": getattr(talib, "__version__", "unknown"),
        "pattern_definition_count": len(signal_arrays),
        "bar_count": len(close),
        "event_window_bars": int(event_window),
        "last_candle_closed": bool(last_candle_closed),
        "event_count_before_limit": sum(counts.values()),
        "event_count": len(events),
        "truncated_event_count": truncated,
        "forming_count": int(forming),
        "completed_count": int(completed),
        "invalidated_count": int(invalidated),
        "pattern_counts": counts,
        "events": events,
        "invalidation_policy": (
            "Generic structural invalidation: bullish patterns invalidate after a later close below "
            "the formation low; bearish patterns invalidate after a later close above the formation high. "
            "This is a review rule, not a TA-Lib rule or a trade exit."
        ),
        "interpretation": (
            "Independent OHLC formula reference only. Raw TA-Lib integers describe pattern match outputs; "
            "they are not probabilities, profitability, or directional votes. Compare against pixel-geometry "
            "candidates; never add both outputs as two independent confirmations."
        ),
    }


__all__ = [
    "analyze_talib_pattern_reference",
    "_pattern_signal_arrays",
    "PATTERN_REFERENCE_VERSION",
    "FORMATION_BARS",
]
