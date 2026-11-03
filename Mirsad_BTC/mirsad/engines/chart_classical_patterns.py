from __future__ import annotations

from typing import Any


def _ordered_pivots(
    swing_highs: list[dict[str, Any]],
    swing_lows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build an alternating sequence, keeping the more extreme same-side pivot."""
    by_index: dict[int, set[str]] = {}
    for pivot in swing_highs:
        by_index.setdefault(int(pivot["index"]), set()).add("high")
    for pivot in swing_lows:
        by_index.setdefault(int(pivot["index"]), set()).add("low")

    high_by_index = {int(p["index"]): p for p in swing_highs}
    low_by_index = {int(p["index"]): p for p in swing_lows}
    candidates: list[dict[str, Any]] = []
    for index in sorted(by_index):
        kinds = by_index[index]
        # OHLC does not reveal the intrabar order of a high and low on one bar.
        if len(kinds) != 1:
            continue
        kind = next(iter(kinds))
        source = high_by_index[index] if kind == "high" else low_by_index[index]
        candidates.append({
            "index": index,
            "price": float(source["price"]),
            "kind": kind,
            "confirmation_index": int(source.get("confirmation_index", index + 2)),
        })

    alternating: list[dict[str, Any]] = []
    for pivot in candidates:
        if alternating and alternating[-1]["kind"] == pivot["kind"]:
            previous = alternating[-1]
            more_extreme = (
                pivot["price"] > previous["price"]
                if pivot["kind"] == "high"
                else pivot["price"] < previous["price"]
            )
            if more_extreme:
                alternating[-1] = pivot
        else:
            alternating.append(pivot)
    return alternating


def _line_value(left: dict[str, Any], right: dict[str, Any], index: int) -> float:
    width = int(right["index"]) - int(left["index"])
    if width == 0:
        return float(right["price"])
    ratio = (index - int(left["index"])) / width
    return float(left["price"]) + (float(right["price"]) - float(left["price"])) * ratio


def _evaluate_pattern(
    *,
    pattern_id: str,
    direction: str,
    pivots: list[dict[str, Any]],
    bars: list[dict[str, float]],
    neckline_left: dict[str, Any],
    neckline_right: dict[str, Any],
    invalidation_level: float,
    tolerance: float,
) -> dict[str, Any]:
    formed_at = max(int(p["confirmation_index"]) for p in pivots)
    state = "CANDIDATE"
    confirmation_index = None
    invalidation_index = None
    neckline_break = None

    # Do not evaluate a formation until every right-hand pivot is confirmed.
    for index in range(formed_at + 1, len(bars)):
        close = float(bars[index]["close"])
        level = _line_value(neckline_left, neckline_right, index)
        if direction == "BEARISH":
            if close < level - tolerance:
                state = "CONFIRMED"
                confirmation_index = index
                neckline_break = level
                break
            if close > invalidation_level + tolerance:
                state = "INVALIDATED"
                invalidation_index = index
                break
        else:
            if close > level + tolerance:
                state = "CONFIRMED"
                confirmation_index = index
                neckline_break = level
                break
            if close < invalidation_level - tolerance:
                state = "INVALIDATED"
                invalidation_index = index
                break

    return {
        "pattern_id": pattern_id,
        "direction": direction,
        "status": state,
        "pivot_indices": [int(p["index"]) for p in pivots],
        "pivot_confirmation_indices": [int(p["confirmation_index"]) for p in pivots],
        "formation_confirmed_at": formed_at,
        "neckline_left": round(float(neckline_left["price"]), 8),
        "neckline_right": round(float(neckline_right["price"]), 8),
        "neckline_slope_per_bar": round(
            (float(neckline_right["price"]) - float(neckline_left["price"]))
            / max(1, int(neckline_right["index"]) - int(neckline_left["index"])),
            10,
        ),
        "neckline_break_level": round(float(neckline_break), 8) if neckline_break is not None else None,
        "confirmation_index": confirmation_index,
        "invalidation_level": round(float(invalidation_level), 8),
        "invalidation_index": invalidation_index,
        "tolerance": round(float(tolerance), 8),
        "confirmation_rule": "closed_candle_beyond_projected_neckline_after_all_pivots_confirmed",
        "invalidation_rule": "closed_candle_beyond_pattern_extreme_after_formation_confirmation",
        "empirical_status": "UNVALIDATED",
    }


def detect_classical_reversal_patterns(
    bars: list[dict[str, Any]],
    swing_highs: list[dict[str, Any]],
    swing_lows: list[dict[str, Any]],
    *,
    range_reference: float,
) -> list[dict[str, Any]]:
    """Detect conservative multi-swing reversal candidates from confirmed pivots.

    Supported structures: double top/bottom and head-and-shoulders/inverse.
    The function reports structural geometry only; it is not a trade signal.
    """
    if len(bars) < 10:
        return []

    sequence = _ordered_pivots(swing_highs, swing_lows)
    if len(sequence) < 3:
        return []

    close = float(bars[-1]["close"])
    tolerance = max(max(float(range_reference), 0.0) * 0.50, close * 0.001)
    prominence = max(max(float(range_reference), 0.0) * 0.50, close * 0.001)
    patterns: list[dict[str, Any]] = []

    triple = sequence[-3:]
    if [p["kind"] for p in triple] == ["high", "low", "high"]:
        first, valley, second = triple
        top_level = max(first["price"], second["price"])
        top_difference = abs(first["price"] - second["price"])
        depth = min(first["price"], second["price"]) - valley["price"]
        if (
            int(second["index"]) - int(first["index"]) >= 3
            and top_difference <= tolerance
            and depth >= prominence
        ):
            patterns.append(_evaluate_pattern(
                pattern_id="double_top", direction="BEARISH", pivots=triple,
                bars=bars, neckline_left=valley, neckline_right=valley,
                invalidation_level=top_level, tolerance=tolerance,
            ))

    if [p["kind"] for p in triple] == ["low", "high", "low"]:
        first, peak, second = triple
        bottom_level = min(first["price"], second["price"])
        bottom_difference = abs(first["price"] - second["price"])
        height = peak["price"] - max(first["price"], second["price"])
        if (
            int(second["index"]) - int(first["index"]) >= 3
            and bottom_difference <= tolerance
            and height >= prominence
        ):
            patterns.append(_evaluate_pattern(
                pattern_id="double_bottom", direction="BULLISH", pivots=triple,
                bars=bars, neckline_left=peak, neckline_right=peak,
                invalidation_level=bottom_level, tolerance=tolerance,
            ))

    five = sequence[-5:]
    kinds = [p["kind"] for p in five]
    if kinds == ["high", "low", "high", "low", "high"]:
        left_shoulder, left_neck, head, right_neck, right_shoulder = five
        shoulders_close = abs(left_shoulder["price"] - right_shoulder["price"]) <= tolerance
        head_prominent = head["price"] - max(left_shoulder["price"], right_shoulder["price"]) >= prominence
        if shoulders_close and head_prominent:
            patterns.append(_evaluate_pattern(
                pattern_id="head_and_shoulders", direction="BEARISH", pivots=five,
                bars=bars, neckline_left=left_neck, neckline_right=right_neck,
                invalidation_level=head["price"], tolerance=tolerance,
            ))

    if kinds == ["low", "high", "low", "high", "low"]:
        left_shoulder, left_neck, head, right_neck, right_shoulder = five
        shoulders_close = abs(left_shoulder["price"] - right_shoulder["price"]) <= tolerance
        head_prominent = min(left_shoulder["price"], right_shoulder["price"]) - head["price"] >= prominence
        if shoulders_close and head_prominent:
            patterns.append(_evaluate_pattern(
                pattern_id="inverse_head_and_shoulders", direction="BULLISH", pivots=five,
                bars=bars, neckline_left=left_neck, neckline_right=right_neck,
                invalidation_level=head["price"], tolerance=tolerance,
            ))

    unique: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
    for item in patterns:
        unique[(item["pattern_id"], tuple(item["pivot_indices"]))] = item
    return list(unique.values())[-4:]


__all__ = ["detect_classical_reversal_patterns"]
