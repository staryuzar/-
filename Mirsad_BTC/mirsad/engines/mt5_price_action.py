from __future__ import annotations

import math
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
MIN_CLOSED_BARS = 24
MAX_STALENESS_INTERVALS = 1
DIRECTION_THRESHOLD = 0.20


def _valid_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _validate_frame(
    timeframe: str,
    raw_bars: Any,
    *,
    as_of_ms: int,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any], dict[str, Any] | None]:
    """Validate the MT5 OHLC contract and return closed bars plus the forming bar."""
    duration = TIMEFRAME_MS[timeframe]
    if not isinstance(raw_bars, list):
        return None, {"status": "INVALID", "reason": "The timeframe candle list is missing."}, None
    if len(raw_bars) < 2:
        return None, {"status": "INSUFFICIENT", "reason": "Fewer than two native MT5 candles were supplied."}, None

    normalized: list[dict[str, Any]] = []
    previous_time = 0
    for index, raw in enumerate(raw_bars):
        if not isinstance(raw, dict):
            return None, {"status": "INVALID", "reason": f"Candle {index} is not an object."}, None
        try:
            stamp = int(raw["open_time_ms"])
            open_price = float(raw["open"])
            high = float(raw["high"])
            low = float(raw["low"])
            close = float(raw["close"])
            volume = float(raw.get("volume", 0.0))
            closed = raw["closed"]
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, {"status": "INVALID", "reason": f"Candle {index} has incomplete OHLC/time data."}, None

        if stamp <= previous_time:
            return None, {"status": "INVALID", "reason": "Candle times are not strictly increasing."}, None
        if not isinstance(closed, bool):
            return None, {"status": "INVALID", "reason": f"Candle {index} has no valid closed/forming flag."}, None
        if not all(math.isfinite(value) for value in (open_price, high, low, close, volume)):
            return None, {"status": "INVALID", "reason": f"Candle {index} contains a non-finite value."}, None
        if min(open_price, high, low, close) <= 0 or volume < 0:
            return None, {"status": "INVALID", "reason": f"Candle {index} contains a non-positive price or negative tick volume."}, None
        if high < max(open_price, close, low) or low > min(open_price, close, high):
            return None, {"status": "INVALID", "reason": f"Candle {index} has inconsistent OHLC bounds."}, None
        if index < len(raw_bars) - 1 and not closed:
            return None, {"status": "INVALID", "reason": "A forming candle appears before the final history row."}, None
        if index == len(raw_bars) - 1 and closed:
            return None, {"status": "INVALID", "reason": "The latest MT5 candle must be marked as forming."}, None

        normalized.append({
            "open_time_ms": stamp,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "closed": closed,
        })
        previous_time = stamp

    closed_bars = normalized[:-1]
    forming_bar = normalized[-1]
    if len(closed_bars) < MIN_CLOSED_BARS:
        return None, {
            "status": "INSUFFICIENT",
            "closed_bars": len(closed_bars),
            "required_closed_bars": MIN_CLOSED_BARS,
            "reason": f"At least {MIN_CLOSED_BARS} completed candles are required for multi-scale swing analysis.",
        }, forming_bar

    last_close_ms = closed_bars[-1]["open_time_ms"] + duration
    expected_forming_open_ms = last_close_ms
    if forming_bar["open_time_ms"] != expected_forming_open_ms:
        return None, {
            "status": "INVALID_SEQUENCE",
            "last_closed_bar_close_time_ms": last_close_ms,
            "forming_bar_open_time_ms": forming_bar["open_time_ms"],
            "expected_forming_bar_open_time_ms": expected_forming_open_ms,
            "reason": "The forming candle does not immediately follow the latest completed candle.",
        }, forming_bar
    staleness_ms = as_of_ms - last_close_ms
    if staleness_ms < -2_000:
        return None, {
            "status": "FUTURE_DATA",
            "last_closed_bar_close_time_ms": last_close_ms,
            "staleness_ms": staleness_ms,
            "reason": "The latest completed candle closes after the common analysis cutoff.",
        }, forming_bar
    if staleness_ms > duration * MAX_STALENESS_INTERVALS:
        return None, {
            "status": "STALE",
            "last_closed_bar_close_time_ms": last_close_ms,
            "staleness_ms": staleness_ms,
            "reason": "The forming candle is older than the allowed timeframe freshness window.",
        }, forming_bar

    gaps: list[dict[str, int]] = []
    missing_intervals = 0
    for index, (left, right) in enumerate(zip(closed_bars[:-1], closed_bars[1:])):
        delta = right["open_time_ms"] - left["open_time_ms"]
        if delta > duration * 1.5:
            missing = max(1, int(round(delta / duration)) - 1)
            missing_intervals += missing
            gaps.append({
                "after_closed_bar_index": index,
                "gap_duration_ms": delta,
                "estimated_missing_intervals": missing,
            })

    interval_count = max(1, len(closed_bars) - 1)
    gap_fraction = missing_intervals / (interval_count + missing_intervals)
    # Never build a pattern or direction across a missing candle. Even one
    # missing interval makes the timeframe visible but ineligible for consensus.
    status = "PARTIAL" if gaps else "READY"
    health = {
        "status": status,
        "closed_bars": len(closed_bars),
        "forming_bar_open_time_ms": forming_bar["open_time_ms"],
        "last_closed_bar_open_time_ms": closed_bars[-1]["open_time_ms"],
        "last_closed_bar_close_time_ms": last_close_ms,
        "staleness_ms": staleness_ms,
        "gap_count": len(gaps),
        "estimated_missing_intervals": missing_intervals,
        "gap_fraction": round(gap_fraction, 5),
        "gaps": gaps[-10:],
        "reason": (
            "One or more candle intervals are missing; this timeframe is excluded from direction consensus."
            if status == "PARTIAL" else None
        ),
    }
    return closed_bars, health, forming_bar


