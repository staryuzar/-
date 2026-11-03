from __future__ import annotations

import math
from typing import Any

GEOMETRY_SCHEMA = "MIR-MT5-CHART-GEOMETRY-1"
_POINT_FIELDS = ("open", "high", "low", "close")


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
            points: dict[str, dict[str, float]] = {}
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
                "reason": f"Geometry item {index} has incomplete point coordinates.",
                "bars": output,
            }

        if stamp != int(native["time_server_ms"]) or closed is not native["is_closed"]:
            return {
                "status": "BAR_IDENTITY_MISMATCH",
                "decision_eligible": False,
                "reason": f"Geometry item {index} does not match its OHLC timestamp/close state.",
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

        visible = bool(item.get("visible"))
        valid = bool(item.get("valid"))
        if visible and not valid:
            return {
                "status": "VISIBLE_POINT_INVALID",
                "decision_eligible": False,
                "reason": f"Geometry item {index} is declared visible but its point set is invalid.",
                "bars": output,
            }
        if valid:
            valid_count += 1
            if previous_x is not None and item_x <= previous_x:
                return {
                    "status": "X_SEQUENCE_INVALID",
                    "decision_eligible": False,
                    "reason": "Native chart X coordinates must increase with chronological OHLC bars.",
                    "bars": output,
                }
            previous_x = item_x
        if visible and valid:
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
