from __future__ import annotations

import hashlib
import math
import time
from pathlib import Path
from typing import Any

from .chart_calibration import calibrate_bars, resolve_chart_calibration
from .chart_extraction import PALETTE_PRESETS, _extract_bars
from .chart_image import load_chart_image
from .chart_metrics import analyze_calibrated_bars
from .chart_patterns import _body_bounds, _patterns
from .chart_ocr import detect_price_axis_ticks, fit_price_axis

SUPPORTED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d", "1w"})
MIN_CALIBRATED_BARS = 20
MIN_LAST_BAR_X_RATIO = 0.68
MIN_MEAN_COLOUR_PURITY = 0.72


def analyze_chart_image(
    image_path: str | Path,
    metadata: dict[str, Any] | None = None,
    expected_symbol: str | None = None,
) -> dict[str, Any]:
    """Run Engine 2's staged chart-image analysis and emit its stable contract."""
    path = Path(image_path)
    meta = metadata if isinstance(metadata, dict) else {}
    result: dict[str, Any] = {
        "engine": "engine_2_chart_visual_analysis",
        "method": "OpenCV computer vision, optional local RapidOCR axis reading and explicit candle rules",
        "ai_used": False,
        "ocr_model_used": False,
        "image": path.name,
        "analyzed_at_ms": int(time.time() * 1000),
        "symbol": meta.get("symbol"),
        "timeframe": meta.get("timeframe"),
    }

    image, image_error = load_chart_image(path)
    if image_error or image is None:
        return {
            **result,
            "status": "ERROR",
            "error": "The image could not be read or decoded: " + str(image_error or "unknown image error"),
            "decision_eligible": False,
        }

    image_height, image_width = image.shape[:2]
    try:
        calibration = resolve_chart_calibration(meta, image_width=image_width, image_height=image_height)
        axis_ocr: dict[str, Any] = {"status": "SKIPPED_MANUAL" if calibration["price_scale_valid"] else "DISABLED"}
        calibration_source = "manual" if calibration["price_scale_valid"] else "unavailable"

        # Manual axis values always take precedence. OCR is a fallback only,
        # and must pass a robust multi-tick fit before becoming price data.
        if not calibration["price_scale_valid"] and bool(meta.get("auto_axis_ocr", False)):
            axis_ocr = detect_price_axis_ticks(
                image,
                plot_top_px=calibration["plot_top_px"],
                plot_bottom_px=calibration["plot_bottom_px"],
                plot_right_px=calibration["plot_right_px"],
            )
            if axis_ocr.get("ticks"):
                axis_fit = fit_price_axis(
                    axis_ocr["ticks"],
                    plot_top_px=calibration["plot_top_px"],
                    plot_bottom_px=calibration["plot_bottom_px"],
                    scale_type=calibration["price_scale_type"],
                )
                axis_ocr["fit"] = axis_fit
                if axis_fit.get("status") == "READY":
                    proposed_right = axis_ocr.get("candidate_plot_right_px")
                    explicit_right = int(meta.get("plot_right_px", 0) or 0)
                    if not explicit_right and proposed_right is not None:
                        proposed_right = int(proposed_right)
                        if calibration["plot_left_px"] + 32 < proposed_right <= image_width:
                            meta = {**meta, "plot_right_px": proposed_right}
                    meta = {
                        **meta,
                        "price_top": float(axis_fit["price_top"]),
                        "price_bottom": float(axis_fit["price_bottom"]),
                        "price_scale_type": calibration["price_scale_type"],
                    }
                    calibration = resolve_chart_calibration(
                        meta, image_width=image_width, image_height=image_height
                    )
                    calibration_source = "ocr" if calibration["price_scale_valid"] else "unavailable"
            elif axis_ocr.get("status") == "OCR_UNAVAILABLE":
                calibration_source = "unavailable"

        extraction_metadata = {
            **meta,
            "plot_left_px": calibration["plot_left_px"],
            "plot_top_px": calibration["plot_top_px"],
            "plot_right_px": calibration["plot_right_px"],
            "plot_bottom_px": calibration["plot_bottom_px"],
        }
        extraction_diagnostics: dict[str, Any] = {}
        bars = _extract_bars(image, extraction_metadata, diagnostics=extraction_diagnostics)
    except (TypeError, ValueError, OverflowError) as exc:
        return {
            **result,
            "status": "ERROR",
            "error": f"Invalid chart crop metadata or extraction settings: {exc}",
            "decision_eligible": False,
        }

    pattern_candidates = _patterns(bars)
    calibrated = calibrate_bars(bars, calibration)
    if calibration["price_scale_valid"]:
        analysis = analyze_calibrated_bars(
            calibrated,
            top_price=float(calibration["price_top"]),
            bottom_price=float(calibration["price_bottom"]),
        )
    else:
        analysis = {
            "visual_bias": "NEUTRAL",
            "visual_trend": {
                "sample_bars": 0, "net_change": None, "net_change_pct": None,
                "visible_range_fraction": None, "rising_close_steps": 0,
                "falling_close_steps": 0, "required_directional_steps": 0,
                "minimum_move": None, "score": 0.0, "direction_consistency": 0.0,
            },
            "market_structure": {
                "status": "INSUFFICIENT", "direction": "UNKNOWN", "score": None,
                "swing_highs": [], "swing_lows": [], "higher_highs": False,
                "higher_lows": False, "lower_highs": False, "lower_lows": False,
                "support": None, "resistance": None,
                "distance_to_support_pct": None, "distance_to_resistance_pct": None,
            },
            "momentum": {"status": "INSUFFICIENT", "score": None, "change": None, "change_pct": None},
            "pattern_score": 0.0, "analysis_score": 0.0, "analysis_confidence": 0.0,
            "confidence_components": {},
            "confidence_kind": "heuristic_evidence_quality_not_probability",
        }

    symbol_value = str(meta.get("symbol", "")).strip().upper()
    expected_value = str(expected_symbol or "").strip().upper()
    symbol_matches = bool(expected_value and symbol_value == expected_value)
    timeframe = str(meta.get("timeframe", "")).strip().lower()
    timeframe_valid = timeframe in SUPPORTED_TIMEFRAMES

    plot_left = int(calibration["plot_left_px"])
    plot_right = int(calibration["plot_right_px"])
    plot_width = max(1, plot_right - plot_left)
    last_bar_x_ratio = (
        (float(bars[-1]["x_px"]) - plot_left) / plot_width if bars else None
    )
    mean_colour_purity = (
        float(sum(float(bar.get("colour_purity", 0.0)) for bar in bars[-24:]) / min(len(bars), 24))
        if bars else 0.0
    )

    quality_gates = {
        "price_axis_calibrated": bool(calibration["price_scale_valid"]),
        "market_symbol_matches": symbol_matches,
        "timeframe_supported": timeframe_valid,
        "minimum_candle_count": len(calibrated) >= MIN_CALIBRATED_BARS,
        "latest_candle_near_right_edge": (
            last_bar_x_ratio is not None and last_bar_x_ratio >= MIN_LAST_BAR_X_RATIO
        ),
        "candle_colour_purity": mean_colour_purity >= MIN_MEAN_COLOUR_PURITY,
    }
    eligible = all(quality_gates.values())
    if eligible:
        state = "READY"
    elif len(bars) < 5:
        state = "LOW_DETECTION"
    elif not calibration["price_scale_valid"]:
        state = "DETECTED_UNCALIBRATED"
    else:
        state = "BLOCKED_QUALITY_GATE"

    score = float(analysis["analysis_score"])
    confidence = float(analysis["analysis_confidence"])
    if not math.isfinite(score):
        score = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0

    return {
        **result,
        "status": state,
        "image_width": image_width,
        "image_height": image_height,
        "detected_bar_count": len(bars),
        "calibrated_bar_count": len(calibrated),
        "last_bar_x_ratio": round(last_bar_x_ratio, 4) if last_bar_x_ratio is not None else None,
        "mean_colour_purity": round(mean_colour_purity, 4),
        "palette_mode": str(meta.get("palette_mode", "auto")),
        "extraction_diagnostics": extraction_diagnostics,
        "colour_counts": {
            "GREEN": sum(bar.get("colour") == "GREEN" for bar in bars),
            "RED": sum(bar.get("colour") == "RED" for bar in bars),
        },
        "visual_bias": analysis["visual_bias"],
        "visual_trend": analysis["visual_trend"],
        "market_structure": analysis["market_structure"],
        "momentum": analysis["momentum"],
        "analysis_score": round(max(-1.0, min(1.0, score)), 4),
        "analysis_confidence": round(max(0.0, min(1.0, confidence)), 4),
        "confidence_kind": analysis.get("confidence_kind", "heuristic_evidence_quality_not_probability"),
        "confidence_components": analysis.get("confidence_components", {}),
        "analysis_components": {
            "trend": analysis["visual_trend"].get("score"),
            "structure": analysis["market_structure"].get("score"),
            "momentum": analysis["momentum"].get("score"),
            "patterns": 0.0,
        },
        "pattern_candidates": pattern_candidates,
        "bars": calibrated[-80:] if calibration["price_scale_valid"] else bars[-80:],
        "decision_eligible": eligible,
        "quality_gates": quality_gates,
        "axis_ocr": axis_ocr,
        "ocr_model_used": axis_ocr.get("ocr_backend") == "RapidOCR",
        "ai_used": axis_ocr.get("ocr_backend") == "RapidOCR",
        "calibration": {
            "source": calibration_source,
            "price_scale_valid": bool(calibration["price_scale_valid"]),
            "price_scale_type": calibration["price_scale_type"],
            "symbol_matches": symbol_matches,
            "timeframe_valid": timeframe_valid,
            "plot_top_px": calibration["plot_top_px"],
            "plot_bottom_px": calibration["plot_bottom_px"],
            "plot_left_px": calibration["plot_left_px"],
            "plot_right_px": calibration["plot_right_px"],
            "price_top": calibration["price_top"],
            "price_bottom": calibration["price_bottom"],
        },
        "limitations": [
            "The price axis depends on user-supplied top/bottom prices and the exact plot rectangle.",
            "The selected linear/logarithmic scale type must match the displayed chart axis.",
            "Candle colours depend on the selected palette and chart theme.",
            "Pattern candidates are low-confidence observations and do not steer Engine 4 direction.",
            "The visual confidence index is heuristic evidence quality, not a statistical probability.",
            "Engine 2 uses deterministic computer vision; it does not use a trained AI vision model.",
        ],
    }


__all__ = [
    "PALETTE_PRESETS", "_body_bounds", "_extract_bars", "_patterns", "analyze_chart_image"
]