def _stamp_indexed_items(
    rows: list[dict[str, Any]],
    bars: list[dict[str, Any]],
    *,
    index_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in index_keys:
            index = item.get(key)
            if isinstance(index, int) and 0 <= index < len(bars):
                item[key.replace("_index", "_time_utc_ms")] = bars[index]["open_time_ms"]
        output.append(item)
    return output


def _summarize_pivots(
    raw: dict[str, Any],
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    def pivots(name: str) -> list[dict[str, Any]]:
        rows = raw.get(name, [])
        result = []
        for pivot in rows[-20:]:
            item = dict(pivot)
            index = item.get("index")
            confirmation = item.get("confirmation_index")
            if isinstance(index, int) and 0 <= index < len(bars):
                item["time_utc_ms"] = bars[index]["open_time_ms"]
            if isinstance(confirmation, int) and 0 <= confirmation < len(bars):
                item["confirmation_time_utc_ms"] = bars[confirmation]["open_time_ms"]
            result.append(item)
        return result

    return {
        "status": raw.get("status", "PARTIAL"),
        "left_bars": raw.get("left_bars"),
        "right_bars": raw.get("right_bars"),
        "direction": raw.get("direction", "MIXED_OR_UNKNOWN"),
        "higher_highs": bool(raw.get("higher_highs")),
        "higher_lows": bool(raw.get("higher_lows")),
        "lower_highs": bool(raw.get("lower_highs")),
        "lower_lows": bool(raw.get("lower_lows")),
        "swing_highs": pivots("swing_highs"),
        "swing_lows": pivots("swing_lows"),
    }


def _summarize_structure(
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = analyze_chart_structure_knowledge(bars, last_candle_closed=True)
    scales = raw.get("scales", {})
    events = _stamp_indexed_items(
        raw.get("bos_choch_events", []), bars,
        index_keys=("pivot_index", "confirmation_index"),
    )
    sweeps = _stamp_indexed_items(
        raw.get("liquidity_sweeps", []), bars,
        index_keys=("pivot_index", "confirmation_index"),
    )
    order_blocks = _stamp_indexed_items(
        raw.get("order_block_candidates", []), bars,
        index_keys=("source_candle_index", "pivot_index", "break_index", "mitigation_index", "invalidation_index"),
    )
    fair_value_gaps = _stamp_indexed_items(
        raw.get("fair_value_gaps", []), bars,
        index_keys=("index",),
    )

    external = scales.get("external", {})
    premium_discount = raw.get("premium_discount")
    return {
        "status": raw.get("status", "UNKNOWN"),
        "direction": raw.get("structure_direction", "MIXED_OR_UNKNOWN"),
        "confirmed_bars": raw.get("confirmed_bars"),
        "internal": _summarize_pivots(scales.get("internal", {}), bars),
        "swing": _summarize_pivots(scales.get("swing", {}), bars),
        "external": _summarize_pivots(external, bars),
        "bos_choch_events": events[-20:],
        "liquidity_sweeps": sweeps[-20:],
        "equal_highs": raw.get("equal_highs", [])[-12:],
        "equal_lows": raw.get("equal_lows", [])[-12:],
        "fair_value_gaps": fair_value_gaps[-20:],
        "order_block_candidates": order_blocks[-12:],
        "classical_patterns": raw.get("classical_patterns", [])[-12:],
        "continuation_patterns": raw.get("continuation_patterns", [])[-12:],
        "premium_discount": premium_discount,
        "limitations": raw.get("limitations", []),
    }


def _summarize_candle_patterns(
    bars: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = analyze_candle_patterns(bars, last_candle_closed=True)
    detected = _stamp_indexed_items(
        raw.get("detected", []), bars,
        index_keys=("start_index", "end_index", "index"),
    )
    latest_index = len(bars) - 1
    latest_patterns = [
        item for item in detected
        if item.get("end_index") == latest_index
    ]
    bullish = [
        item for item in latest_patterns
        if item.get("direction") == "BULLISH"
        and item.get("context_match") is not False
    ]
    bearish = [
        item for item in latest_patterns
        if item.get("direction") == "BEARISH"
        and item.get("context_match") is not False
    ]
    latest = bars[-1]
    body = abs(latest["close"] - latest["open"])
    span = latest["high"] - latest["low"]
    candle_shape = {
        "open": latest["open"],
        "high": latest["high"],
        "low": latest["low"],
        "close": latest["close"],
        "body": body,
        "upper_shadow": latest["high"] - max(latest["open"], latest["close"]),
        "lower_shadow": min(latest["open"], latest["close"]) - latest["low"],
        "range": span,
        "body_to_range_ratio": body / span if span > 0 else 0.0,
        "body_direction": (
            "BULLISH_BODY" if latest["close"] > latest["open"]
            else "BEARISH_BODY" if latest["close"] < latest["open"]
            else "FLAT_BODY"
        ),
        "open_time_utc_ms": latest["open_time_ms"],
    }
    return {
        "status": raw.get("status", "UNKNOWN"),
        "detected_count": raw.get("count", len(detected)),
        "latest_closed_candle": candle_shape,
        "latest_candle_patterns": latest_patterns,
        "recent_patterns": detected[-60:],
        "latest_pattern_bias": (
            "BULLISH" if bullish and not bearish
            else "BEARISH" if bearish and not bullish
            else "MIXED" if bullish and bearish
            else "NONE"
        ),
        "interpretation": "CANDLE_FORMATION_AND_CONTEXT_ONLY_NOT_A_RETURN_PROBABILITY",
        "limitations": [
            "A candle pattern is a geometric classification; context and confirmation must be considered.",
            "Patterns are reported as rule matches, not as predictions or trade commands.",
            "Pattern precision/recall has not yet been measured on an independent human-labelled BTC dataset.",
        ],
    }


def _forming_candle_summary(
    bar: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(bar, dict):
        return None
    span = bar["high"] - bar["low"]
    body = abs(bar["close"] - bar["open"])
    return {
        "state": "FORMING_NOT_USED_FOR_DIRECTION",
        "open_time_utc_ms": bar["open_time_ms"],
        "open": bar["open"],
        "high": bar["high"],
        "low": bar["low"],
        "close": bar["close"],
        "body_to_range_ratio": body / span if span > 0 else 0.0,
        "body_direction": (
            "BULLISH_BODY" if bar["close"] > bar["open"]
            else "BEARISH_BODY" if bar["close"] < bar["open"]
            else "FLAT_BODY"
        ),
    }


DIRECTIONAL_EVIDENCE_WEIGHTS = {
    "confirmed_swing_structure": 0.70,
    "latest_confirmed_bos_choch": 0.15,
    "latest_candle_pattern": 0.10,
    "latest_liquidity_sweep": 0.05,
}


def _directional_evidence_score(
    structure: dict[str, Any],
    candle_analysis: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    """Blend native OHLC price-action evidence; no image or technical-indicator input."""
    swing = structure.get("swing") if isinstance(structure.get("swing"), dict) else {}
    swing_direction = str(swing.get("direction", "MIXED_OR_UNCONFIRMED")).upper()
    component_scores: dict[str, float] = {
        "confirmed_swing_structure": (
            1.0 if swing_direction == "BULLISH"
            else -1.0 if swing_direction == "BEARISH"
            else 0.0
        )
    }

    bos_events = structure.get("bos_choch_events")
    if isinstance(bos_events, list):
        directional_events = [
            item for item in bos_events
            if isinstance(item, dict)
            and str(item.get("event", "")).upper() in {
                "BOS_BULLISH", "CHOCH_BULLISH", "BOS_BEARISH", "CHOCH_BEARISH"
            }
        ]
        if directional_events:
            latest_event = max(
                directional_events,
                key=lambda item: int(
                    item.get("confirmation_time_utc_ms")
                    or item.get("pivot_time_utc_ms")
                    or 0
                ),
            )
            event_name = str(latest_event.get("event", "")).upper()
            component_scores["latest_confirmed_bos_choch"] = (
                1.0 if event_name in {"BOS_BULLISH", "CHOCH_BULLISH"} else -1.0
            )

    pattern_bias = str(candle_analysis.get("latest_pattern_bias", "NONE")).upper()
    if pattern_bias in {"BULLISH", "BEARISH"}:
        component_scores["latest_candle_pattern"] = (
            1.0 if pattern_bias == "BULLISH" else -1.0
        )

    sweeps = structure.get("liquidity_sweeps")
    if isinstance(sweeps, list):
        directional_sweeps = [
            item for item in sweeps
            if isinstance(item, dict)
            and str(item.get("event", "")).upper() in {
                "HIGH_LIQUIDITY_SWEEP", "LOW_LIQUIDITY_SWEEP"
            }
        ]
        if directional_sweeps:
            latest_sweep = max(
                directional_sweeps,
                key=lambda item: int(
                    item.get("confirmation_time_utc_ms")
                    or item.get("pivot_time_utc_ms")
                    or 0
                ),
            )
            sweep_name = str(latest_sweep.get("event", "")).upper()
            component_scores["latest_liquidity_sweep"] = (
                -1.0 if sweep_name == "HIGH_LIQUIDITY_SWEEP" else 1.0
            )

    active_weight = sum(DIRECTIONAL_EVIDENCE_WEIGHTS[name] for name in component_scores)
    if active_weight <= 0:
        return None, {
            "score": None,
            "configured_weights": dict(DIRECTIONAL_EVIDENCE_WEIGHTS),
            "applied_weights": {},
            "component_scores": {},
            "evidence_count": 0,
        }

    applied_weights = {
        name: round(DIRECTIONAL_EVIDENCE_WEIGHTS[name] / active_weight, 6)
        for name in component_scores
    }
    score = sum(
        component_scores[name] * applied_weights[name]
        for name in component_scores
    )
    score = max(-1.0, min(1.0, score))
    return score, {
        "score": round(score, 6),
        "configured_weights": dict(DIRECTIONAL_EVIDENCE_WEIGHTS),
        "applied_weights": applied_weights,
        "component_scores": {
            name: round(value, 6) for name, value in component_scores.items()
        },
        "evidence_count": len(component_scores),
        "interpretation": "WEIGHTED_NATIVE_OHLC_PRICE_ACTION_EVIDENCE_NOT_PROBABILITY",
    }


def _analyze_timeframe(
    timeframe: str,
    bars: list[dict[str, Any]],
    health: dict[str, Any],
    forming: dict[str, Any] | None,
) -> dict[str, Any]:
    structure = _summarize_structure(bars)
    patterns = _summarize_candle_patterns(bars)
    swing = structure["swing"]
    direction = swing.get("direction", "MIXED_OR_UNCONFIRMED")
    directional_score, directional_evidence = _directional_evidence_score(structure, patterns)

    recent_events = structure["bos_choch_events"][-5:]
    directional_event = None
    for event in reversed(recent_events):
        name = str(event.get("event", ""))
        if name in {"BOS_BULLISH", "CHOCH_BULLISH", "BOS_BEARISH", "CHOCH_BEARISH"}:
            directional_event = event
            break

    if direction == "BULLISH":
        if directional_event and directional_event.get("event") in {"BOS_BULLISH", "CHOCH_BULLISH"}:
            strength = "STRUCTURE_WITH_CONFIRMED_BULLISH_BREAK"
        else:
            strength = "HIGHER_HIGH_HIGHER_LOW_SEQUENCE"
    elif direction == "BEARISH":
        if directional_event and directional_event.get("event") in {"BOS_BEARISH", "CHOCH_BEARISH"}:
            strength = "STRUCTURE_WITH_CONFIRMED_BEARISH_BREAK"
        else:
            strength = "LOWER_HIGH_LOWER_LOW_SEQUENCE"
    else:
        strength = "MIXED_OR_UNCONFIRMED_SWINGS"

    structure_status = structure.get("status", "UNKNOWN")
    timeframe_status = (
        "READY"
        if health.get("status") == "READY" and structure_status == "READY"
        else "PARTIAL"
    )
    readiness_reasons: list[str] = []
    if health.get("status") != "READY":
        readiness_reasons.append(str(health.get("reason") or "OHLC quality is not READY."))
    if structure_status != "READY":
        readiness_reasons.append(
            "Confirmed swing structure is incomplete; at least two confirmed swing highs "
            "and two confirmed swing lows are required."
        )

    return {
        "status": timeframe_status,
        "timeframe": timeframe,
        "direction": direction,
        "structure_direction": direction,
        "swing_structure_score": (
            1.0 if direction == "BULLISH" else -1.0 if direction == "BEARISH" else 0.0
        ),
        "directional_evidence_score": (
            round(directional_score, 6) if directional_score is not None else None
        ),
        "directional_evidence": directional_evidence,
        "structure_strength": strength,
        "readiness": {
            "ohlc": health.get("status"),
            "confirmed_swing_structure": structure_status,
        },
        "reason": " ".join(readiness_reasons) if readiness_reasons else None,
        "closed_bars": len(bars),
        "last_closed_bar_open_time_ms": health["last_closed_bar_open_time_ms"],
        "last_closed_bar_close_time_ms": health["last_closed_bar_close_time_ms"],
        "staleness_ms": health["staleness_ms"],
        "structure": structure,
        "candle_analysis": patterns,
        "forming_candle": _forming_candle_summary(forming),
        "data_quality": health,
        "interpretation": "PRICE_ACTION_STRUCTURE_AND_CANDLE_EVIDENCE_ONLY",
    }


def _weighted_structure_score(
    reports: dict[str, dict[str, Any]],
    selected_timeframes: list[str],
    *,
    score_key: str = "directional_evidence_score",
) -> float | None:
    usable = [
        timeframe for timeframe in selected_timeframes
        if timeframe in reports and reports[timeframe].get("status") == "READY"
    ]
    denominator = sum(TIMEFRAME_WEIGHTS[name] for name in usable)
    if denominator <= 0:
        return None
    score = 0.0
    for timeframe in usable:
        report = reports[timeframe]
        raw_score = _valid_number(report.get(score_key))
        if raw_score is None:
            direction = report.get("direction")
            raw_score = 1.0 if direction == "BULLISH" else -1.0 if direction == "BEARISH" else 0.0
        score += TIMEFRAME_WEIGHTS[timeframe] * max(-1.0, min(1.0, raw_score))
    return score / denominator


def _direction(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= DIRECTION_THRESHOLD:
        return "BULLISH"
    if score <= -DIRECTION_THRESHOLD:
        return "BEARISH"
    return "MIXED_OR_UNCONFIRMED"


def _summarize_latest_pattern_alignment(
    latest_pattern_biases: dict[str, str | None],
) -> tuple[str, list[str], list[str], list[str]]:
    bullish = [tf for tf, bias in latest_pattern_biases.items() if bias == "BULLISH"]
    bearish = [tf for tf, bias in latest_pattern_biases.items() if bias == "BEARISH"]
    mixed = [tf for tf, bias in latest_pattern_biases.items() if bias == "MIXED"]
    alignment = (
        "MIXED_CANDLE_PATTERN_EVIDENCE" if mixed or (bullish and bearish)
        else "BULLISH_CANDLE_PATTERN_EVIDENCE" if bullish
        else "BEARISH_CANDLE_PATTERN_EVIDENCE" if bearish
        else "NO_LATEST_DIRECTIONAL_CANDLE_PATTERN"
    )
    return alignment, bullish, bearish, mixed


def analyze_mt5_native_price_action(
    candle_history: dict[str, Any],
) -> dict[str, Any]:
    """Analyse native MT5 candle forms and price structure without technical indicators.

    Engine 2 owns candle formations, confirmed peaks/troughs, BOS/CHOCH,
    liquidity-sweep candidates, price gaps/zones and multi-timeframe
    structural direction. Indicator calculations belong to Engine 3.
    """
    base = {
        "engine": "engine_2_native_price_action",
        "schema": "MIR-ENGINE2-PRICE-ACTION-1",
        "source": "MT5_COPYRATES_CLOSED_BARS",
        "analysis_scope": "CANDLE_TYPES_AND_PRICE_STRUCTURE_ONLY",
        "status": "NOT_READY",
        "decision_eligible": False,
        "direction": "UNKNOWN",
        "direction_ar": "غير معروف",
        "timeframes": {},
        "multi_timeframe_structure": {
            "status": "NOT_READY",
            "source": "NATIVE_MT5_OHLC",
            "alignment": "INSUFFICIENT_TIMEFRAME_CONFLUENCE",
            "bullish_timeframes": [],
            "bearish_timeframes": [],
            "mixed_or_unconfirmed_timeframes": [],
        },
    }
    if not isinstance(candle_history, dict) or candle_history.get("status") != "READY":
        return {
            **base,
            "reason": "A fresh, identity-matched native MT5 candle history is required.",
            "candle_history_status": (
                candle_history.get("status") if isinstance(candle_history, dict) else None
            ),
        }

    raw_frames = candle_history.get("candles_by_tf")
    if not isinstance(raw_frames, dict):
        return {**base, "status": "INVALID", "reason": "The native MT5 timeframe map is missing."}
    try:
        as_of_ms = int(candle_history["captured_at_ms"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {**base, "status": "INVALID", "reason": "The common snapshot cutoff is missing."}
    if as_of_ms <= 0:
        return {**base, "status": "INVALID", "reason": "The common snapshot cutoff is invalid."}

    reports: dict[str, dict[str, Any]] = {}
    timeframe_errors: dict[str, str] = {}
    forming_bars: dict[str, Any] = {}
    for timeframe in TIMEFRAME_MS:
        bars, health, forming = _validate_frame(
            timeframe, raw_frames.get(timeframe), as_of_ms=as_of_ms
        )
        forming_bars[timeframe] = forming
        if bars is None:
            reports[timeframe] = {
                "status": health.get("status", "NOT_READY"),
                "direction": "MIXED_OR_UNKNOWN",
                "reason": health.get("reason"),
                "data_quality": health,
                "forming_candle": _forming_candle_summary(forming),
            }
            timeframe_errors[timeframe] = str(health.get("reason", health.get("status")))
            continue
        try:
            report = _analyze_timeframe(timeframe, bars, health, forming)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            reports[timeframe] = {
                "status": "ERROR",
                "direction": "MIXED_OR_UNKNOWN",
                "reason": f"{type(exc).__name__}: {exc}",
            }
            timeframe_errors[timeframe] = reports[timeframe]["reason"]
            continue
        reports[timeframe] = report
        if report["status"] != "READY":
            timeframe_errors[timeframe] = str(
                report.get("reason") or health.get("reason") or "Timeframe analysis is partial."
            )

    eligible = [
        timeframe for timeframe, report in reports.items()
        if report.get("status") == "READY"
    ]
    bullish = [tf for tf in eligible if reports[tf]["direction"] == "BULLISH"]
    bearish = [tf for tf in eligible if reports[tf]["direction"] == "BEARISH"]
    mixed = [tf for tf in eligible if reports[tf]["direction"] not in {"BULLISH", "BEARISH"}]

    short_frames = ["1m", "5m", "15m"]
    higher_frames = ["15m", "1h", "4h", "1d"]
    short_score = _weighted_structure_score(reports, short_frames)
    higher_score = _weighted_structure_score(reports, higher_frames)
    overall_score = _weighted_structure_score(reports, list(TIMEFRAME_MS))
    swing_structure_score = _weighted_structure_score(
        reports, list(TIMEFRAME_MS), score_key="swing_structure_score"
    )
    short_direction = _direction(short_score)
    higher_direction = _direction(higher_score)

    required_context = (
        "15m" in eligible
        and "1h" in eligible
        and bool({"4h", "1d"} & set(eligible))
    )
    enough_frames = len(eligible) >= 4
    analysis_ready = enough_frames and required_context
    if not analysis_ready:
        overall_direction = "INSUFFICIENT_CONTEXT"
    elif bullish and bearish:
        overall_direction = "MIXED_TIMEFRAME_DIRECTIONS"
    else:
        overall_direction = _direction(overall_score)
    alignment = (
        "MIXED_TIMEFRAME_DIRECTIONS" if bullish and bearish
        else "BULLISH_STRUCTURE_CONFLUENCE" if bullish and not bearish and len(bullish) >= 3
        else "BEARISH_STRUCTURE_CONFLUENCE" if bearish and not bullish and len(bearish) >= 3
        else "NO_CLEAR_STRUCTURE_CONFLUENCE"
    )
    directional_total = len(bullish) + len(bearish)
    agreement = (
        max(len(bullish), len(bearish)) / directional_total
        if directional_total else 0.0
    )
    expected_weight = sum(TIMEFRAME_WEIGHTS.values())
    available_weight = sum(TIMEFRAME_WEIGHTS[name] for name in eligible)
    weight_coverage = available_weight / expected_weight if expected_weight else 0.0

    latest_pattern_biases = {
        timeframe: reports[timeframe].get("candle_analysis", {}).get("latest_pattern_bias")
        for timeframe in eligible
    }
    (
        pattern_alignment,
        bullish_pattern_frames,
        bearish_pattern_frames,
        mixed_pattern_frames,
    ) = _summarize_latest_pattern_alignment(latest_pattern_biases)

    direction_ar = {
        "BULLISH": "صاعد",
        "BEARISH": "هابط",
        "MIXED_TIMEFRAME_DIRECTIONS": "متعارض بين الأطر الزمنية",
        "MIXED_OR_UNCONFIRMED": "مختلط أو غير مؤكد",
        "INSUFFICIENT_CONTEXT": "بيانات غير كافية لتحديد الاتجاه",
        "UNKNOWN": "غير معروف",
    }.get(overall_direction, "مختلط أو غير مؤكد")

    warnings: list[str] = []
    if timeframe_errors:
        warnings.append("Some timeframe histories are missing, stale, discontinuous, or invalid.")
    if bullish and bearish:
        warnings.append("Confirmed swing structures point in opposing directions across timeframes.")
    if pattern_alignment == "MIXED_CANDLE_PATTERN_EVIDENCE":
        warnings.append("Latest candle-pattern candidates conflict across timeframes.")
    if not required_context:
        warnings.append("The higher-timeframe structural context is incomplete.")

    return {
        **base,
        "status": "READY" if analysis_ready else "PARTIAL",
        "symbol": candle_history.get("symbol"),
        "broker_symbol": candle_history.get("broker_symbol"),
        "account_server": candle_history.get("account_server"),
        "as_of_utc_ms": as_of_ms,
        "direction": overall_direction,
        "direction_ar": direction_ar,
        "structure_score": round(overall_score, 4) if overall_score is not None else None,
        "swing_structure_score": round(swing_structure_score, 4) if swing_structure_score is not None else None,
        "summary": {
            "direction": overall_direction,
            "direction_ar": direction_ar,
            "structure_score": round(overall_score, 4) if overall_score is not None else None,
            "swing_structure_score": round(swing_structure_score, 4) if swing_structure_score is not None else None,
            "directional_evidence_weights": dict(DIRECTIONAL_EVIDENCE_WEIGHTS),
            "short_term_direction": short_direction,
            "short_term_structure_score": round(short_score, 4) if short_score is not None else None,
            "higher_timeframe_direction": higher_direction,
            "higher_timeframe_structure_score": round(higher_score, 4) if higher_score is not None else None,
            "timeframe_alignment": alignment,
            "eligible_timeframes": eligible,
            "eligible_timeframe_count": len(eligible),
            "bullish_structure_timeframes": bullish,
            "bearish_structure_timeframes": bearish,
            "mixed_or_unconfirmed_timeframes": mixed,
            "directional_structure_agreement": round(agreement, 4),
            "timeframe_weight_coverage": round(weight_coverage, 4),
            "latest_candle_pattern_alignment": pattern_alignment,
            "bullish_pattern_timeframes": bullish_pattern_frames,
            "bearish_pattern_timeframes": bearish_pattern_frames,
            "mixed_pattern_timeframes": mixed_pattern_frames,
        },
        "timeframes": reports,
        "timeframe_errors": timeframe_errors,
        "multi_timeframe_structure": {
            "status": "READY" if analysis_ready else "PARTIAL",
            "source": "NATIVE_MT5_OHLC",
            "as_of_utc_ms": as_of_ms,
            "alignment": alignment,
            "bullish_timeframes": bullish,
            "bearish_timeframes": bearish,
            "mixed_or_unconfirmed_timeframes": mixed,
        },
        "evidence_quality": {
            "eligible_timeframe_count": len(eligible),
            "expected_timeframe_count": len(TIMEFRAME_MS),
            "timeframe_weight_coverage": round(weight_coverage, 4),
            "directional_structure_agreement": round(agreement, 4),
            "interpretation": "STRUCTURAL_EVIDENCE_COVERAGE_NOT_STATISTICAL_PROBABILITY",
        },
        "warnings": warnings,
        "reason": None if analysis_ready else (
            "A multi-timeframe structural direction requires at least four ready frames, "
            "including 15m, 1h and at least one of 4h/1d."
        ),
        "safety": {
            "read_only": True,
            "decision_eligible": False,
            "creates_orders": False,
            "calculates_indicators": False,
            "controls_positions": False,
        },
        "methodology": {
            "candle_analysis": "Native OHLC candle anatomy and confirmed multi-candle formations; latest pattern direction contributes to the Engine 2 evidence score.",
            "swing_analysis": "Internal (1/1), swing (2/2) and external (4/4) confirmed peaks and troughs; primary directional evidence component.",
            "structure_events": "Closed-candle BOS/CHOCH breaks above/below confirmed swing levels; latest confirmed directional event contributes to the Engine 2 evidence score.",
            "liquidity_candidates": "Equal highs/lows and wick-through-then-close-back rejection around confirmed swing levels; latest confirmed sweep is a low-weight supporting component.",
            "directional_evidence_weights": dict(DIRECTIONAL_EVIDENCE_WEIGHTS),
            "price_zones": "Three-candle price gaps, opposing-candle zones tied to a confirmed break, and premium/discount range context.",
            "direction": "Higher-high/higher-low or lower-high/lower-low swing sequence; aggregated across timeframes with higher-frame weights.",
            "forming_candles": "Reported separately for context only and excluded from all pattern and structural direction calculations.",
        },
        "limitations": [
            "This Engine 2 path deliberately calculates no EMA, RSI, ATR, ADX, MACD, stochastic, or other technical indicator.",
            "Candle patterns are classifications, not probabilities or standalone trade signals.",
            "A swing high/low becomes known only after its right-side confirmation candles close.",
            "Order-block and liquidity labels describe price geometry; they do not prove institutional orders or resting order-book liquidity.",
            "The multi-timeframe direction is descriptive price-action confluence, not a guaranteed forecast.",
            "Image reading and chart drawings are separate deferred work and are not required for this native-OHLC path.",
        ],
    }


__all__ = ["analyze_mt5_native_price_action", "TIMEFRAME_MS", "TIMEFRAME_WEIGHTS"]
