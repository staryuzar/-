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


def calibrate_from_reference_candle(
    reference_bar: dict[str, Any],
    reference_ohlc: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
    plot_left_px: int = 0,
    plot_top_px: int = 0,
    plot_right_px: int | None = None,
    plot_bottom_px: int | None = None,
    scale_type: str = "linear",
    maximum_residual_fraction: float = 0.40,
) -> dict[str, Any]:
    """Calibrate an axis-less benchmark chart from an independently supplied last-candle OHLC anchor.

    This is an explicit reference-assisted path. It must never be enabled merely
    because a chart has no readable axis; callers must supply a trusted candle
    OHLC reference and retain the returned provenance in their report.
    """
    if not isinstance(reference_bar, dict) or not isinstance(reference_ohlc, dict):
        return {"status": "INVALID_REFERENCE", "reason": "reference bar and OHLC must be objects"}

    try:
        values = {key: float(reference_ohlc[key]) for key in ("open", "high", "low", "close")}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID_REFERENCE", "reason": "reference OHLC must contain finite numeric open/high/low/close"}
    if not all(math.isfinite(value) and value > 0 for value in values.values()):
        return {"status": "INVALID_REFERENCE", "reason": "reference OHLC values must be finite and positive"}
    if values["high"] < max(values["open"], values["close"], values["low"]):
        return {"status": "INVALID_REFERENCE", "reason": "reference high is below an OHLC value"}
    if values["low"] > min(values["open"], values["close"], values["high"]):
        return {"status": "INVALID_REFERENCE", "reason": "reference low is above an OHLC value"}
    candle_range = values["high"] - values["low"]
    if candle_range <= 0:
        return {"status": "INVALID_REFERENCE", "reason": "reference candle must have a positive high-low range"}

    colour = str(reference_bar.get("colour", "")).strip().upper()
    if values["close"] > values["open"]:
        expected_colour = "GREEN"
    elif values["close"] < values["open"]:
        expected_colour = "RED"
    else:
        expected_colour = "DOJI"
    if colour != expected_colour:
        return {
            "status": "REFERENCE_DIRECTION_MISMATCH",
            "reason": "detected last-candle colour conflicts with the reference OHLC direction",
            "detected_colour": colour or None,
            "expected_colour": expected_colour,
        }

    try:
        pixel = {
            "high": float(reference_bar["high_y_px"]),
            "low": float(reference_bar["low_y_px"]),
            "body_top": float(reference_bar["body_top_y_px"]),
            "body_bottom": float(reference_bar["body_bottom_y_px"]),
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID_REFERENCE_BAR", "reason": "reference bar is missing finite pixel geometry"}
    if not all(math.isfinite(value) for value in pixel.values()):
        return {"status": "INVALID_REFERENCE_BAR", "reason": "reference bar pixel geometry must be finite"}
    if not (
        pixel["high"] < pixel["low"]
        and pixel["body_top"] <= pixel["body_bottom"]
        and pixel["high"] <= pixel["body_top"] + 1
        and pixel["low"] >= pixel["body_bottom"] - 1
    ):
        return {"status": "INVALID_REFERENCE_BAR", "reason": "reference candle pixel geometry is inconsistent"}

    if expected_colour == "GREEN":
        pixel_open, pixel_close = pixel["body_bottom"], pixel["body_top"]
    elif expected_colour == "RED":
        pixel_open, pixel_close = pixel["body_top"], pixel["body_bottom"]
    else:
        midpoint = (pixel["body_top"] + pixel["body_bottom"]) / 2.0
        pixel_open = pixel_close = midpoint

    # Calibrate the pixel-to-price mapping from the two extreme wick anchors.
    # Open/close pixels are validation evidence, not extra fit points: on small
    # raster charts a body edge can share a row with a wick and must not distort
    # the scale fit.
    if math.isclose(pixel["high"], pixel["low"], rel_tol=0.0, abs_tol=1e-9):
        return {"status": "REFERENCE_GEOMETRY_AMBIGUOUS", "reason": "high and low collapse onto one pixel row"}

    scale = str(scale_type).strip().lower()
    if scale not in {"linear", "logarithmic"}:
        return {"status": "INVALID_SCALE", "reason": "scale_type must be linear or logarithmic"}
    high_value = math.log(values["high"]) if scale == "logarithmic" else values["high"]
    low_value = math.log(values["low"]) if scale == "logarithmic" else values["low"]
    slope = (low_value - high_value) / (pixel["low"] - pixel["high"])
    intercept = high_value - slope * pixel["high"]
    if not math.isfinite(slope) or slope >= 0:
        return {"status": "INVALID_REFERENCE_FIT", "reason": "price must decrease as image y increases"}

    def predict(y_px: float) -> float:
        raw = intercept + slope * y_px
        return math.exp(raw) if scale == "logarithmic" else raw

    body_residuals = {
        "open": abs(predict(pixel_open) - values["open"]) / candle_range,
        "close": abs(predict(pixel_close) - values["close"]) / candle_range,
    }
    maximum_residual = max(body_residuals.values())
    rms_residual = math.sqrt(sum(value * value for value in body_residuals.values()) / 2.0)
    if (
        not all(math.isfinite(value) for value in body_residuals.values())
        or maximum_residual > maximum_residual_fraction
    ):
        return {
            "status": "REFERENCE_FIT_REJECTED",
            "reason": "body open/close pixel positions do not agree with the high-low calibration",
            "maximum_residual_fraction": round(maximum_residual, 6),
            "rms_residual_fraction": round(rms_residual, 6),
            "body_residual_fraction_by_field": {
                key: round(value, 6) for key, value in body_residuals.items()
            },
            "tolerance": maximum_residual_fraction,
            "reference_pixel_rows": {key: round(value, 3) for key, value in pixel.items()},
        }

    right = image_width if plot_right_px is None else int(plot_right_px)
    bottom = image_height if plot_bottom_px is None else int(plot_bottom_px)
    left = int(plot_left_px)
    top = int(plot_top_px)
    if not (0 <= left < right <= image_width and 0 <= top < bottom <= image_height):
        return {"status": "INVALID_PLOT_BOUNDS", "reason": "plot bounds are outside the image"}

    top_price = predict(float(top))
    bottom_price = predict(float(bottom))
    if not (
        math.isfinite(top_price) and math.isfinite(bottom_price)
        and top_price > bottom_price > 0
    ):
        return {
            "status": "INVALID_REFERENCE_FIT",
            "reason": "reference anchor cannot produce a positive descending price axis over the selected plot",
            "derived_price_top": top_price,
            "derived_price_bottom": bottom_price,
        }

    calibration = {
        "plot_left_px": left,
        "plot_top_px": top,
        "plot_right_px": right,
        "plot_bottom_px": bottom,
        "price_top": top_price,
        "price_bottom": bottom_price,
        "price_scale_type": scale,
        "price_scale_valid": True,
        "plot_width_px": right - left,
        "plot_height_px": bottom - top,
    }
    return {
        "status": "READY",
        "calibration": calibration,
        "method": "reference_last_candle_ohlc_pixel_anchor",
        "reference_colour": expected_colour,
        "maximum_residual_fraction": round(maximum_residual, 6),
        "rms_residual_fraction": round(rms_residual, 6),
        "body_residual_fraction_by_field": {
            key: round(value, 6) for key, value in body_residuals.items()
        },
        "reference_pixel_rows": {key: round(value, 3) for key, value in pixel.items()},
    }


def validate_reference_candle_against_calibration(
    reference_bar: dict[str, Any],
    reference_ohlc: dict[str, Any],
    calibration: dict[str, Any],
    *,
    maximum_residual_fraction: float = 0.40,
) -> dict[str, Any]:
    """Cross-check a trusted native OHLC candle against an existing pixel/price axis.

    This does not refit an existing OCR/manual axis. It tests whether the axis
    maps the visible candle's wick and body pixels back to the supplied OHLC.
    """
    if not isinstance(reference_bar, dict) or not isinstance(reference_ohlc, dict):
        return {"status": "INVALID_REFERENCE", "reason": "reference bar and OHLC must be objects"}
    if not isinstance(calibration, dict) or not calibration.get("price_scale_valid"):
        return {"status": "INVALID_CALIBRATION", "reason": "an existing valid price axis is required"}

    try:
        values = {key: float(reference_ohlc[key]) for key in ("open", "high", "low", "close")}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID_REFERENCE", "reason": "reference OHLC must contain finite numeric values"}
    if not all(math.isfinite(value) and value > 0 for value in values.values()):
        return {"status": "INVALID_REFERENCE", "reason": "reference OHLC values must be finite and positive"}
    if values["high"] < max(values["open"], values["close"], values["low"]):
        return {"status": "INVALID_REFERENCE", "reason": "reference high is below an OHLC value"}
    if values["low"] > min(values["open"], values["close"], values["high"]):
        return {"status": "INVALID_REFERENCE", "reason": "reference low is above an OHLC value"}
    candle_range = values["high"] - values["low"]
    if candle_range <= 0:
        return {"status": "INVALID_REFERENCE", "reason": "reference candle must have a positive high-low range"}

    colour = str(reference_bar.get("colour", "")).strip().upper()
    expected_colour = (
        "GREEN" if values["close"] > values["open"]
        else "RED" if values["close"] < values["open"]
        else "DOJI"
    )
    if colour != expected_colour:
        return {
            "status": "REFERENCE_DIRECTION_MISMATCH",
            "reason": "detected last-candle colour conflicts with native OHLC direction",
            "detected_colour": colour or None,
            "expected_colour": expected_colour,
        }

    try:
        pixel = {
            "high": float(reference_bar["high_y_px"]),
            "low": float(reference_bar["low_y_px"]),
            "body_top": float(reference_bar["body_top_y_px"]),
            "body_bottom": float(reference_bar["body_bottom_y_px"]),
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "INVALID_REFERENCE_BAR", "reason": "reference bar is missing finite pixel geometry"}
    if not all(math.isfinite(value) for value in pixel.values()):
        return {"status": "INVALID_REFERENCE_BAR", "reason": "reference bar pixel geometry must be finite"}
    if not (
        pixel["high"] < pixel["low"]
        and pixel["body_top"] <= pixel["body_bottom"]
        and pixel["high"] <= pixel["body_top"] + 1
        and pixel["low"] >= pixel["body_bottom"] - 1
    ):
        return {"status": "INVALID_REFERENCE_BAR", "reason": "reference candle pixel geometry is inconsistent"}

    if expected_colour == "GREEN":
        pixel_open, pixel_close = pixel["body_bottom"], pixel["body_top"]
    elif expected_colour == "RED":
        pixel_open, pixel_close = pixel["body_top"], pixel["body_bottom"]
    else:
        midpoint = (pixel["body_top"] + pixel["body_bottom"]) / 2.0
        pixel_open = pixel_close = midpoint

    plot_top = float(calibration["plot_top_px"])
    plot_bottom = float(calibration["plot_bottom_px"])
    if any(y < plot_top or y > plot_bottom for y in pixel.values()):
        return {"status": "REFERENCE_PIXEL_OUTSIDE_PLOT", "reason": "native candle pixels fall outside the calibrated plot"}

    try:
        predicted = {
            "high": price_at_pixel(pixel["high"], calibration),
            "low": price_at_pixel(pixel["low"], calibration),
            "open": price_at_pixel(pixel_open, calibration),
            "close": price_at_pixel(pixel_close, calibration),
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"status": "INVALID_CALIBRATION", "reason": f"price mapping failed: {type(exc).__name__}"}

    residuals = {
        key: abs(predicted[key] - values[key]) / candle_range
        for key in ("high", "low", "open", "close")
    }
    maximum_residual = max(residuals.values())
    if not all(math.isfinite(value) for value in residuals.values()) or maximum_residual > maximum_residual_fraction:
        return {
            "status": "REFERENCE_AXIS_MISMATCH",
            "reason": "existing price-axis calibration does not reproduce the native MT5 OHLC candle",
            "maximum_residual_fraction": round(maximum_residual, 6),
            "residual_fraction_by_field": {key: round(value, 6) for key, value in residuals.items()},
            "predicted_ohlc": {key: round(value, 8) for key, value in predicted.items()},
            "native_ohlc": values,
            "tolerance": maximum_residual_fraction,
            "reference_pixel_rows": {key: round(value, 3) for key, value in pixel.items()},
        }
    return {
        "status": "READY",
        "method": "native_ohlc_against_existing_axis",
        "maximum_residual_fraction": round(maximum_residual, 6),
        "residual_fraction_by_field": {key: round(value, 6) for key, value in residuals.items()},
        "predicted_ohlc": {key: round(value, 8) for key, value in predicted.items()},
        "native_ohlc": values,
        "tolerance": maximum_residual_fraction,
        "reference_pixel_rows": {key: round(value, 3) for key, value in pixel.items()},
    }

