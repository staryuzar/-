from __future__ import annotations

import math
from statistics import median
from typing import Any


def _pixel_close_y(bar: dict[str, Any]) -> float | None:
    """Return the close-edge y coordinate; smaller y means a higher price."""
    try:
        ratio = float(bar.get("body_ratio", 1.0))
        if not math.isfinite(ratio) or ratio >= 0.98:
            return None
        colour = str(bar.get("colour", "")).strip().upper()
        if colour in {"GREEN", "BLUE", "TEAL"}:
            value = float(bar["body_top_y_px"])
        elif colour in {"RED", "ORANGE", "MAGENTA"}:
            value = float(bar["body_bottom_y_px"])
        else:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _analyse_window(
    bars: list[dict[str, Any]],
    *,
    window: int,
    minimum_coverage: float,
    minimum_consistency: float,
    minimum_move_fraction: float,
) -> dict[str, Any]:
    recent = bars[-window:]
    points: list[tuple[float, float]] = []
    excluded = 0
    for bar in recent:
        close_y = _pixel_close_y(bar)
        if close_y is None:
            excluded += 1
            continue
        try:
            x_px = float(bar["x_px"])
        except (KeyError, TypeError, ValueError, OverflowError):
            excluded += 1
            continue
        if not math.isfinite(x_px):
            excluded += 1
            continue
        points.append((x_px, close_y))

    minimum_samples = max(4, int(math.ceil(window * minimum_coverage)))
    if len(points) < minimum_samples:
        return {
            "status": "INSUFFICIENT",
            "window_bars": window,
            "usable_bars": len(points),
            "excluded_bars": excluded,
            "direction": "NEUTRAL",
            "score": 0.0,
            "reason": "insufficient_body_separated_candles",
        }

    points.sort(key=lambda item: item[0])
    close_values = [item[1] for item in points]
    span = max(close_values) - min(close_values)
    if not math.isfinite(span) or span < 3.0:
        return {
            "status": "INSUFFICIENT",
            "window_bars": window,
            "usable_bars": len(points),
            "excluded_bars": excluded,
            "direction": "NEUTRAL",
            "score": 0.0,
            "reason": "pixel_close_range_too_small",
        }

    edge_size = min(3, max(1, len(close_values) // 4))
    first_edge = float(median(close_values[:edge_size]))
    last_edge = float(median(close_values[-edge_size:]))
    # Image coordinates run downward: a falling y coordinate means rising price.
    net_move_px = first_edge - last_edge
    move_fraction = abs(net_move_px) / span

    aligned_steps = 0
    directional_steps = 0
    for previous, current in zip(close_values, close_values[1:]):
        delta = previous - current
        if abs(delta) < 1.0:
            continue
        directional_steps += 1
        if (net_move_px > 0 and delta > 0) or (net_move_px < 0 and delta < 0):
            aligned_steps += 1
    consistency = aligned_steps / directional_steps if directional_steps else 0.0

    direction = "NEUTRAL"
    if move_fraction >= minimum_move_fraction and consistency >= minimum_consistency:
        direction = "BULLISH" if net_move_px > 0 else "BEARISH"
    signed_strength = (
        (1.0 if net_move_px > 0 else -1.0)
        * min(1.0, move_fraction * 2.0)
        * consistency
    )
    if direction == "NEUTRAL":
        signed_strength = 0.0

    return {
        "status": "READY",
        "window_bars": window,
        "usable_bars": len(points),
        "excluded_bars": excluded,
        "direction": direction,
        "score": round(max(-1.0, min(1.0, signed_strength)), 4),
        "net_move_px": round(net_move_px, 3),
        "visible_close_span_px": round(span, 3),
        "net_move_fraction": round(move_fraction, 4),
        "direction_consistency": round(consistency, 4),
        "directional_steps": directional_steps,
        "aligned_steps": aligned_steps,
    }


def analyze_pixel_visual_evidence(
    bars: list[dict[str, Any]],
    *,
    windows: tuple[int, ...] = (6, 12, 30),
    minimum_coverage: float = 0.60,
    minimum_consistency: float = 0.55,
    minimum_move_fraction: float = 0.08,
) -> dict[str, Any]:
    """Extract scale-free chart direction from body-close pixel positions.

    This is visual-only evidence. It never supplies calibrated OHLC and must not
    make an image eligible for Engine 4 or live execution.
    """
    if not isinstance(bars, list) or not bars:
        return {
            "status": "INSUFFICIENT",
            "method": "scale_free_pixel_close_trend",
            "direction": "NEUTRAL",
            "score": 0.0,
            "windows": {},
            "decision_eligible": False,
        }

    snapshots = {
        str(window): _analyse_window(
            bars,
            window=window,
            minimum_coverage=minimum_coverage,
            minimum_consistency=minimum_consistency,
            minimum_move_fraction=minimum_move_fraction,
        )
        for window in windows
        if isinstance(window, int) and window >= 4
    }
    ready = [item for item in snapshots.values() if item.get("status") == "READY"]
    directional = [
        item for item in ready
        if item.get("direction") in {"BULLISH", "BEARISH"}
    ]
    if not ready:
        overall_direction = "NEUTRAL"
        overall_score = 0.0
        status = "INSUFFICIENT"
    else:
        bullish_count = sum(item["direction"] == "BULLISH" for item in directional)
        bearish_count = sum(item["direction"] == "BEARISH" for item in directional)
        score_values = [float(item.get("score", 0.0)) for item in ready]
        overall_score = round(sum(score_values) / len(score_values), 4)
        status = "READY"
        if bullish_count >= 2 and bullish_count > bearish_count:
            overall_direction = "BULLISH"
        elif bearish_count >= 2 and bearish_count > bullish_count:
            overall_direction = "BEARISH"
        else:
            overall_direction = "NEUTRAL"

    return {
        "status": status,
        "method": "scale_free_pixel_close_trend",
        "direction": overall_direction,
        "score": overall_score,
        "windows": snapshots,
        "decision_eligible": False,
        "limitation": (
            "Relative pixel-coordinate trend only. No absolute price calibration, "
            "OHLC validation, Engine 4 eligibility, or execution authority."
        ),
    }
