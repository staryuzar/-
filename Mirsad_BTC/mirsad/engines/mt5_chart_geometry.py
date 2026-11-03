from __future__ import annotations

import math
from statistics import median
from typing import Any

GEOMETRY_SCHEMA = "MIR-MT5-CHART-GEOMETRY-1"
_POINT_FIELDS = ("open", "high", "low", "close")


def native_geometry_visible_y_max(native_geometry: Any) -> float | None:
    """Return the greatest provisional image Y among valid visible native OHLC points."""
    if not isinstance(native_geometry, dict) or native_geometry.get("status") != "READY_FOR_PIXEL_ALIGNMENT":
        return None
    bars = native_geometry.get("bars")
    if not isinstance(bars, list):
        return None
    values: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict) or bar.get("valid") is not True or bar.get("visible") is not True:
            continue
        points = bar.get("points_image_px_provisional")
        if not isinstance(points, dict):
            continue
        for point in points.values():
            if not isinstance(point, dict):
                continue
            try:
                y = float(point["y"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(y):
                values.append(y)
    return max(values) if values else None


def validate_mt5_chart_geometry(
    raw_geometry: Any,
    *,
    bars: list[dict[str, Any]],
    chart: dict[str, Any],
    image_width: int,
    image_height: int,
) -> dict[str, Any]:
    """Validate MT5's native time/price-to-pixel geometry without trusting its claims.

    The returned image coordinates are provisional dimension-ratio transforms.
    They remain ineligible for visual alignment until a separate pixel-overlay
    check verifies the transform against the PNG itself.
    """
    if not isinstance(raw_geometry, dict):
        return {
            "status": "NOT_AVAILABLE",
            "decision_eligible": False,
            "reason": "The capture has no native MT5 pixel-geometry payload.",
            "bars": [],
        }

    if raw_geometry.get("schema") != GEOMETRY_SCHEMA:
        return {
            "status": "SCHEMA_MISMATCH",
            "decision_eligible": False,
            "reason": "The MT5 pixel-geometry schema is missing or unsupported.",
            "bars": [],
        }
    if raw_geometry.get("coordinate_source") != "MQL5_CHART_TIME_PRICE_TO_XY":
        return {
            "status": "SOURCE_MISMATCH",
            "decision_eligible": False,
            "reason": "Pixel coordinates are not identified as native ChartTimePriceToXY output.",
            "bars": [],
        }
    if raw_geometry.get("coordinate_origin") != "MAIN_CHART_WINDOW_TOP_LEFT":
        return {
            "status": "ORIGIN_MISMATCH",
            "decision_eligible": False,
            "reason": "The coordinate origin is not the main chart window's upper-left corner.",
            "bars": [],
        }

    try:
        source_width = int(raw_geometry["source_width_px"])
        source_height = int(raw_geometry["source_height_px"])
        declared_image_width = int(raw_geometry["image_width_px"])
        declared_image_height = int(raw_geometry["image_height_px"])
        declared_total = int(raw_geometry["bars_total"])
        declared_valid = int(raw_geometry["bars_valid"])
        declared_visible = int(raw_geometry["bars_visible"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {
            "status": "INVALID_METADATA",
            "decision_eligible": False,
            "reason": "Native geometry dimensions or counters are incomplete.",
            "bars": [],
        }

    chart_width = int(chart.get("source_width_px", 0) or 0)
    chart_height = int(chart.get("source_main_window_height_px", 0) or 0)
    if (
        source_width <= 0 or source_height <= 0
        or source_width != chart_width or source_height != chart_height
    ):
        return {
            "status": "SOURCE_DIMENSION_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry dimensions do not match the chart manifest dimensions.",
            "bars": [],
        }
    if declared_image_width != int(image_width) or declared_image_height != int(image_height):
        return {
            "status": "IMAGE_DIMENSION_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry dimensions do not match the decoded PNG dimensions.",
            "bars": [],
        }
    if declared_total != len(bars):
        return {
            "status": "BAR_COUNT_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry bar count does not match the CopyRates OHLC array.",
            "bars": [],
        }

    raw_items = raw_geometry.get("bars")
    if not isinstance(raw_items, list) or len(raw_items) != len(bars):
        return {
            "status": "BAR_ARRAY_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry must contain one item for every copied OHLC bar.",
            "bars": [],
        }

    scale_x = image_width / source_width
    scale_y = image_height / source_height
    output: list[dict[str, Any]] = []
    valid_count = 0
    visible_count = 0
    previous_x: float | None = None

    for index, (item, native) in enumerate(zip(raw_items, bars)):
        if not isinstance(item, dict):
            return {
                "status": "INVALID_BAR_GEOMETRY",
                "decision_eligible": False,
                "reason": f"Geometry item {index} is not an object.",
                "bars": output,
            }
        try:
            stamp = int(item["time_server_ms"])
            closed = item["is_closed"]
            item_x = float(item["x_px"])
            valid = item.get("valid") is True
            visible = item.get("visible") is True
        except (KeyError, TypeError, ValueError, OverflowError):
            return {
                "status": "INVALID_BAR_GEOMETRY",
                "decision_eligible": False,
                "reason": f"Geometry item {index} has incomplete identity or validity metadata.",
                "bars": output,
            }

        if stamp != int(native["time_server_ms"]) or closed is not native["is_closed"]:
            return {
                "status": "BAR_IDENTITY_MISMATCH",
                "decision_eligible": False,
                "reason": f"Geometry item {index} does not match its OHLC timestamp/close state.",
                "bars": output,
            }
        if not math.isfinite(item_x):
            return {
                "status": "NON_FINITE_COORDINATE",
                "decision_eligible": False,
                "reason": f"Geometry item {index} has a non-finite X coordinate.",
                "bars": output,
            }

        # ChartTimePriceToXY can legitimately fail for bars whose OHLC points
        # are outside the drawable chart area. MQL5 serializes those points as
        # null and marks the item invalid/invisible. Preserve that fact without
        # discarding the entire geometry sample; visible invalid bars remain a
        # hard failure.
        if not valid:
            if visible:
                return {
                    "status": "VISIBLE_POINT_INVALID",
                    "decision_eligible": False,
                    "reason": f"Geometry item {index} is declared visible but its point set is invalid.",
                    "bars": output,
                }
            output.append({
                "index": index,
                "time_server_ms": stamp,
                "is_closed": closed,
                "valid": False,
                "visible": False,
                "x_source_px": item_x,
                "x_image_px_provisional": None,
                "points_source_px": None,
                "points_image_px_provisional": None,
                "x_alignment_error_px": None,
            })
            continue

        points: dict[str, dict[str, float]] = {}
        try:
            for name in _POINT_FIELDS:
                point = item.get(name)
                if not isinstance(point, dict):
                    raise ValueError(f"{name} point missing")
                points[name] = {
                    "x": float(point["x_px"]),
                    "y": float(point["y_px"]),
                }
        except (KeyError, TypeError, ValueError, OverflowError):
            return {
                "status": "INVALID_BAR_GEOMETRY",
                "decision_eligible": False,
                "reason": f"Valid geometry item {index} has incomplete point coordinates.",
                "bars": output,
            }

        values = [coordinate for point in points.values() for coordinate in point.values()]
        if not all(math.isfinite(value) for value in values) or not math.isfinite(item_x):
            return {
                "status": "NON_FINITE_COORDINATE",
                "decision_eligible": False,
                "reason": f"Geometry item {index} contains a non-finite coordinate.",
                "bars": output,
            }

        x_values = [points[name]["x"] for name in _POINT_FIELDS]
        x_error = max(x_values) - min(x_values)
        if x_error > 1.0:
            return {
                "status": "X_ALIGNMENT_FAILED",
                "decision_eligible": False,
                "reason": f"OHLC points for candle {index} do not share one time coordinate.",
                "bars": output,
            }

        high_y = points["high"]["y"]
        low_y = points["low"]["y"]
        body_top_y = min(points["open"]["y"], points["close"]["y"])
        body_bottom_y = max(points["open"]["y"], points["close"]["y"])
        if high_y > body_top_y + 1.0 or low_y < body_bottom_y - 1.0 or high_y > low_y:
            return {
                "status": "Y_ORDER_FAILED",
                "decision_eligible": False,
                "reason": f"Geometry item {index} has impossible High/Body/Low pixel ordering.",
                "bars": output,
            }

        valid_count += 1
        if previous_x is not None and item_x <= previous_x:
            return {
                "status": "X_SEQUENCE_INVALID",
                "decision_eligible": False,
                "reason": "Native chart X coordinates must increase with chronological OHLC bars.",
                "bars": output,
            }
        previous_x = item_x
        if visible:
            visible_count += 1

        output.append({
            "index": index,
            "time_server_ms": stamp,
            "is_closed": closed,
            "valid": valid,
            "visible": visible,
            "x_source_px": item_x,
            "x_image_px_provisional": item_x * scale_x,
            "points_source_px": points,
            "points_image_px_provisional": {
                name: {
                    "x": points[name]["x"] * scale_x,
                    "y": points[name]["y"] * scale_y,
                }
                for name in _POINT_FIELDS
            },
            "x_alignment_error_px": round(x_error, 4),
        })

    # Counters are audited but not trusted as a substitute for the array itself.
    if declared_valid != valid_count or declared_visible != visible_count:
        return {
            "status": "COUNTER_MISMATCH",
            "decision_eligible": False,
            "reason": "Native geometry counters do not match the validated items.",
            "bars": output,
            "validated_bars": valid_count,
            "visible_bars": visible_count,
        }

    minimum_visible = max(8, int(chart.get("visible_bars", 0) * 0.50))
    if valid_count < 8 or visible_count < minimum_visible:
        return {
            "status": "PARTIAL",
            "decision_eligible": False,
            "reason": "Too few native OHLC points are visible and valid for pixel alignment.",
            "validated_bars": valid_count,
            "visible_bars": visible_count,
            "minimum_visible_bars": minimum_visible,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "mapping_status": "UNVERIFIED_PROVISIONAL_DIMENSION_RATIO",
            "bars": output,
        }

    return {
        "status": "READY_FOR_PIXEL_ALIGNMENT",
        "decision_eligible": False,
        "source": "MT5_CHART_TIME_PRICE_TO_XY",
        "coordinate_origin": "MAIN_CHART_WINDOW_TOP_LEFT",
        "source_width_px": source_width,
        "source_height_px": source_height,
        "image_width_px": image_width,
        "image_height_px": image_height,
        "validated_bars": valid_count,
        "visible_bars": visible_count,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "mapping_status": "UNVERIFIED_PROVISIONAL_DIMENSION_RATIO",
        "reason": "Native geometry passed structural validation; PNG coordinate alignment still requires an independent visual overlay test.",
        "bars": output,
    }


def validate_mt5_geometry_overlay(
    geometry_validation: dict[str, Any],
    *,
    native_bars: list[dict[str, Any]],
    extracted_bars: list[dict[str, Any]],
    visible_bars: int,
    first_visible_bar_shift: int,
    residual_limit_px: float = 13.5,
    minimum_validation_pass_ratio: float = 0.80,
) -> dict[str, Any]:
    """Validate the affine mapping from native MT5 coordinates to detected PNG candles.

    Fit candles determine the coordinate transform; interleaved hold-out candles
    independently verify it. This function never authorizes a trading decision.
    """
    def fail(status: str, reason: str, **extra: Any) -> dict[str, Any]:
        return {"status": status, "mapping_verified": False, "decision_eligible": False,
                "reason": reason, **extra}

    if geometry_validation.get("status") not in {"READY_FOR_PIXEL_ALIGNMENT", "PARTIAL"}:
        return fail("GEOMETRY_NOT_READY", "Native MT5 geometry did not pass structural validation.")
    if visible_bars < 8 or not native_bars or not extracted_bars:
        return fail("INSUFFICIENT_INPUT", "Visible native bars and extracted image candles are required.")
    if not math.isfinite(residual_limit_px) or residual_limit_px <= 0:
        return fail("INVALID_THRESHOLD", "Overlay residual threshold must be positive and finite.")

    geometry_items = geometry_validation.get("bars")
    if not isinstance(geometry_items, list) or len(geometry_items) != len(native_bars):
        return fail("GEOMETRY_BAR_COUNT_MISMATCH", "Validated geometry does not cover the native OHLC array.")

    extracted_by_slot: dict[int, dict[str, Any]] = {}
    for item in extracted_bars:
        if not isinstance(item, dict):
            continue
        try:
            slot = int(item["slot_index"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if slot in extracted_by_slot:
            return fail("DUPLICATE_IMAGE_SLOT", "More than one extracted candle occupies the same image slot.")
        extracted_by_slot[slot] = item

    rightmost_visible_offset = max(0, int(first_visible_bar_shift) - int(visible_bars) + 1)
    matched: list[dict[str, Any]] = []
    for index, (geometry, native) in enumerate(zip(geometry_items, native_bars)):
        if not isinstance(geometry, dict) or geometry.get("valid") is not True or geometry.get("visible") is not True:
            continue
        offset = len(native_bars) - 1 - index
        relative_offset = offset - rightmost_visible_offset
        if not 0 <= relative_offset < visible_bars:
            continue
        slot = visible_bars - 1 - relative_offset
        extracted = extracted_by_slot.get(slot)
        if extracted is None:
            continue
        if int(geometry.get("time_server_ms", -1)) != int(native.get("time_server_ms", -2)):
            return fail("NATIVE_BAR_IDENTITY_MISMATCH", "Geometry timestamp does not match its OHLC source bar.")
        points = geometry.get("points_source_px")
        if not isinstance(points, dict) or any(not isinstance(points.get(name), dict) for name in _POINT_FIELDS):
            continue
        try:
            x_source = float(geometry["x_source_px"])
            x_image = float(extracted["x_px"])
            y_source = {name: float(points[name]["y"]) for name in _POINT_FIELDS}
            y_image = {
                "high": float(extracted["high_y_px"]),
                "low": float(extracted["low_y_px"]),
            }
            open_price, close_price = float(native["open"]), float(native["close"])
            if close_price > open_price:
                y_image["open"] = float(extracted["body_bottom_y_px"])
                y_image["close"] = float(extracted["body_top_y_px"])
            elif close_price < open_price:
                y_image["open"] = float(extracted["body_top_y_px"])
                y_image["close"] = float(extracted["body_bottom_y_px"])
            else:
                midpoint = (float(extracted["body_top_y_px"]) + float(extracted["body_bottom_y_px"])) / 2.0
                y_image["open"] = midpoint
                y_image["close"] = midpoint
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        coordinates = [x_source, x_image, *y_source.values(), *y_image.values()]
        if not all(math.isfinite(value) for value in coordinates):
            continue
        matched.append({
            "slot_index": slot,
            "x_source": x_source,
            "x_image": x_image,
            "y_source": y_source,
            "y_image": y_image,
        })

    matched.sort(key=lambda row: row["slot_index"])

    def coordinate_range(values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"min": None, "max": None, "span": None}
        return {
            "min": round(min(values), 3),
            "max": round(max(values), 3),
            "span": round(max(values) - min(values), 3),
        }

    coordinate_diagnostics = {
        "x_source": coordinate_range([row["x_source"] for row in matched]),
        "x_image": coordinate_range([row["x_image"] for row in matched]),
        "y_source": {
            name: coordinate_range([row["y_source"][name] for row in matched])
            for name in _POINT_FIELDS
        },
        "y_image": {
            name: coordinate_range([row["y_image"][name] for row in matched])
            for name in _POINT_FIELDS
        },
        "sample_matches": [
            {
                "slot_index": row["slot_index"],
                "x_source": round(row["x_source"], 3),
                "x_image": round(row["x_image"], 3),
                "y_source": {name: round(row["y_source"][name], 3) for name in _POINT_FIELDS},
                "y_image": {name: round(row["y_image"][name], 3) for name in _POINT_FIELDS},
            }
            for row in matched[:3]
        ],
    }

    if len(matched) < 8:
        return fail("INSUFFICIENT_MATCHED_CANDLES",
                    "At least eight exact-slot native/image candle pairs are required.",
                    matched_candles=len(matched),
                    coordinate_diagnostics=coordinate_diagnostics)

    fit_rows = [row for row in matched if row["slot_index"] % 4 != 0]
    holdout_rows = [row for row in matched if row["slot_index"] % 4 == 0]
    if len(fit_rows) < 5 or len(holdout_rows) < 3:
        return fail("INSUFFICIENT_HOLDOUT", "Affine fit and independent hold-out samples are too small.",
                    matched_candles=len(matched), fit_candles=len(fit_rows),
                    validation_candles=len(holdout_rows))

    def robust_affine(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
        slopes = [
            (y2 - y1) / (x2 - x1)
            for i, (x1, y1) in enumerate(pairs)
            for x2, y2 in pairs[i + 1:]
            if abs(x2 - x1) >= 2.0
        ]
        if not slopes:
            return None
        slope = float(median(slopes))
        intercept = float(median(y - slope * x for x, y in pairs))
        if not math.isfinite(slope) or not math.isfinite(intercept) or slope <= 0:
            return None
        return slope, intercept

    x_fit = robust_affine([(row["x_source"], row["x_image"]) for row in fit_rows])
    y_fit = robust_affine([
        (row["y_source"][name], row["y_image"][name])
        for row in fit_rows for name in _POINT_FIELDS
    ])
    if x_fit is None or y_fit is None:
        return fail("AFFINE_FIT_FAILED", "Native-to-image coordinates do not produce positive affine transforms.")

    x_scale, x_offset = x_fit
    y_scale, y_offset = y_fit
    validation_rows = []
    for row in holdout_rows:
        x_error = abs(x_scale * row["x_source"] + x_offset - row["x_image"])
        y_errors = {
            name: abs(y_scale * row["y_source"][name] + y_offset - row["y_image"][name])
            for name in _POINT_FIELDS
        }
        maximum = max([x_error, *y_errors.values()])
        validation_rows.append({
            "slot_index": row["slot_index"],
            "x_residual_px": round(x_error, 3),
            "y_residual_px_by_point": {key: round(value, 3) for key, value in y_errors.items()},
            "maximum_residual_px": round(maximum, 3),
            "passed": maximum <= residual_limit_px,
        })

    passed = [row for row in validation_rows if row["passed"]]
    ratio = len(passed) / len(validation_rows)
    median_error = float(median(row["maximum_residual_px"] for row in validation_rows))
    required = max(3, math.ceil(len(validation_rows) * minimum_validation_pass_ratio))
    if len(passed) < required or median_error > residual_limit_px * 0.5:
        return fail(
            "OVERLAY_HOLDOUT_FAILED",
            "Independent native-to-image candle overlay does not meet residual and pass-ratio limits.",
            matched_candles=len(matched), fit_candles=len(fit_rows),
            validation_candles=len(holdout_rows), validation_passed_candles=len(passed),
            validation_pass_ratio=round(ratio, 4),
            validation_median_max_residual_px=round(median_error, 3),
            validation_max_residual_px=max(row["maximum_residual_px"] for row in validation_rows),
            residual_limit_px=residual_limit_px, validation_rows=validation_rows,
            x_scale=round(x_scale, 8), x_offset=round(x_offset, 4),
            y_scale=round(y_scale, 8), y_offset=round(y_offset, 4),
            coordinate_diagnostics=coordinate_diagnostics,
        )

    return {
        "status": "READY",
        "mapping_verified": True,
        "decision_eligible": False,
        "method": "native_mt5_geometry_affine_fit_with_interleaved_image_holdout",
        "matched_candles": len(matched),
        "fit_candles": len(fit_rows),
        "validation_candles": len(holdout_rows),
        "validation_passed_candles": len(passed),
        "validation_pass_ratio": round(ratio, 4),
        "validation_median_max_residual_px": round(median_error, 3),
        "validation_max_residual_px": max(row["maximum_residual_px"] for row in validation_rows),
        "residual_limit_px": residual_limit_px,
        "x_scale": round(x_scale, 8),
        "x_offset": round(x_offset, 4),
        "y_scale": round(y_scale, 8),
        "y_offset": round(y_offset, 4),
        "validation_rows": validation_rows,
        "coordinate_diagnostics": coordinate_diagnostics,
    }


def analyze_native_mt5_ohlc(
    bars: list[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Run pattern and structure analysis on original MT5 OHLC, not pixel-reconstructed prices."""
    from .chart_pattern_knowledge import analyze_candle_patterns
    from .chart_pattern_reference import analyze_talib_pattern_reference
    from .chart_structure_knowledge import analyze_chart_structure_knowledge

    if not isinstance(bars, list) or not bars:
        return {
            "status": "INSUFFICIENT",
            "source": "MT5_COPYRATES",
            "decision_eligible": False,
            "patterns": {"status": "INSUFFICIENT", "detected": []},
            "reference_patterns": {"status": "INSUFFICIENT", "events": []},
            "structure": {"status": "INSUFFICIENT"},
        }

    if any(not isinstance(bar.get("is_closed"), bool) for bar in bars):
        return {
            "status": "INVALID_BAR_STATE",
            "source": "MT5_COPYRATES",
            "decision_eligible": False,
            "reason": "Every native OHLC bar must carry an explicit closed/forming state.",
        }
    if any(not bar["is_closed"] for bar in bars[:-1]) or bars[-1]["is_closed"]:
        return {
            "status": "INVALID_BAR_SEQUENCE",
            "source": "MT5_COPYRATES",
            "decision_eligible": False,
            "reason": "Only the latest MT5 OHLC bar may be forming.",
        }

    patterns = analyze_candle_patterns(bars, last_candle_closed=False)
    reference_patterns = analyze_talib_pattern_reference(
        bars, last_candle_closed=False
    )
    structure = analyze_chart_structure_knowledge(
        bars, last_candle_closed=False
    )

    def add_times(items: list[dict[str, Any]], start_key: str, end_key: str) -> None:
        for item in items:
            start = item.get(start_key)
            end = item.get(end_key)
            if isinstance(start, int) and 0 <= start < len(bars):
                item["start_time_server_ms"] = bars[start]["time_server_ms"]
            if isinstance(end, int) and 0 <= end < len(bars):
                item["end_time_server_ms"] = bars[end]["time_server_ms"]

    add_times(patterns.get("detected", []), "start_index", "end_index")
    add_times(reference_patterns.get("events", []), "formation_start_index", "formation_end_index")

    for key in ("bos_choch_events", "liquidity_sweeps"):
        for event in structure.get(key, []):
            index = event.get("confirmation_index")
            if isinstance(index, int) and 0 <= index < len(bars):
                event["confirmation_time_server_ms"] = bars[index]["time_server_ms"]

    return {
        "status": "READY" if structure.get("status") in {"READY", "PARTIAL", "INSUFFICIENT"} else "PARTIAL",
        "source": "MT5_COPYRATES",
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_count": len(bars),
        "closed_bar_count": sum(1 for bar in bars if bar["is_closed"]),
        "forming_bar_count": 1,
        "patterns": patterns,
        "reference_patterns": reference_patterns,
        "structure": structure,
        "decision_eligible": False,
        "interpretation": (
            "Native OHLC analysis only. Pattern matches and structure events are evidence, "
            "not probabilities, trade votes, or instructions."
        ),
    }


__all__ = ["analyze_native_mt5_ohlc", "validate_mt5_chart_geometry"]
