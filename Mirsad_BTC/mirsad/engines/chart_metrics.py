from __future__ import annotations

from typing import Any

import numpy as np


def _empty_structure() -> dict[str, Any]:
    return {
        "status": "INSUFFICIENT",
        "direction": "UNKNOWN",
        "score": None,
        "swing_highs": [],
        "swing_lows": [],
        "higher_highs": False,
        "higher_lows": False,
        "lower_highs": False,
        "lower_lows": False,
        "support": None,
        "resistance": None,
        "support_zones": [],
        "resistance_zones": [],
        "entry_zone": None,
        "exit_zone": None,
        "distance_to_support_pct": None,
        "distance_to_resistance_pct": None,
    }


def _build_zones(
    pivots: list[dict[str, Any]],
    *,
    tolerance: float,
    current_price: float,
    side: str,
) -> list[dict[str, Any]]:
    if not pivots:
        return []
    levels = sorted(
        (float(item["price"]), int(item["index"]))
        for item in pivots
        if np.isfinite(float(item["price"])) and float(item["price"]) > 0
    )
    if not levels:
        return []
    clusters: list[list[tuple[float, int]]] = []
    for level in levels:
        if not clusters:
            clusters.append([level])
            continue
        current_mean = float(np.mean([x[0] for x in clusters[-1]]))
        if abs(level[0] - current_mean) <= tolerance:
            clusters[-1].append(level)
        else:
            clusters.append([level])

    zones: list[dict[str, Any]] = []
    half_width = tolerance * 0.5
    for cluster in clusters:
        prices = [item[0] for item in cluster]
        midpoint = float(np.mean(prices))
        lower = min(prices) - half_width
        upper = max(prices) + half_width
        if side == "support" and midpoint > current_price + tolerance:
            continue
        if side == "resistance" and midpoint < current_price - tolerance:
            continue
        zones.append({
            "lower": round(lower, 8),
            "upper": round(upper, 8),
            "midpoint": round(midpoint, 8),
            "touches": len(cluster),
            "pivot_indices": [item[1] for item in cluster],
            "distance_pct": round((midpoint - current_price) / current_price * 100.0, 5),
        })
    return zones


def _trend_window(
    closes: np.ndarray, *, visible_range: float, window: int
) -> dict[str, Any]:
    recent = closes[-window:]
    if len(recent) < 2:
        return {
            "status": "INSUFFICIENT",
            "sample_bars": int(len(recent)),
            "direction": "NEUTRAL",
            "score": 0.0,
            "net_change": None,
            "net_change_pct": None,
            "direction_consistency": 0.0,
        }
    steps = np.diff(recent)
    rising = int(np.count_nonzero(steps > 0))
    falling = int(np.count_nonzero(steps < 0))
    required = int(np.ceil(len(steps) * 0.60))
    dominant = max(rising, falling)
    ratio = dominant / max(1, len(steps))
    net_change = float(recent[-1] - recent[0])
    minimum_move = max(abs(float(recent[0])) * 0.0002, visible_range * 0.012)
    move_met = abs(net_change) >= minimum_move
    consistency_met = dominant >= required
    sign = 1.0 if net_change > 0 else -1.0 if net_change < 0 else 0.0
    if not move_met or not consistency_met:
        sign = 0.0
    magnitude = min(1.0, abs(net_change) / max(visible_range * 0.08, 1e-12))
    score = sign * magnitude * ratio
    direction = "BULLISH" if score > 0.05 else "BEARISH" if score < -0.05 else "NEUTRAL"
    return {
        "status": "READY",
        "sample_bars": int(len(recent)),
        "direction": direction,
        "score": round(float(np.clip(score, -1.0, 1.0)), 4),
        "net_change": round(net_change, 8),
        "net_change_pct": round(net_change / abs(float(recent[0])) * 100.0, 6) if recent[0] else None,
        "rising_close_steps": rising,
        "falling_close_steps": falling,
        "required_directional_steps": required,
        "minimum_move": round(minimum_move, 8),
        "directional_steps_met": bool(consistency_met),
        "minimum_move_met": bool(move_met),
        "direction_consistency": round(ratio, 4),
    }


