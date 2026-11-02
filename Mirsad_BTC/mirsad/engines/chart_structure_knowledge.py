from __future__ import annotations

from statistics import median
from typing import Any

from .chart_classical_patterns import detect_classical_reversal_patterns

def _validate_bars(bars: list[dict[str, Any]]) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for index, bar in enumerate(bars):
        try:
            item = {key: float(bar[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid OHLC at candle index {index}: {exc}") from exc
        if not all(value == value and abs(value) != float("inf") for value in item.values()):
            raise ValueError(f"Non-finite OHLC at candle index {index}")
        if item["low"] <= 0 or item["high"] < max(item["open"], item["close"], item["low"]) or item["low"] > min(item["open"], item["close"]):
            raise ValueError(f"Inconsistent OHLC bounds at candle index {index}")
        normalized.append(item)
    return normalized

def _true_ranges(bars: list[dict[str, float]]) -> list[float]:
    values: list[float] = []
    previous_close: float | None = None
    for bar in bars:
        high, low = bar["high"], bar["low"]
        tr = high - low if previous_close is None else max(high - low, abs(high - previous_close), abs(low - previous_close))
        values.append(tr)
        previous_close = bar["close"]
    return values

def _pivots(bars: list[dict[str, float]], left: int, right: int, kind: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    key = "high" if kind == "high" else "low"
    for index in range(left, len(bars) - right):
        value = bars[index][key]
        neighbours = [bar[key] for bar in bars[index - left:index + right + 1]]
        before = [bar[key] for bar in bars[index - left:index]]
        after = [bar[key] for bar in bars[index + 1:index + right + 1]]
        is_pivot = (
            value >= max(neighbours) and value > max(before) and value >= max(after)
            if kind == "high"
            else value <= min(neighbours) and value < min(before) and value <= min(after)
        )
        if is_pivot:
            result.append({
                "index": index, "price": value, "kind": kind,
                "confirmed": True, "confirmation_index": index + right,
                "left_bars": left, "right_bars": right,
            })
    return result

def _sequence(highs: list[dict[str, Any]], lows: list[dict[str, Any]]) -> dict[str, Any]:
    hh = len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"]
    lh = len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]
    hl = len(lows) >= 2 and lows[-1]["price"] > lows[-2]["price"]
    ll = len(lows) >= 2 and lows[-1]["price"] < lows[-2]["price"]
    if hh and hl:
        direction = "BULLISH"
    elif lh and ll:
        direction = "BEARISH"
    else:
        direction = "MIXED_OR_UNKNOWN"
    return {"higher_highs": bool(hh), "higher_lows": bool(hl),
            "lower_highs": bool(lh), "lower_lows": bool(ll),
            "direction": direction}

def _equal_levels(pivots: list[dict[str, Any]], tolerance: float) -> list[dict[str, Any]]:
    if len(pivots) < 2:
        return []
    clusters: list[list[dict[str, Any]]] = []
    for pivot in sorted(pivots, key=lambda x: x["price"]):
        if not clusters or abs(pivot["price"] - median([p["price"] for p in clusters[-1]])) > tolerance:
            clusters.append([pivot])
        else:
            clusters[-1].append(pivot)
    return [
        {
            "level": round(median([p["price"] for p in cluster]), 8),
            "touches": len(cluster),
            "pivot_indices": [p["index"] for p in cluster],
            "tolerance": round(tolerance, 8),
            "status": "CANDIDATE_LIQUIDITY_POOL",
        }
        for cluster in clusters if len(cluster) >= 2
    ]

def analyze_chart_structure_knowledge(
    bars: list[dict[str, Any]], *, last_candle_closed: bool = True,
) -> dict[str, Any]:
    """Analyse internal/swing/external structure on one supplied chart timeframe."""
    normalized = _validate_bars(bars)
    confirmed = normalized if last_candle_closed else normalized[:-1]
    if len(confirmed) < 8:
        return {
            "status": "INSUFFICIENT", "confirmed_bars": len(confirmed),
            "internal": {}, "swing": {}, "external": {},
            "bos_choch_events": [], "liquidity_sweeps": [],
            "equal_highs": [], "equal_lows": [], "fair_value_gaps": [],
            "classical_patterns": [],
            "premium_discount": None,
            "limitations": ["At least eight confirmed candles are required for this structure pass."],
        }

    true_ranges = _true_ranges(confirmed)
    atr_window = true_ranges[-14:] if true_ranges else []
    atr = median(atr_window) if atr_window else 0.0
    current = confirmed[-1]["close"]
    tolerance = max(atr * 0.15, current * 0.0001)

    scales = {
        "internal": (1, 1),
        "swing": (2, 2),
        "external": (4, 4),
    }
    reports: dict[str, Any] = {}
    pivot_sets: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for name, (left, right) in scales.items():
        highs = _pivots(confirmed, left, right, "high")
        lows = _pivots(confirmed, left, right, "low")
        sequence = _sequence(highs, lows)
        reports[name] = {
            "left_bars": left, "right_bars": right,
            "swing_highs": highs[-20:], "swing_lows": lows[-20:],
            **sequence,
            "status": "READY" if len(highs) >= 2 and len(lows) >= 2 else "PARTIAL",
        }
        pivot_sets[name] = (highs, lows)

    swing_highs, swing_lows = pivot_sets["swing"]
    overall_sequence = reports["swing"]
    events: list[dict[str, Any]] = []
    sweeps: list[dict[str, Any]] = []
    previous_close_by_index = {i: confirmed[i - 1]["close"] for i in range(1, len(confirmed))}

    def prior_direction_at(index: int) -> str:
        # Historical classification must use only pivots confirmed before
        # this event; using the final chart direction would introduce look-ahead.
        available_highs = [p for p in swing_highs if int(p["confirmation_index"]) < index]
        available_lows = [p for p in swing_lows if int(p["confirmation_index"]) < index]
        return _sequence(available_highs, available_lows)["direction"]

    for pivot in swing_highs:
        pivot_index = int(pivot["index"])
        level = float(pivot["price"])
        for index in range(int(pivot["confirmation_index"]) + 1, len(confirmed)):
            previous_close = previous_close_by_index.get(index)
            close = confirmed[index]["close"]
            high = confirmed[index]["high"]
            if previous_close is not None and previous_close <= level < close:
                prior_direction = prior_direction_at(index)
                event_name = "CHOCH_BULLISH" if prior_direction == "BEARISH" else "BOS_BULLISH"
                events.append({
                    "event": event_name, "level": level, "pivot_index": pivot_index,
                    "confirmation_index": index, "confirmation": "closed_candle_above_confirmed_swing_high",
                    "prior_structure": prior_direction,
                })
                break
            if high > level and close <= level:
                sweeps.append({
                    "event": "HIGH_LIQUIDITY_SWEEP", "side": "BEARISH_REJECTION",
                    "level": level, "pivot_index": pivot_index, "confirmation_index": index,
                    "confirmation": "wick_above_confirmed_high_then_close_back_below",
                })
                break

    for pivot in swing_lows:
        pivot_index = int(pivot["index"])
        level = float(pivot["price"])
        for index in range(int(pivot["confirmation_index"]) + 1, len(confirmed)):
            previous_close = previous_close_by_index.get(index)
            close = confirmed[index]["close"]
            low = confirmed[index]["low"]
            if previous_close is not None and previous_close >= level > close:
                prior_direction = prior_direction_at(index)
                event_name = "CHOCH_BEARISH" if prior_direction == "BULLISH" else "BOS_BEARISH"
                events.append({
                    "event": event_name, "level": level, "pivot_index": pivot_index,
                    "confirmation_index": index, "confirmation": "closed_candle_below_confirmed_swing_low",
                    "prior_structure": prior_direction,
                })
                break
            if low < level and close >= level:
                sweeps.append({
                    "event": "LOW_LIQUIDITY_SWEEP", "side": "BULLISH_REJECTION",
                    "level": level, "pivot_index": pivot_index, "confirmation_index": index,
                    "confirmation": "wick_below_confirmed_low_then_close_back_above",
                })
                break

    # Order-block candidates are anchored only to an already confirmed BOS/CHOCH.
    # They are price zones derived from the last opposing candle, not proof of institutional orders.
    order_blocks: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda x: x["confirmation_index"]):
        event_index = int(event["confirmation_index"])
        pivot_index = int(event["pivot_index"])
        event_name = str(event["event"])
        bullish_break = event_name in {"BOS_BULLISH", "CHOCH_BULLISH"}
        bearish_break = event_name in {"BOS_BEARISH", "CHOCH_BEARISH"}
        if not (bullish_break or bearish_break):
            continue
        lower_bound = max(pivot_index + 1, event_index - 8)
        candidate_index = None
        for index in range(event_index - 1, lower_bound - 1, -1):
            candle = confirmed[index]
            if (bearish_break and candle["close"] > candle["open"]) or (
                bullish_break and candle["close"] < candle["open"]
            ):
                candidate_index = index
                break
        if candidate_index is None:
            order_blocks.append({
                "event": event_name, "status": "NO_OPPOSING_CANDLE",
                "break_index": event_index, "pivot_index": pivot_index,
                "direction": "BULLISH" if bullish_break else "BEARISH",
            })
            continue

        source = confirmed[candidate_index]
        zone_low, zone_high = source["low"], source["high"]
        state = "UNMITIGATED_AT_SAMPLE_END"
        mitigation_index = None
        invalidation_index = None
        for index in range(event_index + 1, len(confirmed)):
            candle = confirmed[index]
            if bullish_break and candle["close"] < zone_low:
                state = "INVALIDATED"
                invalidation_index = index
                break
            if bearish_break and candle["close"] > zone_high:
                state = "INVALIDATED"
                invalidation_index = index
                break
            if candle["low"] <= zone_high and candle["high"] >= zone_low:
                state = "MITIGATED"
                mitigation_index = index
                break
        order_blocks.append({
            "structure_id": "bullish_order_block" if bullish_break else "bearish_order_block",
            "direction": "BULLISH" if bullish_break else "BEARISH",
            "status": state, "source_candle_index": candidate_index,
            "break_index": event_index, "pivot_index": pivot_index,
            "zone_low": zone_low, "zone_high": zone_high,
            "mitigation_index": mitigation_index,
            "invalidation_index": invalidation_index,
            "confirmation": "last_opposing_candle_before_confirmed_structure_break",
            "interpretation": "ORDER_BLOCK_CANDIDATE_NOT_INSTITUTIONAL_ORDER_EVIDENCE",
        })

    equal_highs = _equal_levels(swing_highs, tolerance)
    equal_lows = _equal_levels(swing_lows, tolerance)

    gaps: list[dict[str, Any]] = []
    for index in range(2, len(confirmed)):
        first, third = confirmed[index - 2], confirmed[index]
        if first["high"] < third["low"]:
            low, high = first["high"], third["low"]
            mitigated = any(
                confirmed[j]["low"] <= high and confirmed[j]["high"] >= low
                for j in range(index + 1, len(confirmed))
            )
            gaps.append({
                "structure_id": "bullish_fvg", "index": index,
                "zone_low": low, "zone_high": high,
                "midpoint": (low + high) / 2,
                "status": "MITIGATED" if mitigated else "UNMITIGATED_AT_SAMPLE_END",
                "confirmation": "three_closed_candle_price_imbalance",
            })
        elif first["low"] > third["high"]:
            low, high = third["high"], first["low"]
            mitigated = any(
                confirmed[j]["high"] >= low and confirmed[j]["low"] <= high
                for j in range(index + 1, len(confirmed))
            )
            gaps.append({
                "structure_id": "bearish_fvg", "index": index,
                "zone_low": low, "zone_high": high,
                "midpoint": (low + high) / 2,
                "status": "MITIGATED" if mitigated else "UNMITIGATED_AT_SAMPLE_END",
                "confirmation": "three_closed_candle_price_imbalance",
            })

    classical_patterns = detect_classical_reversal_patterns(
        confirmed, swing_highs, swing_lows, atr=atr,
    )

    premium_discount = None
    external_highs, external_lows = pivot_sets["external"]
    if external_highs and external_lows:
        latest_external_high = max(external_highs, key=lambda pivot: int(pivot["index"]))
        latest_external_low = max(external_lows, key=lambda pivot: int(pivot["index"]))
        range_high = float(latest_external_high["price"])
        range_low = float(latest_external_low["price"])
        if range_high > range_low:
            equilibrium = (range_high + range_low) / 2
            premium_discount = {
                "range_high": range_high, "range_low": range_low,
                "equilibrium": equilibrium, "current_price": current,
                "position": "DISCOUNT" if current < equilibrium else "PREMIUM",
                "range_source": "latest_confirmed_external_high_low_pair",
                "range_high_pivot_index": int(latest_external_high["index"]),
                "range_low_pivot_index": int(latest_external_low["index"]),
            }

    return {
        "status": "READY" if reports["swing"]["status"] == "READY" else "PARTIAL",
        "confirmed_bars": len(confirmed),
        "atr_proxy": round(atr, 8),
        "scales": reports,
        "structure_direction": overall_sequence["direction"],
        "bos_choch_events": sorted(events, key=lambda x: x["confirmation_index"])[-20:],
        "liquidity_sweeps": sorted(sweeps, key=lambda x: x["confirmation_index"])[-20:],
        "order_block_candidates": order_blocks[-20:],
        "equal_highs": equal_highs,
        "equal_lows": equal_lows,
        "fair_value_gaps": gaps[-30:],
        "classical_patterns": classical_patterns,
        "premium_discount": premium_discount,
        "limitations": [
            "Internal, swing and external are pivot scales inside this one supplied timeframe, not true multi-timeframe analysis.",
            "Order-block detections are candidates linked to a confirmed structural break; they do not prove institutional orders. Breaker and mitigation block detectors are not implemented.",
            "A wick sweep describes price behaviour around a confirmed level; it does not prove actual resting orders or institutional activity.",
            "Fair value gaps are three-candle price-range imbalances and may be caused by ordinary volatility.",
            "Classical double-top/bottom and head-and-shoulders structures are geometric candidates only; their empirical BTC performance is unvalidated.",
            "Classical structure confirmation waits until every right-side pivot is confirmed, then requires a closed-candle neckline break; it does not create a trade vote.",
            "All event timestamps are candle indices because screenshot-derived OHLC may not include reliable timestamps.",
        ],
    }

__all__ = ["analyze_chart_structure_knowledge"]
