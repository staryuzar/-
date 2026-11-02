from __future__ import annotations

import math
from typing import Any


def resolve_chart_calibration(
    metadata: dict[str, Any], *, image_width: int, image_height: int
) -> dict[str, Any]:
    """Validate the visible plot rectangle and the user-supplied price axis."""
    def pixel_value(key: str, fallback: int) -> int:
        raw = metadata.get(key, fallback)
        value = int(raw or 0)
        return fallback if value == 0 else value

    left = pixel_value("plot_left_px", 0)
    top = pixel_value("plot_top_px", 0)
    right = pixel_value("plot_right_px", image_width)
    bottom = pixel_value("plot_bottom_px", image_height)
    if not (0 <= left < right <= image_width and 0 <= top < bottom <= image_height):
        raise ValueError("plot bounds must be inside the image and have positive width/height")
    if right - left < 32 or bottom - top < 32:
        raise ValueError("plot rectangle is too small to identify reliable candle geometry")

    scale_type = str(metadata.get("price_scale_type", "linear")).strip().lower()
    if scale_type not in {"linear", "logarithmic"}:
        raise ValueError("price_scale_type must be linear or logarithmic")
    try:
        top_price = float(metadata.get("price_top"))
        bottom_price = float(metadata.get("price_bottom"))
    except (TypeError, ValueError, OverflowError):
        top_price = bottom_price = float("nan")
    scale_valid = (
        math.isfinite(top_price) and math.isfinite(bottom_price)
        and top_price > bottom_price > 0
    )
    if scale_valid and scale_type == "logarithmic":
        scale_valid = bottom_price > 0 and top_price / bottom_price > 1.0
    return {
        "plot_left_px": left,
        "plot_top_px": top,
        "plot_right_px": right,
        "plot_bottom_px": bottom,
        "price_top": top_price if math.isfinite(top_price) else None,
        "price_bottom": bottom_price if math.isfinite(bottom_price) else None,
        "price_scale_type": scale_type,
        "price_scale_valid": bool(scale_valid),
        "plot_width_px": right - left,
        "plot_height_px": bottom - top,
    }


def price_at_pixel(y_px: int | float, calibration: dict[str, Any]) -> float:
    if not calibration.get("price_scale_valid"):
        raise ValueError("price axis is not calibrated")
    top = float(calibration["price_top"])
    bottom = float(calibration["price_bottom"])
    y_top = float(calibration["plot_top_px"])
    y_bottom = float(calibration["plot_bottom_px"])
    ratio = (float(y_px) - y_top) / (y_bottom - y_top)
    ratio = min(1.0, max(0.0, ratio))
    if calibration["price_scale_type"] == "logarithmic":
        return math.exp(math.log(top) - ratio * (math.log(top) - math.log(bottom)))
    return top - ratio * (top - bottom)


def calibrate_bars(
    bars: list[dict[str, Any]], calibration: dict[str, Any]
) -> list[dict[str, Any]]:
    if not calibration.get("price_scale_valid"):
        return []
    calibrated: list[dict[str, Any]] = []
    for bar in bars:
        def price_at(y: int) -> float:
            return price_at_pixel(y, calibration)
        if bar["colour"] == "GREEN":
            open_price = price_at(bar["body_bottom_y_px"])
            close_price = price_at(bar["body_top_y_px"])
        else:
            open_price = price_at(bar["body_top_y_px"])
            close_price = price_at(bar["body_bottom_y_px"])
        candle = {
            **bar,
            "open": open_price,
            "close": close_price,
            "high": price_at(bar["high_y_px"]),
            "low": price_at(bar["low_y_px"]),
        }
        if not (
            all(math.isfinite(float(candle[k])) and float(candle[k]) > 0 for k in ("open", "high", "low", "close"))
            and candle["high"] >= max(candle["open"], candle["close"], candle["low"])
            and candle["low"] <= min(candle["open"], candle["close"], candle["high"])
        ):
            continue
        calibrated.append(candle)
    return calibrated
