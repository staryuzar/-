from __future__ import annotations

from typing import Any


def _fit_line(points: list[dict[str, Any]]) -> tuple[float, float, float]:
    """Return least-squares slope, intercept and maximum absolute residual."""
    if len(points) < 2:
        raise ValueError("At least two pivots are required to fit a trendline.")
    xs = [float(point["index"]) for point in points]
    ys = [float(point["price"]) for point in points]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        raise ValueError("Trendline pivots must have distinct candle indices.")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    residual = max(abs(y - (slope * x + intercept)) for x, y in zip(xs, ys))
    return slope, intercept, residual


def _line_value(line: tuple[float, float, float], index: int) -> float:
    return line[0] * float(index) + line[1]


def _best_impulse(
    bars: list[dict[str, Any]],
    consolidation_start: int,
    *,
    direction: str,
    atr: float,
    price: float,
) -> dict[str, Any] | None:
    """Find a directional pole ending before the consolidation begins."""
    start = max(0, consolidation_start - 50)
    end = consolidation_start - 2
    if end - start < 5:
        return None

    best: dict[str, Any] | None = None
    if direction == "BULLISH":
        for left in range(start, end - 2):
            for right in range(left + 3, end):
                move = float(bars[right]["high"]) - float(bars[left]["low"])
                if best is None or move > best["size"]:
                    best = {
                        "direction": direction, "start_index": left, "end_index": right,
                        "start_price": float(bars[left]["low"]),
                        "end_price": float(bars[right]["high"]), "size": move,
                    }
    else:
        for left in range(start, end - 2):
            for right in range(left + 3, end):
                move = float(bars[left]["high"]) - float(bars[right]["low"])
                if best is None or move > best["size"]:
                    best = {
                        "direction": direction, "start_index": left, "end_index": right,
                        "start_price": float(bars[left]["high"]),
                        "end_price": float(bars[right]["low"]), "size": move,
                    }

    minimum_pole = max(max(0.0, atr) * 2.5, price * 0.012)
    if best is None or best["size"] < minimum_pole:
        return None

    consolidation = bars[consolidation_start:]
    if not consolidation:
        return None
    consolidation_high = max(float(bar["high"]) for bar in consolidation)
    consolidation_low = min(float(bar["low"]) for bar in consolidation)
    consolidation_range = consolidation_high - consolidation_low
    if consolidation_range > best["size"] * 0.70:
        return None

    if direction == "BULLISH":
        retracement = (best["end_price"] - consolidation_low) / best["size"]
    else:
        retracement = (consolidation_high - best["end_price"]) / best["size"]
    if retracement < -0.05 or retracement > 0.55:
        return None

    best["consolidation_range"] = consolidation_range
    best["retracement_ratio"] = retracement
    best["size_atr"] = best["size"] / atr if atr > 0 else None
    return best


def _pattern_result(
    *,
    pattern_id: str,
    family: str,
    direction: str,
    high_points: list[dict[str, Any]],
    low_points: list[dict[str, Any]],
    bars: list[dict[str, Any]],
    high_line: tuple[float, float, float],
    low_line: tuple[float, float, float],
    start_index: int,
    formation_confirmed_at: int,
    tolerance: float,
    geometry: str,
    pole: dict[str, Any] | None = None,
) -> dict[str, Any]:
    end_index = len(bars) - 1
    upper_start = _line_value(high_line, start_index)
    lower_start = _line_value(low_line, start_index)
    upper_end = _line_value(high_line, end_index)
    lower_end = _line_value(low_line, end_index)

    status = "CANDIDATE"
    breakout_direction = None
    breakout_index = None
    breakout_level = None
    for index in range(formation_confirmed_at + 1, len(bars)):
        upper = _line_value(high_line, index)
        lower = _line_value(low_line, index)
        close = float(bars[index]["close"])
        if close > upper + tolerance * 0.20:
            status = "BREAKOUT_UP"
            breakout_direction = "UP"
            breakout_index = index
            breakout_level = upper
            break
        if close < lower - tolerance * 0.20:
            status = "BREAKOUT_DOWN"
            breakout_direction = "DOWN"
            breakout_index = index
            breakout_level = lower
            break

    result: dict[str, Any] = {
        "pattern_id": pattern_id, "family": family, "direction": direction,
        "status": status, "geometry": geometry,
        "pivot_indices": sorted([int(p["index"]) for p in high_points + low_points]),
        "high_pivot_indices": [int(p["index"]) for p in high_points],
        "low_pivot_indices": [int(p["index"]) for p in low_points],
        "formation_start_index": start_index,
        "formation_confirmed_at": formation_confirmed_at,
        "end_index": end_index,
        "upper_slope_per_bar": round(high_line[0], 10),
        "lower_slope_per_bar": round(low_line[0], 10),
        "upper_line_start": round(upper_start, 8),
        "lower_line_start": round(lower_start, 8),
        "upper_line_end": round(upper_end, 8),
        "lower_line_end": round(lower_end, 8),
        "width_start": round(upper_start - lower_start, 8),
        "width_end": round(upper_end - lower_end, 8),
        "trendline_max_residual": round(max(high_line[2], low_line[2]), 8),
        "breakout_direction": breakout_direction,
        "breakout_index": breakout_index,
        "breakout_level": round(breakout_level, 8) if breakout_level is not None else None,
        "tolerance": round(tolerance, 8),
        "confirmation_rule": "closed_candle_break_after_all_boundary_pivots_confirmed",
        "empirical_status": "UNVALIDATED",
    }
    if pole is not None:
        result["pole"] = pole
    return result