def analyze_calibrated_bars(
    calibrated: list[dict[str, Any]], *, top_price: float, bottom_price: float
) -> dict[str, Any]:
    """Analyse calibrated OHLC in time order and report auditable evidence."""
    visual_trend: dict[str, Any] = {
        "sample_bars": 0,
        "net_change": None,
        "net_change_pct": None,
        "visible_range_fraction": None,
        "rising_close_steps": 0,
        "falling_close_steps": 0,
        "required_directional_steps": 0,
        "minimum_move": None,
        "directional_steps_met": False,
        "minimum_move_met": False,
        "direction_consistency": 0.0,
        "score": 0.0,
        "direction": "NEUTRAL",
        "windows": {},
    }
    market_structure = _empty_structure()
    momentum: dict[str, Any] = {
        "status": "INSUFFICIENT",
        "score": None,
        "change": None,
        "change_pct": None,
    }
    pattern_score = 0.0
    analysis_score = 0.0
    analysis_confidence = 0.0
    confidence_components: dict[str, float] = {}
    bias = "NEUTRAL"

    if len(calibrated) < 6:
        return {
            "visual_bias": bias,
            "visual_trend": visual_trend,
            "market_structure": market_structure,
            "momentum": momentum,
            "pattern_score": pattern_score,
            "analysis_score": analysis_score,
            "analysis_confidence": analysis_confidence,
            "confidence_components": confidence_components,
            "confidence_kind": "heuristic_evidence_quality_not_probability",
        }

    recent = calibrated[-30:]
    closes = np.asarray([float(bar["close"]) for bar in recent], dtype=float)
    highs = np.asarray([float(bar["high"]) for bar in recent], dtype=float)
    lows = np.asarray([float(bar["low"]) for bar in recent], dtype=float)
    if not np.isfinite(closes).all() or not np.isfinite(highs).all() or not np.isfinite(lows).all():
        raise ValueError("Calibrated OHLC contains non-finite prices.")
    if np.any(closes <= 0) or np.any(highs <= 0) or np.any(lows <= 0):
        raise ValueError("Calibrated OHLC prices must be positive.")

    visible_range = float(top_price - bottom_price)
    if not np.isfinite(visible_range) or visible_range <= 0:
        raise ValueError("Visible price range must be positive and finite.")

    windows: dict[str, Any] = {}
    for key, count in (("short_6", 6), ("medium_12", 12), ("long_30", 30)):
        windows[key] = _trend_window(closes, visible_range=visible_range, window=count)
    dominant = windows["long_30"]

    visual_trend = {
        "sample_bars": len(recent),
        "net_change": dominant.get("net_change"),
        "net_change_pct": dominant.get("net_change_pct"),
        "visible_range_fraction": round(float(dominant["net_change"]) / visible_range, 6),
        "rising_close_steps": dominant["rising_close_steps"],
        "falling_close_steps": dominant["falling_close_steps"],
        "required_directional_steps": dominant["required_directional_steps"],
        "minimum_move": dominant["minimum_move"],
        "directional_steps_met": dominant["directional_steps_met"],
        "minimum_move_met": dominant["minimum_move_met"],
        "direction_consistency": dominant["direction_consistency"],
        "score": dominant["score"],
        "direction": dominant["direction"],
        "windows": windows,
    }
    trend_score = float(dominant["score"])
    direction_ratio = float(dominant["direction_consistency"])

    # Two-sided, two-candle-shoulder pivots; indices refer to the full input list.
    swing_highs: list[dict[str, Any]] = []
    swing_lows: list[dict[str, Any]] = []
    base_index = len(calibrated) - len(recent)
    for index in range(2, len(recent) - 2):
        high_window = highs[index - 2:index + 3]
        low_window = lows[index - 2:index + 3]
        if (
            highs[index] >= np.max(high_window)
            and highs[index] > max(highs[index - 2:index])
            and highs[index] >= max(highs[index + 1:index + 3])
        ):
            swing_highs.append({
                "index": base_index + index,
                "price": float(highs[index]),
            })
        if (
            lows[index] <= np.min(low_window)
            and lows[index] < min(lows[index - 2:index])
            and lows[index] <= min(lows[index + 1:index + 3])
        ):
            swing_lows.append({
                "index": base_index + index,
                "price": float(lows[index]),
            })

    higher_highs = bool(len(swing_highs) >= 2 and swing_highs[-1]["price"] > swing_highs[-2]["price"])
    lower_highs = bool(len(swing_highs) >= 2 and swing_highs[-1]["price"] < swing_highs[-2]["price"])
    higher_lows = bool(len(swing_lows) >= 2 and swing_lows[-1]["price"] > swing_lows[-2]["price"])
    lower_lows = bool(len(swing_lows) >= 2 and swing_lows[-1]["price"] < swing_lows[-2]["price"])

    structure_score: float | None = None
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        high_direction = 1.0 if higher_highs else -1.0 if lower_highs else 0.0
        low_direction = 1.0 if higher_lows else -1.0 if lower_lows else 0.0
        structure_score = (high_direction + low_direction) / 2.0

    current_price = float(closes[-1])
    zone_tolerance = max(visible_range * 0.015, current_price * 0.001)
    support_zones = _build_zones(
        swing_lows, tolerance=zone_tolerance, current_price=current_price, side="support"
    )
    resistance_zones = _build_zones(
        swing_highs, tolerance=zone_tolerance, current_price=current_price, side="resistance"
    )
    supports = [zone["midpoint"] for zone in support_zones]
    resistances = [zone["midpoint"] for zone in resistance_zones]
    support = max(supports) if supports else (float(np.min(lows)) if len(lows) else None)
    resistance = min(resistances) if resistances else (float(np.max(highs)) if len(highs) else None)

    entry_zone = None
    exit_zone = None
    if trend_score > 0.05:
        nearby_support = [zone for zone in support_zones if zone["midpoint"] <= current_price]
        if nearby_support:
            nearest = min(nearby_support, key=lambda zone: current_price - zone["midpoint"])
            entry_zone = {**nearest, "kind": "BULLISH_PULLBACK_WATCH", "status": "OBSERVATION_ONLY"}
        future_resistance = [zone for zone in resistance_zones if zone["midpoint"] > current_price]
        if future_resistance:
            nearest = min(future_resistance, key=lambda zone: zone["midpoint"] - current_price)
            exit_zone = {**nearest, "kind": "NEXT_RESISTANCE_WATCH", "status": "OBSERVATION_ONLY"}
    elif trend_score < -0.05:
        nearby_resistance = [zone for zone in resistance_zones if zone["midpoint"] >= current_price]
        if nearby_resistance:
            nearest = min(nearby_resistance, key=lambda zone: zone["midpoint"] - current_price)
            entry_zone = {**nearest, "kind": "BEARISH_PULLBACK_WATCH", "status": "OBSERVATION_ONLY"}
        future_support = [zone for zone in support_zones if zone["midpoint"] < current_price]
        if future_support:
            nearest = max(future_support, key=lambda zone: zone["midpoint"])
            exit_zone = {**nearest, "kind": "NEXT_SUPPORT_WATCH", "status": "OBSERVATION_ONLY"}

    market_structure = {
        "status": "READY" if structure_score is not None else "PARTIAL",
        "direction": (
            "BULLISH" if structure_score == 1.0
            else "BEARISH" if structure_score == -1.0
            else "MIXED_OR_UNKNOWN"
        ),
        "score": round(structure_score, 4) if structure_score is not None else None,
        "swing_highs": swing_highs[-8:],
        "swing_lows": swing_lows[-8:],
        "higher_highs": higher_highs,
        "higher_lows": higher_lows,
        "lower_highs": lower_highs,
        "lower_lows": lower_lows,
        "support": round(support, 8) if support is not None else None,
        "resistance": round(resistance, 8) if resistance is not None else None,
        "support_zones": support_zones[-6:],
        "resistance_zones": resistance_zones[-6:],
        "entry_zone": entry_zone,
        "exit_zone": exit_zone,
        "distance_to_support_pct": round((current_price - support) / current_price * 100.0, 5) if support is not None and current_price > 0 else None,
        "distance_to_resistance_pct": round((resistance - current_price) / current_price * 100.0, 5) if resistance is not None and current_price > 0 else None,
    }

    if len(closes) >= 6:
        momentum_change = float(closes[-1] - closes[-6])
        momentum_direction = 1.0 if momentum_change > 0 else -1.0 if momentum_change < 0 else 0.0
        momentum_consistency = max(
            np.count_nonzero(np.diff(closes[-6:]) > 0),
            np.count_nonzero(np.diff(closes[-6:]) < 0),
        ) / 5.0
        momentum_minimum_move = max(abs(float(closes[-6])) * 0.0001, visible_range * 0.005)
        if abs(momentum_change) < momentum_minimum_move:
            momentum_direction = 0.0
        momentum_score = (
            momentum_direction
            * min(1.0, abs(momentum_change) / max(visible_range * 0.025, 1e-12))
            * momentum_consistency
        )
        momentum = {
            "status": "READY",
            "score": round(float(np.clip(momentum_score, -1.0, 1.0)), 4),
            "change": round(momentum_change, 8),
            "change_pct": round(momentum_change / abs(float(closes[-6])) * 100.0, 6) if closes[-6] else None,
            "minimum_move": round(momentum_minimum_move, 8),
        }

    # Candlestick patterns stay diagnostic. They do not steer trend direction.
    components: list[tuple[float, float]] = [(trend_score, 0.65)]
    if structure_score is not None:
        components.append((structure_score, 0.25))
    if momentum.get("score") is not None:
        components.append((float(momentum["score"]), 0.10))
    weight_sum = sum(weight for _, weight in components)
    analysis_score = float(np.clip(
        sum(score * weight for score, weight in components) / weight_sum,
        -1.0,
        1.0,
    ))
    if analysis_score >= 0.20:
        bias = "BULLISH"
    elif analysis_score <= -0.20:
        bias = "BEARISH"

    sample_quality = min(1.0, len(recent) / 24.0)
    pivot_quality = min(1.0, min(len(swing_highs), len(swing_lows)) / 2.0)
    colour_quality = float(np.mean([
        float(bar.get("colour_purity", 0.0)) for bar in recent[-24:]
    ]))
    trend_strength = min(1.0, abs(float(dominant["net_change"])) / max(visible_range * 0.08, 1e-12))
    if structure_score is None or trend_score == 0 or structure_score == 0:
        structure_alignment = 0.5
    elif (trend_score > 0) == (structure_score > 0):
        structure_alignment = 1.0
    else:
        structure_alignment = 0.0
    confidence_components = {
        "sample_completeness": round(sample_quality, 4),
        "direction_consistency": round(direction_ratio, 4),
        "swing_structure_completeness": round(pivot_quality, 4),
        "colour_purity": round(colour_quality, 4),
        "net_move_strength": round(trend_strength, 4),
        "trend_structure_alignment": round(structure_alignment, 4),
    }
    analysis_confidence = float(np.clip(
        0.25 * sample_quality
        + 0.20 * direction_ratio
        + 0.15 * pivot_quality
        + 0.15 * colour_quality
        + 0.15 * trend_strength
        + 0.10 * structure_alignment,
        0.0,
        1.0,
    ))
    if structure_score is None:
        analysis_confidence = min(analysis_confidence, 0.69)

    return {
        "visual_bias": bias,
        "visual_trend": visual_trend,
        "market_structure": market_structure,
        "momentum": momentum,
        "pattern_score": pattern_score,
        "analysis_score": analysis_score,
        "analysis_confidence": analysis_confidence,
        "confidence_components": confidence_components,
        "confidence_kind": "heuristic_evidence_quality_not_probability",
    }
