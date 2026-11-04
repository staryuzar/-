from __future__ import annotations
import argparse, hashlib, json, math, sys
from typing import Any
from pathlib import Path
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from mirsad.engines.chart import analyze_chart_image
from mirsad.engines.mt5_observer import MT5ChartObserverInbox, recent_reference_candle_candidates
from mirsad.engines.mt5_market import MT5MarketDataEngine
from mirsad.engines.mt5_chart_candles import MT5ChartCandleHistory
from mirsad.engines.mt5_native_indicators import MT5NativeIndicatorHistory
from mirsad.engines.mt5_chart_geometry import (
    native_geometry_visible_y_max,
    native_geometry_slot_centers,
    validate_mt5_chart_geometry,
    validate_mt5_geometry_overlay,
)

SUPPORTED = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}



def _write_plot_debug_overlay(image_path: Path, analysis: dict[str, Any],
                              native_geometry: dict[str, Any], native_bars: list[dict[str, Any]],
                              chart: dict[str, Any], destination: Path) -> dict[str, Any]:
    """Save only the calibrated plot crop with native and extracted OHLC pixel marks."""
    calibration = analysis.get("calibration") if isinstance(analysis.get("calibration"), dict) else {}
    try:
        left, top = int(calibration["plot_left_px"]), int(calibration["plot_top_px"])
        right, bottom = int(calibration["plot_right_px"]), int(calibration["plot_bottom_px"])
        visible, first_shift = int(chart["visible_bars"]), int(chart["first_visible_bar_shift"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "NOT_CREATED", "reason": "Plot bounds or viewport metadata unavailable."}
    if right <= left or bottom <= top or visible < 1 or first_shift < 0:
        return {"status": "NOT_CREATED", "reason": "Invalid plot bounds or viewport metadata."}
    with Image.open(image_path) as source:
        rgb = source.convert("RGB")
        bounds = (max(0, left), max(0, top), min(rgb.width, right), min(rgb.height, bottom))
        if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
            return {"status": "NOT_CREATED", "reason": "Plot crop lies outside the PNG."}
        crop = rgb.crop(bounds)
    crop_left, crop_top, crop_right, crop_bottom = bounds
    header = 30
    canvas = Image.new("RGB", (crop.width, crop.height + header), (248, 248, 248))
    canvas.paste(crop, (0, header))
    draw = ImageDraw.Draw(canvas)
    rows = analysis.get("bars") if isinstance(analysis.get("bars"), list) else []
    by_slot = {}
    for row in rows:
        if isinstance(row, dict):
            try:
                by_slot.setdefault(int(row["slot_index"]), row)
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
    geometry_rows = native_geometry.get("bars") if isinstance(native_geometry, dict) else None
    if not isinstance(geometry_rows, list) or len(geometry_rows) != len(native_bars):
        return {"status": "NOT_CREATED", "reason": "Native geometry/history length mismatch."}
    rightmost = max(0, first_shift - visible + 1)
    matched = native_drawn = 0
    for i, geom in enumerate(geometry_rows):
        if not isinstance(geom, dict) or geom.get("valid") is not True or geom.get("visible") is not True:
            continue
        points = geom.get("points_image_px_provisional")
        if not isinstance(points, dict):
            continue
        try:
            xs = [float(points[k]["x"]) for k in ("open", "high", "low", "close")]
            ys = {k: float(points[k]["y"]) for k in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not all(math.isfinite(v) for v in xs + list(ys.values())):
            continue
        x = sum(xs) / 4.0
        if not left <= x <= right:
            continue
        offset = len(native_bars) - 1 - i
        rel = offset - rightmost
        if not 0 <= rel < visible:
            continue
        slot = visible - 1 - rel
        xx = int(round(x - crop_left))
        def yy(v): return int(round(v - crop_top + header))
        draw.line((xx, yy(ys["high"]), xx, yy(ys["low"])), fill=(225, 72, 42), width=2)
        for key in ("open", "high", "low", "close"):
            y = yy(ys[key]); draw.ellipse((xx-2, y-2, xx+2, y+2), fill=(225, 72, 42))
        native_drawn += 1
        row = by_slot.get(slot)
        if row is None:
            continue
        try:
            ex = float(row["x_px"])
            ey = [float(row[k]) for k in ("high_y_px", "low_y_px", "body_top_y_px", "body_bottom_y_px")]
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(ex) or not all(math.isfinite(v) for v in ey):
            continue
        if not crop_left <= ex <= crop_right or not all(crop_top <= v <= crop_bottom for v in ey):
            continue
        ix = int(round(ex - crop_left)); yh, yl, yt, yb = [yy(v) for v in ey]
        draw.line((ix, yh, ix, yl), fill=(42, 180, 92), width=2)
        draw.line((ix-3, yt, ix+3, yt), fill=(42, 180, 92), width=2)
        draw.line((ix-3, yb, ix+3, yb), fill=(42, 180, 92), width=2)
        matched += 1
    outside = int(((analysis.get("native_geometry_slot_assignment") or {})
                   .get("plot_bounds_diagnostics", {})
                   .get("native_slots_beyond_ocr_plot_right", 0) or 0))
    draw.rectangle((0, 0, canvas.width, header), fill=(248, 248, 248))
    draw.text((6, 8), f"MT5 native RED | extracted GREEN | exact-slot matches {matched} | outside right {outside}", fill=(20, 20, 20))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="PNG", optimize=True)
    return {"status": "CREATED", "file": destination.name, "matched_exact_slots": matched,
            "native_marks": native_drawn, "native_slots_beyond_ocr_right": outside,
            "plot_width_px": crop.width, "plot_height_px": crop.height}

def analyze(observer_root: Path, market_symbol: str, broker_symbol: str, *, debug_overlay: Path | None = None) -> dict:
    capture = MT5ChartObserverInbox(observer_root, max_age_seconds=120).inspect_latest()
    chart = capture.get("chart") if isinstance(capture.get("chart"), dict) else {}

    # Validate the real, separated MT5 market and candle files on this runner.
    common_files = observer_root.parent.parent
    market_result = MT5MarketDataEngine(common_files=str(common_files), symbol=market_symbol).collect()
    candle_result = MT5ChartCandleHistory(common_files=str(common_files), symbol=market_symbol).collect()
    native_indicators = MT5NativeIndicatorHistory(
        common_files=str(common_files), symbol=market_symbol,
    ).collect(candle_history=candle_result)
    market_context = market_result.get("market_context") if isinstance(market_result.get("market_context"), dict) else {}
    microstructure = market_context.get("microstructure") if isinstance(market_context.get("microstructure"), dict) else {}
    engine5_quote_summary = {
        "status": market_result.get("status"),
        "source": market_result.get("source"),
        "captured_at_ms": market_result.get("captured_at_ms"),
        "price": market_result.get("price"),
        "feed_health": {key: (market_result.get("feed_health") or {}).get(key) for key in
                        ("terminal_connected", "quote_fresh", "snapshot_age_seconds", "tick_age_seconds", "tick_history_status", "broker_symbol", "account_server")},
        "microstructure": {key: microstructure.get(key) for key in
                            ("status", "tick_count", "quote_tick_count", "tick_rate_per_minute", "upticks", "downticks", "quote_direction_balance", "midpoint_change_pct", "current_spread_pct", "mean_observed_spread_pct", "reported_last_price_tick_count", "latest_reported_last_price", "reported_volume_update_count", "reported_volume_sum", "reported_buy_flag_count", "reported_sell_flag_count")},
        "order_book": {
            "status": (market_context.get("order_book") or {}).get("status"),
            "level_count": (market_context.get("order_book") or {}).get("level_count"),
            "bid_level_count": (market_context.get("order_book") or {}).get("bid_level_count"),
            "ask_level_count": (market_context.get("order_book") or {}).get("ask_level_count"),
            "reason": (market_context.get("order_book") or {}).get("reason"),
        },
        "reason": market_result.get("reason"),
        "ownership": "engine_5_broker_quote_feed_not_engine_1_intelligence",
    }
    engine2_candles_summary = {
        "status": candle_result.get("status"),
        "source": candle_result.get("source"),
        "captured_at_ms": candle_result.get("captured_at_ms"),
        "broker_symbol": candle_result.get("broker_symbol"),
        "account_server": candle_result.get("account_server"),
        "source_terminal_connected": candle_result.get("source_terminal_connected"),
        "source_account_server_present": candle_result.get("source_account_server_present"),
        "source_broker_symbol_present": candle_result.get("source_broker_symbol_present"),
        "timeframes": candle_result.get("timeframes", {}),
        "closed_candles": candle_result.get("closed_candles", {}),
        "reason": candle_result.get("reason"),
    }
    native_indicator_summary = {
        "status": native_indicators.get("status"),
        "source": native_indicators.get("source"),
        "ready_timeframe_count": native_indicators.get("ready_timeframe_count"),
        "missing_required_timeframes": native_indicators.get("missing_required_timeframes", []),
        "reason": native_indicators.get("reason"),
        "timeframes": {
            name: {
                "status": frame.get("status"),
                "ready_indicator_count": frame.get("ready_indicator_count", 0),
                "missing_required_indicators": frame.get("missing_required_indicators", []),
            }
            for name, frame in (native_indicators.get("timeframes") or {}).items()
        },
    }

    def blocked(code: str, reason: str, **details: Any) -> dict:
        return {
            "schema": "MIR-ENGINE2-OBSERVER-SMOKE-1",
            "capture_id": capture.get("capture_id"),
            "capture": {
                "source_width_px": chart.get("source_width_px"),
                "source_main_window_height_px": chart.get("source_main_window_height_px"),
                "visible_bars": chart.get("visible_bars"),
                "windows_total": chart.get("windows_total"),
                "chart_autoscroll": chart.get("chart_autoscroll"),
                "chart_mode": chart.get("chart_mode"),
                "chart_scale": chart.get("chart_scale"),
                "chart_shift": chart.get("chart_shift"),
                "price_scale_visible": bool(chart.get("price_scale_visible", False)),
                "date_scale_visible": bool(chart.get("date_scale_visible", False)),
                "one_click_panel_visible": bool(chart.get("one_click_visible", False)),
                "source_dimensions_usable": chart.get("source_dimensions_usable"),
            },
            "engine5_quote_feed": engine5_quote_summary,
            "engine2_candle_history": engine2_candles_summary,
            "engine2_native_indicators": native_indicator_summary,
            "decision_eligible": False,
            "engine2": {"status": code, "visual_eligible": False, "reason": reason,
                        "detected_bars": 0, "confirmed_bars": 0,
                        "reference_calibration_status": "NOT_ATTEMPTED", "quality_gates": {},
                        "diagnostics": details},
            "safety": {"read_only": True, "decision_eligible": False}
        }
    if capture.get("status") != "READY_FOR_ENGINE_2_VALIDATION":
        return blocked("CAPTURE_NOT_READY", str(capture.get("reason") or capture.get("status")))
    bars = capture.get("bars") if isinstance(capture.get("bars"), list) else []
    timeframe = str(chart.get("timeframe", "")).lower()
    if chart.get("symbol") != broker_symbol:
        return blocked("SYMBOL_MISMATCH", "Broker symbol differs from the explicit input.")
    if timeframe not in SUPPORTED:
        return blocked("TIMEFRAME_UNSUPPORTED", "Observer timeframe is unsupported.")
    if not capture.get("visual_calibration_eligible") or not chart.get("source_dimensions_usable"):
        return blocked("VIEWPORT_UNSUITABLE", "Original MT5 viewport is below the calibration threshold.")
    try:
        visible_bars = int(chart.get("visible_bars", 0) or 0)
        first_visible_bar_shift = int(chart.get("first_visible_bar_shift", -1))
    except (TypeError, ValueError, OverflowError):
        return blocked("VIEWPORT_METADATA_INVALID", "MT5 visible-bar position metadata is invalid.")
    if visible_bars <= 0 or first_visible_bar_shift < 0:
        return blocked("VIEWPORT_METADATA_INVALID", "MT5 visible-bar count or first-visible shift is missing.")
    rightmost_visible_offset = max(0, first_visible_bar_shift - visible_bars + 1)
    maximum_allowed_rightmost_offset = max(2, int(math.ceil(visible_bars * 0.20)))
    if rightmost_visible_offset > maximum_allowed_rightmost_offset:
        return blocked(
            "CHART_VIEWPORT_NOT_CURRENT",
            "The rightmost visible candle is too far behind the latest MT5 candle; navigate to CHART_END before image analysis.",
            visible_bars=visible_bars,
            first_visible_bar_shift=first_visible_bar_shift,
            rightmost_visible_offset=rightmost_visible_offset,
            maximum_allowed_rightmost_offset=maximum_allowed_rightmost_offset,
        )
    if int(chart.get("source_width_px", 0)) < 320 or int(chart.get("source_main_window_height_px", 0)) < 160:
        return blocked("VIEWPORT_UNSUITABLE", "Original MT5 viewport is too small.")
    if chart.get("chart_autoscroll") is not True or int(chart.get("windows_total", 0)) != 1:
        return blocked("LAYOUT_UNVERIFIED", "AutoScroll must be enabled and the chart must have one calibrated window.")
    if int(chart.get("visible_bars", 0)) < 21 or len(bars) < 21:
        return blocked("HISTORY_INSUFFICIENT", "Need 20 closed candles and one forming candle.")
    if capture.get("rates_status") != "AVAILABLE" or int(capture.get("rates_error_code", -1)) != 0:
        return blocked("OHLC_UNAVAILABLE", "CopyRates did not provide a valid OHLC snapshot.")
    if any(x.get("is_closed") is not True for x in bars[:-1]) or bars[-1].get("is_closed") is not False:
        return blocked("BAR_STATE_INVALID", "Exactly the last OHLC bar must be forming.")
    try:
        age = float(capture.get("age_seconds", math.inf))
        skew = int(capture.get("capture_data_skew_ms", -1))
        pmin, pmax = float(chart["price_min"]), float(chart["price_max"])
        low, high = float(bars[-1]["low"]), float(bars[-1]["high"])
    except (TypeError, ValueError, KeyError, OverflowError):
        return blocked("METADATA_INVALID", "Capture timing or visible price range is missing.")
    if not all(math.isfinite(x) for x in (age, pmin, pmax, low, high)) or age > 120 or age < 0 or not 0 <= skew <= 2000:
        return blocked("CAPTURE_NOT_SYNCHRONIZED", "Image and OHLC timing exceeds the allowed two seconds.")
    if not 0 < pmin < pmax or low < pmin or high > pmax:
        return blocked("PRICE_RANGE_MISMATCH", "Latest MT5 candle is outside the visible chart range.")
    image = Path(str(capture.get("image_path", "")))
    if not image.is_file():
        return blocked("IMAGE_MISSING", "Validated PNG is no longer available.")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    if digest != str(capture.get("image_sha256", "")).lower():
        return blocked("IMAGE_CHANGED", "PNG hash changed after inbox verification.")
    with Image.open(image) as source_image:
        image_width, image_height = source_image.size
    native_pixel_geometry = validate_mt5_chart_geometry(
        chart.get("pixel_geometry"), bars=bars, chart=chart,
        image_width=image_width, image_height=image_height,
    )
    if not market_symbol or len(market_symbol) > 32:
        return blocked("MARKET_MAPPING_INVALID", "Explicit Mirsad market symbol is invalid.")
    reference_candidates = recent_reference_candle_candidates(
        bars, max_candidates=256, max_lookback=256
    )
    if not reference_candidates:
        return blocked(
            "REFERENCE_CANDLE_UNAVAILABLE",
            "No recent native MT5 candle has a positive range suitable for visual calibration.",
        )
    candidates_for_chart = [{
        "offset_from_right": item["offset_from_right"],
        "time_server_ms": item.get("time_server_ms"),
        "closed": item.get("closed"),
        "ohlc": item["ohlc"],
    } for item in reference_candidates]
    metadata = {
        "symbol": market_symbol, "timeframe": timeframe,
        "price_scale_type": str(chart.get("price_scale_type", "linear")).lower(),
        "expected_candle_count": int(chart.get("visible_bars", 0) or 0),
        "first_visible_bar_shift": int(chart.get("first_visible_bar_shift", 0) or 0),
        "allow_reference_anchor_override": True,
        "require_multi_reference_validation": True,
        "last_candle_closed": False, "auto_axis_ocr": True,
        "reference_candle_candidates": candidates_for_chart,
        "reference_last_candle_ohlc": candidates_for_chart[0]["ohlc"],
        "reference_candle_offset_from_right": candidates_for_chart[0]["offset_from_right"],
    }
    native_slot_center_result = native_geometry_slot_centers(
        native_pixel_geometry,
        native_bar_count=len(bars),
        visible_bars=int(chart.get("visible_bars", 0) or 0),
        first_visible_bar_shift=int(chart.get("first_visible_bar_shift", 0) or 0),
    )
    metadata["native_geometry_slot_centers"] = native_slot_center_result.get("slots", [])
    metadata["native_geometry_slot_center_status"] = native_slot_center_result.get("status")
    native_max_y = native_geometry_visible_y_max(native_pixel_geometry)
    if native_max_y is not None:
        metadata["native_geometry_max_y_image_px"] = native_max_y
    result = analyze_chart_image(image, metadata, expected_symbol=market_symbol)
    native_geometry_overlay = validate_mt5_geometry_overlay(
        native_pixel_geometry,
        native_bars=bars,
        extracted_bars=result.get("bars", []),
        visible_bars=int(chart.get("visible_bars", 0) or 0),
        first_visible_bar_shift=int(chart.get("first_visible_bar_shift", 0) or 0),
    )
    reference = result.get("reference_multi_calibration") or {}
    axis_validation = result.get("reference_axis_validation") or {}
    axis_ocr = result.get("axis_ocr") or {}
    axis_fit = axis_ocr.get("fit") or {}
    calibration = result.get("calibration") or {}
    reference_reason = reference.get("reason")
    reference_diagnostics = {
        "detected_colour": reference.get("detected_colour"),
        "expected_colour": reference.get("expected_colour"),
        "maximum_residual_fraction": reference.get("maximum_residual_fraction"),
        "body_residual_fraction_by_field": reference.get("body_residual_fraction_by_field", {}),
        "reference_pixel_rows": reference.get("reference_pixel_rows", {}),
    }
    # Keep the live MT5 native candle as the only trusted calibration anchor.
    # OCR may independently suggest axis ticks, but OCR-only calibration is not
    # accepted until a separate native-OHLC-to-visible-candle residual check exists.
    anchor = (calibration.get("source") == "reference_multi_candle_ohlc"
              and reference.get("status") == "READY"
              and axis_validation.get("status") == "READY")
    eligible = bool(result.get("decision_eligible")) and anchor
    selected_reference_anchor = result.get("reference_anchor") or {}
    summary = {
        "schema": "MIR-ENGINE2-OBSERVER-SMOKE-1",
        "capture_id": capture.get("capture_id"),
        "broker_symbol": broker_symbol, "market_symbol": market_symbol, "timeframe": timeframe,
        "capture": {"age_seconds": round(age, 2), "capture_data_skew_ms": skew,
                    "image_sha256": digest, "native_ohlc_bars": len(bars),
                    "source_width_px": int(chart["source_width_px"]),
                    "source_height_px": int(chart["source_main_window_height_px"]),
                    "chart_mode": chart.get("chart_mode"),
                    "chart_scale": chart.get("chart_scale"),
                    "chart_shift": chart.get("chart_shift"),
                    "price_scale_visible": bool(chart.get("price_scale_visible", False)),
                    "date_scale_visible": bool(chart.get("date_scale_visible", False)),
                    "one_click_panel_visible": bool(chart.get("one_click_visible", False)),
                    "price_min": chart.get("price_min"),
                    "price_max": chart.get("price_max"),
                    "visible_bars": visible_bars,
                    "first_visible_bar_shift": first_visible_bar_shift,
                    "rightmost_visible_offset": rightmost_visible_offset,
                    "maximum_allowed_rightmost_offset": maximum_allowed_rightmost_offset},
        "engine2": {
            "status": result.get("status") if anchor else "REFERENCE_NOT_VERIFIED",
            "visual_eligible": eligible, "visual_bias": result.get("visual_bias", "NEUTRAL"),
            "analysis_score": result.get("analysis_score", 0),
            "analysis_confidence": result.get("analysis_confidence", 0),
            "detected_bars": result.get("detected_bar_count", 0),
            "confirmed_bars": result.get("confirmed_bar_count", 0),
            "reference_calibration_status": reference.get("status", "NOT_VERIFIED"),
            "reference_axis_validation": axis_validation,
            "reference_anchor": selected_reference_anchor,
            "reference_candidates_considered": len(candidates_for_chart),
            "reference_calibration_reason": reference_reason,
            "reference_calibration_diagnostics": reference_diagnostics,
            "reference_slot_diagnostics": result.get("reference_slot_diagnostics", {}),
            "native_geometry_slot_center_status": native_slot_center_result.get("status"),
            "native_geometry_slot_center_count": native_slot_center_result.get("native_slot_count", 0),
            "native_geometry_slot_assignment": result.get("native_geometry_slot_assignment", {}),
            "native_pixel_geometry": {
                **{
                    key: native_pixel_geometry.get(key) for key in (
                        "status", "decision_eligible", "validated_bars", "visible_bars",
                        "minimum_visible_bars", "mapping_status", "scale_x", "scale_y", "reason"
                    )
                },
                # Expose the MT5 inverse transform result so live evidence can
                # separate ChartTimePriceToXY errors from PNG/image alignment.
                "roundtrip_validation": native_pixel_geometry.get("roundtrip_validation", {
                    "status": "NOT_AVAILABLE",
                    "reason": "Inverse ChartXYToTimePrice evidence is missing from this capture.",
                    "decision_eligible": False,
                }),
            },
            "native_geometry_overlay": {
                **{
                    key: native_geometry_overlay.get(key) for key in (
                        "status", "mapping_verified", "matched_candles", "fit_candles",
                        "validation_candles", "validation_passed_candles",
                        "validation_pass_ratio", "validation_median_max_residual_px",
                        "validation_max_residual_px", "x_scale", "x_offset",
                        "y_scale", "y_offset", "reason", "coordinate_diagnostics"
                    )
                },
                "worst_validation_rows": sorted(
                    [row for row in native_geometry_overlay.get("validation_rows", [])
                     if isinstance(row, dict)],
                    key=lambda row: float(row.get("maximum_residual_px", 0.0)),
                    reverse=True,
                )[:5],
            },
            "multi_reference_validation": {
                **{
                    key: reference.get(key) for key in (
                        "matched_candles", "fit_candles", "validation_candles",
                        "validation_passed_candles", "validation_pass_ratio",
                        "validation_median_max_residual_fraction",
                        "fit_point_count", "fit_inlier_count", "fit_inlier_ratio",
                        "fit_residual_limit_px", "fit_vertical_coverage",
                        "fit_x_coverage", "validation_x_coverage",
                    )
                },
                "worst_validation_rows": sorted(
                    [row for row in reference.get("validation_rows", [])
                     if isinstance(row, dict)],
                    key=lambda row: float(row.get("maximum_residual_fraction", 0.0)),
                    reverse=True,
                )[:5],
            },
            "calibration_source": calibration.get("source", "unavailable"),
            "axis_ocr": {
                "status": axis_ocr.get("status", "NOT_RUN"),
                "tick_count": len(axis_ocr.get("ticks", [])),
                "fit_status": axis_fit.get("status", "NOT_RUN"),
                "fit_inlier_ratio": axis_fit.get("inlier_ratio"),
                "fit_rms_residual_px": axis_fit.get("rms_residual_px"),
                "fit_price_top": axis_fit.get("price_top"),
                "fit_price_bottom": axis_fit.get("price_bottom"),
                "tick_sample": [
                    {
                        "y_px": tick.get("y_px"),
                        "price": tick.get("price"),
                        "score": tick.get("score"),
                        "inlier": tick.get("inlier"),
                    }
                    for tick in axis_fit.get("ticks", [])[:24]
                    if isinstance(tick, dict)
                ],
                "tick_y_min_px": min(
                    (float(tick["y_px"]) for tick in axis_fit.get("ticks", [])
                     if isinstance(tick, dict) and tick.get("inlier", True)),
                    default=None,
                ),
                "tick_y_max_px": max(
                    (float(tick["y_px"]) for tick in axis_fit.get("ticks", [])
                     if isinstance(tick, dict) and tick.get("inlier", True)),
                    default=None,
                ),
                "plot_bottom_px": calibration.get("plot_bottom_px"),
                "plot_bounds_refinement": axis_ocr.get("plot_bounds_refinement"),
                "candidate_plot_right_px": axis_ocr.get("candidate_plot_right_px"),
                "native_geometry_plot_right_refinement": axis_ocr.get("native_geometry_plot_right_refinement"),
                "calibrated_plot_right_px": calibration.get("plot_right_px"),
                "reason": axis_ocr.get("reason"),
            },
            "detected_bar_count": int(result.get("detected_bar_count", 0)),
            "confirmed_bar_count": int(result.get("confirmed_bar_count", 0)),
            "last_bar_x_ratio": result.get("last_bar_x_ratio"),
            "extraction": {
                "expected_candle_count": int(chart.get("visible_bars", 0) or 0),
                "segmentation_mode": (result.get("extraction_diagnostics") or {}).get("segmentation_mode"),
                "selected_palette_mode": (result.get("extraction_diagnostics") or {}).get("selected_palette_mode"),
                "accepted_bars": (result.get("extraction_diagnostics") or {}).get("accepted_bars"),
                "slot_guided": {
                    key: value for key, value in (
                        (result.get("extraction_diagnostics") or {}).get("slot_guided_extraction") or {}
                    ).items()
                    if key in {"mode", "slots_considered", "occupied_slots", "rejected_low_activity",
                               "rejected_component_quality", "rejected_low_pixels", "rejected_mixed_palette",
                               "rejected_off_center_components", "count_fit_improves", "geometry_quality_improves",
                               "mean_colour_purity", "legacy_mean_colour_purity", "mean_body_ratio",
                               "legacy_mean_body_ratio", "bars_with_both_wicks_separated",
                               "legacy_bars_with_both_wicks_separated", "adopted"}
                },
                "native_geometry_guided": {
                    key: value for key, value in (
                        (result.get("extraction_diagnostics") or {}).get("native_geometry_guided_extraction") or {}
                    ).items()
                    if key in {"status", "slots_considered", "occupied_slots", "rejected_empty_pixels",
                               "rejected_components", "rejected_off_center", "rejected_body",
                               "mean_colour_purity", "median_native_x_residual_px",
                               "maximum_native_x_residual_px", "native_median_spacing_px",
                               "minimum_recovery_threshold", "adopted", "reason"}
                },
            },
            "quality_gates": result.get("quality_gates", {}),
            "reason": None if eligible else (
                reference_reason
                or (axis_ocr.get("reason") if axis_ocr.get("status") == "OCR_UNAVAILABLE" else None)
                or "Visual quality or multi-candle OHLC hold-out validation did not pass."
            )
        },
        "engine5_quote_feed": engine5_quote_summary,
        "engine2_candle_history": engine2_candles_summary,
        "engine2_native_indicators": native_indicator_summary,
        "decision_eligible": False,
        "safety": {"read_only": True, "decision_eligible": False,
                   "reason": "Actual MT5 diagnostics only. No order is created or authorized."}
    }
    if debug_overlay is not None:
        summary["plot_debug_overlay"] = _write_plot_debug_overlay(
            image, result, native_pixel_geometry, bars, chart, debug_overlay
        )
    return summary

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--observer-root", type=Path, required=True)
    p.add_argument("--market-symbol", required=True)
    p.add_argument("--expected-broker-symbol", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--debug-overlay", type=Path, default=None)
    a = p.parse_args()
    result = analyze(a.observer_root, a.market_symbol.strip().upper(), a.expected_broker_symbol.strip(), debug_overlay=a.debug_overlay)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["engine2"]["status"],
                      "visual_eligible": result["engine2"]["visual_eligible"],
                      "decision_eligible": False}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