def detect_classical_continuation_patterns(
    bars: list[dict[str, Any]],
    swing_highs: list[dict[str, Any]],
    swing_lows: list[dict[str, Any]],
    *,
    atr: float,
) -> list[dict[str, Any]]:
    """Detect triangles, wedges, channels, flags and pennants from confirmed pivots.

    The output describes chart geometry only. A breakout is recognized only
    from a closed candle after every boundary pivot has become confirmable.
    """
    if len(bars) < 16 or len(swing_highs) < 3 or len(swing_lows) < 3:
        return []

    cutoff = max(0, len(bars) - 80)
    highs = sorted(
        [p for p in swing_highs if int(p["index"]) >= cutoff],
        key=lambda p: int(p["index"]),
    )[-4:]
    lows = sorted(
        [p for p in swing_lows if int(p["index"]) >= cutoff],
        key=lambda p: int(p["index"]),
    )[-4:]
    if len(highs) < 3 or len(lows) < 3:
        return []

    high_line = _fit_line(highs)
    low_line = _fit_line(lows)
    start_index = min(
        min(int(p["index"]) for p in highs),
        min(int(p["index"]) for p in lows),
    )
    end_index = len(bars) - 1
    span = end_index - start_index
    if span < 6:
        return []

    price = float(bars[-1]["close"])
    atr = max(float(atr), 0.0)
    tolerance = max(atr * 0.65, price * 0.0015)
    residual_limit = max(atr * 1.25, price * 0.003)
    if max(high_line[2], low_line[2]) > residual_limit:
        return []

    upper_start = _line_value(high_line, start_index)
    lower_start = _line_value(low_line, start_index)
    upper_end = _line_value(high_line, end_index)
    lower_end = _line_value(low_line, end_index)
    width_start = upper_start - lower_start
    width_end = upper_end - lower_end
    if width_start <= tolerance or width_end <= tolerance:
        return []

    upper_delta = upper_end - upper_start
    lower_delta = lower_end - lower_start
    horizontal_limit = max(atr * 0.60, price * 0.0015)
    upper_flat = abs(upper_delta) <= horizontal_limit
    lower_flat = abs(lower_delta) <= horizontal_limit
    upper_rising = upper_delta > horizontal_limit
    lower_rising = lower_delta > horizontal_limit
    upper_falling = upper_delta < -horizontal_limit
    lower_falling = lower_delta < -horizontal_limit
    converging = width_end < width_start * 0.90 and width_end > tolerance * 0.25

    formation_confirmed_at = max(
        int(p.get("confirmation_index", int(p["index"]) + 2))
        for p in highs + lows
    )
    patterns: list[dict[str, Any]] = []
    triangle_geometry: str | None = None
    channel_geometry: str | None = None

    if converging:
        if upper_flat and lower_rising:
            triangle_geometry = "ascending"
        elif upper_falling and lower_flat:
            triangle_geometry = "descending"
        elif upper_falling and lower_rising:
            triangle_geometry = "symmetrical"
        if triangle_geometry:
            patterns.append(_pattern_result(
                pattern_id=triangle_geometry + "_triangle", family="triangle",
                direction="NEUTRAL_COMPRESSION", high_points=highs, low_points=lows,
                bars=bars, high_line=high_line, low_line=low_line,
                start_index=start_index, formation_confirmed_at=formation_confirmed_at,
                tolerance=tolerance, geometry=triangle_geometry,
            ))

        if upper_rising and lower_rising and lower_delta > upper_delta + horizontal_limit * 0.15:
            patterns.append(_pattern_result(
                pattern_id="rising_wedge", family="wedge",
                direction="NEUTRAL_COMPRESSION", high_points=highs, low_points=lows,
                bars=bars, high_line=high_line, low_line=low_line,
                start_index=start_index, formation_confirmed_at=formation_confirmed_at,
                tolerance=tolerance, geometry="both_boundaries_rising_and_converging",
            ))
        elif upper_falling and lower_falling and upper_delta < lower_delta - horizontal_limit * 0.15:
            patterns.append(_pattern_result(
                pattern_id="falling_wedge", family="wedge",
                direction="NEUTRAL_COMPRESSION", high_points=highs, low_points=lows,
                bars=bars, high_line=high_line, low_line=low_line,
                start_index=start_index, formation_confirmed_at=formation_confirmed_at,
                tolerance=tolerance, geometry="both_boundaries_falling_and_converging",
            ))

    parallel_limit = max(atr * 0.60, price * 0.0015)
    width_change = abs(width_end - width_start)
    if (
        width_start > tolerance
        and width_change <= max(width_start * 0.25, parallel_limit)
        and abs(upper_delta - lower_delta) <= parallel_limit
    ):
        mean_delta = (upper_delta + lower_delta) / 2
        if mean_delta > horizontal_limit:
            channel_geometry, channel_id = "rising", "rising_channel"
        elif mean_delta < -horizontal_limit:
            channel_geometry, channel_id = "falling", "falling_channel"
        else:
            channel_geometry, channel_id = "horizontal", "horizontal_channel"
        patterns.append(_pattern_result(
            pattern_id=channel_id, family="channel", direction="NEUTRAL_RANGE",
            high_points=highs, low_points=lows, bars=bars,
            high_line=high_line, low_line=low_line, start_index=start_index,
            formation_confirmed_at=formation_confirmed_at, tolerance=tolerance,
            geometry="approximately_parallel_boundaries",
        ))

    pole_up = _best_impulse(bars, start_index, direction="BULLISH", atr=atr, price=price)
    pole_down = _best_impulse(bars, start_index, direction="BEARISH", atr=atr, price=price)
    poles = [pole for pole in (pole_up, pole_down) if pole is not None]
    best_pole = max(poles, key=lambda pole: float(pole["size"])) if poles else None

    if best_pole is not None and triangle_geometry == "symmetrical":
        pennant_id = "bull_pennant" if best_pole["direction"] == "BULLISH" else "bear_pennant"
        pennant_direction = (
            "BULLISH_CONTINUATION" if best_pole["direction"] == "BULLISH"
            else "BEARISH_CONTINUATION"
        )
        patterns.append(_pattern_result(
            pattern_id=pennant_id, family="pennant", direction=pennant_direction,
            high_points=highs, low_points=lows, bars=bars,
            high_line=high_line, low_line=low_line, start_index=start_index,
            formation_confirmed_at=formation_confirmed_at, tolerance=tolerance,
            geometry="impulse_pole_followed_by_symmetrical_convergence", pole=best_pole,
        ))

    if best_pole is not None and channel_geometry is not None:
        if best_pole["direction"] == "BULLISH" and upper_delta <= horizontal_limit and lower_delta <= horizontal_limit:
            patterns.append(_pattern_result(
                pattern_id="bull_flag", family="flag", direction="BULLISH_CONTINUATION",
                high_points=highs, low_points=lows, bars=bars,
                high_line=high_line, low_line=low_line, start_index=start_index,
                formation_confirmed_at=formation_confirmed_at, tolerance=tolerance,
                geometry="bullish_impulse_followed_by_flat_or_down_channel", pole=best_pole,
            ))
        elif best_pole["direction"] == "BEARISH" and upper_delta >= -horizontal_limit and lower_delta >= -horizontal_limit:
            patterns.append(_pattern_result(
                pattern_id="bear_flag", family="flag", direction="BEARISH_CONTINUATION",
                high_points=highs, low_points=lows, bars=bars,
                high_line=high_line, low_line=low_line, start_index=start_index,
                formation_confirmed_at=formation_confirmed_at, tolerance=tolerance,
                geometry="bearish_impulse_followed_by_flat_or_up_channel", pole=best_pole,
            ))

    unique: dict[tuple[str, tuple[int, ...]], dict[str, Any]] = {}
    for item in patterns:
        unique[(item["pattern_id"], tuple(item["pivot_indices"]))] = item
    return list(unique.values())[-12:]


__all__ = ["detect_classical_continuation_patterns"]
